from __future__ import annotations

import logging
from typing import Any

from app.agents.state import (
    SHARED_PARTY_KEYS,
    empty_party,
    empty_private,
    new_shared_state,
    normalize_private,
    pending_audit,
)
from app.db import get_supabase
from app.retention import structured_audit

logger = logging.getLogger(__name__)


class PersistError(RuntimeError):
    """A read or write the turn depends on failed. The request must not pretend it worked."""


class StateConflict(RuntimeError):
    """Another request updated the shared state first (optimistic lock lost)."""


def load_state(session: dict[str, Any]) -> dict[str, Any]:
    stored = session.get("mediation_state")
    if isinstance(stored, dict) and stored.get("dispute_id"):
        state = scrub_legacy_state(stored)
    else:
        state = new_shared_state(session["id"], session.get("relationship_context"))
    # The room owns the names, so the mediator always sees what people see.
    parties = state.setdefault("parties", {})
    parties.setdefault("A", empty_party())["name"] = session.get("name_a")
    # Their own name once they've joined; until then, what Person A calls them.
    parties.setdefault("B", empty_party())["name"] = session.get("name_b") or session.get("invited_as")
    return state


def scrub_legacy_state(state: dict[str, Any]) -> dict[str, Any]:
    """Drop private content that older versions wrote into the shared state."""
    for code, party in (state.get("parties") or {}).items():
        if isinstance(party, dict):
            state["parties"][code] = {key: party[key] for key in SHARED_PARTY_KEYS if key in party}
    if "diagnosis" not in state:
        # Before the split, caucus-raised (private) issue topics were stored here.
        # Shared issues now only come from the Diagnostician.
        state["issues"] = []
    state.setdefault("safety", {"flags": {}, "joint_blocked_by": []})
    return state


def state_version(session: dict[str, Any]) -> int:
    return int(session.get("state_version") or 0)


def load_private(session_id: str, party_role: str) -> dict[str, Any]:
    try:
        result = (
            get_supabase()
            .table("private_memories")
            .select("notes, profile")
            .eq("session_id", session_id)
            .eq("party_role", party_role)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        # Carrying on with empty memory would overwrite the real notes on save.
        raise PersistError("Could not load private memory") from exc
    if not result.data:
        return empty_private()
    return normalize_private(result.data[0])


def save_state(session_id: str, state: dict[str, Any], expected_version: int) -> int:
    """Write the shared state only if nobody else has since. Returns the new version."""
    pending = pending_audit(state)
    previous_seq = state.get("audit_persisted_seq")
    if pending:
        state["audit_persisted_seq"] = max(int(entry["seq"]) for entry in pending)
    new_version = expected_version + 1
    try:
        result = (
            get_supabase()
            .table("sessions")
            .update({"mediation_state": storable_state(state), "state_version": new_version})
            .eq("id", session_id)
            .eq("state_version", expected_version)
            .execute()
        )
    except Exception as exc:
        state["audit_persisted_seq"] = previous_seq
        raise PersistError("Could not save mediation state") from exc
    if not result.data:
        state["audit_persisted_seq"] = previous_seq
        raise StateConflict(session_id)
    _insert_audit(session_id, pending)
    return new_version


def storable_state(state: dict[str, Any]) -> dict[str, Any]:
    """The shared state as written to the sessions row.

    The in-row audit log keeps only structured fields (stage, agent, gate...).
    Agents' free-text reasons go to mediation_audit_events alone, where they
    are cleared after the audit retention period.
    """
    stored = dict(state)
    stored["audit_log"] = [structured_audit(entry) for entry in state.get("audit_log") or [] if isinstance(entry, dict)]
    return stored


def save_private(session_id: str, party_role: str, private: dict[str, Any]) -> None:
    private = normalize_private(private)
    try:
        get_supabase().table("private_memories").upsert(
            {
                "session_id": session_id,
                "party_role": party_role,
                "notes": private["notes"],
                "profile": private["profile"],
            },
            on_conflict="session_id,party_role",
        ).execute()
    except Exception as exc:
        raise PersistError("Could not save private memory") from exc


def persist_turn(
    session_id: str,
    party_role: str,
    state: dict[str, Any],
    private: dict[str, Any] | None,
    expected_version: int,
) -> int:
    version = save_state(session_id, state, expected_version)
    if private is not None:
        save_private(session_id, party_role, private)
    return version


def _insert_audit(session_id: str, entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    rows = [
        {
            "session_id": session_id,
            "stage": entry.get("stage"),
            "agent": entry.get("agent"),
            "gate": entry.get("gate") if isinstance(entry.get("gate"), int) else None,
            "reason": str(entry.get("reason") or entry.get("detail") or "")[:2000],
            "payload": entry,
        }
        for entry in entries
    ]
    try:
        get_supabase().table("mediation_audit_events").insert(rows).execute()
    except Exception:
        # The state (and its in-row audit_log) is already saved; the audit table
        # is a secondary copy, so log loudly rather than fail the user's turn.
        logger.exception("failed to insert %d audit events for session %s", len(rows), session_id)
