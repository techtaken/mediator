from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from app.agents.llm import AgentCaller, call_agent, dumps
from app.agents.state import (
    PartyKey,
    append_approved_share,
    append_audit,
    apply_caucus_updates,
    normalize_private,
    record_safety_flag,
    shared_view,
)
from app.safety import HELP_MESSAGE, is_crisis_or_severe_harm, with_helplines

logger = logging.getLogger(__name__)

INTERNAL_AGENTS = {"DIAGNOSTICIAN", "OPTIONS", "REALITY_TESTER", "DRAFTER"}
HANDOFF_AGENTS = {"HUMAN", "HANDOFF"}
MAX_INTERNAL_HOPS = 4

# Sent when no draft survives the outbound checks. Deliberately content-free.
NEUTRAL_FALLBACK = "Thank you for telling me. Take your time. What feels most important to you right now?"
# Sent when the caucus agent itself fails.
CAUCUS_FALLBACK = "I heard you. Say a little more about what you need to feel this is resolved."

DEFAULT_COMPROMISES = (
    "Write a weekly check-in of 15 minutes that both of you can keep.",
    "Handle money and visiting decisions in a shared note, not through relatives.",
    "Agree one pause word either of you can use when the talk gets sharp.",
)

CARE_NOTES = {
    1: "Go gently. Check that they are choosing freely to continue, and keep the pace slow.",
    2: (
        "Pause the move toward a joint session. Check in privately about their safety and "
        "whether they feel free to take part. Offer a trusted person or a professional if they want one."
    ),
}


@dataclass
class TurnResult:
    reply: str
    halt: bool = False
    halt_kind: str | None = None  # "safety" | "referral"
    state: dict[str, Any] = field(default_factory=dict)
    private: dict[str, Any] | None = None
    agent: str = "CAUCUS"
    extras: dict[str, Any] = field(default_factory=dict)


def _safety_unavailable() -> dict[str, Any]:
    # Fail closed: an unchecked turn is treated as needing care, never as clean.
    return {
        "flag": True,
        "severity": 1,
        "categories": ["safety_check_unavailable"],
        "evidence": "",
        "action": "CONTINUE_WITH_CARE",
        "message_to_affected_party": None,
        "block_outgoing_message": False,
    }


def _default_plan(party: PartyKey) -> dict[str, Any]:
    return {
        "stage": "STORYTELLING",
        "focus": party,
        "gate_triggered": 5,
        "next_agent": f"CAUCUS_{party}",
        "mode": "private",
        "instructions_to_agent": "Listen, reflect interests, do not propose a deal yet.",
        "reason": "Default to private storytelling until both feel heard.",
    }


def _is_halt(safety: dict[str, Any]) -> bool:
    return safety.get("action") == "HALT_AND_REFER" or int(safety.get("severity") or 0) >= 3


def _severity(safety: dict[str, Any]) -> int:
    severity = int(safety.get("severity") or 0)
    action = safety.get("action")
    if action == "PAUSE_AND_CHECK":
        severity = max(severity, 2)
    elif action == "CONTINUE_WITH_CARE":
        severity = max(severity, 1)
    return severity


