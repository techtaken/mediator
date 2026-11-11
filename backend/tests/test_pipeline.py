import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.agents import llm
from app.agents.pipeline import (
    NEUTRAL_FALLBACK,
    MediatorUnavailable,
    check_share,
    draft_share,
    handle_party_turn,
    run_joint_pipeline,
    share_severity,
)
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
        if role == "SHARE_DRAFTER":
            return {"summary": "I felt left out when plans were made without me. I want to be asked next time.", "left_out": []}
        return {}

    def roles(self):
        return [call["role"] for call in self.calls]

    def of(self, role):
        return [call for call in self.calls if call["role"] == role]


def _turn(agents, party="A", message="I want my money back.", state=None, private=None, use_orchestrator=False):
    return handle_party_turn(
        party=party,
        message=message,
        state=state if state is not None else new_shared_state("D-1"),
        private=private if private is not None else empty_private(),
        caller=agents,
        use_orchestrator=use_orchestrator,
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
    assert "audit_log" not in view
    assert "handoff" not in view
    assert "hidden_concerns" not in view["parties"]["B"]


# --- Fix 3: replies go to the speaking party's own caucus ---------------------


@pytest.mark.parametrize("routed_to", ["CAUCUS_B", "JOINT_VOICE", "DIAGNOSTICIAN", "SOMETHING_ELSE"])
def test_orchestrator_cannot_route_a_message_away_from_the_speaker(routed_to):
    agents = FakeAgents(ORCHESTRATOR={"stage": "STORYTELLING", "next_agent": routed_to, "reason": "x"})
    state = new_shared_state("D-1")
    result = _turn(agents, state=state, private={"notes": A_SECRET}, use_orchestrator=True)
    caucus = agents.of("CAUCUS")
    assert len(caucus) == 1
    assert caucus[0]["mapping"]["PARTY_ID"] == "A"
    assert A_SECRET in caucus[0]["mapping"]["PRIVATE_MEMORY"]
    assert "JOINT_VOICE" not in agents.roles()
    assert result.agent == "CAUCUS_A"
    assert result.state["parties"]["B"]["intensity"] == 5  # B untouched
    coerced = [entry for entry in result.state["audit_log"] if entry.get("coerced")]
    assert coerced and coerced[0]["requested_agent"] == routed_to


def test_internal_agents_are_not_run_during_intake():
    agents = FakeAgents(ORCHESTRATOR={"stage": "DIAGNOSIS", "next_agent": "DIAGNOSTICIAN"})
    result = _turn(agents, use_orchestrator=True)
    assert "DIAGNOSTICIAN" not in agents.roles()
    assert result.agent == "CAUCUS_A"
    assert result.state["issues"] == []


def test_unknown_stage_label_is_not_stored():
    agents = FakeAgents(ORCHESTRATOR={"stage": "A_IS_HURT_ABOUT_THE_TRIP", "next_agent": "CAUCUS_A"})
    assert _turn(agents, use_orchestrator=True).state["stage"] == "STORYTELLING"


TRIP = "B went on the Goa trip without me"


def _echoing_agents():
    """A's agents echo A's words in every free-text field, like a real model."""
    return FakeAgents(
        SAFETY_GUARDIAN=lambda m: {**SAFE, "flag": True, "severity": 1, "action": "CONTINUE_WITH_CARE", "evidence": TRIP},
        ORCHESTRATOR={
            "stage": f"HURT: {TRIP}",
            "next_agent": "DIAGNOSTICIAN",
            "instructions_to_agent": f"Reflect that {TRIP}.",
            "reason": f"A says {TRIP}.",
        },
        DIAGNOSTICIAN={"issues": [{"id": "I1", "topic": TRIP}], "agenda": ["I1"]},
        CAUCUS={
            "reply_to_party": f"It hurt that {TRIP}?",
            "state_updates": {"positions": [TRIP], "new_issues": [{"topic": TRIP}]},
            "share_proposal": {"text": TRIP, "approved_by_party": True},
            "private_notes": TRIP,
        },
        NEUTRALITY_AUDITOR=lambda m: {
            "final_message": m["DRAFT"],
            "alert_orchestrator": True,
            "issues_found": [f"quotes '{TRIP}'"],
        },
    )


@pytest.mark.parametrize("use_orchestrator", [False, True])
def test_nothing_a_said_reaches_any_of_b_agents(use_orchestrator):
    first = _turn(_echoing_agents(), message=f"{TRIP}, and didn't even tell me.", use_orchestrator=use_orchestrator)
    b_agents = FakeAgents()
    _turn(b_agents, party="B", message="hi", state=first.state, private=empty_private(), use_orchestrator=use_orchestrator)
    assert b_agents.calls
    for call in b_agents.calls:
        assert TRIP not in call["prompt"], f"A's words leaked into B's {call['role']}"


def test_nothing_a_said_reaches_b_through_a_handoff():
    first = _turn(_echoing_agents(), message=TRIP, use_orchestrator=True)
    first.state["handoff"] = {"dispute_summary": TRIP, "message_to_parties": TRIP}
    b_agents = FakeAgents(ORCHESTRATOR={"stage": "REFER_TO_HUMAN", "next_agent": "HANDOFF", "reason": "B asked"})
    _turn(b_agents, party="B", message="can I talk to a human?", state=first.state, private=empty_private(), use_orchestrator=True)
    assert "HANDOFF" in b_agents.roles()
    for call in b_agents.calls:
        assert TRIP not in call["prompt"], f"A's words leaked into B's {call['role']}"


# --- Dispute topic is framed with explicit roles for each party --------------

GOA = "You went on the Goa trip without me"


def test_b_caucus_gets_topic_attributed_to_a():
    agents = FakeAgents()
    handle_party_turn(party="B", message="hi", state=new_shared_state("D-1"), private=empty_private(),
                      topic=GOA, caller=agents)
    framing = agents.of("CAUCUS")[0]["mapping"]["DISPUTE_TOPIC"]
    assert f"<<<PARTY_DATA dispute_topic>>>\n{GOA}\n<<<END_PARTY_DATA dispute_topic>>>" in framing
    assert "The OTHER person (A) opened this room" in framing
    assert "did not write this" in framing and "not a fact" in framing
    assert '"I", "me" or "my" in it means A' in framing


def test_a_caucus_gets_topic_as_its_own_words():
    agents = FakeAgents()
    _turn(agents)  # no topic
    assert agents.of("CAUCUS")[0]["mapping"]["DISPUTE_TOPIC"] == "Not given."
    agents = FakeAgents()
    handle_party_turn(party="A", message="hi", state=new_shared_state("D-1"), private=empty_private(),
                      topic=GOA, caller=agents)
    framing = agents.of("CAUCUS")[0]["mapping"]["DISPUTE_TOPIC"]
    assert framing.startswith("The person you are talking to (A) opened this room")


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
    # The reply started early is set aside; the one sent was written with care.
    assert "Go gently" in agents.of("CAUCUS")[-1]["mapping"]["INSTRUCTION"]
    assert result.state["safety"]["flags"]["A"]["severity"] == 1
    # The auditor still checked the outbound draft, so it can go out.
    assert result.reply.startswith("It sounds like trust matters")


def test_nothing_unchecked_goes_out_when_no_checker_runs():
    agents = FakeAgents(SAFETY_GUARDIAN=RuntimeError("down"), NEUTRALITY_AUDITOR=RuntimeError("down"))
    with pytest.raises(MediatorUnavailable):
        _turn(agents)


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
    assert "Pause the move toward a joint session" in agents.of("CAUCUS")[-1]["mapping"]["INSTRUCTION"]
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


A_SHARE = "I felt hurt when the Goa trip happened without me. I want to be included in plans."
B_SHARE = "I did invite them, but I thought they said no. I don't want them to feel left out."


def _both_shared():
    state = new_shared_state("D-1")
    state["approved_shares"] = {"A": [A_SHARE], "B": [B_SHARE]}
    return state


def test_joint_view_shows_each_partys_approved_words_verbatim():
    agents = FakeAgents(JOINT_VOICE={"message": "You both care about being included."})
    built = run_joint_pipeline(state=_both_shared(), caller=agents)
    assert built["user_a_perspective"] == A_SHARE
    assert built["user_b_perspective"] == B_SHARE
    assert built["common_ground"] == "You both care about being included."
    assert built["compromises"] == ["Repay in three installments."]


def test_no_canned_compromises_when_there_are_no_real_options():
    built = run_joint_pipeline(state=_both_shared(), caller=FakeAgents(OPTIONS={"options": []}))
    assert built["compromises"] == []


def test_options_using_other_keys_are_kept():
    agents = FakeAgents(OPTIONS={"options": [{"text": "Plan the next trip together."}, "Check in before booking."]})
    built = run_joint_pipeline(state=_both_shared(), caller=agents)
    assert built["compromises"] == ["Plan the next trip together.", "Check in before booking."]


def test_options_are_dropped_if_their_check_cannot_run():
    def safety(mapping):
        if "Repay" in mapping["LATEST_EVENT"]:
            raise RuntimeError("down")
        return dict(SAFE)

    built = run_joint_pipeline(state=_both_shared(), caller=FakeAgents(SAFETY_GUARDIAN=safety))
    assert built["compromises"] == []


def test_common_ground_is_omitted_when_joint_voice_fails():
    built = run_joint_pipeline(state=_both_shared(), caller=FakeAgents(JOINT_VOICE=RuntimeError("down")))
    assert built["common_ground"] is None


def test_caucus_cannot_approve_a_share_on_a_partys_behalf():
    agents = FakeAgents(
        CAUCUS={
            "reply_to_party": "Shall I tell them?",
            "state_updates": {},
            "share_proposal": {"text": "secret", "approved_by_party": True},
        }
    )
    result = _turn(agents)
    assert result.state["approved_shares"] == {"A": [], "B": []}


# --- Share drafting and checking ----------------------------------------------


def test_draft_uses_only_the_partys_own_material():
    agents = FakeAgents()
    out = draft_share(
        party="B",
        transcript="Them: I did invite them\nMediator: That sounds confusing.",
        private={"notes": "B notes"},
        topic=GOA,
        state=_both_shared(),
        caller=agents,
    )
    assert out["summary"].startswith("I felt left out")
    prompt = agents.of("SHARE_DRAFTER")[0]["prompt"]
    assert "I did invite them" in prompt and "B notes" in prompt
    assert "The OTHER person (A) opened this room" in prompt
    for call in agents.calls:
        assert A_SHARE not in call["prompt"], f"A's share leaked into B's {call['role']}"


def test_unsafe_draft_is_redrafted_then_dropped():
    drafts = iter(["You are selfish.", "You are still selfish."])
    agents = FakeAgents(
        SHARE_DRAFTER=lambda _m: {"summary": next(drafts)},
        SAFETY_GUARDIAN=_outbound_safety({"You are selfish.", "You are still selfish."}),
    )
    out = draft_share(party="A", transcript="x", private=None, topic=None, state=new_shared_state("D"), caller=agents)
    assert out is None
    assert agents.roles().count("SHARE_DRAFTER") == 2


def test_drafter_failure_returns_none():
    agents = FakeAgents(SHARE_DRAFTER=RuntimeError("down"))
    assert draft_share(party="A", transcript="x", private=None, topic=None, state=new_shared_state("D"), caller=agents) is None


def test_check_share_halts_on_crisis_words_without_llm():
    out = check_share(party="A", text="I want to die", state=new_shared_state("D"), caller=lambda *_: pytest.fail("no LLM"))
    assert share_severity(out) == 3


def test_check_share_shows_the_exact_text_to_safety():
    agents = FakeAgents()
    check_share(party="A", text=A_SHARE, state=new_shared_state("D"), caller=agents)
    assert A_SHARE in agents.of("SAFETY_GUARDIAN")[0]["prompt"]


def test_check_share_raises_when_safety_is_down():
    with pytest.raises(RuntimeError):
        check_share(party="A", text=A_SHARE, state=new_shared_state("D"), caller=FakeAgents(SAFETY_GUARDIAN=RuntimeError("down")))


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


# --- Language for text both people read ----------------------------------------

from app.agents.prompts import detect_language, joint_language  # noqa: E402
from app.agents.state import note_clean_turn, record_safety_flag  # noqa: E402
from app.agents.pipeline import summarize_agreement  # noqa: E402

HINGLISH_SHARE = "Main 10 ghante ki job karti hoon aur weekend par poora khana banati hoon. Meri mehnat kisi ko dikhti nahi hai."
HINDI_SHARE = "मुझे लगता है कि मेरी मेहनत किसी को दिखती नहीं है।"
ENGLISH_SHARE = "I work long hours and cook every weekend, and nobody seems to notice."


@pytest.mark.parametrize(
    "text, code",
    [(HINGLISH_SHARE, "hinglish"), (HINDI_SHARE, "hi"), (ENGLISH_SHARE, "en"), ("", "en")],
)
def test_detect_language(text, code):
    assert detect_language(text) == code


@pytest.mark.parametrize(
    "prefs, shares, code",
    [
        ({}, {"A": [HINGLISH_SHARE], "B": [HINGLISH_SHARE]}, "hinglish"),
        ({}, {"A": [HINDI_SHARE], "B": [HINDI_SHARE]}, "hi"),
        ({}, {"A": [HINDI_SHARE], "B": [HINGLISH_SHARE]}, "hinglish"),
        ({}, {"A": [ENGLISH_SHARE], "B": [HINGLISH_SHARE]}, "en"),
        ({"A": "hi", "B": "hi"}, {"A": [ENGLISH_SHARE], "B": [ENGLISH_SHARE]}, "hi"),
        ({"A": "hinglish"}, {"A": [ENGLISH_SHARE], "B": [HINGLISH_SHARE]}, "hinglish"),
    ],
)
def test_joint_language(prefs, shares, code):
    assert joint_language(prefs, shares) == code


def test_joint_outputs_are_asked_for_in_the_shared_language():
    state = new_shared_state("D-1")
    state["approved_shares"] = {"A": [HINGLISH_SHARE], "B": [HINGLISH_SHARE]}
    agents = FakeAgents()
    run_joint_pipeline(state=state, caller=agents)
    assert state["joint_language"] == "hinglish"
    for role in ("OPTIONS", "JOINT_VOICE", "DIAGNOSTICIAN"):
        call = agents.of(role)[0]
        if "LANGUAGE" in call["mapping"]:
            assert "Hinglish" in call["mapping"]["LANGUAGE"], role
    assert "Hinglish" in agents.of("OPTIONS")[0]["prompt"]
    assert "Hinglish" in agents.of("JOINT_VOICE")[0]["prompt"]


def test_saved_preferences_win_over_detection():
    state = new_shared_state("D-1")
    state["approved_shares"] = {"A": [ENGLISH_SHARE], "B": [ENGLISH_SHARE]}
    agents = FakeAgents()
    run_joint_pipeline(state=state, caller=agents, languages={"A": "hi", "B": "hi"})
    assert "Hindi" in agents.of("OPTIONS")[0]["prompt"]


def test_agreement_summary_uses_the_joint_language():
    state = new_shared_state("D-1")
    state["approved_shares"] = {"A": [HINDI_SHARE], "B": [HINDI_SHARE]}
    state["joint_language"] = "hi"
    agents = FakeAgents(DRAFTER={"summary": "सारांश", "flags": []})
    summarize_agreement(state=state, terms=["हर रविवार बात करेंगे"], caller=agents)
    assert "Hindi" in agents.of("DRAFTER")[0]["prompt"]


# --- Moderate holds lift after clean turns ----------------------------------------


def _held(severity=2):
    state = new_shared_state("D-1")
    record_safety_flag(state, "B", {"severity": severity, "action": "PAUSE_AND_CHECK" if severity == 2 else "HALT_AND_REFER"})
    return state


def test_hold_lifts_after_two_clean_turns():
    state = _held()
    assert joint_blocked_by(state) == ["B"]
    assert note_clean_turn(state, "B") is False
    assert joint_blocked_by(state) == ["B"]
    assert note_clean_turn(state, "B") is True
    assert joint_blocked_by(state) == []


def test_a_new_concern_restarts_the_count():
    state = _held()
    note_clean_turn(state, "B")
    record_safety_flag(state, "B", {"severity": 1, "action": "CONTINUE_WITH_CARE"})
    assert note_clean_turn(state, "B") is False
    assert joint_blocked_by(state) == ["B"]


def test_halts_never_lift():
    state = _held(severity=3)
    for _ in range(5):
        assert note_clean_turn(state, "B") is False
    assert joint_blocked_by(state) == ["B"]


def test_held_party_is_released_through_real_turns():
    state = _held()
    for _ in range(2):
        _turn(FakeAgents(), party="B", message="Theek hai, main baat karne ko taiyaar hoon.", state=state)
    assert joint_blocked_by(state) == []
    assert any(entry.get("reason") == "hold lifted after clean turns" for entry in state["audit_log"])


def test_unchecked_turns_never_lift_a_hold():
    state = _held()
    for _ in range(3):
        _turn(FakeAgents(SAFETY_GUARDIAN=RuntimeError("down")), party="B", message="ok", state=state)
    assert joint_blocked_by(state) == ["B"]


def test_safety_rules_separate_embarrassment_from_danger():
    from app.agents.constitution import CONSTITUTION
    from app.agents.prompts import ROLE_PROMPTS

    assert "fear for someone's safety" in CONSTITUTION
    assert "log kya kahenge" in CONSTITUTION
    safety = " ".join(ROLE_PROMPTS["SAFETY_GUARDIAN"].split())
    assert "NOT SAFETY CONCERNS" in safety
    assert "scared the other will tell people" in safety


def test_english_options_for_hinglish_readers_are_rewritten_once():
    state = new_shared_state("D-1")
    state["approved_shares"] = {"A": [HINGLISH_SHARE], "B": [HINGLISH_SHARE]}
    replies = iter([
        {"options": [{"description": "Share the cooking on weekends and agree a weekday chore list."}]},
        {"options": [{"description": "Weekend par khana dono milkar banayein aur hafte ke kaam ki list banayein."}]},
    ])
    agents = FakeAgents(OPTIONS=lambda _m: next(replies))
    built = run_joint_pipeline(state=state, caller=agents)
    assert len(agents.of("OPTIONS")) == 2
    assert "REWRITE" in agents.of("OPTIONS")[1]["mapping"]["INSTRUCTION"]
    assert built["compromises"] == ["Weekend par khana dono milkar banayein aur hafte ke kaam ki list banayein."]


def test_options_already_in_the_right_language_are_not_rewritten():
    state = new_shared_state("D-1")
    state["approved_shares"] = {"A": [ENGLISH_SHARE], "B": [ENGLISH_SHARE]}
    agents = FakeAgents()
    run_joint_pipeline(state=state, caller=agents)
    assert len(agents.of("OPTIONS")) == 1


def test_options_prompt_bans_internal_labels():
    from app.agents.prompts import ROLE_PROMPTS

    text = " ".join(ROLE_PROMPTS["OPTIONS"].split())
    assert 'Never call anyone "A", "B"' in text
