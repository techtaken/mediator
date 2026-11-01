import asyncio
import hashlib
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.agents.pipeline import check_share, draft_share, handle_party_turn, run_joint_pipeline, share_severity
from app.agents.state import (
    append_audit,
    empty_party,
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
from app.agents.telemetry import track_calls
from app.auth import (
    PIN_REQUIRED_DETAIL,
    Actor,
    invite_expired,
    invite_matches,
    load_session,
    parse_time,
    require_logged_in,
    resolve_actor,
)
from app.pin import WEAK_PIN_DETAIL, hash_access_token, hash_pin, new_access_token, verify_pin, weak_pin
from app.ratelimit import limit_messages, limit_session_creation, limit_writes
from app.retention import delete_party_data, delete_room
from app.joint_store import now_iso, seed_ideas
from app.config import get_settings
from app.db import get_supabase
from app.safety import HELP_MESSAGE, HELPLINES, PAUSED_FOR_OTHER_MESSAGE, is_crisis_or_severe_harm, with_helplines
from app.schemas import (
    ApproveShareBody,
    CreateSessionBody,
    DeletedOut,
    LanguageBody,
    JointSummaryOut,
    MessageOut,
    PinBody,
    ReadyBody,
    RoomAccessOut,
    RoomSummaryOut,
    SendMessageBody,
    SessionOut,
    ShareOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

HALTED_DETAIL = "This room has been paused."
INVITE_RESET_DETAIL = "This link no longer works. Ask the person who invited you for a new one."
NOT_YET_READY_DETAIL = "Let's keep talking privately a little longer before the joint session."
APPROVE_FIRST_DETAIL = "Review and approve what you'd like to share first."
ALREADY_SHARED_DETAIL = "You've already shared. Withdraw it first to make changes."

# The one place the parties are told they are talking to an AI and what it
# can't do. Agents are told not to repeat this in every reply.
AI_DISCLOSURE = (
    "I'm an AI mediator: I won't take sides, and I can't give legal, medical or "
    "financial advice. You can stop at any time."
)


AI_DISCLOSURE_BY_LANGUAGE = {
    "hinglish": (
        "Main ek AI mediator hoon: main kisi ka paksh nahi leta, aur legal, medical ya "
        "financial salah nahi de sakta. Aap kabhi bhi ruk sakte hain."
    ),
    "hi": "मैं एक AI मध्यस्थ हूँ: मैं किसी का पक्ष नहीं लेता, और कानूनी, चिकित्सा या आर्थिक सलाह नहीं दे सकता। आप कभी भी रुक सकते हैं।",
}


def welcome_a(topic: str | None, language: str | None = None) -> str:
    if language == "hinglish":
        about = f'Aapne yeh room is baare mein khola: "{topic}". Woh yeh line dekhenge, par yeh chat kabhi nahi.\n\n' if topic else ""
        return (
            "Yeh aapka private room hai. Doosra insaan ise padh nahi sakta.\n\n"
            f"{about}{AI_DISCLOSURE_BY_LANGUAGE['hinglish']}\n\n"
            "Bataiye kya hua."
        )
    if language == "hi":
        about = f'आपने यह कमरा इस बारे में खोला: "{topic}"। वे यह पंक्ति देखेंगे, पर यह चैट कभी नहीं।\n\n' if topic else ""
        return (
            "यह आपका निजी कमरा है। दूसरा व्यक्ति इसे नहीं पढ़ सकता।\n\n"
            f"{about}{AI_DISCLOSURE_BY_LANGUAGE['hi']}\n\n"
            "बताइए क्या हुआ।"
        )
    about = f'You opened this room about: "{topic}". They\'ll see that line, but never this chat.\n\n' if topic else ""
    return (
        "This is your private room. The other person can't read it.\n\n"
        f"{about}{AI_DISCLOSURE}\n\n"
        "Tell me what happened, in English, Hinglish or Hindi."
    )


def welcome_b(topic: str | None, language: str | None = None) -> str:
    if language == "hinglish":
        about = (
            f'Unhone yeh room is baare mein khola: "{topic}". Yeh unka nazariya hai. Yahan aap apni baat rakh sakte hain.\n\n'
            if topic
            else "Unhone yeh room aapke saath baat karne ke liye khola hai. Yahan aap apni baat rakh sakte hain.\n\n"
        )
        return (
            "Yeh aapka private room hai. Jinhone aapko invite kiya, woh ise padh nahi sakte.\n\n"
            f"{about}{AI_DISCLOSURE_BY_LANGUAGE['hinglish']}"
        )
    if language == "hi":
        about = (
            f'उन्होंने यह कमरा इस बारे में खोला: "{topic}"। यह उनका नज़रिया है। यहाँ आप अपनी बात रख सकते हैं।\n\n'
            if topic
            else "उन्होंने यह कमरा आपसे बात करने के लिए खोला है। यहाँ आप अपनी बात रख सकते हैं।\n\n"
        )
        return f"यह आपका निजी कमरा है। जिन्होंने आपको बुलाया है, वे इसे नहीं पढ़ सकते।\n\n{about}{AI_DISCLOSURE_BY_LANGUAGE['hi']}"
    about = (
        f'They opened this room about: "{topic}". That\'s how they see it. Here you can tell your side.\n\n'
        if topic
        else "They opened this room to talk something through with you. Here you can tell your side.\n\n"
    )
    return (
        "This is your private room. The person who invited you can't read it.\n\n"
        f"{about}{AI_DISCLOSURE}"
    )


def language_field(party_role: str) -> str:
    return "language_a" if party_role == "user_a" else "language_b"


def get_actor(
    session_id: str,
    authorization: Annotated[str | None, Header()] = None,
    x_invite_token: Annotated[str | None, Header()] = None,
    x_room_access: Annotated[str | None, Header()] = None,
) -> tuple[dict, Actor]:
    return resolve_actor(session_id, authorization, x_invite_token, x_room_access)


def get_entry_actor(
    session_id: str,
    authorization: Annotated[str | None, Header()] = None,
    x_invite_token: Annotated[str | None, Header()] = None,
    x_room_access: Annotated[str | None, Header()] = None,
) -> tuple[dict, Actor]:
    """Also lets in someone holding an unused invite link who hasn't chosen a
    PIN yet. Only for what they need to decide whether to join."""
    return resolve_actor(session_id, authorization, x_invite_token, x_room_access, allow_limited=True)


def _invite_link(session_id: str, token: str) -> str:
    base = get_settings().frontend_base_url.rstrip("/")
    return f"{base}/join/{session_id}?token={token}"


def _halt_view(session: dict, actor: Actor) -> str | None:
    if session["status"] != "halted":
        return None
    if actor.limited:
        return "other"
    halted_for = session.get("halted_for")
    # Rooms halted before halted_for existed: show support, the safer default.
    if halted_for is None or halted_for == actor.party:
        return "self"
    return "other"


def _other_joined(session: dict) -> bool:
    return bool(session.get("consented_b_at"))


def _session_out(session: dict, actor: Actor) -> SessionOut:
    invite = None
    expired = actor.party == "user_a" and invite_expired(session)
    # Once the other person has joined, or the link has expired, there's
    # nothing left for Person A to send.
    if actor.party == "user_a" and not _other_joined(session) and not expired:
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
        my_share=None if actor.limited else _get_share(session["id"], actor.party).get("approved_text"),
        i_consented=bool(session.get(_consent_field(actor.party))),
        invite_expires_at=session.get("invite_expires_at") if invite else None,
        other_joined=_other_joined(session) if actor.party == "user_a" else True,
        invite_expired=expired,
        needs_pin=actor.limited,
        retention_days=get_settings().retention_days,
        my_data_deleted=bool(session.get(_deleted_field(actor.party))),
        my_language=session.get(language_field(actor.party)),
    )


def _deleted_field(party_role: str) -> str:
    return "data_deleted_a_at" if party_role == "user_a" else "data_deleted_b_at"


def _invite_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=get_settings().invite_ttl_days)).isoformat()


