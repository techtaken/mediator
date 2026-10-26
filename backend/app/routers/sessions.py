import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from datetime import datetime, timezone

from app.agents.pipeline import check_share, draft_share, handle_party_turn, run_joint_pipeline, share_severity
from app.agents.state import (
    joint_blocked_by,
    new_shared_state,
    party_code,
    record_safety_flag,
    set_approved_share,
)
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
from app.joint_store import seed_ideas
from app.config import get_settings
from app.db import get_supabase
from app.safety import HELP_MESSAGE, HELPLINES, PAUSED_FOR_OTHER_MESSAGE, is_crisis_or_severe_harm, with_helplines
from app.schemas import (
    ApproveShareBody,
    CreateSessionBody,
    JointSummaryOut,
    MessageOut,
    ReadyBody,
    SendMessageBody,
    SessionOut,
    ShareOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

HALTED_DETAIL = "This room has been paused."
NOT_YET_READY_DETAIL = "Let's keep talking privately a little longer before the joint session."
APPROVE_FIRST_DETAIL = "Review and approve what you'd like to share first."
ALREADY_SHARED_DETAIL = "You've already shared. Withdraw it first to make changes."

# The one place the parties are told they are talking to an AI and what it
# can't do. Agents are told not to repeat this in every reply.
AI_DISCLOSURE = (
    "I'm an AI mediator: I won't take sides, and I can't give legal, medical or "
    "financial advice. You can stop at any time."
)


def welcome_a(topic: str | None) -> str:
    about = f'You opened this room about: "{topic}". They\'ll see that line, but never this chat.\n\n' if topic else ""
    return (
        "This is your private room. The other person can't read it.\n\n"
        f"{about}{AI_DISCLOSURE}\n\n"
        "Tell me what happened, in English or Hinglish."
    )


def welcome_b(topic: str | None) -> str:
    about = (
        f'They opened this room about: "{topic}". That\'s how they see it. Here you can tell your side.\n\n'
        if topic
        else "They opened this room to talk something through with you. Here you can tell your side.\n\n"
    )
    return (
        "This is your private room. The person who invited you can't read it.\n\n"
        f"{about}{AI_DISCLOSURE}"
    )


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
        topic=session.get("topic"),
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
        my_share=_get_share(session["id"], actor.party).get("approved_text"),
    )


def _get_share(session_id: str, party_role: str) -> dict:
    rows = (
        get_supabase()
        .table("party_shares")
        .select("*")
        .eq("session_id", session_id)
        .eq("party_role", party_role)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else {}


def _upsert_share(session_id: str, party_role: str, **fields) -> None:
    get_supabase().table("party_shares").upsert(
        {
            "session_id": session_id,
            "party_role": party_role,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **fields,
        },
        on_conflict="session_id,party_role",
    ).execute()


def _own_transcript(session_id: str, party_role: str) -> str:
    rows = (
        get_supabase()
        .table("messages")
        .select("sender_role, content")
        .eq("session_id", session_id)
        .eq("audience_role", party_role)
        .order("created_at")
        .execute()
        .data
        or []
    )
    return "\n".join(
        f"{'Them' if row['sender_role'] == party_role else 'Mediator'}: {row['content']}" for row in rows
    )


def _update_state(session: dict, change) -> dict:
    """Apply `change(state)` and save it, re-reading once if another write won."""
    for attempt in range(2):
        state = load_state(session)
        change(state)
        try:
            save_state(session["id"], state, state_version(session))
            return state
        except StateConflict:
            if attempt == 1:
                raise HTTPException(status_code=409, detail="The room was busy. Please try again.")
            session = load_session(session["id"])
        except PersistError as exc:
            raise HTTPException(status_code=503, detail="Could not save. Please try again.") from exc
    raise AssertionError("unreachable")


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
    state = load_state(session)
    if joint_blocked_by(state):
        return
    shares = state.get("approved_shares") or {}
    if not (shares.get("A") and shares.get("B")):
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
                "common_ground": built.get("common_ground"),
                "compromises": built["compromises"],
            },
            on_conflict="session_id",
        ).execute()
        seed_ideas(sid, built["compromises"])
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
                "topic": body.topic.strip(),
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
        welcome_a(session.get("topic")),
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
                welcome_b(session.get("topic")),
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
    if session["user_a_ready" if actor.party == "user_a" else "user_b_ready"]:
        raise HTTPException(status_code=409, detail="You've already shared. Withdraw it to keep talking.")

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
                topic=session.get("topic"),
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
    """Withdraw readiness (and the approved share). Becoming ready goes through
    POST /share/approve, so nobody is ready without approving what is shared."""
    session, actor = ctx
    _require_intake(session)
    if body.ready:
        raise HTTPException(status_code=409, detail=APPROVE_FIRST_DETAIL)
    code = party_code(actor.party)
    _update_state(session, lambda state: set_approved_share(state, code, None))
    _upsert_share(session["id"], actor.party, approved_text=None, approved_at=None)
    field = "user_a_ready" if actor.party == "user_a" else "user_b_ready"
    get_supabase().table("sessions").update({field: False}).eq("id", session["id"]).execute()
    return _session_out(load_session(session["id"]), actor)


