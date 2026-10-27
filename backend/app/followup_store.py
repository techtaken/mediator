"""Check-ins after an agreement is signed.

Each person gets their own check-in, on the schedule they picked when
signing (default FOLLOWUP_DEFAULT_DAYS). A job opens check-ins that have come
due; the person answers privately in their room. Nobody ever sees the other
person's answers; when both have answered, each sees only which terms their
accounts differ on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.auth import parse_time
from app.db import get_supabase

PARTY_ROLES = ("user_a", "user_b")
CHECKIN_CHOICES = (0, 7, 14, 30)


def days_field(party_role: str) -> str:
    return "followup_days_a" if party_role == "user_a" else "followup_days_b"


def list_followups(session_id: str, party_role: str | None = None) -> list[dict[str, Any]]:
    query = get_supabase().table("followups").select("*").eq("session_id", session_id)
    if party_role:
        query = query.eq("party_role", party_role)
    rows = query.execute().data or []
    return sorted(rows, key=lambda row: (row.get("round") or 0, row.get("party_role") or ""))


def latest_round(session_id: str) -> int:
    return max((int(row.get("round") or 0) for row in list_followups(session_id)), default=0)


def schedule_followups(session: dict[str, Any], signed_at: str, default_days: int) -> list[dict[str, Any]]:
    """Create the next round of check-ins, one per person who wants one."""
    base = parse_time(signed_at) or datetime.now(timezone.utc)
    round_number = latest_round(session["id"]) + 1
    rows = []
    for party in PARTY_ROLES:
        chosen = session.get(days_field(party))
        days = default_days if chosen is None else int(chosen)
        if days <= 0:
            continue
        rows.append(
            {
                "session_id": session["id"],
                "party_role": party,
                "round": round_number,
                "due_at": (base + timedelta(days=days)).isoformat(),
                "status": "scheduled",
            }
        )
    if rows:
        get_supabase().table("followups").insert(rows).execute()
    return rows


def open_due_followups(now: datetime | None = None) -> int:
    """Open every scheduled check-in whose time has come. Idempotent."""
    moment = (now or datetime.now(timezone.utc)).isoformat()
    supabase = get_supabase()
    due = (
        supabase.table("followups").select("id").eq("status", "scheduled").lte("due_at", moment).limit(500).execute().data
        or []
    )
    for row in due:
        supabase.table("followups").update({"status": "open", "opened_at": moment}).eq("id", row["id"]).eq(
            "status", "scheduled"
        ).execute()
    return len(due)


def save_answers(followup_id: str, answers: dict[str, Any], reply: str, answered_at: str) -> None:
    get_supabase().table("followups").update(
        {"status": "answered", "answers": answers, "reply": reply, "answered_at": answered_at}
    ).eq("id", followup_id).execute()


def accounts_differ(mine: dict[str, Any] | None, theirs: dict[str, Any] | None) -> list[int]:
    """1-based numbers of terms the two people described differently.

    Only *that* they differ is shown, never which account is right or what the
    other person said.
    """
    if not mine or not theirs:
        return []
    their_status = {int(item["term"]): item["status"] for item in theirs.get("term_status") or []}
    return sorted(
        int(item["term"]) + 1
        for item in mine.get("term_status") or []
        if int(item["term"]) in their_status and their_status[int(item["term"])] != item["status"]
    )
