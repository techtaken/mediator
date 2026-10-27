"""Data retention and deletion.

- `delete_party_data`: one person's "Delete my data".
- `delete_room`: Person A removes the whole room (every table cascades from it).
- `purge_old_rooms`: rooms older than RETENTION_DAYS are removed (a job).
- `scrub_audit_reasons`: free-text agent reasoning in audit rows is cleared
  after AUDIT_REASON_RETENTION_DAYS; the structured fields stay (a job).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db import get_supabase

logger = logging.getLogger(__name__)

# Audit fields that describe the process, never what anyone said.
STRUCTURED_AUDIT_KEYS = ("seq", "stage", "agent", "gate", "type", "coerced", "requested_agent")
BATCH = 200


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def structured_audit(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: entry[key] for key in STRUCTURED_AUDIT_KEYS if key in entry}


def delete_party_data(session_id: str, party_role: str, *, keep_approved_share: bool) -> dict[str, int]:
    """Remove one person's private chat (both sides of it), private memory and
    share drafts. An approved share the other person has already read in the
    joint view stays there; otherwise it is removed too."""
    supabase = get_supabase()
    removed = supabase.table("messages").delete().eq("session_id", session_id).eq("audience_role", party_role).execute()
    supabase.table("private_memories").delete().eq("session_id", session_id).eq("party_role", party_role).execute()
    if keep_approved_share:
        supabase.table("party_shares").update({"draft_text": None}).eq("session_id", session_id).eq(
            "party_role", party_role
        ).execute()
    else:
        supabase.table("party_shares").delete().eq("session_id", session_id).eq("party_role", party_role).execute()
    for table in PARTY_PRIVATE_TABLES:
        supabase.table(table).delete().eq("session_id", session_id).eq("party_role", party_role).execute()
    return {"messages": len(removed.data or [])}


# Tables holding one person's private answers, keyed by party_role.
PARTY_PRIVATE_TABLES: tuple[str, ...] = ("followups", "reality_checks")


def delete_room(session_id: str) -> None:
    """Every other table references sessions with ON DELETE CASCADE."""
    get_supabase().table("sessions").delete().eq("id", session_id).execute()


def purge_old_rooms(days: int, now: datetime | None = None) -> dict[str, Any]:
    if days <= 0:
        return {"enabled": False, "deleted": 0}
    cutoff = _iso((now or datetime.now(timezone.utc)) - timedelta(days=days))
    supabase = get_supabase()
    deleted = 0
    while True:
        rows = supabase.table("sessions").select("id").lt("created_at", cutoff).limit(BATCH).execute().data or []
        if not rows:
            break
        for row in rows:
            delete_room(row["id"])
            deleted += 1
        if len(rows) < BATCH:
            break
    logger.info("retention purge removed %d rooms created before %s", deleted, cutoff)
    return {"enabled": True, "deleted": deleted, "cutoff": cutoff}


def scrub_audit_reasons(days: int, now: datetime | None = None) -> dict[str, Any]:
    if days <= 0:
        return {"enabled": False, "scrubbed": 0}
    cutoff = _iso((now or datetime.now(timezone.utc)) - timedelta(days=days))
    supabase = get_supabase()
    scrubbed = 0
    while True:
        rows = (
            supabase.table("mediation_audit_events")
            .select("id, payload")
            .lt("created_at", cutoff)
            .eq("reason_scrubbed", False)
            .limit(BATCH)
            .execute()
            .data
            or []
        )
        for row in rows:
            supabase.table("mediation_audit_events").update(
                {"reason": None, "payload": structured_audit(row.get("payload") or {}), "reason_scrubbed": True}
            ).eq("id", row["id"]).execute()
            scrubbed += 1
        if len(rows) < BATCH:
            break
    logger.info("audit scrub cleared %d reasons older than %s", scrubbed, cutoff)
    return {"enabled": True, "scrubbed": scrubbed, "cutoff": cutoff}
