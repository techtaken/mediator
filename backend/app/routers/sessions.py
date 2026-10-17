from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from app.auth import Actor, require_logged_in, resolve_actor
from app.config import get_settings
from app.db import get_supabase
from app.gemini_client import generate_intake_reply, generate_joint_summary
from app.safety import HELP_MESSAGE, is_crisis_or_severe_harm
from app.schemas import (
    CreateSessionBody,
    JointSummaryOut,
    MessageOut,
    ReadyBody,
    SendMessageBody,
    SessionOut,
)

router = APIRouter(prefix="/api")


def get_actor(
    session_id: str,
    authorization: Annotated[str | None, Header()] = None,
    x_invite_token: Annotated[str | None, Header()] = None,
) -> tuple[dict, Actor]:
    return resolve_actor(session_id, authorization, x_invite_token)


def _invite_link(session_id: str, token: str) -> str:
    base = get_settings().frontend_base_url.rstrip("/")
    return f"{base}/join/{session_id}?token={token}"


def _session_out(session: dict, actor: Actor) -> SessionOut:
    invite = None
    if actor.party == "user_a":
        invite = _invite_link(session["id"], session["invite_token_b"])
    return SessionOut(
        id=session["id"],
        status=session["status"],
        relationship_context=session.get("relationship_context"),
        created_at=session["created_at"],
        user_a_ready=session["user_a_ready"],
        user_b_ready=session["user_b_ready"],
        party=actor.party,
        invite_link=invite,
        halted_reason=session.get("halted_reason"),
    )


def _halt(session_id: str) -> None:
    get_supabase().table("sessions").update(
        {"status": "halted", "halted_reason": "safety"}
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
    if session["status"] == "halted":
        return
    if not (session["user_a_ready"] and session["user_b_ready"]):
        return
    if session["status"] == "joint_review":
        return

    sid = session["id"]
    summary = generate_joint_summary(
        relationship_context=session.get("relationship_context") or "",
        transcript_a=_transcript(sid, "user_a"),
        transcript_b=_transcript(sid, "user_b"),
    )
    supabase = get_supabase()
    existing = (
        supabase.table("joint_summaries").select("id").eq("session_id", sid).limit(1).execute()
    )
    payload = {
        "session_id": sid,
        "user_a_perspective": summary["user_a_perspective"],
        "user_b_perspective": summary["user_b_perspective"],
        "compromises": summary["compromises"],
    }
    if existing.data:
        supabase.table("joint_summaries").update(payload).eq("session_id", sid).execute()
    else:
        supabase.table("joint_summaries").insert(payload).execute()
    supabase.table("sessions").update({"status": "joint_review"}).eq("id", sid).execute()
    session["status"] = "joint_review"


def _transcript(session_id: str, party: str) -> str:
    result = (
        get_supabase()
        .table("messages")
        .select("sender_role, content")
        .eq("session_id", session_id)
        .eq("audience_role", party)
        .order("created_at")
        .execute()
    )
    lines = []
    for row in result.data or []:
        who = "User" if row["sender_role"] == party else "Mediator"
        lines.append(f"{who}: {row['content']}")
    return "\n".join(lines)


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
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status_code=500, detail="Could not create session")
    session = inserted.data[0]
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


@router.post("/sessions/{session_id}/messages", response_model=list[MessageOut])
def send_message(body: SendMessageBody, ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    if session["status"] == "halted":
        raise HTTPException(status_code=409, detail="This room was stopped for safety.")
    if session["status"] != "intake":
        raise HTTPException(status_code=409, detail="Private intake is closed.")

    text = body.content.strip()
    if is_crisis_or_severe_harm(text):
        _halt(session["id"])
        user_row = _insert_message(session["id"], actor.party, actor.party, text)
        ai_row = _insert_message(session["id"], "ai", actor.party, HELP_MESSAGE)
        return [MessageOut(**user_row), MessageOut(**ai_row)]

    user_row = _insert_message(session["id"], actor.party, actor.party, text)
    reply = generate_intake_reply(
        party=actor.party,
        relationship_context=session.get("relationship_context") or "",
        user_input=text,
    )
    if is_crisis_or_severe_harm(reply):
        _halt(session["id"])
        ai_row = _insert_message(session["id"], "ai", actor.party, HELP_MESSAGE)
        return [MessageOut(**user_row), MessageOut(**ai_row)]

    ai_row = _insert_message(session["id"], "ai", actor.party, reply)
    return [MessageOut(**user_row), MessageOut(**ai_row)]


@router.post("/sessions/{session_id}/ready", response_model=SessionOut)
def mark_ready(body: ReadyBody, ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    if session["status"] == "halted":
        raise HTTPException(status_code=409, detail="This room was stopped for safety.")

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
    session = updated.data[0]
    _maybe_build_summary(session)
    refreshed = (
        get_supabase().table("sessions").select("*").eq("id", session["id"]).limit(1).execute()
    )
    session = refreshed.data[0]
    return _session_out(session, actor)


@router.get("/sessions/{session_id}/summary", response_model=JointSummaryOut)
def get_summary(ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, _actor = ctx
    if session["status"] == "halted":
        raise HTTPException(status_code=409, detail="This room was stopped for safety.")
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