def _consent_field(party_role: str) -> str:
    return "consented_a_at" if party_role == "user_a" else "consented_b_at"


def _require_consent(session: dict, actor: Actor) -> None:
    if not session.get(_consent_field(actor.party)):
        raise HTTPException(status_code=409, detail="Please read how Mediator works and accept it first.")


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


def _claim_joint(session: dict) -> dict | None:
    """Atomically move a ready room to building_joint. Returns the claimed row,
    or None if it isn't ready or another request already claimed it."""
    if session["status"] != "intake":
        return None
    if not (session["user_a_ready"] and session["user_b_ready"]):
        return None
    state = load_state(session)
    if joint_blocked_by(state):
        return None
    shares = state.get("approved_shares") or {}
    if not (shares.get("A") and shares.get("B")):
        return None
    claimed = (
        get_supabase()
        .table("sessions")
        .update({"status": "building_joint"})
        .eq("id", session["id"])
        .eq("status", "intake")
        .eq("user_a_ready", True)
        .eq("user_b_ready", True)
        .execute()
    )
    return claimed.data[0] if claimed.data else None


def _build_joint(session: dict) -> bool:
    """Build the joint view for a claimed room. On failure, reopen the room so
    the build can be retried. Never raises: it runs as a background task."""
    sid = session["id"]
    supabase = get_supabase()
    try:
        with track_calls(sid):
            built = run_joint_pipeline(
                state=load_state(session),
                languages={"A": session.get("language_a"), "B": session.get("language_b")},
            )
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
        opened = (
            supabase.table("sessions")
            .update({"status": "joint_review"})
            .eq("id", sid)
            .eq("status", "building_joint")
            .execute()
        )
        if not opened.data:
            # The room was stopped (or data deleted) while this ran. Nobody has
            # seen this joint view, so don't keep it.
            supabase.table("joint_ideas").delete().eq("session_id", sid).execute()
            supabase.table("joint_summaries").delete().eq("session_id", sid).execute()
            return False
        return True
    except Exception:
        logger.exception("joint build failed for %s", sid)
        supabase.table("sessions").update({"status": "intake"}).eq("id", sid).eq("status", "building_joint").execute()
        return False


