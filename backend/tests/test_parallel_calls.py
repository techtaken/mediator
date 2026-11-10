"""Agent calls that don't need each other's results run side by side.

The overlap tests use a barrier both calls must reach before either can return,
so they only pass if the two calls really are running at the same time.
"""

import json
import threading
import time

from app.agents import telemetry
from app.agents.pipeline import ASSUMED_CLEAN_SAFETY, NEUTRAL_FALLBACK, _side_by_side, handle_party_turn
from app.agents.state import empty_private, new_shared_state
from tests.test_pipeline import SAFE, FakeAgents


def _turn(agents, message="He keeps teasing me in front of family"):
    return handle_party_turn(
        party="A", message=message, state=new_shared_state("D-1"), private=empty_private(), caller=agents
    )


def _direction(mapping):
    return json.loads(mapping["LATEST_EVENT"]).get("direction")


def _meeting_point():
    return threading.Barrier(2, timeout=3)


# --- Running together ---------------------------------------------------------------


def test_the_message_check_and_the_orchestrator_run_at_the_same_time():
    both = _meeting_point()
    agents = FakeAgents()

    def safety(mapping):
        if _direction(mapping) == "inbound":
            both.wait()
        return dict(SAFE)

    def orchestrator(mapping):
        both.wait()
        return agents.default("ORCHESTRATOR", mapping)

    agents.overrides.update(SAFETY_GUARDIAN=safety, ORCHESTRATOR=orchestrator)
    result = _turn(agents)
    # Had they run one after another, both would have failed and been treated with care.
    assert len(agents.of("ORCHESTRATOR")) == 1
    assert not any(entry.get("reason") == "inbound check unavailable" for entry in result.state["audit_log"])
    assert result.reply.startswith("It sounds like trust matters")


def test_the_two_checks_on_a_reply_run_at_the_same_time():
    both = _meeting_point()
    agents = FakeAgents()

    def safety(mapping):
        if _direction(mapping) == "outbound":
            both.wait()
        return dict(SAFE)

    def auditor(mapping):
        both.wait()
        return agents.default("NEUTRALITY_AUDITOR", mapping)

    agents.overrides.update(SAFETY_GUARDIAN=safety, NEUTRALITY_AUDITOR=auditor)
    # Had they run one after another, both checks would have failed and the fallback gone out.
    assert _turn(agents).reply.startswith("It sounds like trust matters")


def test_a_reply_waits_about_as_long_as_its_slowest_pair_not_their_sum():
    """Five calls of 0.2s each: about 0.6s side by side, 1s one after another."""
    agents = FakeAgents()

    def slow(role):
        def answer(mapping):
            time.sleep(0.2)
            return dict(SAFE) if role == "SAFETY_GUARDIAN" else agents.default(role, mapping)

        return answer

    agents.overrides.update({role: slow(role) for role in ("SAFETY_GUARDIAN", "ORCHESTRATOR", "CAUCUS", "NEUTRALITY_AUDITOR")})
    started = time.monotonic()
    _turn(agents)
    assert time.monotonic() - started < 0.85


# --- Behaving as before -------------------------------------------------------------


def test_a_clean_message_asks_the_orchestrator_once():
    agents = FakeAgents()
    _turn(agents)
    (call,) = agents.of("ORCHESTRATOR")
    assert json.loads(call["mapping"]["SAFETY_REPORT"]) == ASSUMED_CLEAN_SAFETY


def test_a_flagged_message_asks_the_orchestrator_again_with_the_real_report():
    flagged = {"flag": True, "severity": 2, "action": "PAUSE_AND_CHECK", "categories": ["threat"], "block_outgoing_message": False}
    agents = FakeAgents(
        SAFETY_GUARDIAN=lambda mapping: dict(flagged) if _direction(mapping) == "inbound" else dict(SAFE)
    )
    _turn(agents)
    calls = agents.of("ORCHESTRATOR")
    assert len(calls) == 2
    assert "PAUSE_AND_CHECK" not in calls[0]["mapping"]["SAFETY_REPORT"]
    assert "PAUSE_AND_CHECK" in calls[1]["mapping"]["SAFETY_REPORT"]


def test_a_failed_message_check_also_asks_again_with_care():
    def safety(mapping):
        if _direction(mapping) == "inbound":
            raise RuntimeError("check down")
        return dict(SAFE)

    agents = FakeAgents(SAFETY_GUARDIAN=safety)
    result = _turn(agents)
    calls = agents.of("ORCHESTRATOR")
    assert len(calls) == 2 and "safety_check_unavailable" in calls[1]["mapping"]["SAFETY_REPORT"]
    assert any(entry.get("reason") == "inbound check unavailable" for entry in result.state["audit_log"])


def test_a_halt_still_stops_the_turn_and_never_reaches_the_mediator():
    halt = {"flag": True, "severity": 3, "action": "HALT_AND_REFER", "categories": ["self_harm"],
            "message_to_affected_party": "Please reach out now.", "block_outgoing_message": True}
    agents = FakeAgents(SAFETY_GUARDIAN=lambda mapping: dict(halt) if _direction(mapping) == "inbound" else dict(SAFE))
    result = _turn(agents)
    assert result.halt and result.halt_kind == "safety"
    assert len(agents.of("ORCHESTRATOR")) <= 1
    assert agents.of("CAUCUS") == []


def test_a_rewritten_reply_is_checked_again_in_full():
    agents = FakeAgents()
    outbound = {"count": 0}

    def safety(mapping):
        if _direction(mapping) == "outbound":
            outbound["count"] += 1
            if outbound["count"] == 1:
                return {**SAFE, "block_outgoing_message": True, "evidence": "takes a side"}
        return dict(SAFE)

    def caucus(mapping):
        reply = agents.default("CAUCUS", mapping)
        if "REWRITE" in mapping["INSTRUCTION"]:
            reply["reply_to_party"] = "What would feel fair to both of you?"
        return reply

    agents.overrides.update(SAFETY_GUARDIAN=safety, CAUCUS=caucus)
    result = _turn(agents)
    assert result.reply == "What would feel fair to both of you?"
    assert [call["mapping"]["DRAFT"] for call in agents.of("NEUTRALITY_AUDITOR")][-1] == "What would feel fair to both of you?"


def test_a_reply_still_blocked_after_a_rewrite_falls_back():
    agents = FakeAgents(
        SAFETY_GUARDIAN=lambda mapping: {**SAFE, "block_outgoing_message": True}
        if _direction(mapping) == "outbound"
        else dict(SAFE)
    )
    assert _turn(agents).reply == NEUTRAL_FALLBACK


def test_if_both_reply_checks_fail_the_neutral_fallback_goes_out():
    def broken(mapping):
        raise RuntimeError("down")

    agents = FakeAgents(
        SAFETY_GUARDIAN=lambda mapping: broken(mapping) if _direction(mapping) == "outbound" else dict(SAFE),
        NEUTRALITY_AUDITOR=broken,
    )
    assert _turn(agents).reply == NEUTRAL_FALLBACK


# --- Call stats ---------------------------------------------------------------------


def test_call_stats_from_both_sides_are_kept_for_the_room():
    with telemetry.collect_calls() as bucket:
        _side_by_side(
            lambda: telemetry.record(telemetry.CallRecord(role="SAFETY_GUARDIAN", ok=True, attempts=1, latency_ms=5)),
            lambda: telemetry.record(telemetry.CallRecord(role="ORCHESTRATOR", ok=True, attempts=1, latency_ms=5)),
        )
    assert sorted(entry.role for entry in bucket) == ["ORCHESTRATOR", "SAFETY_GUARDIAN"]
