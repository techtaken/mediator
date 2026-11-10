from __future__ import annotations

import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from app.agents.llm import AgentCaller, call_agent, dumps
from app.agents.prompts import (
    LANGUAGE_NAMES,
    STYLES,
    data_block,
    detect_language,
    joint_language,
    joint_language_instruction,
    language_instruction,
    style_guide,
)
from app.agents.schemas import REALITY_TYPES
from app.agents.state import (
    PartyKey,
    append_audit,
    apply_caucus_updates,
    normalize_private,
    party_view,
    note_clean_turn,
    record_safety_flag,
    shared_view,
)
from app.config import get_settings
from app.safety import HELP_MESSAGE, is_crisis_or_severe_harm, with_helplines

logger = logging.getLogger(__name__)

INTERNAL_AGENTS = {"DIAGNOSTICIAN", "OPTIONS", "REALITY_TESTER", "DRAFTER"}
HANDOFF_AGENTS = {"HUMAN", "HANDOFF"}
STAGES = {
    "INTAKE", "CONSENT", "STORYTELLING", "SHARE_CONSENT", "DIAGNOSIS", "RECOGNITION",
    "ESTABLISH_FACTS", "NEGOTIATE", "REALITY_TEST", "DRAFT_AGREEMENT", "FOLLOW_UP",
    "DE_ESCALATE", "BUILD_READINESS", "HALT_AND_REFER", "REFER_TO_HUMAN",
}

# Sent when no draft survives the outbound checks. Deliberately content-free.
NEUTRAL_FALLBACK = "Thank you for telling me. Take your time. What feels most important to you right now?"
# Sent when the caucus agent itself fails.
CAUCUS_FALLBACK = "I heard you. Say a little more about what you need to feel this is resolved."

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


T = TypeVar("T")
U = TypeVar("U")

# Agent calls that don't need each other's results run side by side. Each runs
# in a copy of the request's context, so call stats still land on the right room.
_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="agent-call")


def _side_by_side(first: Callable[[], T], second: Callable[[], U]) -> tuple[T, U]:
    """Run `first` on a worker while `second` runs here. Both must handle their own errors."""
    pending = _POOL.submit(contextvars.copy_context().run, first)
    second_result = second()
    return pending.result(), second_result


# What a clean safety check reports. The orchestrator starts with this while the
# real check runs; anything else from the check means it's asked again.
ASSUMED_CLEAN_SAFETY: dict[str, Any] = {
    "flag": False,
    "severity": 0,
    "categories": [],
    "evidence": "",
    "action": "CONTINUE",
    "message_to_affected_party": None,
    "block_outgoing_message": False,
}


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


def topic_for(party: PartyKey, topic: str | None) -> str:
    """The dispute topic, framed for this party's caucus.

    Written out with explicit roles so the model never has to work out who
    said what. Without this it once told B "your sibling is planning a trip
    without you" when A had said B went on a trip without A.
    """
    text = (topic or "").strip()
    if not text:
        return "Not given."
    quoted = data_block("dispute_topic", text)
    if party == "A":
        return (
            f"The person you are talking to (A) opened this room and described it as:{quoted}\n"
            "B has been shown this line as A's description."
        )
    return (
        f"The OTHER person (A) opened this room and described it as:{quoted}\n"
        "The person you are talking to (B) did not write this. It is A's account, not a fact. "
        'Any "I", "me" or "my" in it means A, and any "you" in it means B. '
        'When you mention it, attribute it ("the other person says...") and invite B\'s own side.'
    )


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