def _maybe_build_summary(session: dict) -> bool:
    """Claim and build in one go (used where waiting is fine)."""
    claimed = _claim_joint(session)
    return _build_joint(claimed) if claimed else False


@router.post("/sessions", response_model=SessionOut)
def create_session(body: CreateSessionBody, user_id: str = Depends(require_logged_in)):
    limit_session_creation(user_id)
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
                "invite_expires_at": _invite_expiry(),
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
def get_session(ctx: tuple[dict, Actor] = Depends(get_entry_actor)):
    session, actor = ctx
    if actor.party == "user_b" and session["status"] == "intake" and not session.get(_deleted_field("user_b")):
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


def _require_same_invited_person(session: dict, actor: Actor) -> None:
    """The invite can be reset during a slow model call. What that call produced
    belongs to the person who was here, so it mustn't be saved where the next
    person through the new link could read it."""
    if actor.party != "user_b":
        return
    if load_session(session["id"]).get("invite_token_b") != session.get("invite_token_b"):
        raise HTTPException(status_code=409, detail=INVITE_RESET_DETAIL)


def _require_intake(session: dict) -> None:
    if session["status"] == "halted":
        raise HTTPException(status_code=409, detail=HALTED_DETAIL)
    if session["status"] != "intake":
        raise HTTPException(status_code=409, detail="Private intake is closed.")