@router.get("/sessions/{session_id}/share", response_model=ShareOut)
def get_share(ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    row = _get_share(session["id"], actor.party)
    return ShareOut(draft=row.get("draft_text"), approved=row.get("approved_text"), approved_at=row.get("approved_at"))


@router.post("/sessions/{session_id}/share/draft", response_model=ShareOut)
def draft_my_share(ctx: tuple[dict, Actor] = Depends(get_actor)):
    """Draft what the other person would see, from this party's own chat only."""
    session, actor = ctx
    _require_intake(session)
    existing = _get_share(session["id"], actor.party)
    if existing.get("approved_text"):
        raise HTTPException(status_code=409, detail=ALREADY_SHARED_DETAIL)
    try:
        private = load_private(session["id"], actor.party)
    except PersistError as exc:
        raise HTTPException(status_code=503, detail="Could not load your conversation. Please try again.") from exc

    state = load_state(session)
    drafted = draft_share(
        party=party_code(actor.party),
        transcript=_own_transcript(session["id"], actor.party),
        private=private,
        topic=session.get("topic"),
        state=state,
    )
    try:
        save_state(session["id"], state, state_version(session))
    except (StateConflict, PersistError):
        logger.warning("could not save draft audit for %s", session["id"])
    if drafted is None:
        return ShareOut(draft=None)
    _upsert_share(session["id"], actor.party, draft_text=drafted["summary"])
    return ShareOut(draft=drafted["summary"], left_out=drafted["left_out"])


@router.post("/sessions/{session_id}/share/approve", response_model=SessionOut)
def approve_my_share(body: ApproveShareBody, ctx: tuple[dict, Actor] = Depends(get_actor)):
    """Approve the exact text the other person will see, and mark this party ready.

    The text is safety-checked first. If that check can't run, nothing is shared.
    """
    session, actor = ctx
    _require_intake(session)
    if _get_share(session["id"], actor.party).get("approved_text"):
        raise HTTPException(status_code=409, detail=ALREADY_SHARED_DETAIL)
    code = party_code(actor.party)
    text = body.text
    state = load_state(session)
    if code in joint_blocked_by(state):
        raise HTTPException(status_code=409, detail=NOT_YET_READY_DETAIL)

    try:
        safety = check_share(party=code, text=text, state=state)
    except Exception as exc:
        logger.exception("share safety check failed for %s", session["id"])
        raise HTTPException(status_code=503, detail="We couldn't check your text just now. Please try again.") from exc

    severity = share_severity(safety)
    if severity >= 3:
        _update_state(session, lambda state: record_safety_flag(state, code, {**safety, "severity": 3}))
        _halt(session["id"], actor.party, "safety")
        _insert_message(session["id"], "ai", actor.party, with_helplines(safety.get("message_to_affected_party")))
        return _session_out(load_session(session["id"]), actor)
    if severity == 2:
        _update_state(session, lambda state: record_safety_flag(state, code, {**safety, "severity": 2}))
        raise HTTPException(status_code=409, detail=NOT_YET_READY_DETAIL)

    def approve(state: dict) -> None:
        if severity:
            record_safety_flag(state, code, {**safety, "severity": severity})
        set_approved_share(state, code, text)

    _update_state(session, approve)
    _upsert_share(
        session["id"],
        actor.party,
        draft_text=text,
        approved_text=text,
        approved_at=datetime.now(timezone.utc).isoformat(),
    )
    field = "user_a_ready" if actor.party == "user_a" else "user_b_ready"
    updated = get_supabase().table("sessions").update({field: True}).eq("id", session["id"]).execute()
    if not updated.data:
        raise HTTPException(status_code=500, detail="Could not update ready state")
    try:
        _maybe_build_summary(updated.data[0])
    except HTTPException:
        # The share is saved and this party is ready. The joint view can be
        # retried from the waiting screen via POST /joint.
        pass
    return _session_out(load_session(session["id"]), actor)


@router.post("/sessions/{session_id}/joint", response_model=SessionOut)
def build_joint(ctx: tuple[dict, Actor] = Depends(get_actor)):
    """Retry building the joint view once both parties have shared."""
    session, actor = ctx
    if session["status"] == "intake":
        _maybe_build_summary(session)
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
        common_ground=row.get("common_ground"),
        compromises=list(compromises),
        created_at=row["created_at"],
    )
