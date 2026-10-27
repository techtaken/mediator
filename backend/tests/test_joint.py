from functools import partial
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.pipeline import check_share as real_check_share
from app.agents.pipeline import summarize_agreement as real_summarize
from app.agents.state import new_shared_state
from app.auth import Actor, load_session
from app.routers import joint as joint_module
from app.routers import sessions as sessions_module
from app.routers.sessions import get_actor
from tests.fakes import FakeSupabase
from tests.test_pipeline import FakeAgents, _outbound_safety

app = FastAPI()
app.include_router(sessions_module.router)
app.include_router(joint_module.router)
client = TestClient(app)

A_TEXT = "I felt hurt when the Goa trip happened without me. I want to be asked."
B_TEXT = "I thought they weren't interested, so I didn't ask. I see it hurt."
IDEAS = ["Ask in the family group before booking trips.", "Plan one outing together next month."]


@pytest.fixture
def db():
    fake = FakeSupabase()
    targets = (
        "app.routers.sessions.get_supabase",
        "app.routers.joint.get_supabase",
        "app.joint_store.get_supabase",
        "app.agents.store.get_supabase",
        "app.auth.get_supabase",
        "app.followup_store.get_supabase",
        "app.retention.get_supabase",
    )
    patches = [patch(target, return_value=fake) for target in targets]
    for item in patches:
        item.start()
    yield fake
    for item in patches:
        item.stop()


@pytest.fixture
def as_party():
    current = {"party": "user_a"}

    def actor_override(session_id: str):
        party = current["party"]
        actor = Actor(party, user_id="user_123") if party == "user_a" else Actor(party, invite_token="token_xyz")
        return load_session(session_id), actor

    app.dependency_overrides[get_actor] = actor_override
    yield lambda party: current.update(party=party)
    app.dependency_overrides.clear()


@pytest.fixture
def agents():
    fake = FakeAgents(DRAFTER={"summary": "You disagreed about being included in plans.", "flags": ["Term 2 has no date"]})
    with patch.object(joint_module, "check_share", partial(real_check_share, caller=fake)), \
         patch.object(joint_module, "summarize_agreement", partial(real_summarize, caller=fake)):
        yield fake


@pytest.fixture
def room(db):
    state = new_shared_state("sess_abc")
    state["approved_shares"] = {"A": [A_TEXT], "B": [B_TEXT]}
    db.add_session(status="joint_review", user_a_ready=True, user_b_ready=True, mediation_state=state)
    db.table("joint_summaries").insert(
        {"session_id": "sess_abc", "user_a_perspective": A_TEXT, "user_b_perspective": B_TEXT, "compromises": IDEAS}
    ).execute()
    return db


def _ideas():
    return client.get("/api/sessions/sess_abc/joint").json()["ideas"]


def _respond(as_party, party, idea_id, response, note=None):
    as_party(party)
    return client.post(f"/api/sessions/sess_abc/ideas/{idea_id}/response", json={"response": response, "note": note})


def _agree_on_first(as_party):
    as_party("user_a")
    first = _ideas()[0]["id"]
    _respond(as_party, "user_a", first, "yes")
    _respond(as_party, "user_b", first, "yes")
    return first


# --- ideas --------------------------------------------------------------------


def test_options_become_ideas_for_both(room, as_party):
    ideas = _ideas()
    assert [idea["text"] for idea in ideas] == IDEAS
    assert all(idea["source"] == "mediator" for idea in ideas)
    as_party("user_b")
    assert [idea["text"] for idea in _ideas()] == IDEAS
    assert len(room.rows("joint_ideas")) == 2  # seeded once


def test_other_answer_is_hidden_until_you_answer(room, as_party, agents):
    idea = _ideas()[0]["id"]
    _respond(as_party, "user_a", idea, "change", "Only for big trips")

    as_party("user_b")
    seen = _ideas()[0]
    assert seen["other_responded"] is True
    assert seen["other_response"] is None and seen["other_note"] is None

    after = _respond(as_party, "user_b", idea, "yes").json()["ideas"][0]
    assert after["other_response"] == "change"
    assert after["other_note"] == "Only for big trips"
    assert after["agreed"] is False


def test_both_yes_means_agreed(room, as_party):
    _agree_on_first(as_party)
    state = client.get("/api/sessions/sess_abc/joint").json()
    assert state["agreed_count"] == 1 and state["ideas"][0]["agreed"] is True


def test_note_is_dropped_on_yes(room, as_party):
    idea = _ideas()[0]["id"]
    _respond(as_party, "user_a", idea, "yes", "ignored")
    assert room.rows("idea_responses")[0]["note"] is None


def test_suggested_idea_counts_as_yes_from_suggester(room, as_party, agents):
    as_party("user_b")
    state = client.post("/api/sessions/sess_abc/ideas", json={"text": "Call each other before any family trip."}).json()
    mine = state["ideas"][-1]
    assert mine["source"] == "you" and mine["my_response"] == "yes"
    as_party("user_a")
    theirs = _ideas()[-1]
    assert theirs["source"] == "them" and theirs["other_responded"] is True and theirs["other_response"] is None


def test_crisis_words_in_a_suggestion_pause_the_room_for_that_party(room, as_party, agents):
    as_party("user_b")
    response = client.post("/api/sessions/sess_abc/ideas", json={"text": "Honestly I want to die over this"})
    assert response.status_code == 409
    session = room.rows("sessions")[0]
    assert session["status"] == "halted" and session["halted_for"] == "user_b"
    assert len(room.rows("joint_ideas")) == 0 or all(i["source"] == "mediator" for i in room.rows("joint_ideas"))