@router.post("/sessions/{session_id}/messages", response_model=list[MessageOut])
def send_message(body: SendMessageBody, ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    _require_intake(session)
    _require_consent(session, actor)
    if session["user_a_ready" if actor.party == "user_a" else "user_b_ready"]:
        raise HTTPException(status_code=409, detail="You've already shared. Withdraw it to keep talking.")

    limit_messages(session["id"], actor.party)
    text = body.content.strip()
    if is_crisis_or_severe_harm(text):
        _halt(session["id"], actor.party, "safety")
        user_row = _insert_message(session["id"], actor.party, actor.party, text)
        ai_row = _insert_message(session["id"], "ai", actor.party, HELP_MESSAGE)
        return [MessageOut(**user_row), MessageOut(**ai_row)]

    user_row = _insert_message(session["id"], actor.party, actor.party, text)
    started = session
    turn = None
    for attempt in range(2):
        try:
            with track_calls(session["id"]):
                turn = handle_party_turn(
                    party=party_code(actor.party),
                    message=text,
                    state=load_state(session),
                    private=load_private(session["id"], actor.party),
                    relationship_context=session.get("relationship_context") or "",
                    topic=session.get("topic"),
                    language=session.get(language_field(actor.party)),
                )
            _require_same_invited_person(started, actor)
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
    _require_consent(session, actor)
    limit_writes(session["id"], actor.party)
    existing = _get_share(session["id"], actor.party)
    if existing.get("approved_text"):
        raise HTTPException(status_code=409, detail=ALREADY_SHARED_DETAIL)
    try:
        private = load_private(session["id"], actor.party)
    except PersistError as exc:
        raise HTTPException(status_code=503, detail="Could not load your conversation. Please try again.") from exc

    state = load_state(session)
    with track_calls(session["id"]):
        drafted = draft_share(
            party=party_code(actor.party),
            transcript=_own_transcript(session["id"], actor.party),
            private=private,
            topic=session.get("topic"),
            state=state,
            language=session.get(language_field(actor.party)),
        )
    _require_same_invited_person(session, actor)
    try:
        save_state(session["id"], state, state_version(session))
    except (StateConflict, PersistError):
        logger.warning("could not save draft audit for %s", session["id"])
    if drafted is None:
        return ShareOut(draft=None)
    _upsert_share(session["id"], actor.party, draft_text=drafted["summary"])
    return ShareOut(draft=drafted["summary"], left_out=drafted["left_out"])


@router.post("/sessions/{session_id}/share/approve", response_model=SessionOut)
def approve_my_share(
    body: ApproveShareBody,
    background: BackgroundTasks,
    ctx: tuple[dict, Actor] = Depends(get_actor),
):
    """Approve the exact text the other person will see, and mark this party ready.

    The text is safety-checked first. If that check can't run, nothing is shared.
    """
    session, actor = ctx
    _require_intake(session)
    _require_consent(session, actor)
    limit_writes(session["id"], actor.party)
    if _get_share(session["id"], actor.party).get("approved_text"):
        raise HTTPException(status_code=409, detail=ALREADY_SHARED_DETAIL)
    code = party_code(actor.party)
    text = body.text
    state = load_state(session)
    if code in joint_blocked_by(state):
        raise HTTPException(status_code=409, detail=NOT_YET_READY_DETAIL)

    try:
        with track_calls(session["id"]):
            safety = check_share(party=code, text=text, state=state)
    except Exception as exc:
        logger.exception("share safety check failed for %s", session["id"])
        raise HTTPException(status_code=503, detail="We couldn't check your text just now. Please try again.") from exc
    _require_same_invited_person(session, actor)

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
    # If both have now shared, build the joint view after responding so this
    # person isn't kept waiting on several model calls. Failures reopen the
    # room, and the waiting screen can retry via POST /joint.
    claimed = _claim_joint(updated.data[0])
    if claimed:
        background.add_task(_build_joint, claimed)
    return _session_out(load_session(session["id"]), actor)


@router.post("/sessions/{session_id}/joint", response_model=SessionOut)
def build_joint(background: BackgroundTasks, ctx: tuple[dict, Actor] = Depends(get_actor)):
    """Retry building the joint view once both parties have shared."""
    session, actor = ctx
    claimed = _claim_joint(session)
    if claimed:
        background.add_task(_build_joint, claimed)
    return _session_out(load_session(session["id"]), actor)


@router.get("/sessions", response_model=list[RoomSummaryOut])
def my_rooms(user_id: str = Depends(require_logged_in)):
    """Rooms the signed-in person opened, newest first."""
    rows = (
        get_supabase()
        .table("sessions")
        .select("id, status, topic, created_at, user_a_ready, user_b_ready, consented_b_at, invite_expires_at")
        .eq("created_by", user_id)
        .order("created_at", desc=True)
        .limit(50)
        .execute()
        .data
        or []
    )
    return [
        RoomSummaryOut(
            id=row["id"],
            status=row["status"],
            topic=row.get("topic"),
            created_at=row["created_at"],
            user_a_ready=row["user_a_ready"],
            user_b_ready=row["user_b_ready"],
            other_joined=_other_joined(row),
            invite_expired=invite_expired(row),
        )
        for row in rows
    ]


@router.post("/sessions/{session_id}/consent", response_model=SessionOut)
def accept_terms(ctx: tuple[dict, Actor] = Depends(get_actor)):
    """Record that this party read and accepted how Mediator works."""
    session, actor = ctx
    field = _consent_field(actor.party)
    if not session.get(field):
        get_supabase().table("sessions").update({field: now_iso()}).eq("id", session["id"]).execute()
    return _session_out(load_session(session["id"]), actor)


def _issue_room_access(session_id: str) -> RoomAccessOut:
    token = new_access_token()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=get_settings().pin_access_ttl_minutes)).isoformat()
    supabase = get_supabase()
    supabase.table("room_access_tokens").delete().eq("session_id", session_id).lt("expires_at", now_iso()).execute()
    supabase.table("room_access_tokens").insert(
        {"token_hash": hash_access_token(token), "session_id": session_id, "expires_at": expires_at}
    ).execute()
    return RoomAccessOut(access_token=token, expires_at=expires_at)