def handle_party_turn(
    *,
    party: PartyKey,
    message: str,
    state: dict[str, Any],
    private: dict[str, Any] | str | None,
    relationship_context: str = "",
    caller: AgentCaller = call_agent,
) -> TurnResult:
    """One private-intake turn. The reply always goes back to `party`."""
    private = normalize_private(private)

    if is_crisis_or_severe_harm(message):
        state["stage"] = "HALT_AND_REFER"
        record_safety_flag(state, party, {"severity": 3, "action": "HALT_AND_REFER", "categories": ["keyword"]})
        append_audit(state, {"stage": "HALT_AND_REFER", "agent": "KEYWORD_SAFETY", "gate": 1, "reason": "keyword"})
        return TurnResult(reply=HELP_MESSAGE, halt=True, halt_kind="safety", state=state, agent="SAFETY_GUARDIAN")

    view = shared_view(state)
    try:
        safety = caller(
            "SAFETY_GUARDIAN",
            {
                "SHARED_STATE_JSON": dumps(view),
                "LATEST_EVENT": dumps({"party": party, "message": message, "direction": "inbound"}),
            },
        )
    except Exception:
        logger.exception("inbound safety check failed; continuing with care")
        safety = _safety_unavailable()
        append_audit(state, {"stage": state.get("stage"), "agent": "SAFETY_GUARDIAN", "reason": "inbound check unavailable"})

    if _is_halt(safety):
        return _halt_for_safety(state, view, party, safety, caller)

    severity = _severity(safety)
    if severity:
        record_safety_flag(state, party, {**safety, "severity": severity})

    plan = _plan_turn(state, party, message, safety, caller)
    next_agent = plan["next_agent"]

    if next_agent in HANDOFF_AGENTS or plan.get("stage") in {"HALT_AND_REFER", "REFER_TO_HUMAN"}:
        return _handoff(state, party, plan, caller)

    care = CARE_NOTES.get(min(severity, 2), "")
    instruction = " ".join(part for part in (care, str(plan.get("instructions_to_agent") or "")) if part)
    mapping = {
        "PARTY_ID": party,
        "SHARED_STATE_JSON": dumps(shared_view(state)),
        # Confidentiality in code: only the speaking party's own memory is ever passed.
        "PRIVATE_MEMORY": dumps(private),
        "LATEST_EVENT": dumps({"party": party, "message": message}),
        "INSTRUCTION": instruction,
        "RELATIONSHIP_CONTEXT": relationship_context or "",
    }

    try:
        caucus = caller("CAUCUS", mapping)
    except Exception:
        logger.exception("caucus agent failed")
        caucus = {
            "reply_to_party": CAUCUS_FALLBACK,
            "state_updates": {},
            "share_proposal": {"text": None, "approved_by_party": False},
        }

    def regenerate(feedback: str) -> str:
        retry = caller("CAUCUS", {**mapping, "INSTRUCTION": f"{instruction}\nREWRITE: the previous draft was rejected: {feedback}"})
        return str(retry.get("reply_to_party") or "")

    draft = _guard_outgoing(
        str(caucus.get("reply_to_party") or "").strip(),
        state,
        plan,
        party,
        caller,
        regenerate,
    )
    apply_caucus_updates(state, private, party, caucus.get("state_updates") or {})
    append_approved_share(state, party, caucus.get("share_proposal"))
    if caucus.get("private_notes"):
        private["notes"] = str(caucus["private_notes"])
    turns = state.setdefault("signals", {}).setdefault("turns", {"A": 0, "B": 0})
    turns[party] = int(turns.get(party) or 0) + 1
    return TurnResult(
        reply=draft,
        state=state,
        private=private,
        agent=f"CAUCUS_{party}",
        extras={"caucus": caucus},
    )


def _plan_turn(
    state: dict[str, Any],
    party: PartyKey,
    message: str,
    safety: dict[str, Any],
    caller: AgentCaller,
) -> dict[str, Any]:
    """Ask the orchestrator for the next agent, running internal agents in between.

    During private intake the only party-facing agent allowed is the speaking
    party's own caucus. Anything else the orchestrator picks is coerced.
    """
    allowed = {f"CAUCUS_{party}"} | INTERNAL_AGENTS | HANDOFF_AGENTS
    plan = _default_plan(party)
    for hop in range(MAX_INTERNAL_HOPS + 1):
        try:
            plan = caller(
                "ORCHESTRATOR",
                {
                    "SHARED_STATE_JSON": dumps(shared_view(state)),
                    "LATEST_EVENT": dumps({"party": party, "message": message}),
                    "SAFETY_REPORT": dumps(safety),
                },
            )
        except Exception:
            logger.exception("orchestrator failed; defaulting to caucus")
            plan = _default_plan(party)

        requested = str(plan.get("next_agent") or "")
        next_agent = requested if requested in allowed else f"CAUCUS_{party}"
        if next_agent in INTERNAL_AGENTS and hop == MAX_INTERNAL_HOPS:
            next_agent = f"CAUCUS_{party}"
        plan["next_agent"] = next_agent

        state["stage"] = plan.get("stage") or state.get("stage")
        state["mode"] = "private"
        append_audit(
            state,
            {
                "stage": plan.get("stage"),
                "agent": next_agent,
                "gate": plan.get("gate_triggered"),
                "reason": plan.get("reason"),
                **({"requested_agent": requested, "coerced": True} if requested != next_agent else {}),
            },
        )
        if next_agent not in INTERNAL_AGENTS:
            return plan
        _run_internal(next_agent, state, plan, party, caller)
    return plan


def _halt_for_safety(
    state: dict[str, Any],
    view: dict[str, Any],
    party: PartyKey,
    safety: dict[str, Any],
    caller: AgentCaller,
) -> TurnResult:
    support = safety.get("message_to_affected_party") or HELP_MESSAGE
    try:
        handoff = caller("HANDOFF", {"SHARED_STATE_JSON": dumps(view), "REASON": dumps(safety)})
    except Exception:
        logger.exception("handoff packager failed during safety halt")
        handoff = {"message_to_parties": "", "urgency": "URGENT"}
    state["stage"] = "HALT_AND_REFER"
    state["handoff"] = handoff
    record_safety_flag(state, party, {**safety, "severity": 3})
    append_audit(state, {"stage": "HALT_AND_REFER", "agent": "SAFETY_GUARDIAN", "gate": 1, "reason": safety.get("evidence")})
    # The supportive message comes first and always carries the helplines; the
    # handoff text is for a human mediator and is never allowed to replace it.
    return TurnResult(
        reply=with_helplines(support),
        halt=True,
        halt_kind="safety",
        state=state,
        agent="SAFETY_GUARDIAN",
        extras={"handoff": handoff},
    )