def test_moderate_flag_refuses_suggestion(room, as_party):
    fake = FakeAgents(SAFETY_GUARDIAN={"flag": True, "severity": 2, "action": "PAUSE_AND_CHECK"})
    with patch.object(joint_module, "check_share", partial(real_check_share, caller=fake)):
        response = client.post("/api/sessions/sess_abc/ideas", json={"text": "You will do what I say from now on."})
    assert response.status_code == 409
    assert all(i["source"] == "mediator" for i in room.rows("joint_ideas"))


def test_suggestion_refused_when_safety_is_down(room, as_party):
    fake = FakeAgents(SAFETY_GUARDIAN=RuntimeError("down"))
    with patch.object(joint_module, "check_share", partial(real_check_share, caller=fake)):
        response = client.post("/api/sessions/sess_abc/ideas", json={"text": "Call each other before any trip."})
    assert response.status_code == 503


def test_unknown_idea_is_404(room, as_party):
    _ideas()
    assert _respond(as_party, "user_a", "nope", "yes").status_code == 404


def test_joint_actions_need_an_open_joint_session(db, as_party):
    db.add_session(status="intake")
    assert client.post("/api/sessions/sess_abc/ideas", json={"text": "Call each other first."}).status_code == 409
    assert client.get("/api/sessions/sess_abc/joint").status_code == 409


# --- agreement ----------------------------------------------------------------


def test_draft_needs_an_agreed_idea(room, as_party, agents):
    _ideas()
    assert client.post("/api/sessions/sess_abc/agreement/draft").status_code == 409


def test_agreement_lists_agreed_ideas_word_for_word(room, as_party, agents):
    _agree_on_first(as_party)
    agreement = client.post("/api/sessions/sess_abc/agreement/draft").json()["agreement"]
    assert agreement["terms"] == [IDEAS[0]]
    assert agreement["summary"] == "You disagreed about being included in plans."
    assert agreement["flags"] == ["Term 2 has no date"]
    assert agreement["version"] == 1 and agreement["fully_signed"] is False
    # The drafter is told the terms but never asked to rewrite them.
    assert "summary" in agents.of("DRAFTER")[0]["prompt"]


def test_drafter_output_never_becomes_a_term(room, as_party):
    fake = FakeAgents(DRAFTER={"summary": "Summary.", "flags": [], "terms": ["Pay me 50,000 rupees"]})
    with patch.object(joint_module, "summarize_agreement", partial(real_summarize, caller=fake)):
        _agree_on_first(as_party)
        agreement = client.post("/api/sessions/sess_abc/agreement/draft").json()["agreement"]
    assert agreement["terms"] == [IDEAS[0]]


def test_unsafe_summary_is_left_out(room, as_party):
    fake = FakeAgents(
        DRAFTER={"summary": "A was clearly in the wrong.", "flags": []},
        SAFETY_GUARDIAN=_outbound_safety({"A was clearly in the wrong."}),
    )
    with patch.object(joint_module, "summarize_agreement", partial(real_summarize, caller=fake)):
        _agree_on_first(as_party)
        agreement = client.post("/api/sessions/sess_abc/agreement/draft").json()["agreement"]
    assert agreement["summary"] is None and agreement["terms"] == [IDEAS[0]]


def test_changing_an_agreed_answer_clears_the_unsigned_draft(room, as_party, agents):
    first = _agree_on_first(as_party)
    client.post("/api/sessions/sess_abc/agreement/draft")
    state = _respond(as_party, "user_a", first, "no").json()
    assert state["agreement"] is None and state["agreed_count"] == 0


def test_unrelated_answers_keep_the_draft(room, as_party, agents):
    _agree_on_first(as_party)
    client.post("/api/sessions/sess_abc/agreement/draft")
    second = _ideas()[1]["id"]
    assert _respond(as_party, "user_a", second, "change", "Make it next week").json()["agreement"] is not None


def test_resolved_only_when_both_sign_the_same_version(room, as_party, agents):
    _agree_on_first(as_party)
    client.post("/api/sessions/sess_abc/agreement/draft")

    as_party("user_a")
    assert client.post("/api/sessions/sess_abc/agreement/sign", json={"version": 99}).status_code == 409
    signed = client.post("/api/sessions/sess_abc/agreement/sign", json={"version": 1}).json()["agreement"]
    assert signed["signed_by_me_at"] and not signed["fully_signed"]
    assert room.rows("sessions")[0]["status"] == "joint_review"

    as_party("user_b")
    both = client.post("/api/sessions/sess_abc/agreement/sign", json={"version": 1}).json()["agreement"]
    assert both["fully_signed"] and both["signed_by_them_at"]
    assert room.rows("sessions")[0]["status"] == "resolved"

    # Once resolved, nothing can be changed; the signed agreement stays readable.
    assert client.post("/api/sessions/sess_abc/agreement/draft").status_code == 409
    assert client.get("/api/sessions/sess_abc/joint").json()["agreement"]["fully_signed"] is True


def test_redrafting_bumps_version_and_clears_signatures(room, as_party, agents):
    _agree_on_first(as_party)
    client.post("/api/sessions/sess_abc/agreement/draft")
    client.post("/api/sessions/sess_abc/agreement/sign", json={"version": 1})
    redrafted = client.post("/api/sessions/sess_abc/agreement/draft").json()["agreement"]
    assert redrafted["version"] == 2 and redrafted["signed_by_me_at"] is None


def test_one_sided_resolve_is_gone(room, as_party):
    assert client.post("/api/sessions/sess_abc/resolve").status_code in (404, 405)
