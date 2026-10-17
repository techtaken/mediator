from unittest.mock import MagicMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.sessions import router
from app.auth import Actor, require_logged_in, resolve_actor

app = FastAPI()
app.include_router(router)

client = TestClient(app)


@pytest.fixture(autouse=True)
def override_auth():
    # Use FastAPI's official dependency override for require_logged_in
    app.dependency_overrides[require_logged_in] = lambda: "user_123"
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def mock_supabase():
    with patch("app.routers.sessions.get_supabase") as mock_get_db:
        supabase_mock = MagicMock()
        mock_get_db.return_value = supabase_mock
        yield supabase_mock


@pytest.fixture
def mock_resolve_actor():
    with patch("app.routers.sessions.resolve_actor") as mock_resolve:
        yield mock_resolve


def test_create_session(mock_supabase):
    mock_supabase.table.return_value.insert.return_value.execute.side_effect = [
        MagicMock(data=[{
            "id": "sess_abc",
            "created_by": "user_123",
            "relationship_context": "Roommates",
            "status": "intake",
            "created_at": "2026-06-01T00:00:00Z",
            "user_a_ready": False,
            "user_b_ready": False,
            "invite_token_b": "token_xyz"
        }]),
        MagicMock(data=[{
            "id": "msg_1",
            "session_id": "sess_abc",
            "sender_role": "ai",
            "audience_role": "user_a",
            "content": "Welcome",
            "is_private": True,
            "created_at": "2026-06-01T00:00:00Z"
        }])
    ]

    response = client.post(
        "/api/sessions",
        json={"relationship_context": "Roommates"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "sess_abc"
    assert data["status"] == "intake"
    assert data["party"] == "user_a"
    assert "invite_link" in data


def test_get_session_user_a(mock_supabase, mock_resolve_actor):
    mock_session = {
        "id": "sess_abc",
        "status": "intake",
        "relationship_context": "Partners",
        "created_at": "2026-06-01T00:00:00Z",
        "user_a_ready": False,
        "user_b_ready": False,
        "invite_token_b": "token_xyz"
    }
    mock_resolve_actor.return_value = (mock_session, Actor("user_a", user_id="user_123"))

    response = client.get("/api/sessions/sess_abc", headers={"Authorization": "Bearer fake-token"})

    assert response.status_code == 200
    data = response.json()
    assert data["party"] == "user_a"
    assert data["invite_link"] is not None


def test_send_message_normal(mock_supabase, mock_resolve_actor):
    mock_session = {
        "id": "sess_abc",
        "status": "intake",
        "relationship_context": "Coworkers",
        "user_a_ready": False,
        "user_b_ready": False,
        "invite_token_b": "token_xyz"
    }
    mock_resolve_actor.return_value = (mock_session, Actor("user_a", user_id="user_123"))

    with patch("app.routers.sessions.is_crisis_or_severe_harm", return_value=False), \
         patch("app.routers.sessions.generate_intake_reply", return_value="I hear your frustration. Tell me more."):
        
        mock_supabase.table.return_value.insert.return_value.execute.side_effect = [
            MagicMock(data=[{
                "id": "msg_user",
                "session_id": "sess_abc",
                "sender_role": "user_a",
                "audience_role": "user_a",
                "content": "I am upset.",
                "is_private": True,
                "created_at": "2026-06-01T00:00:00Z"
            }]),
            MagicMock(data=[{
                "id": "msg_ai",
                "session_id": "sess_abc",
                "sender_role": "ai",
                "audience_role": "user_a",
                "content": "I hear your frustration. Tell me more.",
                "is_private": True,
                "created_at": "2026-06-01T00:00:00Z"
            }])
        ]

        response = client.post(
            "/api/sessions/sess_abc/messages",
            json={"content": "I am upset."}
        )

        assert response.status_code == 200
        messages = response.json()
        assert len(messages) == 2
        assert messages[0]["content"] == "I am upset."
        assert messages[1]["sender_role"] == "ai"


def test_send_message_crisis_safety_halt(mock_supabase, mock_resolve_actor):
    mock_session = {
        "id": "sess_abc",
        "status": "intake",
        "relationship_context": "Family",
        "user_a_ready": False,
        "user_b_ready": False,
        "invite_token_b": "token_xyz"
    }
    mock_resolve_actor.return_value = (mock_session, Actor("user_a", user_id="user_123"))

    with patch("app.routers.sessions.is_crisis_or_severe_harm", return_value=True):
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_supabase.table.return_value.insert.return_value.execute.side_effect = [
            MagicMock(data=[{
                "id": "msg_user",
                "session_id": "sess_abc",
                "sender_role": "user_a",
                "audience_role": "user_a",
                "content": "harmful content",
                "is_private": True,
                "created_at": "2026-06-01T00:00:00Z"
            }]),
            MagicMock(data=[{
                "id": "msg_help",
                "session_id": "sess_abc",
                "sender_role": "ai",
                "audience_role": "user_a",
                "content": "Help resources...",
                "is_private": True,
                "created_at": "2026-06-01T00:00:00Z"
            }])
        ]

        response = client.post(
            "/api/sessions/sess_abc/messages",
            json={"content": "harmful content"}
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2


def test_mark_ready_triggers_summary(mock_supabase, mock_resolve_actor):
    mock_session = {
        "id": "sess_abc",
        "status": "intake",
        "user_a_ready": True,
        "user_b_ready": True,
        "relationship_context": "Friends",
        "invite_token_b": "token_xyz",
        "created_at": "2026-06-01T00:00:00Z"
    }
    mock_resolve_actor.return_value = (mock_session, Actor("user_a", user_id="user_123"))

    updated_session = {**mock_session, "status": "joint_review"}
    
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[updated_session])
    mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[updated_session])

    with patch("app.routers.sessions.generate_joint_summary", return_value={
        "user_a_perspective": "Perspective A",
        "user_b_perspective": "Perspective B",
        "compromises": ["Compromise 1"]
    }), patch("app.routers.sessions._transcript", return_value="transcript text"):
        
        response = client.post(
            "/api/sessions/sess_abc/ready",
            json={"ready": True}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "joint_review"


def test_resolve_session(mock_supabase, mock_resolve_actor):
    mock_session = {
        "id": "sess_abc",
        "status": "joint_review",
        "user_a_ready": True,
        "user_b_ready": True,
        "invite_token_b": "token_xyz",
        "created_at": "2026-06-01T00:00:00Z"
    }
    mock_resolve_actor.return_value = (mock_session, Actor("user_a", user_id="user_123"))

    resolved_session = {**mock_session, "status": "resolved"}
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[resolved_session])

    response = client.post("/api/sessions/sess_abc/resolve")

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"