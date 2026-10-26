from functools import partial
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.pipeline import handle_party_turn as real_handle_party_turn
from app.agents.state import new_shared_state
from app.auth import Actor, load_session, require_logged_in
from app.routers import sessions as sessions_module
from app.routers.sessions import get_actor, router
from tests.fakes import FakeSupabase
from tests.test_pipeline import FakeAgents

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture
def db():
    fake = FakeSupabase()
    targets = ("app.routers.sessions.get_supabase", "app.agents.store.get_supabase", "app.auth.get_supabase")
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
    yield lambda party: current.update(party=party)
    app.dependency_overrides.clear()


@pytest.fixture
def agents():
    fake = FakeAgents()
    with patch.object(sessions_module, "handle_party_turn", partial(real_handle_party_turn, caller=fake)):
        yield fake


def _session(db, **overrides):
    state = overrides.pop("mediation_state", None) or new_shared_state("sess_abc")
    return db.add_session(mediation_state=state, **overrides)


def test_create_session_saves_initial_state(db, as_party):
    response = client.post("/api/sessions", json={"relationship_context": "Roommates"})
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


JOINT = {
    "user_a_perspective": "Perspective A",
    "user_b_perspective": "Perspective B",
    "compromises": ["Compromise 1"],
    "joint_message": "Joint",
}


def test_mark_ready_builds_joint_view_once(db, as_party):
    _session(db, user_b_ready=True)
    with patch.object(sessions_module, "run_joint_pipeline", side_effect=lambda state: {"state": state, **JOINT}) as run:
        response = client.post("/api/sessions/sess_abc/ready", json={"ready": True})
        assert response.status_code == 200
        assert response.json()["status"] == "joint_review"
        # A second, late build attempt finds the claim already taken.
        sessions_module._maybe_build_summary({**db.rows("sessions")[0], "status": "intake"})
    assert run.call_count == 1
    assert len(db.rows("joint_summaries")) == 1
    summary = client.get("/api/sessions/sess_abc/summary").json()
    assert summary["user_a_perspective"] == "Perspective A"


def test_joint_build_failure_reopens_intake(db, as_party):
    _session(db, user_b_ready=True)
    with patch.object(sessions_module, "run_joint_pipeline", side_effect=RuntimeError("llm down")):
        response = client.post("/api/sessions/sess_abc/ready", json={"ready": True})
    assert response.status_code == 502
    assert db.rows("sessions")[0]["status"] == "intake"


def test_flagged_party_cannot_move_to_joint(db, as_party):
    state = new_shared_state("sess_abc")
    state["safety"]["joint_blocked_by"] = ["B"]
    _session(db, mediation_state=state, user_a_ready=True)

    as_party("user_b")
    response = client.post("/api/sessions/sess_abc/ready", json={"ready": True})
    assert response.status_code == 409
    assert "safety" not in response.json()["detail"].lower()

    # Even if both flags are set, the joint build does not start.
    db.rows("sessions")[0]["user_b_ready"] = True
    with patch.object(sessions_module, "run_joint_pipeline") as run:
        sessions_module._maybe_build_summary(db.rows("sessions")[0])
    run.assert_not_called()
    assert db.rows("sessions")[0]["status"] == "intake"


def test_messages_rejected_after_intake(db, as_party):
    _session(db, status="building_joint")
    response = client.post("/api/sessions/sess_abc/messages", json={"content": "Hello"})
    assert response.status_code == 409


def test_resolve_session(db, as_party):
    _session(db, status="joint_review")
    response = client.post("/api/sessions/sess_abc/resolve")
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
