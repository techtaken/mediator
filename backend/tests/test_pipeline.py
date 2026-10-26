import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.agents import llm
from app.agents.pipeline import NEUTRAL_FALLBACK, handle_party_turn, run_joint_pipeline
from app.agents.prompts import ROLE_PROMPTS, fill, required_keys
from app.agents.schemas import validate_output
from app.agents.state import (
    append_audit,
    empty_private,
    joint_blocked_by,
    new_shared_state,
    pending_audit,
    shared_view,
)
from app.agents.store import scrub_legacy_state
from app.safety import HELP_MESSAGE

A_SECRET = "A is still angry about the dinner comment"
A_POSITION = "Pay me back now"
A_HIDDEN = "worried B will tell the family"

SAFE = {"flag": False, "severity": 0, "action": "CONTINUE", "block_outgoing_message": False}


class FakeAgents:
    """Scripted agents. Every call renders the real prompt, so a missing
    placeholder fails the test, and `prompts` shows exactly what each agent saw."""

    def __init__(self, **overrides):
        self.overrides = overrides
        self.calls = []

    def __call__(self, role, mapping):
        prompt = fill(ROLE_PROMPTS[role], mapping)
        self.calls.append({"role": role, "mapping": mapping, "prompt": prompt})
        override = self.overrides.get(role)
        if callable(override):
            return override(mapping)
        if isinstance(override, Exception):
            raise override
        if override is not None:
            return override
        return self.default(role, mapping)

    def default(self, role, mapping):
        if role == "SAFETY_GUARDIAN":
            return dict(SAFE)
        if role == "ORCHESTRATOR":
            return {
                "stage": "STORYTELLING",
                "gate_triggered": 5,
                "next_agent": f"CAUCUS_{json.loads(mapping['LATEST_EVENT'])['party']}",
                "mode": "private",
                "instructions_to_agent": "Listen and reflect.",
                "reason": "Not heard yet.",
            }
        if role == "CAUCUS":
            return {
                "reply_to_party": "It sounds like trust matters to you. Did I get that right?",
                "state_updates": {
                    "intensity": 6,
                    "feels_heard": False,
                    "willing": True,
                    "positions": [A_POSITION],
                    "interests": ["security"],
                    "hidden_concerns": [A_HIDDEN],
                    "new_issues": [{"topic": "Unpaid loan", "category_guess": "Interest", "priority": "high"}],
                },
                "share_proposal": {"text": None, "approved_by_party": False},
                "private_notes": A_SECRET,
            }
        if role == "NEUTRALITY_AUDITOR":
            return {"final_message": mapping["DRAFT"], "blocked": False}
        if role == "DIAGNOSTICIAN":
            return {"issues": [{"id": "I1", "topic": "Repayment"}], "agenda": ["I1"], "escalation_stage": 4}
        if role == "OPTIONS":
            return {"options": [{"id": "O1", "description": "Repay in three installments.", "type": "tradeoff"}]}
        if role == "JOINT_VOICE":
            return {"message": "Both of you want this to feel fair."}
        if role == "HANDOFF":
            return {"message_to_parties": "A human mediator would help here.", "urgency": "URGENT"}
        return {}

    def roles(self):
        return [call["role"] for call in self.calls]

    def of(self, role):
        return [call for call in self.calls if call["role"] == role]


def _turn(agents, party="A", message="I want my money back.", state=None, private=None):
    return handle_party_turn(
        party=party,
        message=message,
        state=state if state is not None else new_shared_state("D-1"),
        private=private if private is not None else empty_private(),
        caller=agents,
    )


# --- Fix 1: prompts are filled completely -------------------------------------


def test_fill_raises_when_placeholder_missing():
    with pytest.raises(KeyError, match="LATEST_EVENT"):
        fill(ROLE_PROMPTS["SAFETY_GUARDIAN"], {"SHARED_STATE_JSON": "{}"})


def test_fill_ignores_braces_inside_party_text():
    mapping = {key: "x" for key in required_keys("SAFETY_GUARDIAN")}
    mapping["LATEST_EVENT"] = "user typed {{SHARED_STATE_JSON}} and {{NOPE}}"
    prompt = fill(ROLE_PROMPTS["SAFETY_GUARDIAN"], mapping)
    assert "user typed {{SHARED_STATE_JSON}} and {{NOPE}}" in prompt