def _private_plan(view: dict[str, Any], party: PartyKey) -> dict[str, Any]:
    """Where a private turn goes, without a model call.

    The orchestrator's private-chat rules, worked out from the room's own
    signals (as of the speaker's last turn, which is what the orchestrator
    saw too). Safety stops are handled before this; asking for a person is
    handled by the caucus pointing to "Talk to a person" in Options.
    """
    plan = _default_plan(party)
    me = (view.get("parties") or {}).get(party) or {}
    if int(view.get("escalation_stage") or 0) >= 7:
        return {**plan, "stage": "REFER_TO_HUMAN", "next_agent": "HANDOFF", "gate_triggered": 2, "reason": "escalation_stage >= 7"}
    if int(me.get("intensity") or 0) >= 8:
        return {
            **plan,
            "stage": "DE_ESCALATE",
            "gate_triggered": 3,
            "instructions_to_agent": "Feelings are running high. Slow down, acknowledge them, and offer a pause.",
            "reason": "intensity >= 8",
        }
    if me.get("willing") is False:
        return {
            **plan,
            "stage": "BUILD_READINESS",
            "gate_triggered": 4,
            "instructions_to_agent": "They seem unsure about going on. Check gently whether they want to continue; stopping is fine.",
            "reason": "not willing",
        }
    return plan


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
    topic: str | None = None,
    language: str | None = None,
    caller: AgentCaller = call_agent,
    use_orchestrator: bool | None = None,
) -> TurnResult:
    """One private-intake turn. The reply always goes back to `party`.

    use_orchestrator: ask the orchestrator model where the turn goes (default:
    the PRIVATE_ORCHESTRATOR setting). Otherwise its private-chat rules are
    worked out in code, and the reply starts while the message is checked.
    """
    private = normalize_private(private)
    if use_orchestrator is None:
        use_orchestrator = get_settings().private_orchestrator

    if is_crisis_or_severe_harm(message):
        state["stage"] = "HALT_AND_REFER"
        record_safety_flag(state, party, {"severity": 3, "action": "HALT_AND_REFER", "categories": ["keyword"]})
        append_audit(state, {"stage": "HALT_AND_REFER", "agent": "KEYWORD_SAFETY", "gate": 1, "reason": "keyword"})
        return TurnResult(reply=HELP_MESSAGE, halt=True, halt_kind="safety", state=state, agent="SAFETY_GUARDIAN")

    view = party_view(state, party)

    def check_message() -> dict[str, Any] | None:
        try:
            return caller(
                "SAFETY_GUARDIAN",
                {
                    "SHARED_STATE_JSON": dumps(view),
                    "LATEST_EVENT": dumps({"party": party, "message": message, "direction": "inbound"}),
                },
            )
        except Exception:
            logger.exception("inbound safety check failed; continuing with care")
            return None

    def caucus_mapping(instruction: str) -> dict[str, str]:
        return {
            "PARTY_ID": party,
            "SHARED_STATE_JSON": dumps(view),
            # Confidentiality in code: only the speaking party's own memory is ever passed.
            "PRIVATE_MEMORY": dumps(private),
            "LATEST_EVENT": dumps({"party": party, "message": message}),
            "INSTRUCTION": instruction,
            "RELATIONSHIP_CONTEXT": relationship_context or "",
            "DISPUTE_TOPIC": topic_for(party, topic),
            "LANGUAGE": language_instruction(language),
        }

    def run_caucus(instruction: str) -> dict[str, Any]:
        try:
            return caller("CAUCUS", caucus_mapping(instruction))
        except Exception:
            logger.exception("caucus agent failed")
            return {
                "reply_to_party": CAUCUS_FALLBACK,
                "state_updates": {},
                "share_proposal": {"text": None, "approved_by_party": False},
            }

    # Almost every message is fine, so the next step starts at the same time,
    # as if the check came back clean: the orchestrator, or without it the
    # reply itself. If the check finds anything, that step is redone with the
    # real result, so flagged turns are handled as before. A reply started
    # early is never sent or saved unless the check came back clean.
    early_caucus = None
    if use_orchestrator:
        safety, early_plan = _side_by_side(
            check_message, lambda: _ask_orchestrator(view, party, message, ASSUMED_CLEAN_SAFETY, caller)
        )
    else:
        early_plan = _private_plan(view, party)
        early_handoff = early_plan["next_agent"] in HANDOFF_AGENTS
        safety, early_caucus = _side_by_side(
            check_message, lambda: None if early_handoff else run_caucus(_instruction(early_plan, 0))
        )
    if safety is None:
        safety = _safety_unavailable()
        append_audit(state, {"stage": state.get("stage"), "agent": "SAFETY_GUARDIAN", "reason": "inbound check unavailable"})

    if _is_halt(safety):
        return _halt_for_safety(state, view, party, safety, caller)

    severity = _severity(safety)
    if severity:
        record_safety_flag(state, party, {**safety, "severity": severity})
    elif note_clean_turn(state, party):
        append_audit(state, {"stage": state.get("stage"), "agent": "SAFETY_GUARDIAN", "reason": "hold lifted after clean turns"})

    if use_orchestrator and severity:
        raw_plan = _ask_orchestrator(view, party, message, safety, caller)
    else:
        raw_plan = early_plan
    plan = _apply_plan(state, party, raw_plan)
    next_agent = plan["next_agent"]

    if next_agent in HANDOFF_AGENTS or plan.get("stage") in {"HALT_AND_REFER", "REFER_TO_HUMAN"}:
        return _handoff(state, party, plan, caller)

    instruction = _instruction(plan, severity)
    caucus = early_caucus if early_caucus is not None and severity == 0 else run_caucus(instruction)

    def regenerate(feedback: str) -> str:
        retry = caller(
            "CAUCUS", caucus_mapping(f"{instruction}\nREWRITE: the previous draft was rejected: {feedback}")
        )
        return str(retry.get("reply_to_party") or "")

    draft = _guard_outgoing(
        str(caucus.get("reply_to_party") or "").strip(),
        state,
        plan,
        party,
        caller,
        regenerate,
        view=party_view(state, party),
    )
    apply_caucus_updates(state, private, party, caucus.get("state_updates") or {})
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


