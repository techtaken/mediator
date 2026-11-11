"""Agent calls that don't need each other's results run side by side.

The overlap tests use a barrier both calls must reach before either can return,
so they only pass if the two calls really are running at the same time.
"""

import json
import threading
import time

import pytest

from app.agents import telemetry
from app.agents.llm import QuotaExceeded
from app.agents.pipeline import ASSUMED_CLEAN_SAFETY, NEUTRAL_FALLBACK, MediatorUnavailable, _side_by_side, handle_party_turn
from app.agents.state import empty_private, new_shared_state
from tests.test_pipeline import SAFE, FakeAgents


def _turn(agents, message="He keeps teasing me in front of family", use_orchestrator=False, state=None):
    return handle_party_turn(
        party="A",
        message=message,
        state=state if state is not None else new_shared_state("D-1"),
        private=empty_private(),
        caller=agents,
        use_orchestrator=use_orchestrator,
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
    result = _turn(agents, use_orchestrator=True)
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
    """Four calls of 0.2s each: about 0.4s side by side, 0.8s one after another."""
    agents = FakeAgents()

    def slow(role):
        def answer(mapping):
            time.sleep(0.2)
            return dict(SAFE) if role == "SAFETY_GUARDIAN" else agents.default(role, mapping)

        return answer

    agents.overrides.update({role: slow(role) for role in ("SAFETY_GUARDIAN", "ORCHESTRATOR", "CAUCUS", "NEUTRALITY_AUDITOR")})
    started = time.monotonic()
    _turn(agents)
    assert time.monotonic() - started < 0.65
    assert agents.of("ORCHESTRATOR") == []


def test_the_message_check_and_the_reply_run_at_the_same_time():
    both = _meeting_point()
    agents = FakeAgents()

    def safety(mapping):
        if _direction(mapping) == "inbound":
            both.wait()
        return dict(SAFE)

    def caucus(mapping):
        both.wait()
        return agents.default("CAUCUS", mapping)

    agents.overrides.update(SAFETY_GUARDIAN=safety, CAUCUS=caucus)
    result = _turn(agents)
    # Had they run one after another, both would have failed: a fallback reply, with care.
    assert result.reply.startswith("It sounds like trust matters")
    assert len(agents.of("CAUCUS")) == 1


# --- Without the orchestrator -------------------------------------------------------


def test_private_chat_skips_the_orchestrator_by_default():
    agents = FakeAgents()
    result = handle_party_turn(party="A", message="hi", state=new_shared_state("D-1"), private=empty_private(), caller=agents)
    assert agents.of("ORCHESTRATOR") == []
    assert result.state["stage"] == "STORYTELLING" and result.agent == "CAUCUS_A"
    assert "Listen, reflect interests" in agents.of("CAUCUS")[0]["mapping"]["INSTRUCTION"]


def test_a_flagged_message_gets_a_fresh_reply_written_with_care():
    flagged = {"flag": True, "severity": 2, "action": "PAUSE_AND_CHECK", "categories": ["threat"], "block_outgoing_message": False}
    agents = FakeAgents()

    def caucus(mapping):
        reply = agents.default("CAUCUS", mapping)
        reply["reply_to_party"] = "Careful reply." if "Pause the move" in mapping["INSTRUCTION"] else "Early reply."
        return reply

    agents.overrides.update(
        SAFETY_GUARDIAN=lambda mapping: dict(flagged) if _direction(mapping) == "inbound" else dict(SAFE), CAUCUS=caucus
    )
    result = _turn(agents)
    assert result.reply == "Careful reply."
    assert len(agents.of("CAUCUS")) == 2


def test_a_failed_message_check_also_gets_a_reply_written_with_care():
    def safety(mapping):
        if _direction(mapping) == "inbound":
            raise RuntimeError("check down")
        return dict(SAFE)

    agents = FakeAgents(SAFETY_GUARDIAN=safety)
    result = _turn(agents)
    assert "Go gently" in agents.of("CAUCUS")[-1]["mapping"]["INSTRUCTION"]
    assert result.state["safety"]["flags"]["A"]["severity"] == 1


def _state_where_a(**signals):
    state = new_shared_state("D-1")
    state["parties"]["A"].update(signals)
    return state


def test_very_strong_feelings_slow_the_reply_down():
    agents = FakeAgents()
    result = _turn(agents, state=_state_where_a(intensity=9))
    assert result.state["stage"] == "DE_ESCALATE"
    assert "offer a pause" in agents.of("CAUCUS")[0]["mapping"]["INSTRUCTION"]


def test_someone_unsure_about_going_on_is_checked_on():
    agents = FakeAgents()
    result = _turn(agents, state=_state_where_a(willing=False))
    assert result.state["stage"] == "BUILD_READINESS"
    assert "stopping is fine" in agents.of("CAUCUS")[0]["mapping"]["INSTRUCTION"]


def test_only_the_speaker_feelings_set_the_pace_of_their_own_chat():
    state = new_shared_state("D-1")
    state["parties"]["B"]["intensity"] = 9
    assert _turn(FakeAgents(), state=state).state["stage"] == "STORYTELLING"


def test_a_badly_escalated_room_goes_to_a_person_without_a_reply_attempt():
    state = new_shared_state("D-1")
    state["escalation_stage"] = 7
    agents = FakeAgents()
    result = _turn(agents, state=state)
    assert "HANDOFF" in agents.roles() and agents.of("CAUCUS") == []
    assert result.reply == "A human mediator would help here."


def test_the_mediator_knows_to_point_to_talk_to_a_person():
    agents = FakeAgents()
    _turn(agents, message="Can I talk to a real person?")
    assert 'choose "Talk to a' in agents.of("CAUCUS")[0]["prompt"]


# --- Behaving as before -------------------------------------------------------------


def test_a_clean_message_asks_the_orchestrator_once():
    agents = FakeAgents()
    _turn(agents, use_orchestrator=True)
    (call,) = agents.of("ORCHESTRATOR")
    assert json.loads(call["mapping"]["SAFETY_REPORT"]) == ASSUMED_CLEAN_SAFETY


def test_a_flagged_message_asks_the_orchestrator_again_with_the_real_report():
    flagged = {"flag": True, "severity": 2, "action": "PAUSE_AND_CHECK", "categories": ["threat"], "block_outgoing_message": False}
    agents = FakeAgents(
        SAFETY_GUARDIAN=lambda mapping: dict(flagged) if _direction(mapping) == "inbound" else dict(SAFE)
    )
    _turn(agents, use_orchestrator=True)
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
    result = _turn(agents, use_orchestrator=True)
    calls = agents.of("ORCHESTRATOR")
    assert len(calls) == 2 and "safety_check_unavailable" in calls[1]["mapping"]["SAFETY_REPORT"]
    assert any(entry.get("reason") == "inbound check unavailable" for entry in result.state["audit_log"])


@pytest.mark.parametrize("use_orchestrator", [False, True])
def test_a_halt_still_stops_the_turn_and_no_mediator_reply_goes_out(use_orchestrator):
    halt = {"flag": True, "severity": 3, "action": "HALT_AND_REFER", "categories": ["self_harm"],
            "message_to_affected_party": "Please reach out now.", "block_outgoing_message": True}
    agents = FakeAgents(SAFETY_GUARDIAN=lambda mapping: dict(halt) if _direction(mapping) == "inbound" else dict(SAFE))
    result = _turn(agents, use_orchestrator=use_orchestrator)
    assert result.halt and result.halt_kind == "safety"
    assert result.reply.startswith("Please reach out now.")
    # A reply may have been started early, but nothing from it is sent or kept.
    assert result.private is None
    assert result.state["parties"]["A"]["intensity"] == 5
    assert agents.of("NEUTRALITY_AUDITOR") == []


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


def test_if_both_reply_checks_fail_no_reply_goes_out():
    def broken(mapping):
        raise RuntimeError("down")

    agents = FakeAgents(
        SAFETY_GUARDIAN=lambda mapping: broken(mapping) if _direction(mapping) == "outbound" else dict(SAFE),
        NEUTRALITY_AUDITOR=broken,
    )
    with pytest.raises(MediatorUnavailable):
        _turn(agents)


# --- When no reply can be written ---------------------------------------------------


@pytest.mark.parametrize("use_orchestrator", [False, True])
@pytest.mark.parametrize("failure", [QuotaExceeded("quota"), RuntimeError("overloaded")])
def test_no_stock_line_goes_out_when_the_reply_cannot_be_written(failure, use_orchestrator):
    agents = FakeAgents(CAUCUS=failure)
    with pytest.raises(MediatorUnavailable):
        _turn(agents, use_orchestrator=use_orchestrator)


def test_an_early_reply_that_failed_gets_one_more_try():
    agents = FakeAgents()
    tries = {"count": 0}

    def caucus(mapping):
        tries["count"] += 1
        if tries["count"] == 1:
            raise RuntimeError("blip")
        return agents.default("CAUCUS", mapping)

    agents.overrides["CAUCUS"] = caucus
    assert _turn(agents).reply.startswith("It sounds like trust matters")
    assert tries["count"] == 2


def test_a_reply_judged_unsafe_still_gets_the_neutral_line():
    """That's a real decision, not an outage, so it isn't treated as one."""
    agents = FakeAgents(
        SAFETY_GUARDIAN=lambda mapping: {**SAFE, "block_outgoing_message": True}
        if _direction(mapping) == "outbound"
        else dict(SAFE)
    )
    assert _turn(agents).reply == NEUTRAL_FALLBACK


def test_a_safety_stop_still_works_when_replies_cannot_be_written():
    halt = {"flag": True, "severity": 3, "action": "HALT_AND_REFER", "message_to_affected_party": "Please reach out now."}
    agents = FakeAgents(
        SAFETY_GUARDIAN=lambda mapping: dict(halt) if _direction(mapping) == "inbound" else dict(SAFE),
        CAUCUS=QuotaExceeded("quota"),
    )
    result = _turn(agents)
    assert result.halt and result.reply.startswith("Please reach out now.")


# --- Call stats ---------------------------------------------------------------------


def test_call_stats_from_both_sides_are_kept_for_the_room():
    with telemetry.collect_calls() as bucket:
        _side_by_side(
            lambda: telemetry.record(telemetry.CallRecord(role="SAFETY_GUARDIAN", ok=True, attempts=1, latency_ms=5)),
            lambda: telemetry.record(telemetry.CallRecord(role="ORCHESTRATOR", ok=True, attempts=1, latency_ms=5)),
        )
    assert sorted(entry.role for entry in bucket) == ["ORCHESTRATOR", "SAFETY_GUARDIAN"]


def test_calls_starting_together_share_one_client():
    """Two clients built at once used to close one another's connection."""
    from unittest.mock import patch

    import app.gemini_client as gemini_client

    built = []

    def slow_client(**_kwargs):
        time.sleep(0.05)
        built.append(object())
        return built[-1]

    gemini_client._build_client.cache_clear()
    try:
        with patch.object(gemini_client.genai, "Client", side_effect=slow_client):
            first, second = _side_by_side(gemini_client.get_client, gemini_client.get_client)
        assert first is second and len(built) == 1
    finally:
        gemini_client._build_client.cache_clear()


# --- Talking to the person, not about them --------------------------------------


@pytest.mark.parametrize(
    "slip",
    [
        "A's account describes feeling frustrated about the parking spot.",
        "In A's account, the parking spot feels like respect.",
        "A feels unheard. What would help?",
        "Party A wants the spot back.",
        "nk feels unheard when this happens.",
        "B's view matters too.",
    ],
)
def test_a_reply_that_talks_about_the_person_is_rewritten(slip):
    state = new_shared_state("D-1")
    state["parties"]["A"]["name"] = "nk"
    agents = FakeAgents()

    def caucus(mapping):
        reply = agents.default("CAUCUS", mapping)
        reply["reply_to_party"] = "What matters most to you here?" if "REWRITE" in mapping["INSTRUCTION"] else slip
        return reply

    agents.overrides["CAUCUS"] = caucus
    result = _turn(agents, state=state)
    assert result.reply == "What matters most to you here?"
    assert '"you"' in agents.of("CAUCUS")[-1]["mapping"]["INSTRUCTION"]


@pytest.mark.parametrize(
    "fine",
    [
        "A lot of people feel this way. What would help you?",
        "A small step could be talking about it calmly. What do you think?",
        "What would you like Ramprasad to understand?",
    ],
)
def test_a_reply_that_talks_to_the_person_is_left_alone(fine):
    state = new_shared_state("D-1")
    state["parties"]["A"]["name"] = "nk"
    agents = FakeAgents()

    def caucus(mapping):
        reply = agents.default("CAUCUS", mapping)
        reply["reply_to_party"] = fine
        return reply

    agents.overrides["CAUCUS"] = caucus
    assert _turn(agents, state=state).reply == fine
    assert len(agents.of("CAUCUS")) == 1


def test_the_mediator_is_told_to_say_you():
    agents = FakeAgents()
    _turn(agents)
    prompt = " ".join(agents.of("CAUCUS")[0]["prompt"].split())
    assert 'Talk to this person directly, as "you"' in prompt and "never use their name" in prompt

