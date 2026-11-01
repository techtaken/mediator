from functools import partial
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.pipeline import check_share as real_check_share
from app.agents.pipeline import draft_share as real_draft_share
from app.agents.pipeline import handle_party_turn as real_handle_party_turn
from app.agents.pipeline import run_joint_pipeline as real_run_joint_pipeline
from app.agents.state import new_shared_state
from app.auth import Actor, load_session, require_logged_in
from app.routers import sessions as sessions_module
from app.routers.sessions import get_actor, get_entry_actor, router
from tests.fakes import FakeSupabase
from tests.test_pipeline import FakeAgents

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture
def db():
    fake = FakeSupabase()
    targets = (
        "app.routers.sessions.get_supabase",
        "app.agents.store.get_supabase",
        "app.auth.get_supabase",
        "app.joint_store.get_supabase",
    )
    patches = [patch(target, return_value=fake) for target in targets]
    for item in patches:
        item.start()
    yield fake
    for item in patches:
        item.stop()


@pytest.fixture
def as_party():
    """Choose who is calling: as_party("user_a") or as_party("user_b")."""
    current = {"party": "user_a"}

    def actor_override(session_id: str):
        party = current["party"]
        actor = Actor(party, user_id="user_123") if party == "user_a" else Actor(party, invite_token="token_xyz")
        return load_session(session_id), actor

    app.dependency_overrides[require_logged_in] = lambda: "user_123"
    app.dependency_overrides[get_actor] = actor_override
    app.dependency_overrides[get_entry_actor] = actor_override
    yield lambda party: current.update(party=party)
    app.dependency_overrides.clear()


@pytest.fixture
def agents():
    fake = FakeAgents()
    with patch.object(sessions_module, "handle_party_turn", partial(real_handle_party_turn, caller=fake)), \
         patch.object(sessions_module, "draft_share", partial(real_draft_share, caller=fake)), \
         patch.object(sessions_module, "check_share", partial(real_check_share, caller=fake)), \
         patch.object(sessions_module, "run_joint_pipeline", partial(real_run_joint_pipeline, caller=fake)):
        yield fake


def _session(db, **overrides):
    state = overrides.pop("mediation_state", None) or new_shared_state("sess_abc")
    overrides.setdefault("consented_a_at", "2026-06-01T00:00:00Z")
    overrides.setdefault("consented_b_at", "2026-06-01T00:00:00Z")
    return db.add_session(mediation_state=state, **overrides)