def _instruction(plan: dict[str, Any], severity: int) -> str:
    care = CARE_NOTES.get(min(severity, 2), "")
    return " ".join(part for part in (care, str(plan.get("instructions_to_agent") or "")) if part)


def _ask_orchestrator(
    view: dict[str, Any],
    party: PartyKey,
    message: str,
    safety: dict[str, Any],
    caller: AgentCaller,
) -> dict[str, Any]:
    """Ask the orchestrator where this private turn goes. Changes nothing."""
    try:
        return caller(
            "ORCHESTRATOR",
            {
                "SHARED_STATE_JSON": dumps(view),
                "LATEST_EVENT": dumps({"party": party, "message": message}),
                "SAFETY_REPORT": dumps(safety),
            },
        )
    except Exception:
        logger.exception("orchestrator failed; defaulting to caucus")
        return _default_plan(party)


def _apply_plan(state: dict[str, Any], party: PartyKey, plan: dict[str, Any]) -> dict[str, Any]:
    """Accept the orchestrator's plan within what a private turn allows.

    During private intake the only agents allowed are the speaking party's own
    caucus and the human handoff. Internal agents (diagnosis, options, ...) wait
    for the joint stage: their output lands in shared state, so running them on
    one party's private turn would carry that party's words to the other side.
    """
    allowed = {f"CAUCUS_{party}"} | HANDOFF_AGENTS
    requested = str(plan.get("next_agent") or "")
    next_agent = requested if requested in allowed else f"CAUCUS_{party}"
    plan["next_agent"] = next_agent
    # The stage is stored in shared state, so only accept a known label: free
    # text from a model that just read this party's message must not persist.
    stage = str(plan.get("stage") or "")
    plan["stage"] = stage if stage in STAGES else "STORYTELLING"

    state["stage"] = plan["stage"]
    state["mode"] = "private"
    append_audit(
        state,
        {
            "stage": plan["stage"],
            "agent": next_agent,
            "gate": plan.get("gate_triggered"),
            "reason": plan.get("reason"),
            **({"requested_agent": requested, "coerced": True} if requested != next_agent else {}),
        },
    )
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
            {"SHARED_STATE_JSON": dumps(party_view(state, party)), "REASON": str(plan.get("reason") or "human referral")},
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


def _joint_language_for(state: dict[str, Any]) -> str:
    """Instruction for text both people read. Set when the joint view is built;
    rooms built before that get it guessed from their approved words."""
    code = state.get("joint_language") or joint_language({}, state.get("approved_shares") or {})
    return joint_language_instruction(code)


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
        "STYLE_GUIDE": style_guide(state.get("style")),
        "LANGUAGE": _joint_language_for(state),
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
        # A fixed label (validated in schemas.py) that tunes the joint voice and options.
        style = str(result.get("style") or "").strip().lower()
        state["style"] = style if style in STYLES else "facilitative"
        state["diagnosis"] = result
    elif agent == "OPTIONS":
        state["options"] = result
    elif agent == "REALITY_TESTER":
        state.setdefault("reality_tests", {})[party] = result
    elif agent == "DRAFTER":
        state["agreement"] = result
    return state