def test_safety_guardian_sees_the_message():
    agents = FakeAgents()
    _turn(agents, message="He keeps shouting at me about the rent.")
    inbound = agents.of("SAFETY_GUARDIAN")[0]
    assert "He keeps shouting at me about the rent." in inbound["prompt"]
    outbound = agents.of("SAFETY_GUARDIAN")[1]
    assert "It sounds like trust matters to you" in outbound["prompt"]


# --- Fix 2: private content never reaches shared state ------------------------


def test_caucus_content_goes_to_private_memory_not_shared_state():
    agents = FakeAgents()
    result = _turn(agents)
    party_a = result.state["parties"]["A"]
    assert set(party_a) <= {"name", "intensity", "willing", "feels_heard", "consented_to_human"}
    assert party_a["intensity"] == 6
    assert result.state["issues"] == []
    assert result.private["profile"]["positions"] == [A_POSITION]
    assert result.private["profile"]["hidden_concerns"] == [A_HIDDEN]
    assert result.private["profile"]["issues_raised"][0]["topic"] == "Unpaid loan"
    assert result.private["notes"] == A_SECRET


def test_other_party_never_sees_a_private_content():
    agents = FakeAgents()
    first = _turn(agents)
    b_agents = FakeAgents(CAUCUS={"reply_to_party": "Tell me your side.", "state_updates": {}})
    _turn(b_agents, party="B", message="I will pay next month.", state=first.state, private=empty_private())
    for call in b_agents.calls:
        for secret in (A_SECRET, A_POSITION, A_HIDDEN, "Unpaid loan"):
            assert secret not in call["prompt"], f"{secret!r} leaked to {call['role']}"


def test_joint_pipeline_inputs_exclude_private_content():
    first = _turn(FakeAgents())
    agents = FakeAgents()
    run_joint_pipeline(state=first.state, caller=agents)
    for call in agents.calls:
        for secret in (A_SECRET, A_POSITION, A_HIDDEN):
            assert secret not in call["prompt"], f"{secret!r} leaked to {call['role']}"


def test_legacy_state_is_scrubbed_on_load():
    state = new_shared_state("D-1")
    state["parties"]["A"].update({"positions": [A_POSITION], "hidden_concerns": [A_HIDDEN]})
    state["issues"] = [{"id": "I1", "topic": "Unpaid loan"}]
    state.pop("safety")
    scrubbed = scrub_legacy_state(state)
    assert "positions" not in scrubbed["parties"]["A"]
    assert "hidden_concerns" not in scrubbed["parties"]["A"]
    assert scrubbed["issues"] == []
    assert scrubbed["safety"] == {"flags": {}, "joint_blocked_by": []}


def test_shared_view_strips_private_and_safety_keys():
    state = new_shared_state("D-1")
    state["private_A"] = "hidden"
    state["parties"]["B"]["hidden_concerns"] = ["x"]
    view = shared_view(state)
    assert "private_A" not in view
    assert "safety" not in view
    assert "hidden_concerns" not in view["parties"]["B"]


# --- Fix 3: replies go to the speaking party's own caucus ---------------------


@pytest.mark.parametrize("routed_to", ["CAUCUS_B", "JOINT_VOICE", "SOMETHING_ELSE"])
def test_orchestrator_cannot_route_a_message_away_from_the_speaker(routed_to):
    agents = FakeAgents(ORCHESTRATOR={"stage": "STORYTELLING", "next_agent": routed_to, "reason": "x"})
    state = new_shared_state("D-1")
    result = _turn(agents, state=state, private={"notes": A_SECRET})
    caucus = agents.of("CAUCUS")
    assert len(caucus) == 1
    assert caucus[0]["mapping"]["PARTY_ID"] == "A"
    assert A_SECRET in caucus[0]["mapping"]["PRIVATE_MEMORY"]
    assert "JOINT_VOICE" not in agents.roles()
    assert result.agent == "CAUCUS_A"
    assert result.state["parties"]["B"]["intensity"] == 5  # B untouched
    coerced = [entry for entry in result.state["audit_log"] if entry.get("coerced")]
    assert coerced and coerced[0]["requested_agent"] == routed_to