def _handoff(state: dict[str, Any], party: PartyKey, plan: dict[str, Any], caller: AgentCaller) -> TurnResult:
    halting = plan.get("stage") == "HALT_AND_REFER"
    try:
        handoff = caller(
            "HANDOFF",
            {"SHARED_STATE_JSON": dumps(shared_view(state)), "REASON": str(plan.get("reason") or "human referral")},
        )
    except Exception:
        logger.exception("handoff packager failed")
        handoff = {"message_to_parties": "", "urgency": "URGENT" if halting else "STANDARD"}
    state["handoff"] = handoff
    message = str(handoff.get("message_to_parties") or "").strip() or (
        "This is more than this AI room can hold. Please speak with a trusted person or a professional mediator."
    )
    if halting:
        record_safety_flag(state, party, {"severity": 3, "action": "HALT_AND_REFER", "categories": ["orchestrator"]})
        message = with_helplines(message)
    return TurnResult(
        reply=message,
        halt=halting,
        halt_kind="safety" if halting else None,
        state=state,
        agent="HANDOFF",
        extras={"handoff": handoff},
    )


def _run_internal(
    agent: str,
    state: dict[str, Any],
    plan: dict[str, Any],
    party: PartyKey,
    caller: AgentCaller,
) -> dict[str, Any]:
    view = shared_view(state)
    mapping = {
        "SHARED_STATE_JSON": dumps(view),
        "APPROVED_SHARES": dumps(view.get("approved_shares") or {}),
        "SIGNALS": dumps(view.get("signals") or {}),
        "INSTRUCTION": str(plan.get("instructions_to_agent") or ""),
        "OPTIONS": dumps(view.get("options") or {}),
        "PARTY_ID": party,
        "AGREED_TERMS": dumps(view.get("agreed_terms") or []),
        "FOCUS": str(plan.get("focus") or ""),
    }
    try:
        result = caller(agent, mapping)
    except Exception:
        logger.exception("internal agent %s failed", agent)
        return state
    if agent == "DIAGNOSTICIAN":
        if result.get("issues"):
            state["issues"] = result["issues"]
        if result.get("issue_links") is not None:
            state["issue_links"] = result["issue_links"]
        if result.get("agenda"):
            state["agenda"] = result["agenda"]
        if result.get("escalation_stage") is not None:
            state["escalation_stage"] = result["escalation_stage"]
        state["diagnosis"] = result
    elif agent == "OPTIONS":
        state["options"] = result
    elif agent == "REALITY_TESTER":
        state.setdefault("reality_tests", {})[party] = result
    elif agent == "DRAFTER":
        state["agreement"] = result
    return state


def _run_joint_voice(
    state: dict[str, Any],
    plan: dict[str, Any],
    caller: AgentCaller,
) -> tuple[str, dict[str, Any]]:
    view = shared_view(state)
    mapping = {
        "SHARED_STATE_JSON": dumps(view),
        "FOCUS": str(plan.get("focus") or ""),
        "INSTRUCTION": str(plan.get("instructions_to_agent") or ""),
        "APPROVED_SHARES": dumps(view.get("approved_shares") or {}),
    }
    try:
        result = caller("JOINT_VOICE", mapping)
    except Exception:
        logger.exception("joint voice failed")
        result = {"message": "Here is a joint reading of what both of you have agreed to share."}

    def regenerate(feedback: str) -> str:
        retry = caller("JOINT_VOICE", {**mapping, "INSTRUCTION": f"{mapping['INSTRUCTION']}\nREWRITE: {feedback}"})
        return str(retry.get("message") or "")

    draft = _guard_outgoing(str(result.get("message") or "").strip(), state, plan, "both", caller, regenerate)
    return draft, result


def _check_outbound(draft: str, state: dict[str, Any], recipient: str, caller: AgentCaller) -> tuple[bool | None, str]:
    """Return (blocked, feedback). blocked is None when the check itself failed."""
    if is_crisis_or_severe_harm(draft):
        return True, "Do not repeat crisis or violence wording; respond with care in neutral words."
    try:
        out_safety = caller(
            "SAFETY_GUARDIAN",
            {
                "SHARED_STATE_JSON": dumps(shared_view(state)),
                "LATEST_EVENT": dumps({"direction": "outbound", "draft": draft, "recipient": recipient}),
            },
        )
    except Exception:
        logger.exception("outbound safety check failed")
        return None, ""
    if out_safety.get("block_outgoing_message"):
        return True, str(out_safety.get("evidence") or "unsafe or one-sided wording")
    return False, ""