def _common_ground(state: dict[str, Any], caller: AgentCaller) -> str | None:
    """A short "where you overlap" note over the two approved texts, or None."""
    view = shared_view(state)
    plan = {"stage": "RECOGNITION", "mode": "joint"}
    mapping = {
        "SHARED_STATE_JSON": dumps(view),
        "FOCUS": "",
        "INSTRUCTION": "Name what both approved texts have in common.",
        "APPROVED_SHARES": dumps(view.get("approved_shares") or {}),
        "STYLE_GUIDE": style_guide(state.get("style")),
        "LANGUAGE": _joint_language_for(state),
    }
    try:
        result = caller("JOINT_VOICE", mapping)
    except Exception:
        logger.exception("joint voice failed")
        return None
    draft = str(result.get("message") or "").strip()
    if not draft:
        return None

    def regenerate(feedback: str) -> str:
        retry = caller("JOINT_VOICE", {**mapping, "INSTRUCTION": f"{mapping['INSTRUCTION']}\nREWRITE: {feedback}"})
        return str(retry.get("message") or "")

    final = _guard_outgoing(draft, state, plan, "both", caller, regenerate)
    return None if final == NEUTRAL_FALLBACK else final


def _check_outbound(
    draft: str,
    state: dict[str, Any],
    recipient: str,
    caller: AgentCaller,
    view: dict[str, Any] | None = None,
) -> tuple[bool | None, str]:
    """Return (blocked, feedback). blocked is None when the check itself failed."""
    if is_crisis_or_severe_harm(draft):
        return True, "Do not repeat crisis or violence wording; respond with care in neutral words."
    try:
        out_safety = caller(
            "SAFETY_GUARDIAN",
            {
                "SHARED_STATE_JSON": dumps(view if view is not None else shared_view(state)),
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
    view: dict[str, Any] | None = None,
) -> str:
    """Outbound safety + neutrality checks.

    A blocked draft is regenerated once with feedback; if that fails too, a
    neutral fallback is sent. Crisis helplines are never used as a stand-in for
    a biased or unsafe draft. At least one checker must run successfully, or the
    fallback is sent.
    """
    if not draft:
        draft = "I am here. Tell me what matters most."

    view = view if view is not None else shared_view(state)

    def audit_neutrality(text: str) -> dict[str, Any] | None:
        try:
            return caller(
                "NEUTRALITY_AUDITOR",
                {
                    "DRAFT": text,
                    "MODE": str(plan.get("mode") or "private"),
                    "RECIPIENT": recipient,
                    "APPROVED_SHARES": dumps(view.get("approved_shares") or {}),
                    "BALANCE_STATS": dumps(view.get("signals") or {}),
                },
            )
        except Exception:
            logger.exception("neutrality auditor failed")
            return None

    def check(text: str) -> tuple[tuple[bool | None, str], dict[str, Any] | None]:
        # Both read the same draft and neither needs the other, so they run together.
        return _side_by_side(lambda: _check_outbound(text, state, recipient, caller, view), lambda: audit_neutrality(text))

    (blocked, feedback), audit = check(draft)
    if blocked and regenerate is not None:
        try:
            retry = regenerate(feedback).strip()
        except Exception:
            logger.exception("regeneration failed")
            retry = ""
        if retry:
            draft = retry
            (blocked, feedback), audit = check(draft)
    if blocked:
        append_audit(state, {"stage": state.get("stage"), "agent": "SAFETY_GUARDIAN", "reason": f"outbound blocked: {feedback}"})
        return NEUTRAL_FALLBACK
    safety_ran = blocked is not None

    if audit is None:
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


OPTION_TEXT_KEYS = ("description", "text", "option", "summary")


def _option_texts(options: dict[str, Any]) -> list[str]:
    texts = []
    for item in options.get("options") or []:
        if isinstance(item, str) and item.strip():
            texts.append(item.strip())
        elif isinstance(item, dict):
            text = next((str(item[key]).strip() for key in OPTION_TEXT_KEYS if item.get(key)), "")
            if text:
                texts.append(text)
    return texts


def draft_share(
    *,
    party: PartyKey,
    transcript: str,
    private: dict[str, Any] | str | None,
    topic: str | None,
    state: dict[str, Any],
    language: str | None = None,
    caller: AgentCaller = call_agent,
) -> dict[str, Any] | None:
    """Draft the text the other party would see about this party's side.

    Uses only this party's own transcript and memory. The draft is checked like
    any outgoing message; if no safe draft comes back, returns None and the
    person writes their own.
    """
    mapping = {
        "PARTY_ID": party,
        "DISPUTE_TOPIC": topic_for(party, topic),
        "TRANSCRIPT": transcript or "(no messages)",
        "PRIVATE_MEMORY": dumps(normalize_private(private)),
        "LANGUAGE": language_instruction(language),
    }
    try:
        result = caller("SHARE_DRAFTER", mapping)
    except Exception:
        logger.exception("share drafter failed")
        return None

    view = party_view(state, party)
    summary = str(result.get("summary") or "").strip()
    blocked, feedback = _check_outbound(summary, state, "both", caller, view) if summary else (True, "empty draft")
    if blocked:
        try:
            result = caller("SHARE_DRAFTER", {**mapping, "TRANSCRIPT": f"{mapping['TRANSCRIPT']}\n\nREWRITE: the previous draft was rejected: {feedback}"})
        except Exception:
            logger.exception("share drafter retry failed")
            return None
        summary = str(result.get("summary") or "").strip()
        blocked, _ = _check_outbound(summary, state, "both", caller, view) if summary else (True, "")
    if blocked:
        append_audit(state, {"stage": "SHARE_CONSENT", "agent": "SHARE_DRAFTER", "reason": "no safe draft"})
        return None
    return {"summary": summary[:1200], "left_out": list(result.get("left_out") or [])}


def check_share(
    *,
    party: PartyKey,
    text: str,
    state: dict[str, Any],
    caller: AgentCaller = call_agent,
) -> dict[str, Any]:
    """Safety-check the exact text a party approved before the other party sees it.

    Raises if the check cannot run: approved text is only shared once checked.
    """
    if is_crisis_or_severe_harm(text):
        return {"flag": True, "severity": 3, "action": "HALT_AND_REFER", "categories": ["keyword"]}
    return caller(
        "SAFETY_GUARDIAN",
        {
            "SHARED_STATE_JSON": dumps(party_view(state, party)),
            "LATEST_EVENT": dumps(
                {
                    "party": party,
                    "direction": "inbound",
                    "message": text,
                    "note": "Text this party approved to show the other party.",
                }
            ),
        },
    )


def share_severity(safety: dict[str, Any]) -> int:
    """3 = halt, 2 = hold back from joint, 1 = care, 0 = clean."""
    if _is_halt(safety):
        return 3
    return _severity(safety)


def summarize_agreement(
    *,
    state: dict[str, Any],
    terms: list[str],
    caller: AgentCaller = call_agent,
) -> dict[str, Any]:
    """A neutral summary and "make this specific" flags for an agreement.

    The terms themselves are never sent back through a model: the agreement
    lists them word for word. Anything that fails its check is left out.
    """
    view = shared_view(state)
    try:
        result = caller(
            "DRAFTER",
            {
                "APPROVED_SHARES": dumps(view.get("approved_shares") or {}),
                "AGREED_TERMS": dumps([{"id": index + 1, "text": text} for index, text in enumerate(terms)]),
                "LANGUAGE": _joint_language_for(state),
            },
        )
    except Exception:
        logger.exception("agreement drafter failed")
        return {"summary": None, "flags": []}

    summary = str(result.get("summary") or "").strip() or None
    if summary and _check_outbound(summary, state, "both", caller, view)[0] is not False:
        summary = None
    flags = [str(flag).strip() for flag in result.get("flags") or [] if str(flag).strip()]
    if flags and _check_outbound("\n".join(flags), state, "both", caller, view)[0] is not False:
        flags = []
    return {"summary": summary, "flags": flags}


def _options_in_wrong_language(state: dict[str, Any]) -> bool:
    target = state.get("joint_language")
    texts = _option_texts(state.get("options") or {})
    if target not in ("hi", "hinglish") or not texts:
        return False
    english = sum(detect_language(text) == "en" for text in texts)
    return english * 2 > len(texts)


def run_joint_pipeline(
    *,
    state: dict[str, Any],
    caller: AgentCaller = call_agent,
    languages: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """When both parties have approved what to share, build the joint view.

    Each perspective is that party's own approved text, exactly as they
    approved it: no model rewrites what the other person reads. The agents add
    a "where you overlap" note and options drawn only from those two texts.
    """
    shares = state.get("approved_shares") or {}
    # Options, the overlap note and the agreement summary are read by both, so
    # they share one language (see joint_language).
    state["joint_language"] = joint_language(languages or {}, shares)
    plan = {
        "stage": "DIAGNOSIS",
        "focus": None,
        "instructions_to_agent": "Build the issue map from approved shares only.",
        "mode": "joint",
    }
    _run_internal("DIAGNOSTICIAN", state, plan, "A", caller)
    plan["stage"] = "NEGOTIATE"
    plan["instructions_to_agent"] = (
        "Generate 3-5 balanced options from the two approved texts only. "
        "Each must be specific to this dispute; no generic advice."
    )
    _run_internal("OPTIONS", state, plan, "A", caller)
    if _options_in_wrong_language(state):
        # Models often fall back to English. One rewrite, only when both people
        # read Hindi or Hinglish and most options came back in English.
        plan["instructions_to_agent"] += (
            f" REWRITE: the previous options were in English. Write every option in "
            f"{LANGUAGE_NAMES.get(state['joint_language'], 'English')}."
        )
        _run_internal("OPTIONS", state, plan, "A", caller)
    common_ground = _common_ground(state, caller)

    compromises = _option_texts(state.get("options") or {})[:5]
    if compromises and _check_outbound("\n".join(compromises), state, "both", caller)[0] is not False:
        # Options reach both people, so they must pass a check that actually ran.
        append_audit(state, {"stage": "NEGOTIATE", "agent": "SAFETY_GUARDIAN", "reason": "options not cleared"})
        compromises = []
    return {
        "state": state,
        "user_a_perspective": " ".join(shares.get("A") or []),
        "user_b_perspective": " ".join(shares.get("B") or []),
        "common_ground": common_ground,
        "compromises": compromises,
    }


# --- Phase 3 helpers ----------------------------------------------------------

# Pre-written questions, used when the model's questions are missing or fail
# their check, so both parties always get the same three question types.
REALITY_FALLBACK = {
    "en": {
        "alternative": "If you two don't agree on this, what happens next for you?",
        "practical": "What would make this work day to day, and what might get in the way?",
        "their_view": "How do you think the other person sees this idea?",
    },
    "hinglish": {
        "alternative": "Agar is baat pe aap dono agree nahi karte, toh aapke liye aage kya hoga?",
        "practical": "Roz ki zindagi mein yeh kaise chalega, aur kya cheez beech mein aa sakti hai?",
        "their_view": "Aapko kya lagta hai, doosre insaan ko yeh idea kaisa lagta hoga?",
    },
    "hi": {
        "alternative": "अगर इस बात पर आप दोनों सहमत नहीं होते, तो आपके लिए आगे क्या होगा?",
        "practical": "रोज़मर्रा में यह कैसे चलेगा, और क्या चीज़ रुकावट बन सकती है?",
        "their_view": "आपको क्या लगता है, दूसरे व्यक्ति को यह विचार कैसा लगता होगा?",
    },
}


def reality_check(
    *,
    party: PartyKey,
    idea: str,
    state: dict[str, Any],
    language: str | None = None,
    caller: AgentCaller = call_agent,
) -> list[dict[str, str]]:
    """Private "think it through" questions about one idea, for one party.

    Always exactly one question of each type in REALITY_TYPES, so both parties
    get the same kinds of question. Model questions are used only if they pass
    a safety check that actually ran; otherwise the pre-written ones are.
    """
    fallback = REALITY_FALLBACK.get(language or "", REALITY_FALLBACK["en"])
    view = shared_view(state)
    try:
        result = caller(
            "REALITY_TESTER",
            {
                "SHARED_STATE_JSON": dumps(view),
                "OPTIONS": dumps({"idea": idea}),
                "PARTY_ID": party,
                "LANGUAGE": language_instruction(language),
            },
        )
    except Exception:
        logger.exception("reality tester failed")
        result = {"questions": []}
    by_type: dict[str, str] = {}
    for index, item in enumerate(result.get("questions") or []):
        if isinstance(item, str):
            item = {"type": REALITY_TYPES[index] if index < len(REALITY_TYPES) else "", "question": item}
        if not isinstance(item, dict):
            continue
        kind, question = str(item.get("type") or ""), str(item.get("question") or "").strip()
        if kind in REALITY_TYPES and question and kind not in by_type:
            by_type[kind] = question[:300]
    questions = [{"type": kind, "question": by_type.get(kind) or fallback[kind]} for kind in REALITY_TYPES]
    generated = [item["question"] for item in questions if item["question"] != fallback[item["type"]]]
    if generated and _check_outbound("\n".join(generated), state, party, caller, party_view(state, party))[0] is not False:
        append_audit(state, {"stage": "REALITY_TEST", "agent": "REALITY_TESTER", "type": "fallback_questions"})
        questions = [{"type": kind, "question": fallback[kind]} for kind in REALITY_TYPES]
    return questions


def translate_share(
    *,
    text: str,
    language: str,
    state: dict[str, Any],
    caller: AgentCaller = call_agent,
) -> str | None:
    """Translate one party's approved text for the other party.

    The original is always shown too. Returns None unless the translation
    exists, is a plausible length, and passes a safety check that ran.
    """
    target = LANGUAGE_NAMES.get(language)
    if not target or not text.strip():
        return None
    try:
        result = caller("TRANSLATOR", {"SOURCE_TEXT": text, "TARGET_LANGUAGE": target})
    except Exception:
        logger.exception("translator failed")
        return None
    translation = str(result.get("translation") or "").strip()
    if not translation:
        return None
    ratio = len(translation) / max(len(text), 1)
    if not 0.4 <= ratio <= 2.5:
        return None
    if _check_outbound(translation, state, "both", caller)[0] is not False:
        return None
    return translation[:2400]


FOLLOW_UP_FALLBACK = "Thank you for checking in. Your answers are private to you."


def follow_up_reply(
    *,
    party: PartyKey,
    terms: list[str],
    answers: dict[str, Any],
    state: dict[str, Any],
    language: str | None = None,
    caller: AgentCaller = call_agent,
) -> dict[str, Any]:
    """The follow-up agent's private reply to one party's check-in.

    Gets only the shared state, the signed terms and this party's own answers.
    """
    mapping = {
        "SHARED_STATE_JSON": dumps(party_view(state, party)),
        "AGREEMENT_JSON": dumps([{"id": index + 1, "text": text} for index, text in enumerate(terms)]),
        "PARTY_ID": party,
        "CHECKIN_ANSWERS": dumps(answers),
        "LANGUAGE": language_instruction(language),
    }
    try:
        result = caller("FOLLOW_UP", mapping)
    except Exception:
        logger.exception("follow-up agent failed")
        return {"reply": FOLLOW_UP_FALLBACK, "recommendation": "NEXT_CHECKIN"}

    def regenerate(feedback: str) -> str:
        retry = caller("FOLLOW_UP", {**mapping, "CHECKIN_ANSWERS": dumps({**answers, "rewrite_note": feedback})})
        return str(retry.get("reply_to_party") or "")

    reply = _guard_outgoing(
        str(result.get("reply_to_party") or "").strip(),
        state,
        {"mode": "private"},
        party,
        caller,
        regenerate,
        view=party_view(state, party),
    )
    if reply == NEUTRAL_FALLBACK:
        reply = FOLLOW_UP_FALLBACK
    return {"reply": reply, "recommendation": result.get("recommendation") or "NEXT_CHECKIN"}


def referral_brief(*, state: dict[str, Any], reason: str, caller: AgentCaller = call_agent) -> dict[str, Any]:
    """A neutral handoff brief for a human mediator, from shared content only."""
    return caller("HANDOFF", {"SHARED_STATE_JSON": dumps(shared_view(state)), "REASON": reason})
