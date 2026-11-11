"""Encrypt private text written before encryption at rest was added.

Run once after setting DATA_ENCRYPTION_KEY and running migration 014:

    cd backend && .venv/bin/python -m app.encrypt_existing

Safe to run again: rows that are already encrypted are skipped. The app reads
both forms, so it can stay up while this runs.
"""

from __future__ import annotations

import logging
from typing import Any

from app.crypto import (
    JSON_KEY,
    audit_context,
    is_sealed,
    memory_context,
    message_context,
    seal,
    seal_json,
    share_context,
)
from app.db import get_supabase
from app.retention import structured_audit

logger = logging.getLogger(__name__)
PAGE = 500


def _rows(table: str, columns: str) -> list[dict[str, Any]]:
    supabase = get_supabase()
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        page = supabase.table(table).select(columns).range(start, start + PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        start += PAGE


def _json_sealed(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {JSON_KEY}


def encrypt_existing() -> dict[str, int]:
    supabase = get_supabase()
    done = {"messages": 0, "private_memories": 0, "party_shares": 0, "mediation_audit_events": 0}

    for row in _rows("messages", "id, session_id, content"):
        if row.get("content") is not None and not is_sealed(row["content"]):
            supabase.table("messages").update({"content": seal(row["content"], message_context(row["session_id"]))}).eq(
                "id", row["id"]
            ).execute()
            done["messages"] += 1

    for row in _rows("private_memories", "session_id, party_role, notes, profile"):
        sid, party = row["session_id"], row["party_role"]
        update: dict[str, Any] = {}
        if row.get("notes") is not None and not is_sealed(row["notes"]):
            update["notes"] = seal(row["notes"], memory_context(sid, party, "notes"))
        if row.get("profile") is not None and not _json_sealed(row["profile"]):
            update["profile"] = seal_json(row["profile"], memory_context(sid, party, "profile"))
        if update:
            supabase.table("private_memories").update(update).eq("session_id", sid).eq("party_role", party).execute()
            done["private_memories"] += 1

    for row in _rows("party_shares", "session_id, party_role, draft_text, approved_text"):
        sid, party = row["session_id"], row["party_role"]
        update = {
            field: seal(row[field], share_context(sid, party, field))
            for field in ("draft_text", "approved_text")
            if row.get(field) is not None and not is_sealed(row[field])
        }
        if update:
            supabase.table("party_shares").update(update).eq("session_id", sid).eq("party_role", party).execute()
            done["party_shares"] += 1

    # Only the agents' reasoning; admins' own view records hold no private text.
    for row in _rows("mediation_audit_events", "id, session_id, agent, reason, payload, reason_scrubbed"):
        payload = row.get("payload") or {}
        if row.get("reason_scrubbed") or is_sealed(row.get("reason")) or payload.get("admin_user_id"):
            continue
        context = audit_context(row["session_id"])
        supabase.table("mediation_audit_events").update(
            {
                "reason": seal(row["reason"], context) if row.get("reason") is not None else None,
                "payload": {**structured_audit(payload), "sealed": seal_json(payload, context)},
            }
        ).eq("id", row["id"]).execute()
        done["mediation_audit_events"] += 1

    return done


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(encrypt_existing())
