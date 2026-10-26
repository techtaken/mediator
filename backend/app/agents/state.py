from __future__ import annotations

import copy
from typing import Any

PartyKey = str  # "A" | "B"

# Only process signals live in shared party state. Anything describing what a
# party said (positions, interests, hidden concerns, issues they raised) is
# private and stored in that party's private memory.
SHARED_PARTY_KEYS = ("name", "intensity", "willing", "feels_heard", "consented_to_human")
SHARED_SIGNAL_UPDATES = ("intensity", "willing", "feels_heard")
PRIVATE_PROFILE_LISTS = ("positions", "interests", "hidden_concerns", "resolution_needs")

# Top-level keys never shown to agents.
# - "safety" holds per-party flags: the other party must never learn about one.
# - "audit_log" and "handoff" hold agents' free-text reasoning about a party's
#   private turns ("A is hurt that B..."). Passing them on leaked one party's
#   words into the other party's caucus.
PRIVATE_TOP_LEVEL_KEYS = (
    "private_A",
    "private_B",
    "safety",
    "audit_log",
    "audit_seq",
    "audit_persisted_seq",
    "handoff",
)


def empty_party() -> dict[str, Any]:
    return {
        "name": None,
        "intensity": 5,
        "willing": True,
        "feels_heard": False,
        "consented_to_human": None,
    }


def empty_private() -> dict[str, Any]:
    return {
        "notes": "",
        "profile": {
            "positions": [],
            "interests": [],
            "hidden_concerns": [],
            "resolution_needs": [],
            "issues_raised": [],
        },
    }


def new_shared_state(dispute_id: str, relationship_context: str | None = None) -> dict[str, Any]:
    return {
        "dispute_id": dispute_id,
        "stage": "INTAKE",
        "mode": "private",
        "relationship_context": relationship_context,
        "parties": {"A": empty_party(), "B": empty_party()},
        "issues": [],
        "issue_links": [],
        "agenda": [],
        "escalation_stage": 3,
        "approved_shares": {"A": [], "B": []},
        "options": {},
        "agreed_terms": [],
        "agreement": None,
        "signals": {"stall_counter": 0, "turns": {"A": 0, "B": 0}},
        "audit_log": [],
        "handoff": None,
        "safety": {"flags": {}, "joint_blocked_by": []},
    }


def party_code(user_role: str) -> PartyKey:
    return "A" if user_role == "user_a" else "B"


def user_role(code: PartyKey) -> str:
    return "user_a" if code == "A" else "user_b"


def shared_view(state: dict[str, Any]) -> dict[str, Any]:
    """What agents may see: approved shares, process signals and joint-stage results.

    Private memory, safety flags and anything holding agents' free-text notes
    about a private turn are never included. Party entries are filtered to an
    allowlist, which also scrubs states saved before private fields moved out.
    """
    view = copy.deepcopy(state)
    for key in PRIVATE_TOP_LEVEL_KEYS:
        view.pop(key, None)
    parties = view.get("parties") or {}
    view["parties"] = {
        code: {key: party.get(key) for key in SHARED_PARTY_KEYS if key in party}
        for code, party in parties.items()
        if isinstance(party, dict)
    }
    return view


def party_view(state: dict[str, Any], party: PartyKey) -> dict[str, Any]:
    """What agents may see during one party's private intake turn.

    Only that party's own approved shares, plus neutral signals. Nothing the
    other party said, even content a model judged "approved to share", reaches
    this party's agents before the joint stage.
    """
    view = shared_view(state)
    shares = view.get("approved_shares") or {}
    view["approved_shares"] = {party: list(shares.get(party) or [])}
    return view


def normalize_private(private: dict[str, Any] | str | None) -> dict[str, Any]:
    base = empty_private()
    if isinstance(private, str):
        base["notes"] = private
        return base
    if not isinstance(private, dict):
        return base
    base["notes"] = str(private.get("notes") or "")
    profile = private.get("profile") or {}
    if isinstance(profile, dict):
        for key in base["profile"]:
            value = profile.get(key)
            if isinstance(value, list):
                base["profile"][key] = value
    return base


def apply_caucus_updates(
    state: dict[str, Any],
    private: dict[str, Any],
    party: PartyKey,
    updates: dict[str, Any] | None,
) -> None:
    """Split a caucus update: process signals to shared state, content to private memory."""
    if not updates:
        return
    party_state = state.setdefault("parties", {}).setdefault(party, empty_party())
    for key in SHARED_SIGNAL_UPDATES:
        if updates.get(key) is not None:
            party_state[key] = updates[key]

    profile = private.setdefault("profile", empty_private()["profile"])
    for key in PRIVATE_PROFILE_LISTS:
        values = updates.get(key)
        if values:
            profile[key] = list(values)

    raised = profile.setdefault("issues_raised", [])
    known = {str(item.get("topic") or "").strip().casefold() for item in raised if isinstance(item, dict)}
    for issue in updates.get("new_issues") or []:
        topic = str(issue.get("topic") or "").strip()
        if not topic or topic.casefold() in known:
            continue
        known.add(topic.casefold())
        raised.append(
            {
                "topic": topic,
                "category": issue.get("category_guess") or "Interest",
                "priority": issue.get("priority") or "medium",
            }
        )


def set_approved_share(state: dict[str, Any], party: PartyKey, text: str | None) -> None:
    """Set (or clear) the one text this party approved for the other to see.

    The only way anything enters approved_shares: an explicit approval by the
    party in the app. Agents never approve on a party's behalf.
    """
    shares = state.setdefault("approved_shares", {"A": [], "B": []})
    shares[party] = [text] if text else []


def record_safety_flag(state: dict[str, Any], party: PartyKey, report: dict[str, Any]) -> None:
    safety = state.setdefault("safety", {"flags": {}, "joint_blocked_by": []})
    flags = safety.setdefault("flags", {})
    previous = flags.get(party) or {}
    severity = int(report.get("severity") or 0)
    if severity >= int(previous.get("severity") or 0):
        flags[party] = {
            "severity": severity,
            "action": report.get("action"),
            "categories": report.get("categories") or [],
        }
    if severity >= 2 or report.get("action") == "PAUSE_AND_CHECK":
        blocked = safety.setdefault("joint_blocked_by", [])
        if party not in blocked:
            blocked.append(party)


def joint_blocked_by(state: dict[str, Any]) -> list[PartyKey]:
    return list((state.get("safety") or {}).get("joint_blocked_by") or [])


def append_audit(state: dict[str, Any], entry: dict[str, Any]) -> None:
    seq = int(state.get("audit_seq") or 0) + 1
    state["audit_seq"] = seq
    log = state.setdefault("audit_log", [])
    log.append({**entry, "seq": seq})
    state["audit_log"] = log[-100:]


def pending_audit(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Audit entries appended since the last successful persist."""
    done = int(state.get("audit_persisted_seq") or 0)
    return [entry for entry in state.get("audit_log") or [] if int(entry.get("seq") or 0) > done]