@router.post("/sessions/{session_id}/claim", response_model=RoomAccessOut)
def claim_room(body: PinBody, ctx: tuple[dict, Actor] = Depends(get_entry_actor)):
    """The first person through the invite link accepts how Mediator works and
    chooses a PIN. From then on the link alone opens nothing, so the person who
    sent it can't read this person's private chat."""
    session, actor = ctx
    sid = session["id"]
    if actor.party != "user_b":
        raise HTTPException(status_code=403, detail="Only the invited person can choose a PIN.")
    if not actor.limited:
        raise HTTPException(status_code=409, detail="You've already chosen a PIN.")
    if session["status"] == "halted" and not _other_joined(session):
        raise HTTPException(status_code=409, detail=HALTED_DETAIL)
    if weak_pin(body.pin):
        raise HTTPException(status_code=400, detail=WEAK_PIN_DETAIL)
    limit_writes(sid, actor.party)
    # Two people can open the link at once; only the first gets the room.
    claimed = (
        get_supabase()
        .table("sessions")
        .update(
            {
                "b_pin_hash": hash_pin(body.pin),
                "b_pin_set_at": now_iso(),
                "consented_b_at": session.get("consented_b_at") or now_iso(),
            }
        )
        .eq("id", sid)
        .eq("invite_token_b", actor.invite_token)
        .is_("b_pin_hash", "null")
        .execute()
    )
    if not claimed.data:
        raise HTTPException(status_code=423, detail=PIN_REQUIRED_DETAIL)
    return _issue_room_access(sid)


