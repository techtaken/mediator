"""Storage for the joint session: ideas, each party's responses, the agreement."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db import get_supabase


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_ideas(session_id: str) -> list[dict[str, Any]]:
    rows = get_supabase().table("joint_ideas").select("*").eq("session_id", session_id).execute().data or []
    return sorted(rows, key=lambda row: (row.get("position") or 0, row.get("created_at") or ""))


def add_idea(session_id: str, text: str, source: str) -> dict[str, Any]:
    ideas = list_ideas(session_id)
    position = max((idea.get("position") or 0 for idea in ideas), default=-1) + 1
    result = (
        get_supabase()
        .table("joint_ideas")
        .insert({"session_id": session_id, "text": text, "source": source, "position": position})
        .execute()
    )
    return result.data[0]


def seed_ideas(session_id: str, texts: list[str]) -> None:
    """Add the mediator's options as ideas, once per session."""
    if not texts or list_ideas(session_id):
        return
    get_supabase().table("joint_ideas").insert(
        [
            {"session_id": session_id, "text": text[:300], "source": "mediator", "position": index}
            for index, text in enumerate(texts)
        ]
    ).execute()


def list_responses(session_id: str) -> list[dict[str, Any]]:
    return get_supabase().table("idea_responses").select("*").eq("session_id", session_id).execute().data or []


def set_response(session_id: str, idea_id: str, party_role: str, response: str, note: str | None) -> None:
    get_supabase().table("idea_responses").upsert(
        {
            "idea_id": idea_id,
            "session_id": session_id,
            "party_role": party_role,
            "response": response,
            "note": note,
            "updated_at": now_iso(),
        },
        on_conflict="idea_id,party_role",
    ).execute()


def agreed_idea_ids(ideas: list[dict[str, Any]], responses: list[dict[str, Any]]) -> list[str]:
    """Ideas both parties said "works for me" to, in display order."""
    yes = {(row["idea_id"], row["party_role"]) for row in responses if row.get("response") == "yes"}
    return [idea["id"] for idea in ideas if (idea["id"], "user_a") in yes and (idea["id"], "user_b") in yes]


def get_agreement(session_id: str) -> dict[str, Any] | None:
    rows = get_supabase().table("agreements").select("*").eq("session_id", session_id).limit(1).execute().data
    return rows[0] if rows else None


def save_agreement(session_id: str, row: dict[str, Any]) -> None:
    get_supabase().table("agreements").upsert({"session_id": session_id, **row}, on_conflict="session_id").execute()


def clear_agreement(session_id: str) -> None:
    get_supabase().table("agreements").delete().eq("session_id", session_id).execute()
