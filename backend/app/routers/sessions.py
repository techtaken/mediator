import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from app.agents.pipeline import handle_party_turn, run_joint_pipeline
from app.agents.state import joint_blocked_by, new_shared_state, party_code
from app.agents.store import (
    PersistError,
    StateConflict,
    load_private,
    load_state,
    persist_turn,
    save_state,
    state_version,
)
from app.auth import Actor, load_session, require_logged_in, resolve_actor
from app.config import get_settings
from app.db import get_supabase
from app.safety import HELP_MESSAGE, HELPLINES, PAUSED_FOR_OTHER_MESSAGE, is_crisis_or_severe_harm
from app.schemas import (
    CreateSessionBody,
    JointSummaryOut,
    MessageOut,
    ReadyBody,
    SendMessageBody,
    SessionOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

HALTED_DETAIL = "This room has been paused."
NOT_YET_READY_DETAIL = "Let's keep talking privately a little longer before the joint session."


def get_actor(
    session_id: str,
    authorization: Annotated[str | None, Header()] = None,
    x_invite_token: Annotated[str | None, Header()] = None,
) -> tuple[dict, Actor]:
    return resolve_actor(session_id, authorization, x_invite_token)


def _invite_link(session_id: str, token: str) -> str:
    base = get_settings().frontend_base_url.rstrip("/")
    return f"{base}/join/{session_id}?token={token}"


def _halt_view(session: dict, actor: Actor) -> str | None:
    if session["status"] != "halted":
        return None
    halted_for = session.get("halted_for")
    # Rooms halted before halted_for existed: show support, the safer default.
    if halted_for is None or halted_for == actor.party:
        return "self"
    return "other"


def _session_out(session: dict, actor: Actor) -> SessionOut:
    invite = None
    if actor.party == "user_a":
        invite = _invite_link(session["id"], session["invite_token_b"])
    halt_view = _halt_view(session, actor)
    return SessionOut(
        id=session["id"],
        status=session["status"],
        relationship_context=session.get("relationship_context"),
        created_at=session["created_at"],
        user_a_ready=session["user_a_ready"],
        user_b_ready=session["user_b_ready"],
        party=actor.party,
        invite_link=invite,
        # The other party never learns why a room stopped.
        halted_reason=(session.get("halt_kind") or session.get("halted_reason")) if halt_view == "self" else None,
        halt_view=halt_view,
        halt_message=PAUSED_FOR_OTHER_MESSAGE if halt_view == "other" else None,
        helplines=HELPLINES if halt_view == "self" else [],
    )


def _halt(session_id: str, party_role: str, kind: str = "safety") -> None:
    get_supabase().table("sessions").update(
        {"status": "halted", "halted_reason": kind, "halt_kind": kind, "halted_for": party_role}
    ).eq("id", session_id).execute()


def _insert_message(
    session_id: str,
    sender_role: str,
    audience_role: str,
    content: str,
    is_private: bool = True,
) -> dict:
    result = (
        get_supabase()
        .table("messages")
        .insert(
            {
                "session_id": session_id,
                "sender_role": sender_role,
                "audience_role": audience_role,
                "content": content,
                "is_private": is_private,
            }
        )
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Could not store message")
    return result.data[0]


def _maybe_build_summary(session: dict) -> None:
    if session["status"] != "intake":
        return
    if not (session["user_a_ready"] and session["user_b_ready"]):
        return
    if joint_blocked_by(load_state(session)):
        return

    sid = session["id"]
    supabase = get_supabase()
    # Claim the build atomically: only one of two simultaneous "ready" calls wins.
    claimed = (
        supabase.table("sessions")
        .update({"status": "building_joint"})
        .eq("id", sid)
        .eq("status", "intake")
        .eq("user_a_ready", True)
        .eq("user_b_ready", True)
        .execute()
    )
    if not claimed.data:
        return
    session = claimed.data[0]

    try:
        built = run_joint_pipeline(state=load_state(session))
        try:
            save_state(sid, built["state"], state_version(session))
        except StateConflict:
            # Intake is closed, so only an in-flight turn can race us. The summary
            # below is what matters; the diagnosis is rebuilt on the next joint step.
            logger.warning("joint state for %s lost a version race; summary still saved", sid)
        supabase.table("joint_summaries").upsert(
            {
                "session_id": sid,
                "user_a_perspective": built["user_a_perspective"],
                "user_b_perspective": built["user_b_perspective"],
                "compromises": built["compromises"],
            },
            on_conflict="session_id",
        ).execute()
        supabase.table("sessions").update({"status": "joint_review"}).eq("id", sid).execute()
    except Exception as exc:
        logger.exception("joint build failed for %s", sid)
        supabase.table("sessions").update({"status": "intake"}).eq("id", sid).eq("status", "building_joint").execute()
        raise HTTPException(status_code=502, detail="Could not prepare the joint view. Please try again.") from exc


@router.post("/sessions", response_model=SessionOut)
def create_session(body: CreateSessionBody, user_id: str = Depends(require_logged_in)):
    supabase = get_supabase()
    inserted = (
        supabase.table("sessions")
        .insert(
            {
                "created_by": user_id,
                "relationship_context": body.relationship_context.strip() or None,
                "status": "intake",
                "mediation_state": {},
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status_code=500, detail="Could not create session")
    session = inserted.data[0]
    try:
        save_state(session["id"], new_shared_state(session["id"], session.get("relationship_context")), state_version(session))
    except (PersistError, StateConflict) as exc:
        raise HTTPException(status_code=500, detail="Could not create session") from exc
    _insert_message(
        session["id"],
        "ai",
        "user_a",
        "This is your private room. The other person cannot read it. "
        "Tell me what happened, in English or Hinglish. I will help name the need underneath the frustration.",
    )
    return _session_out(session, Actor("user_a", user_id=user_id))


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    if actor.party == "user_b":
        existing = (
            get_supabase()
            .table("messages")
            .select("id")
            .eq("session_id", session["id"])
            .eq("audience_role", "user_b")
            .limit(1)
            .execute()
        )
        if not existing.data:
            _insert_message(
                session["id"],
                "ai",
                "user_b",
                "This is your private room. The person who invited you cannot read it. "
                "Tell me your side, in English or Hinglish. I will not take sides.",
            )
    return _session_out(session, actor)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
def list_messages(ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    result = (
        get_supabase()
        .table("messages")
        .select("*")
        .eq("session_id", session["id"])
        .eq("audience_role", actor.party)
        .order("created_at")
        .execute()
    )
    return [MessageOut(**row) for row in result.data or []]


def _require_intake(session: dict) -> None:
    if session["status"] == "halted":
        raise HTTPException(status_code=409, detail=HALTED_DETAIL)
    if session["status"] != "intake":
        raise HTTPException(status_code=409, detail="Private intake is closed.")


@router.post("/sessions/{session_id}/messages", response_model=list[MessageOut])
def send_message(body: SendMessageBody, ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    _require_intake(session)

    text = body.content.strip()
    if is_crisis_or_severe_harm(text):
        _halt(session["id"], actor.party, "safety")
        user_row = _insert_message(session["id"], actor.party, actor.party, text)
        ai_row = _insert_message(session["id"], "ai", actor.party, HELP_MESSAGE)
        return [MessageOut(**user_row), MessageOut(**ai_row)]

    user_row = _insert_message(session["id"], actor.party, actor.party, text)
    turn = None
    for attempt in range(2):
        try:
            turn = handle_party_turn(
                party=party_code(actor.party),
                message=text,
                state=load_state(session),
                private=load_private(session["id"], actor.party),
                relationship_context=session.get("relationship_context") or "",
            )
            persist_turn(session["id"], actor.party, turn.state, turn.private, state_version(session))
            break
        except StateConflict:
            # The other party's turn saved first. Re-run once on the fresh state.
            if attempt == 1:
                raise HTTPException(status_code=409, detail="The room was busy. Please send that again.")
            session = load_session(session["id"])
            _require_intake(session)
        except PersistError as exc:
            logger.exception("turn persistence failed for %s", session["id"])
            raise HTTPException(status_code=503, detail="Could not save your conversation. Please try again.") from exc

    assert turn is not None
    if turn.halt:
        _halt(session["id"], actor.party, turn.halt_kind or "safety")
    ai_row = _insert_message(session["id"], "ai", actor.party, turn.reply)
    return [MessageOut(**user_row), MessageOut(**ai_row)]


@router.post("/sessions/{session_id}/ready", response_model=SessionOut)
def mark_ready(body: ReadyBody, ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    _require_intake(session)
    if body.ready and party_code(actor.party) in joint_blocked_by(load_state(session)):
        raise HTTPException(status_code=409, detail=NOT_YET_READY_DETAIL)

    field = "user_a_ready" if actor.party == "user_a" else "user_b_ready"
    updated = (
        get_supabase()
        .table("sessions")
        .update({field: body.ready})
        .eq("id", session["id"])
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=500, detail="Could not update ready state")
    _maybe_build_summary(updated.data[0])
    return _session_out(load_session(session["id"]), actor)


@router.get("/sessions/{session_id}/summary", response_model=JointSummaryOut)
def get_summary(ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, _actor = ctx
    if session["status"] == "halted":
        raise HTTPException(status_code=409, detail=HALTED_DETAIL)
    if session["status"] == "intake":
        raise HTTPException(status_code=409, detail="Waiting for both people to be ready.")
    result = (
        get_supabase()
        .table("joint_summaries")
        .select("*")
        .eq("session_id", session["id"])
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Summary not ready yet")
    row = result.data[0]
    compromises = row.get("compromises") or []
    if isinstance(compromises, str):
        compromises = [compromises]
    return JointSummaryOut(
        user_a_perspective=row["user_a_perspective"],
        user_b_perspective=row["user_b_perspective"],
        compromises=list(compromises),
        created_at=row["created_at"],
    )


@router.post("/sessions/{session_id}/resolve", response_model=SessionOut)
def resolve_session(ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    if session["status"] != "joint_review":
        raise HTTPException(status_code=409, detail="Joint view is not open yet.")
    updated = (
        get_supabase()
        .table("sessions")
        .update({"status": "resolved"})
        .eq("id", session["id"])
        .execute()
    )
    return _session_out(updated.data[0], actor)
