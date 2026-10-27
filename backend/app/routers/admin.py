"""Read-only admin views over every session, including both private rooms.

Access is limited to ADMIN_EMAILS. Every session an admin opens is written to
mediation_audit_events first; if that write fails the view is refused, so no
private room can be read without a record of who read it.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.agents.telemetry import summarize
from app.auth import Admin, load_session, require_admin
from app.config import get_settings
from app.db import get_supabase
from app.joint_store import get_agreement, list_ideas, list_responses

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin")

SESSION_STATUSES = {"intake", "building_joint", "joint_review", "resolved", "halted"}
# Never shown to admins: the invite secret would let them act as Person B.
HIDDEN_SESSION_FIELDS = {"invite_token_b", "mediation_state"}


def _session_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in HIDDEN_SESSION_FIELDS}


@router.get("/me")
def whoami(admin: Admin = Depends(require_admin)):
    return {"email": admin.email}


@router.get("/sessions")
def list_sessions(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: Admin = Depends(require_admin),
):
    if status is not None and status not in SESSION_STATUSES:
        raise HTTPException(status_code=422, detail=f"Unknown status: {status}")
    supabase = get_supabase()
    query = supabase.table("sessions").select(
        "id, status, topic, relationship_context, created_by, created_at, updated_at, "
        "user_a_ready, user_b_ready, halted_for, halt_kind, halted_reason, state_version"
    )
    if status:
        query = query.eq("status", status)
    # Fetch one extra row to know whether another page exists.
    rows = query.order("created_at", desc=True).range(offset, offset + limit).execute().data or []
    has_more = len(rows) > limit
    rows = rows[:limit]

    stats: dict[str, dict[str, Any]] = {
        row["id"]: {"messages_a": 0, "messages_b": 0, "last_activity": None} for row in rows
    }
    if rows:
        messages = (
            supabase.table("messages")
            .select("session_id, sender_role, created_at")
            .in_("session_id", list(stats))
            .execute()
            .data
            or []
        )
        for message in messages:
            entry = stats.get(message["session_id"])
            if entry is None:
                continue
            if message["sender_role"] == "user_a":
                entry["messages_a"] += 1
            elif message["sender_role"] == "user_b":
                entry["messages_b"] += 1
            if entry["last_activity"] is None or message["created_at"] > entry["last_activity"]:
                entry["last_activity"] = message["created_at"]

    return {
        "sessions": [{**_session_summary(row), **stats[row["id"]]} for row in rows],
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
    }


def _record_view(session_id: str, admin: Admin) -> None:
    try:
        get_supabase().table("mediation_audit_events").insert(
            {
                "session_id": session_id,
                "stage": None,
                "agent": "ADMIN",
                "gate": None,
                "reason": f"session viewed by admin {admin.email}",
                "payload": {"type": "admin_view", "admin_user_id": admin.user_id, "admin_email": admin.email},
            }
        ).execute()
    except Exception as exc:
        logger.exception("could not record admin view of %s", session_id)
        raise HTTPException(status_code=503, detail="Could not record this access, so it was refused.") from exc


@router.get("/sessions/{session_id}")
def session_detail(session_id: str, admin: Admin = Depends(require_admin)):
    session = load_session(session_id)
    _record_view(session_id, admin)
    supabase = get_supabase()

    messages = (
        supabase.table("messages").select("*").eq("session_id", session_id).order("created_at").execute().data or []
    )
    rooms: dict[str, list[dict[str, Any]]] = {"user_a": [], "user_b": []}
    for message in messages:
        rooms.setdefault(message["audience_role"], []).append(message)

    memories = (
        supabase.table("private_memories").select("*").eq("session_id", session_id).execute().data or []
    )
    audit = (
        supabase.table("mediation_audit_events")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
        .data
        or []
    )
    summary = (
        supabase.table("joint_summaries").select("*").eq("session_id", session_id).limit(1).execute().data or []
    )
    settings = get_settings()
    calls = supabase.table("agent_calls").select("*").eq("session_id", session_id).execute().data or []

    return {
        "session": _session_summary(session),
        "rooms": rooms,
        "private_memories": {row["party_role"]: row for row in memories},
        "state": session.get("mediation_state") or {},
        "audit_events": audit,
        "agent_calls": summarize(calls, settings.gemini_price_input_per_m, settings.gemini_price_output_per_m),
        "joint_summary": summary[0] if summary else None,
        "joint": {
            "ideas": list_ideas(session_id),
            "responses": list_responses(session_id),
            "agreement": get_agreement(session_id),
        },
    }