def _count_pin_attempt(session: dict) -> int:
    """Count this try before checking the PIN, one request at a time, so guessing
    in parallel can't get past the limit. Returns the tries left."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    locked_until = parse_time(session.get("b_pin_locked_until"))
    if locked_until and locked_until > now:
        minutes = int((locked_until - now).total_seconds() // 60) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Too many wrong tries. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
            headers={"Retry-After": str(minutes * 60)},
        )
    attempts = int(session.get("b_pin_failed_attempts") or 0)
    used = attempts + 1
    lock = used >= settings.pin_max_attempts
    counted = (
        get_supabase()
        .table("sessions")
        .update(
            {
                "b_pin_failed_attempts": 0 if lock else used,
                "b_pin_locked_until": (now + timedelta(minutes=settings.pin_lock_minutes)).isoformat() if lock else None,
            }
        )
        .eq("id", session["id"])
        .eq("b_pin_failed_attempts", attempts)
        .execute()
    )
    if not counted.data:
        raise HTTPException(status_code=409, detail="Please try again.")
    return max(0, settings.pin_max_attempts - used)


@router.post("/sessions/{session_id}/unlock", response_model=RoomAccessOut)
def unlock_room(
    session_id: str,
    body: PinBody,
    x_invite_token: Annotated[str | None, Header()] = None,
):
    """Link + PIN: a short-lived token that opens the invited person's room."""
    session = load_session(session_id)
    if not invite_matches(session, x_invite_token):
        raise HTTPException(status_code=403, detail=INVITE_RESET_DETAIL)
    stored = session.get("b_pin_hash")
    if not stored:
        raise HTTPException(status_code=409, detail="This room doesn't have a PIN yet.")
    tries_left = _count_pin_attempt(session)
    if not verify_pin(body.pin, stored):
        if tries_left == 0:
            minutes = get_settings().pin_lock_minutes
            raise HTTPException(status_code=429, detail=f"Too many wrong tries. Try again in {minutes} minutes.")
        raise HTTPException(
            status_code=401,
            detail=f"That PIN isn't right. {tries_left} {'try' if tries_left == 1 else 'tries'} left.",
        )
    get_supabase().table("sessions").update({"b_pin_failed_attempts": 0, "b_pin_locked_until": None}).eq(
        "id", session_id
    ).execute()
    return _issue_room_access(session_id)


STOPPABLE = ("intake", "building_joint", "joint_review")


def _stop(session: dict, actor: Actor, kind: str, reason: str) -> SessionOut:
    """Stop the room for both people. Only the person who stopped it sees why."""
    if session["status"] not in STOPPABLE:
        raise HTTPException(status_code=409, detail="This session has already ended.")
    _update_state(session, lambda state: append_audit(state, {"stage": state.get("stage"), "agent": kind.upper(), "reason": reason}))
    _halt(session["id"], actor.party, kind)
    return _session_out(load_session(session["id"]), actor)


@router.post("/sessions/{session_id}/leave", response_model=SessionOut)
def leave_session(ctx: tuple[dict, Actor] = Depends(get_actor)):
    """Either person can stop at any time (R2: participation is voluntary)."""
    session, actor = ctx
    return _stop(session, actor, "withdrawn", f"{actor.party} left the session")


@router.post("/sessions/{session_id}/human", response_model=SessionOut)
def ask_for_a_person(ctx: tuple[dict, Actor] = Depends(get_actor)):
    """Pause the room and flag it for the Mediator team (shown as a referral in admin)."""
    session, actor = ctx
    return _stop(session, actor, "referral", f"{actor.party} asked to talk to a person")


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


