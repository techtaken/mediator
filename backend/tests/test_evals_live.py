"""Two eval scenarios against real Gemini. Skipped without a real key."""

import pytest

from app.agents.llm import call_agent
from evals.harness import load_scenarios, run_scenario
from tests.conftest import has_real_gemini_key

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not has_real_gemini_key(), reason="No Gemini key configured; skip live evals."),
]

SCENARIOS = {scenario["id"]: scenario for scenario in load_scenarios()}


def test_live_manipulator_gets_nothing_from_the_other_side():
    result = run_scenario(SCENARIOS["manipulator-en"], call_agent)
    assert not result.leaks, result.leaks
    assert not result.errors


def test_live_hidden_threat_is_flagged():
    result = run_scenario(SCENARIOS["hidden-threat"], call_agent)
    assert result.safety_caught.get("A"), result.severity
    assert not result.reached_joint
