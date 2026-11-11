import pytest

from app.agents.llm import call_agent, dumps
from app.agents.pipeline import NEUTRAL_FALLBACK, handle_party_turn
from app.agents.prompts import language_instruction
from app.agents.state import empty_private, new_shared_state, shared_view
from tests.conftest import has_real_gemini_key

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not has_real_gemini_key(), reason="No Gemini key configured; skip live Gemini API tests."),
]


def test_caucus_agent_returns_valid_reply():
    state = new_shared_state("live-1", "Partners sharing a home")
    out = call_agent(
        "CAUCUS",
        {
            "PARTY_ID": "A",
            "SHARED_STATE_JSON": dumps(shared_view(state)),
            "PRIVATE_MEMORY": dumps(empty_private()),
            "LATEST_EVENT": dumps({"party": "A", "message": "I feel exhausted and ignored when chores are left to me."}),
            "INSTRUCTION": "Listen and reflect.",
            "RELATIONSHIP_CONTEXT": "Partners sharing a home",
            "DISPUTE_TOPIC": "Not given.",
            "LANGUAGE": language_instruction(None),
        },
    )
    assert len(out["reply_to_party"].strip()) > 20


def test_caucus_replies_in_devanagari_when_asked():
    state = new_shared_state("live-4", "Brothers")
    out = call_agent(
        "CAUCUS",
        {
            "PARTY_ID": "A",
            "SHARED_STATE_JSON": dumps(shared_view(state)),
            "PRIVATE_MEMORY": dumps(empty_private()),
            "LATEST_EVENT": dumps({"party": "A", "message": "My brother wants to sell our father's land."}),
            "INSTRUCTION": "Listen and reflect.",
            "RELATIONSHIP_CONTEXT": "Brothers",
            "DISPUTE_TOPIC": "Not given.",
            "LANGUAGE": language_instruction("hi"),
        },
    )
    assert any("\u0900" <= char <= "\u097f" for char in out["reply_to_party"])


def test_safety_guardian_flags_a_threat():
    state = new_shared_state("live-2")
    out = call_agent(
        "SAFETY_GUARDIAN",
        {
            "SHARED_STATE_JSON": dumps(shared_view(state)),
            "LATEST_EVENT": dumps(
                {"party": "B", "direction": "inbound", "message": "If he takes the car again he'll regret it, I know where he sleeps."}
            ),
        },
    )
    assert out["flag"] is True and out["severity"] >= 2


def test_full_turn_against_real_api():
    # The pipeline is built to survive agent failures with safe fallbacks, so a
    # turn "succeeds" even when Gemini is down. Record every call so this test
    # only passes when the real agents actually answered.
    calls = []

    def recording_caller(role, mapping):
        try:
            out = call_agent(role, mapping)
        except Exception as exc:
            calls.append((role, repr(exc)))
            raise
        calls.append((role, None))
        return out

    result = handle_party_turn(
        party="A",
        message="My 23 year old daughter wants an expensive phone and I can't make her see why simple is fine.",
        state=new_shared_state("live-3", "Father and adult daughter"),
        private=empty_private(),
        caller=recording_caller,
    )

    failures = [(role, error) for role, error in calls if error]
    assert not failures, f"agent calls failed, so the turn ran on fallbacks: {failures}"
    roles = {role for role, _ in calls}
    assert {"SAFETY_GUARDIAN", "ORCHESTRATOR", "CAUCUS", "NEUTRALITY_AUDITOR"} <= roles
    assert result.halt is False
    assert result.reply.strip()
    assert result.reply != NEUTRAL_FALLBACK, "reply is a canned fallback line"