def test_create_session_saves_initial_state(db, as_party):
    db.table("profiles").insert({"user_id": "user_123", "name": "Rahul"}).execute()
    response = client.post("/api/sessions", json={"topic": "Rent split", "invited_name": "Priya", "relationship_context": "Roommates"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "intake" and data["party"] == "user_a"
    assert data["invite_link"].endswith("?token=token_xyz")
    row = db.rows("sessions")[0]
    assert row["state_version"] == 1
    assert row["mediation_state"]["dispute_id"] == row["id"]
    assert db.rows("messages", audience_role="user_a")


def test_get_session_hides_invite_from_b(db, as_party):
    _session(db)
    as_party("user_b")
    data = client.get("/api/sessions/sess_abc").json()
    assert data["party"] == "user_b" and data["invite_link"] is None
    assert db.rows("messages", audience_role="user_b")  # welcome message


def _open_room_and_join(as_party, db, topic="You went on the Goa trip without me"):
    db.table("profiles").insert({"user_id": "user_123", "name": "Rahul"}).execute()
    client.post("/api/sessions", json={"topic": topic, "invited_name": "Priya", "relationship_context": "Siblings"})
    sid = db.rows("sessions")[0]["id"]
    as_party("user_b")
    client.get(f"/api/sessions/{sid}")
    return sid


def test_both_welcome_messages_disclose_the_ai_once(db, as_party):
    # Agents are told not to repeat disclaimers, so the welcome must carry them.
    _open_room_and_join(as_party, db)
    for party in ("user_a", "user_b"):
        (welcome,) = db.rows("messages", audience_role=party)
        assert "AI mediator" in welcome["content"]
        assert "legal, medical or financial advice" in welcome["content"]
        assert "stop at any time" in welcome["content"]


def test_b_is_told_who_opened_the_room_and_why(db, as_party):
    _open_room_and_join(as_party, db)
    (welcome_b,) = db.rows("messages", audience_role="user_b")
    assert "Rahul can't read it" in welcome_b["content"]
    assert "Rahul opened this room about" in welcome_b["content"]
    assert '"You went on the Goa trip without me"' in welcome_b["content"]
    assert "your side" in welcome_b["content"]
    (welcome_a,) = db.rows("messages", audience_role="user_a")
    assert 'You opened this room about: "You went on the Goa trip without me"' in welcome_a["content"]


def test_topic_is_returned_to_both_parties(db, as_party):
    sid = _open_room_and_join(as_party, db)
    assert client.get(f"/api/sessions/{sid}").json()["topic"] == "You went on the Goa trip without me"


@pytest.mark.parametrize("topic", [None, "", "     ", "x" * 301])
def test_topic_is_required_and_bounded(db, as_party, topic):
    body = {} if topic is None else {"topic": topic}
    assert client.post("/api/sessions", json=body).status_code == 422
    assert db.rows("sessions") == []


def test_send_message_passes_topic_to_the_turn(db, as_party):
    _session(db, topic="You went on the Goa trip without me")
    seen = {}

    def turn(**kwargs):
        seen.update(kwargs)
        return real_handle_party_turn(caller=FakeAgents(), **kwargs)

    as_party("user_b")
    with patch.object(sessions_module, "handle_party_turn", turn):
        client.post("/api/sessions/sess_abc/messages", json={"content": "hi"})
    assert seen["topic"] == "You went on the Goa trip without me"


def test_send_message_runs_turn_and_persists_everything(db, as_party, agents):
    _session(db)
    response = client.post("/api/sessions/sess_abc/messages", json={"content": "I want my money back."})
    assert response.status_code == 200
    user_msg, ai_msg = response.json()
    assert user_msg["audience_role"] == "user_a" and ai_msg["audience_role"] == "user_a"
    assert ai_msg["content"].startswith("It sounds like trust matters")

    session = db.rows("sessions")[0]
    assert session["state_version"] == 1
    assert "positions" not in session["mediation_state"]["parties"]["A"]
    private = db.rows("private_memories", party_role="user_a")[0]
    assert private["profile"]["positions"] == ["Pay me back now"]
    audit = db.rows("mediation_audit_events")
    assert audit and len(audit) == len(session["mediation_state"]["audit_log"])
    assert session["mediation_state"]["audit_persisted_seq"] == session["mediation_state"]["audit_seq"]


def test_nothing_from_a_reaches_b_room(db, as_party, agents):
    _session(db)
    client.post("/api/sessions/sess_abc/messages", json={"content": "I want my money back."})
    as_party("user_b")
    messages = client.get("/api/sessions/sess_abc/messages").json()
    assert all(m["audience_role"] == "user_b" for m in messages)
    assert not any("money back" in m["content"] for m in messages)


def test_keyword_halt_is_only_explained_to_the_party_who_triggered_it(db, as_party):
    _session(db)
    as_party("user_b")
    response = client.post("/api/sessions/sess_abc/messages", json={"content": "I want to die"})
    assert response.status_code == 200
    assert "112" in response.json()[1]["content"]

    session = db.rows("sessions")[0]
    assert session["status"] == "halted" and session["halted_for"] == "user_b"

    mine = client.get("/api/sessions/sess_abc").json()
    assert mine["halt_view"] == "self"
    assert any("112" in line for line in mine["helplines"])

    as_party("user_a")
    other = client.get("/api/sessions/sess_abc").json()
    assert other["status"] == "halted"
    assert other["halt_view"] == "other"
    assert other["halted_reason"] is None and other["helplines"] == []
    assert "safety" not in (other["halt_message"] or "").lower()


def test_llm_halt_marks_the_speaking_party(db, as_party):
    _session(db)
    fake = FakeAgents(SAFETY_GUARDIAN={"flag": True, "severity": 3, "action": "HALT_AND_REFER"})
    with patch.object(sessions_module, "handle_party_turn", partial(real_handle_party_turn, caller=fake)):
        client.post("/api/sessions/sess_abc/messages", json={"content": "Things at home scare me."})
    session = db.rows("sessions")[0]
    assert session["status"] == "halted" and session["halted_for"] == "user_a"
    assert session["halt_kind"] == "safety"


def test_state_conflict_reruns_turn_on_fresh_state(db, as_party):
    _session(db)
    fake = FakeAgents()
    calls = []

    def racing_turn(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            # The other party's turn lands while ours is thinking.
            row = db.rows("sessions")[0]
            row["state_version"] += 1
            row["mediation_state"]["parties"]["B"]["intensity"] = 9
        return real_handle_party_turn(caller=fake, **kwargs)

    with patch.object(sessions_module, "handle_party_turn", racing_turn):
        response = client.post("/api/sessions/sess_abc/messages", json={"content": "Hello"})
    assert response.status_code == 200
    assert len(calls) == 2
    session = db.rows("sessions")[0]
    assert session["state_version"] == 2
    assert session["mediation_state"]["parties"]["B"]["intensity"] == 9  # not overwritten


def test_repeated_conflict_asks_user_to_resend(db, as_party):
    _session(db)
    fake = FakeAgents()

    def always_racing(**kwargs):
        db.rows("sessions")[0]["state_version"] += 1
        return real_handle_party_turn(caller=fake, **kwargs)

    with patch.object(sessions_module, "handle_party_turn", always_racing):
        response = client.post("/api/sessions/sess_abc/messages", json={"content": "Hello"})
    assert response.status_code == 409


def test_state_write_failure_is_reported(db, as_party, agents):
    _session(db)
    db.failures[("sessions", "update")] = RuntimeError("db down")
    response = client.post("/api/sessions/sess_abc/messages", json={"content": "Hello"})
    assert response.status_code == 503


def test_private_memory_read_failure_is_reported(db, as_party, agents):
    _session(db)
    db.failures[("private_memories", "select")] = RuntimeError("db down")
    response = client.post("/api/sessions/sess_abc/messages", json={"content": "Hello"})
    assert response.status_code == 503
    assert db.rows("sessions")[0]["state_version"] == 0


A_TEXT = "I felt hurt when the Goa trip happened without me. I want to be included in plans."
B_TEXT = "I did invite them, but I thought they said no. I don't want them to feel left out."


def _approve(as_party, party, text):
    as_party(party)
    return client.post("/api/sessions/sess_abc/share/approve", json={"text": text})


def test_draft_is_built_from_own_room_and_private_to_its_author(db, as_party, agents):
    _session(db)
    db.table("messages").insert({"session_id": "sess_abc", "sender_role": "user_a", "audience_role": "user_a", "content": "A-ONLY words"}).execute()
    db.table("messages").insert({"session_id": "sess_abc", "sender_role": "user_b", "audience_role": "user_b", "content": "B-ONLY words"}).execute()

    response = client.post("/api/sessions/sess_abc/share/draft")
    assert response.status_code == 200
    assert response.json()["draft"].startswith("I felt left out")
    prompt = agents.of("SHARE_DRAFTER")[0]["prompt"]
    assert "A-ONLY words" in prompt and "B-ONLY words" not in prompt

    assert client.get("/api/sessions/sess_abc/share").json()["draft"].startswith("I felt left out")
    as_party("user_b")
    assert client.get("/api/sessions/sess_abc/share").json()["draft"] is None


def test_draft_failure_lets_the_person_write_their_own(db, as_party):
    _session(db)
    fake = FakeAgents(SHARE_DRAFTER=RuntimeError("down"))
    with patch.object(sessions_module, "draft_share", partial(real_draft_share, caller=fake)):
        response = client.post("/api/sessions/sess_abc/share/draft")
    assert response.status_code == 200 and response.json()["draft"] is None


def test_approving_records_exact_text_and_marks_ready(db, as_party, agents):
    _session(db)
    response = _approve(as_party, "user_a", A_TEXT)
    assert response.status_code == 200
    assert response.json()["user_a_ready"] is True
    assert response.json()["my_share"] == A_TEXT
    session = db.rows("sessions")[0]
    assert session["mediation_state"]["approved_shares"]["A"] == [A_TEXT]
    assert session["status"] == "intake"  # waiting for B
    as_party("user_b")
    assert client.get("/api/sessions/sess_abc").json()["my_share"] is None


def test_both_approving_builds_joint_view_from_their_exact_words(db, as_party, agents):
    _session(db)
    _approve(as_party, "user_a", A_TEXT)
    response = _approve(as_party, "user_b", B_TEXT)
    # The share returns straight away; the joint view is built in the background.
    assert response.json()["status"] == "building_joint"
    assert db.rows("sessions")[0]["status"] == "joint_review"
    summary = client.get("/api/sessions/sess_abc/summary").json()
    assert summary["user_a_perspective"] == A_TEXT
    assert summary["user_b_perspective"] == B_TEXT
    assert summary["common_ground"] == "Both of you want this to feel fair."
    assert summary["compromises"] == ["Repay in three installments."]
    assert len(db.rows("joint_summaries")) == 1


def test_ready_requires_approval(db, as_party):
    _session(db)
    response = client.post("/api/sessions/sess_abc/ready", json={"ready": True})
    assert response.status_code == 409
    assert db.rows("sessions")[0]["user_a_ready"] is False


def test_withdrawing_clears_the_share_and_reopens_chat(db, as_party, agents):
    _session(db)
    _approve(as_party, "user_a", A_TEXT)
    assert client.post("/api/sessions/sess_abc/messages", json={"content": "more"}).status_code == 409
    assert client.post("/api/sessions/sess_abc/share/draft").status_code == 409

    response = client.post("/api/sessions/sess_abc/ready", json={"ready": False})
    assert response.status_code == 200
    assert response.json()["user_a_ready"] is False and response.json()["my_share"] is None
    assert db.rows("sessions")[0]["mediation_state"]["approved_shares"]["A"] == []
    assert client.post("/api/sessions/sess_abc/messages", json={"content": "more"}).status_code == 200


def test_share_with_crisis_words_halts_only_its_author(db, as_party, agents):
    _session(db)
    response = _approve(as_party, "user_b", "Honestly some days I want to die over all this family stuff.")
    assert response.json()["status"] == "halted" and response.json()["halt_view"] == "self"
    assert db.rows("sessions")[0]["halted_for"] == "user_b"
    assert db.rows("sessions")[0]["mediation_state"]["approved_shares"]["B"] == []
    as_party("user_a")
    assert client.get("/api/sessions/sess_abc").json()["halt_view"] == "other"


def test_share_flagged_moderate_is_held_back(db, as_party):
    _session(db)
    fake = FakeAgents(SAFETY_GUARDIAN={"flag": True, "severity": 2, "action": "PAUSE_AND_CHECK"})
    with patch.object(sessions_module, "check_share", partial(real_check_share, caller=fake)):
        response = _approve(as_party, "user_a", A_TEXT)
    assert response.status_code == 409
    session = db.rows("sessions")[0]
    assert session["user_a_ready"] is False
    assert session["mediation_state"]["approved_shares"]["A"] == []
    assert session["mediation_state"]["safety"]["joint_blocked_by"] == ["A"]


def test_share_is_not_released_if_safety_check_is_down(db, as_party):
    _session(db)
    fake = FakeAgents(SAFETY_GUARDIAN=RuntimeError("down"))
    with patch.object(sessions_module, "check_share", partial(real_check_share, caller=fake)):
        response = _approve(as_party, "user_a", A_TEXT)
    assert response.status_code == 503
    assert db.rows("sessions")[0]["user_a_ready"] is False
    assert db.rows("party_shares") == []


def test_previously_flagged_party_cannot_approve(db, as_party, agents):
    state = new_shared_state("sess_abc")
    state["safety"]["joint_blocked_by"] = ["B"]
    _session(db, mediation_state=state)
    response = _approve(as_party, "user_b", B_TEXT)
    assert response.status_code == 409
    assert "safety" not in response.json()["detail"].lower()
    assert agents.of("SAFETY_GUARDIAN") == []


@pytest.mark.parametrize("text", ["", "too short", "x" * 1201])
def test_share_text_is_bounded(db, as_party, agents, text):
    _session(db)
    assert _approve(as_party, "user_a", text).status_code == 422


def test_joint_build_failure_reopens_intake(db, as_party, agents):
    _session(db)
    _approve(as_party, "user_a", A_TEXT)
    with patch.object(sessions_module, "run_joint_pipeline", side_effect=RuntimeError("llm down")):
        response = _approve(as_party, "user_b", B_TEXT)
        # The share still went through; only the joint build failed.
        assert response.status_code == 200 and response.json()["user_b_ready"] is True
        assert db.rows("sessions")[0]["status"] == "intake"
        # A retry that fails again also leaves the room open for another try.
        assert client.post("/api/sessions/sess_abc/joint").status_code == 200
        assert db.rows("sessions")[0]["status"] == "intake"

    retry = client.post("/api/sessions/sess_abc/joint")
    assert retry.status_code == 200 and retry.json()["status"] == "building_joint"
    assert db.rows("sessions")[0]["status"] == "joint_review"


def test_joint_view_is_built_only_once(db, as_party, agents):
    _session(db)
    _approve(as_party, "user_a", A_TEXT)
    _approve(as_party, "user_b", B_TEXT)
    with patch.object(sessions_module, "run_joint_pipeline") as run:
        sessions_module._maybe_build_summary({**db.rows("sessions")[0], "status": "intake"})
    run.assert_not_called()


def test_messages_rejected_after_intake(db, as_party):
    _session(db, status="building_joint")
    response = client.post("/api/sessions/sess_abc/messages", json={"content": "Hello"})
    assert response.status_code == 409


# --- Consent ------------------------------------------------------------------


def test_nobody_can_talk_or_share_before_accepting(db, as_party, agents):
    _session(db, consented_a_at=None)
    assert client.post("/api/sessions/sess_abc/messages", json={"content": "hi"}).status_code == 409
    assert client.post("/api/sessions/sess_abc/share/draft").status_code == 409
    assert _approve(as_party, "user_a", A_TEXT).status_code == 409
    assert client.get("/api/sessions/sess_abc").json()["i_consented"] is False

    accepted = client.post("/api/sessions/sess_abc/consent").json()
    assert accepted["i_consented"] is True
    assert client.post("/api/sessions/sess_abc/messages", json={"content": "hi"}).status_code == 200


def test_consent_is_per_person_and_kept(db, as_party):
    _session(db, consented_a_at=None, consented_b_at=None)
    client.post("/api/sessions/sess_abc/consent")
    first = db.rows("sessions")[0]["consented_a_at"]
    client.post("/api/sessions/sess_abc/consent")
    assert db.rows("sessions")[0]["consented_a_at"] == first
    as_party("user_b")
    assert client.get("/api/sessions/sess_abc").json()["i_consented"] is False


# --- Leaving and asking for a person -------------------------------------------


@pytest.mark.parametrize("path, kind", [("leave", "withdrawn"), ("human", "referral")])
def test_stopping_pauses_for_both_and_only_the_stopper_sees_why(db, as_party, path, kind):
    _session(db)
    as_party("user_b")
    mine = client.post(f"/api/sessions/sess_abc/{path}").json()
    assert mine["status"] == "halted" and mine["halt_view"] == "self" and mine["halted_reason"] == kind
    session = db.rows("sessions")[0]
    assert session["halted_for"] == "user_b" and session["halt_kind"] == kind
    assert any(e["agent"] == kind.upper() for e in db.rows("mediation_audit_events"))

    as_party("user_a")
    theirs = client.get("/api/sessions/sess_abc").json()
    assert theirs["halt_view"] == "other" and theirs["halted_reason"] is None and theirs["helplines"] == []
    assert client.post("/api/sessions/sess_abc/messages", json={"content": "hello?"}).status_code == 409


def test_can_stop_during_the_joint_session_but_not_after_it_ends(db, as_party):
    _session(db, status="joint_review")
    assert client.post("/api/sessions/sess_abc/leave").status_code == 200
    db.rows("sessions")[0]["status"] = "resolved"
    assert client.post("/api/sessions/sess_abc/human").status_code == 409


# --- My rooms -----------------------------------------------------------------


def test_my_rooms_lists_only_my_rooms_newest_first(db, as_party):
    db.add_session(id="old", created_by="user_123", topic="Old", created_at="2026-01-01T00:00:00Z")
    db.add_session(id="new", created_by="user_123", topic="New", created_at="2026-02-01T00:00:00Z")
    db.add_session(id="other", created_by="someone_else", topic="Not mine")
    rooms = client.get("/api/sessions").json()
    assert [room["id"] for room in rooms] == ["new", "old"]
    assert "invite_token_b" not in rooms[0] and "mediation_state" not in rooms[0]


def test_my_rooms_says_whether_the_other_person_joined(db, as_party):
    db.add_session(id="waiting", created_by="user_123", topic="Waiting")
    db.add_session(id="joined", created_by="user_123", topic="Joined", consented_b_at="2026-02-01T00:00:00Z")
    rooms = {room["id"]: room for room in client.get("/api/sessions").json()}
    assert rooms["waiting"]["other_joined"] is False
    assert rooms["joined"]["other_joined"] is True