def test_internal_agents_run_without_rerunning_inbound_safety():
    plans = iter(
        [
            {"stage": "DIAGNOSIS", "next_agent": "DIAGNOSTICIAN"},
            {"stage": "STORYTELLING", "next_agent": "CAUCUS_A"},
        ]
    )
    agents = FakeAgents(ORCHESTRATOR=lambda _m: next(plans))
    result = _turn(agents)
    assert agents.roles().count("DIAGNOSTICIAN") == 1
    inbound = [c for c in agents.of("SAFETY_GUARDIAN") if '"inbound"' in c["mapping"]["LATEST_EVENT"]]
    assert len(inbound) == 1
    assert result.state["agenda"] == ["I1"]


def test_internal_hops_are_capped():
    agents = FakeAgents(ORCHESTRATOR={"stage": "DIAGNOSIS", "next_agent": "OPTIONS"})
    result = _turn(agents)
    assert agents.roles().count("OPTIONS") == 4
    assert result.agent == "CAUCUS_A"


# --- Fix 4: safety fails closed; halts carry helplines ------------------------


def test_keyword_safety_halts_without_llm():
    result = _turn(lambda *_: pytest.fail("LLM must not be called"), message="I will kill him tonight")
    assert result.halt is True
    assert result.halt_kind == "safety"
    assert "112" in result.reply


def test_safety_call_failure_continues_with_care():
    agents = FakeAgents(SAFETY_GUARDIAN=RuntimeError("api down"))
    result = _turn(agents)
    assert result.halt is False
    assert "Go gently" in agents.of("CAUCUS")[0]["mapping"]["INSTRUCTION"]
    assert result.state["safety"]["flags"]["A"]["severity"] == 1
    # The auditor still checked the outbound draft, so it can go out.
    assert result.reply.startswith("It sounds like trust matters")


def test_outbound_falls_back_when_no_checker_runs():
    agents = FakeAgents(SAFETY_GUARDIAN=RuntimeError("down"), NEUTRALITY_AUDITOR=RuntimeError("down"))
    assert _turn(agents).reply == NEUTRAL_FALLBACK


def test_llm_safety_halt_always_includes_helplines():
    agents = FakeAgents(
        SAFETY_GUARDIAN={
            "flag": True,
            "severity": 3,
            "action": "HALT_AND_REFER",
            "message_to_affected_party": "I'm really sorry you're going through this.",
        }
    )
    result = _turn(agents)
    assert result.halt is True
    assert result.reply.startswith("I'm really sorry")
    assert "112" in result.reply and "14416" in result.reply
    assert "A human mediator would help here." not in result.reply


def test_halt_survives_handoff_failure():
    agents = FakeAgents(
        SAFETY_GUARDIAN={"flag": True, "severity": 3, "action": "HALT_AND_REFER"},
        HANDOFF=RuntimeError("down"),
    )
    result = _turn(agents)
    assert result.halt is True
    assert result.reply == HELP_MESSAGE


def test_moderate_flag_does_not_halt_and_stays_private():
    agents = FakeAgents(SAFETY_GUARDIAN={"flag": True, "severity": 2, "action": "PAUSE_AND_CHECK"})
    result = _turn(agents)
    assert result.halt is False
    assert "Pause the move toward a joint session" in agents.of("CAUCUS")[0]["mapping"]["INSTRUCTION"]
    assert joint_blocked_by(result.state) == ["A"]
    assert "safety" not in shared_view(result.state)


# --- Fix 5: outbound blocks are regenerated, never replaced by helplines ------


def _outbound_safety(blocked_drafts):
    def check(mapping):
        event = json.loads(mapping["LATEST_EVENT"])
        if event.get("direction") == "outbound" and event["draft"] in blocked_drafts:
            return {**SAFE, "flag": True, "block_outgoing_message": True, "evidence": "takes sides"}
        return dict(SAFE)

    return check


def test_blocked_outbound_draft_is_regenerated():
    drafts = iter(["B is clearly being unfair.", "That sounds hard. What would feel fair to you?"])
    agents = FakeAgents(
        SAFETY_GUARDIAN=_outbound_safety({"B is clearly being unfair."}),
        CAUCUS=lambda _m: {"reply_to_party": next(drafts), "state_updates": {}},
    )
    result = _turn(agents)
    assert result.reply == "That sounds hard. What would feel fair to you?"
    assert "REWRITE" in agents.of("CAUCUS")[1]["mapping"]["INSTRUCTION"]