@router.post("/sessions/{session_id}/invite/rotate", response_model=SessionOut)
def rotate_invite(ctx: tuple[dict, Actor] = Depends(get_actor)):
    """Person A replaces the invite link; the old one stops working at once.

    If someone already joined with it (the wrong person, or they lost their
    PIN), everything on their side is deleted, so the new link opens an empty
    room and Person A never sees what was written. Safety flags stay. Once they
    have shared their side it can't be reset: A can delete the room instead.
    """
    session, actor = ctx
    sid = session["id"]
    if actor.party != "user_a":
        raise HTTPException(status_code=403, detail="Only the person who opened the room can change the link.")
    if session["status"] != "intake":
        raise HTTPException(status_code=409, detail="This room is no longer open to new people.")
    if session.get("user_b_ready") or _get_share(sid, "user_b").get("approved_text"):
        raise HTTPException(
            status_code=409,
            detail="They've already shared their side, so the invite can't be reset. If they can't get back in, you can delete this room and start a new one.",
        )
    limit_writes(sid, actor.party)

    def reset(state: dict) -> None:
        state.setdefault("parties", {})["B"] = empty_party()
        state.setdefault("signals", {}).setdefault("turns", {})["B"] = 0
        append_audit(state, {"stage": state.get("stage"), "agent": "INVITE", "type": "invite_rotated"})

    # Saving the state first makes any turn still running for them fail to save.
    _update_state(session, reset)
    delete_party_data(sid, "user_b", keep_approved_share=False)
    supabase = get_supabase()
    supabase.table("room_access_tokens").delete().eq("session_id", sid).execute()
    supabase.table("sessions").update(
        {
            "invite_token_b": secrets.token_hex(24),
            "invite_expires_at": _invite_expiry(),
            "invite_rotated_at": now_iso(),
            "b_pin_hash": None,
            "b_pin_set_at": None,
            "b_pin_failed_attempts": 0,
            "b_pin_locked_until": None,
            "consented_b_at": None,
            "language_b": None,
            "data_deleted_b_at": None,
        }
    ).eq("id", sid).execute()
    # Anything a request already under way wrote after the first delete goes too.
    delete_party_data(sid, "user_b", keep_approved_share=False)
    return _session_out(load_session(sid), actor)


@router.post("/sessions/{session_id}/delete-my-data", response_model=SessionOut)
def delete_my_data(ctx: tuple[dict, Actor] = Depends(get_actor)):
    """Delete this person's private chat, private memory and share drafts.

    An open room is ended for both people first (the other person sees only a
    neutral pause). Words this person approved that the other has already read
    in the joint view stay there, since they were shared with consent.
    """
    session, actor = ctx
    sid = session["id"]
    code = party_code(actor.party)
    shared_already = session["status"] in ("joint_review", "resolved") or (
        session["status"] == "halted" and bool(_joint_exists(sid))
    )

    def forget(state: dict) -> None:
        if not shared_already:
            set_approved_share(state, code, None)
        append_audit(state, {"stage": state.get("stage"), "agent": "PARTY", "type": f"data_deleted_{actor.party}"})

    _update_state(session, forget)
    if session["status"] in STOPPABLE:
        _halt(sid, actor.party, "withdrawn")
    delete_party_data(sid, actor.party, keep_approved_share=shared_already)
    update = {_deleted_field(actor.party): now_iso()}
    if not shared_already:
        update["user_a_ready" if actor.party == "user_a" else "user_b_ready"] = False
    get_supabase().table("sessions").update(update).eq("id", sid).execute()
    return _session_out(load_session(sid), actor)


def _joint_exists(session_id: str) -> bool:
    rows = get_supabase().table("joint_summaries").select("session_id").eq("session_id", session_id).limit(1).execute()
    return bool(rows.data)


@router.delete("/sessions/{session_id}", response_model=DeletedOut)
def delete_whole_room(ctx: tuple[dict, Actor] = Depends(get_actor)):
    """Person A deletes the room and everything in it, for both people."""
    session, actor = ctx
    if actor.party != "user_a":
        raise HTTPException(status_code=403, detail="Only the person who opened the room can delete it.")
    delete_room(session["id"])
    return DeletedOut(deleted=True)


@router.post("/sessions/{session_id}/language", response_model=SessionOut)
def set_language(body: LanguageBody, ctx: tuple[dict, Actor] = Depends(get_entry_actor)):
    """This person's language for the mediator's replies and share draft.

    If they haven't written anything yet, their welcome message is replaced
    with the same welcome in that language.
    """
    session, actor = ctx
    sid = session["id"]
    supabase = get_supabase()
    supabase.table("sessions").update({language_field(actor.party): body.language}).eq("id", sid).execute()
    rows = (
        supabase.table("messages")
        .select("id, sender_role")
        .eq("session_id", sid)
        .eq("audience_role", actor.party)
        .order("created_at")
        .execute()
        .data
        or []
    )
    if rows and not any(row["sender_role"] == actor.party for row in rows) and rows[0]["sender_role"] == "ai":
        welcome = welcome_a if actor.party == "user_a" else welcome_b
        supabase.table("messages").update({"content": welcome(session.get("topic"), body.language)}).eq(
            "id", rows[0]["id"]
        ).execute()
    return _session_out(load_session(sid), actor)