def _guard_outgoing(
    draft: str,
    state: dict[str, Any],
    plan: dict[str, Any],
    recipient: str,
    caller: AgentCaller,
    regenerate: Callable[[str], str] | None = None,
) -> str:
    """Outbound safety + neutrality checks.

    A blocked draft is regenerated once with feedback; if that fails too, a
    neutral fallback is sent. Crisis helplines are never used as a stand-in for
    a biased or unsafe draft. At least one checker must run successfully, or the
    fallback is sent.
    """
    if not draft:
        draft = "I am here. Tell me what matters most."

    blocked, feedback = _check_outbound(draft, state, recipient, caller)
    if blocked and regenerate is not None:
        try:
            retry = regenerate(feedback).strip()
        except Exception:
            logger.exception("regeneration failed")
            retry = ""
        if retry:
            draft = retry
            blocked, feedback = _check_outbound(draft, state, recipient, caller)
    if blocked:
        append_audit(state, {"stage": state.get("stage"), "agent": "SAFETY_GUARDIAN", "reason": f"outbound blocked: {feedback}"})
        return NEUTRAL_FALLBACK
    safety_ran = blocked is not None

    view = shared_view(state)
    try:
        audit = caller(
            "NEUTRALITY_AUDITOR",
            {
                "DRAFT": draft,
                "MODE": str(plan.get("mode") or "private"),
                "RECIPIENT": recipient,
                "APPROVED_SHARES": dumps(view.get("approved_shares") or {}),
                "BALANCE_STATS": dumps(view.get("signals") or {}),
            },
        )
    except Exception:
        logger.exception("neutrality auditor failed")
        if not safety_ran:
            append_audit(state, {"stage": state.get("stage"), "agent": "NEUTRALITY_AUDITOR", "reason": "no outbound check available"})
            return NEUTRAL_FALLBACK
        return draft

    if audit.get("alert_orchestrator") or audit.get("blocked"):
        append_audit(state, {"type": "neutrality_alert", "agent": "NEUTRALITY_AUDITOR", "detail": audit.get("issues_found")})
    final = str(audit.get("final_message") or "").strip()
    if audit.get("blocked"):
        # Blocked means "rewrite from scratch": only a fresh, clean rewrite may go out.
        if final and final != draft and not is_crisis_or_severe_harm(final):
            return final
        return NEUTRAL_FALLBACK
    return final or draft


def _perspective(result: dict[str, Any], key: str, shares: list[str], label: str) -> str:
    text = str(result.get(key) or "").strip()
    if text:
        return text
    if shares:
        return " ".join(shares)
    return f"{label} has not chosen anything to share yet."


def run_joint_pipeline(
    *,
    state: dict[str, Any],
    caller: AgentCaller = call_agent,
) -> dict[str, Any]:
    """When both parties are ready: diagnose, generate options, write a joint view.

    Every agent here sees only the shared view: approved shares plus process
    signals. Private memory is never loaded.
    """
    plan = {
        "stage": "DIAGNOSIS",
        "focus": None,
        "instructions_to_agent": "Build the issue map from approved shares only.",
        "mode": "joint",
    }
    _run_internal("DIAGNOSTICIAN", state, plan, "A", caller)
    plan["stage"] = "NEGOTIATE"
    plan["instructions_to_agent"] = "Generate balanced options from shared interests."
    _run_internal("OPTIONS", state, plan, "A", caller)
    message, joint = _run_joint_voice(
        state,
        {
            "stage": "RECOGNITION",
            "focus": None,
            "instructions_to_agent": "Present neutralized perspectives and invite recognition.",
            "mode": "joint",
        },
        caller,
    )
    options = state.get("options") or {}
    descriptions = []
    for item in options.get("options") or []:
        if isinstance(item, dict) and item.get("description"):
            descriptions.append(str(item["description"]))
        elif isinstance(item, str):
            descriptions.append(item)
    shares = state.get("approved_shares") or {}
    perspectives = {}
    for key, code, label in (("user_a_perspective", "A", "Person A"), ("user_b_perspective", "B", "Person B")):
        party_shares = shares.get(code) or []
        text = _perspective(joint, key, party_shares, label)
        if text != " ".join(party_shares) and _check_outbound(text, state, "both", caller)[0]:
            # A blocked summary falls back to the party's own approved words.
            text = _perspective({}, key, party_shares, label)
        perspectives[key] = text

    compromises = descriptions[:6]
    if compromises and _check_outbound("\n".join(compromises), state, "both", caller)[0]:
        append_audit(state, {"stage": "NEGOTIATE", "agent": "SAFETY_GUARDIAN", "reason": "options blocked"})
        compromises = []
    return {
        "state": state,
        **perspectives,
        "compromises": compromises or list(DEFAULT_COMPROMISES),
        "joint_message": message,
    }