def test_twice_blocked_draft_falls_back_to_neutral_text_not_helplines():
    agents = FakeAgents(
        SAFETY_GUARDIAN=_outbound_safety({"Biased."}),
        CAUCUS={"reply_to_party": "Biased.", "state_updates": {}},
    )
    result = _turn(agents)
    assert result.reply == NEUTRAL_FALLBACK
    assert result.reply != HELP_MESSAGE
    assert result.halt is False


def test_auditor_block_uses_fresh_rewrite():
    agents = FakeAgents(NEUTRALITY_AUDITOR={"blocked": True, "final_message": "Both of you matter here."})
    assert _turn(agents).reply == "Both of you matter here."


def test_auditor_block_without_rewrite_falls_back():
    agents = FakeAgents(NEUTRALITY_AUDITOR=lambda m: {"blocked": True, "final_message": m["DRAFT"]})
    assert _turn(agents).reply == NEUTRAL_FALLBACK


def test_outbound_passes_when_only_auditor_is_down():
    agents = FakeAgents(NEUTRALITY_AUDITOR=RuntimeError("down"))
    assert _turn(agents).reply.startswith("It sounds like trust matters")


# --- Joint pipeline -----------------------------------------------------------


def test_joint_pipeline_uses_only_shared_agents():
    agents = FakeAgents()
    built = run_joint_pipeline(state=new_shared_state("D-1"), caller=agents)
    assert {"DIAGNOSTICIAN", "OPTIONS", "JOINT_VOICE"} <= set(agents.roles())
    assert "CAUCUS" not in agents.roles()
    assert built["compromises"][0].startswith("Repay")


def test_joint_perspectives_are_never_duplicated():
    state = new_shared_state("D-1")
    state["approved_shares"] = {"A": ["I need to know I'll be repaid."], "B": []}
    built = run_joint_pipeline(state=state, caller=FakeAgents())
    assert built["user_a_perspective"] == "I need to know I'll be repaid."
    assert built["user_b_perspective"] == "Person B has not chosen anything to share yet."


# --- Schemas, retries, audit --------------------------------------------------


def test_schema_coerces_and_clamps():
    out = validate_output("SAFETY_GUARDIAN", {"flag": "true", "severity": "7", "categories": "threat"})
    assert out["severity"] == 3
    assert out["categories"] == ["threat"]
    caucus = validate_output("CAUCUS", {"reply_to_party": "hi", "state_updates": {"intensity": "12"}})
    assert caucus["state_updates"]["intensity"] == 10


def test_schema_rejects_missing_required_fields():
    with pytest.raises(ValidationError):
        validate_output("CAUCUS", {"state_updates": {}})


def test_call_agent_retries_api_errors_then_validates():
    good = MagicMock(text=json.dumps({"reply_to_party": "Hello"}))
    client = MagicMock()
    client.models.generate_content.side_effect = [RuntimeError("503"), MagicMock(text="not json"), good]
    mapping = {key: "x" for key in required_keys("CAUCUS")}
    with patch.object(llm, "get_client", return_value=client), patch.object(llm.time, "sleep"):
        out = llm.call_agent("CAUCUS", mapping)
    assert out["reply_to_party"] == "Hello"
    assert client.models.generate_content.call_count == 3


def test_call_agent_raises_after_all_attempts():
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("down")
    mapping = {key: "x" for key in required_keys("CAUCUS")}
    with patch.object(llm, "get_client", return_value=client), patch.object(llm.time, "sleep"):
        with pytest.raises(RuntimeError, match="CAUCUS failed"):
            llm.call_agent("CAUCUS", mapping)


def test_pending_audit_tracks_every_entry_since_last_persist():
    state = new_shared_state("D-1")
    append_audit(state, {"agent": "ORCHESTRATOR"})
    state["audit_persisted_seq"] = 1
    append_audit(state, {"agent": "DIAGNOSTICIAN"})
    append_audit(state, {"agent": "CAUCUS_A"})
    assert [entry["agent"] for entry in pending_audit(state)] == ["DIAGNOSTICIAN", "CAUCUS_A"]
