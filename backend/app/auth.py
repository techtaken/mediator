import secrets
from datetime import datetime, timezone
from functools import lru_cache
from typing import Annotated, Literal

import jwt
from fastapi import Depends, Header, HTTPException
from jwt import InvalidTokenError, PyJWKClient

from app.config import get_settings
from app.db import get_supabase

Party = Literal["user_a", "user_b"]


class Actor:
    def __init__(
        self,
        party: Party,
        user_id: str | None = None,
        invite_token: str | None = None,
    ):
        self.party = party
        self.user_id = user_id
        self.invite_token = invite_token


@lru_cache
def _jwks_client() -> PyJWKClient:
    return PyJWKClient(get_settings().jwks_url)


def _decode_claims(authorization: str | None) -> dict | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256", "HS256"],
            audience="authenticated",
        )
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid session token") from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid session token") from exc
    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid session token")
    return payload


def _decode_user(authorization: str | None) -> str | None:
    claims = _decode_claims(authorization)
    return claims["sub"] if claims else None


def require_logged_in(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    user_id = _decode_user(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user_id


class Admin:
    def __init__(self, user_id: str, email: str):
        self.user_id = user_id
        self.email = email


def require_admin(
    authorization: Annotated[str | None, Header()] = None,
) -> Admin:
    """Signed-in user whose email is in ADMIN_EMAILS. Fails closed when unset."""
    claims = _decode_claims(authorization)
    if not claims:
        raise HTTPException(status_code=401, detail="Sign in required")
    email = str(claims.get("email") or "").strip().lower()
    if not email or email not in get_settings().admin_email_set:
        raise HTTPException(status_code=403, detail="Admins only")
    return Admin(claims["sub"], email)


def load_session(session_id: str) -> dict:
    supabase = get_supabase()
    result = supabase.table("sessions").select("*").eq("id", session_id).limit(1).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Session not found")
    return result.data[0]


def resolve_actor(
    session_id: str,
    authorization: Annotated[str | None, Header()] = None,
    x_invite_token: Annotated[str | None, Header()] = None,
) -> tuple[dict, Actor]:
    session = load_session(session_id)
    user_id = _decode_user(authorization) if authorization else None

    if user_id and session.get("created_by") == user_id:
        return session, Actor("user_a", user_id=user_id)

    if x_invite_token and secrets.compare_digest(x_invite_token, str(session.get("invite_token_b") or "")):
        if invite_expired(session):
            raise HTTPException(status_code=410, detail=INVITE_EXPIRED_DETAIL)
        return session, Actor("user_b", invite_token=x_invite_token)

    raise HTTPException(status_code=403, detail="You cannot access this dispute room")


INVITE_EXPIRED_DETAIL = "This invite link has expired. Ask the person who invited you for a new one."


def parse_time(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def invite_expired(session: dict, now: datetime | None = None) -> bool:
    """An invite expires only while unused. Once the invited person has joined
    (accepted how Mediator works), the link is their key to their own room."""
    if session.get("consented_b_at"):
        return False
    expires = parse_time(session.get("invite_expires_at"))
    return expires is not None and expires <= (now or datetime.now(timezone.utc))


def job_or_admin(
    authorization: Annotated[str | None, Header()] = None,
    x_job_token: Annotated[str | None, Header()] = None,
) -> str:
    """For maintenance jobs: a scheduler's X-Job-Token, or a signed-in admin."""
    expected = get_settings().job_token
    if expected and x_job_token and secrets.compare_digest(x_job_token, expected):
        return "job"
    return f"admin:{require_admin(authorization).email}"