# --- Live updates ----------------------------------------------------------

SSE_POLL_SECONDS = 1.5
SSE_KEEPALIVE_SECONDS = 15


def _sse_limits() -> tuple[float, float]:
    return float(get_settings().sse_max_seconds), SSE_POLL_SECONDS


def _room_fingerprint(session_id: str, party_role: str) -> str:
    """A hash of what this person can see in the room right now.

    Only things already visible to them go in: never the other person's
    message count, state version or other activity, so the timing of events
    reveals nothing about what the other person is doing in private.
    """
    supabase = get_supabase()
    session = load_session(session_id)
    mine = (
        supabase.table("messages").select("id").eq("session_id", session_id).eq("audience_role", party_role).execute().data
        or []
    )
    parts: list = [
        session["status"],
        session.get("user_a_ready"),
        session.get("user_b_ready"),
        session.get("halted_for"),
        session.get(_consent_field(party_role)),
        session.get(language_field(party_role)),
        session.get("invite_token_b") if party_role == "user_a" else None,
        bool(session.get("consented_b_at")) if party_role == "user_a" else None,
        len(mine),
        mine[-1]["id"] if mine else None,
    ]
    if session["status"] in ("joint_review", "resolved", "building_joint"):
        ideas = supabase.table("joint_ideas").select("id").eq("session_id", session_id).execute().data or []
        answers = (
            supabase.table("idea_responses").select("idea_id, party_role, response, note").eq("session_id", session_id).execute().data
            or []
        )
        agreement = supabase.table("agreements").select("version, signed_a_at, signed_b_at").eq("session_id", session_id).execute().data
        summary = supabase.table("joint_summaries").select("session_id").eq("session_id", session_id).execute().data
        parts += [
            sorted(row["id"] for row in ideas),
            sorted((row["idea_id"], row["party_role"], row.get("response"), row.get("note")) for row in answers),
            agreement,
            bool(summary),
        ]
    if session["status"] == "resolved":
        followups = (
            supabase.table("followups").select("round, status, party_role").eq("session_id", session_id).execute().data or []
        )
        # The other person's check-in only shows as "answered or not".
        parts.append(sorted((row["round"], row["party_role"], row["status"] == "answered") for row in followups))
    return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()[:16]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/sessions/{session_id}/events")
async def room_events(request: Request, ctx: tuple[dict, Actor] = Depends(get_actor)):
    """Server-sent events: a `change` event whenever this person's view changes.

    Browsers can't send Authorization / X-Invite-Token with EventSource, so the
    frontend reads this with fetch. The stream closes after SSE_MAX_SECONDS
    (the client reconnects); clients fall back to polling if it fails.
    """
    session, actor = ctx
    sid, party = session["id"], actor.party
    max_seconds, poll = _sse_limits()

    async def stream():
        yield "retry: 3000\n\n"
        last, started, beat = None, time.monotonic(), time.monotonic()
        while time.monotonic() - started < max_seconds:
            if await request.is_disconnected():
                return
            try:
                fingerprint = await run_in_threadpool(_room_fingerprint, sid, party)
            except HTTPException as exc:
                if exc.status_code == 404:
                    yield _sse("gone", {})
                    return
                fingerprint = last
            except Exception:
                logger.exception("live update check failed for %s", sid)
                fingerprint = last
            if fingerprint != last:
                last, beat = fingerprint, time.monotonic()
                yield _sse("change", {"v": fingerprint})
            elif time.monotonic() - beat >= SSE_KEEPALIVE_SECONDS:
                beat = time.monotonic()
                yield ": keepalive\n\n"
            await asyncio.sleep(poll)
        yield _sse("reconnect", {})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
