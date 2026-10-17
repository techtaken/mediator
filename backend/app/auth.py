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


def _decode_user(authorization: str | None) -> str | None:
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
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session token")
    return user_id


def require_logged_in(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    user_id = _decode_user(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user_id


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

    if x_invite_token and x_invite_token == session.get("invite_token_b"):
        return session, Actor("user_b", invite_token=x_invite_token)

    raise HTTPException(status_code=403, detail="You cannot access this dispute room")
