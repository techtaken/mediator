from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.state import new_shared_state
from app.routers.admin import router
from tests.fakes import FakeSupabase

app = FastAPI()
app.include_router(router)
client = TestClient(app)

ADMIN = {"Authorization": "Bearer admin"}
USER = {"Authorization": "Bearer user"}
CLAIMS = {
    "Bearer admin": {"sub": "admin-1", "email": "Admin@Example.com"},
    "Bearer user": {"sub": "user-1", "email": "someone@example.com"},
}


@pytest.fixture
def db():
    fake = FakeSupabase()
    targets = (
        "app.routers.admin.get_supabase",
        "app.auth.get_supabase",
        "app.joint_store.get_supabase",
        "app.followup_store.get_supabase",
        "app.agents.store.get_supabase",
    )
    patches = [patch(target, return_value=fake) for target in targets]
    for item in patches:
        item.start()
    yield fake
    for item in patches:
        item.stop()


@pytest.fixture(autouse=True)
def auth():
    settings = SimpleNamespace(admin_email_set={"admin@example.com"})
    with patch("app.auth._decode_claims", side_effect=lambda header: CLAIMS.get(header)), \
         patch("app.auth.get_settings", return_value=settings):
        yield settings


def _seed(db):
    state = new_shared_state("s1")
    state["safety"]["flags"]["B"] = {"severity": 2, "action": "PAUSE_AND_CHECK"}
    db.add_session(id="s1", topic="Goa trip", created_at="2026-06-01T00:00:01Z", mediation_state=state)
    db.add_session(id="s2", topic="Rent", status="halted", halted_for="user_b", created_at="2026-06-02T00:00:01Z")
    db.add_session(id="s3", topic="Chores", status="resolved", created_at="2026-06-03T00:00:01Z")
    for sid, sender, audience, text in [
        ("s1", "user_a", "user_a", "B went to Goa without me"),
        ("s1", "ai", "user_a", "That sounds hurtful."),
        ("s1", "user_b", "user_b", "I did invite them"),
        ("s1", "user_b", "user_b", "they said no"),
        ("s2", "user_a", "user_a", "rent"),
    ]:
        db.table("messages").insert(
            {"session_id": sid, "sender_role": sender, "audience_role": audience, "content": text}
        ).execute()
    db.table("private_memories").insert(
        {"session_id": "s1", "party_role": "user_b", "notes": "B feels excluded too", "profile": {}}
    ).execute()


# --- access -------------------------------------------------------------------


def test_signed_out_is_rejected(db):
    assert client.get("/api/admin/sessions").status_code == 401


def test_non_admin_is_rejected(db):
    _seed(db)
    assert client.get("/api/admin/sessions", headers=USER).status_code == 403
    assert client.get("/api/admin/sessions/s1", headers=USER).status_code == 403
    assert db.rows("mediation_audit_events") == []


def test_no_admins_configured_means_nobody_gets_in(db, auth):
    auth.admin_email_set = set()
    assert client.get("/api/admin/sessions", headers=ADMIN).status_code == 403


def test_admin_email_match_is_case_insensitive(db):
    assert client.get("/api/admin/me", headers=ADMIN).json() == {"email": "admin@example.com"}


# --- list ---------------------------------------------------------------------


def test_list_is_newest_first_with_counts_and_no_secrets(db):
    _seed(db)
    data = client.get("/api/admin/sessions", headers=ADMIN).json()
    assert [row["id"] for row in data["sessions"]] == ["s3", "s2", "s1"]
    s1 = data["sessions"][2]
    assert (s1["messages_a"], s1["messages_b"]) == (1, 2)
    assert s1["last_activity"] is not None
    for row in data["sessions"]:
        assert "invite_token_b" not in row and "mediation_state" not in row
    assert data["has_more"] is False


def test_list_filters_by_status_and_pages(db):
    _seed(db)
    halted = client.get("/api/admin/sessions?status=halted", headers=ADMIN).json()
    assert [row["id"] for row in halted["sessions"]] == ["s2"]

    page1 = client.get("/api/admin/sessions?limit=2", headers=ADMIN).json()
    assert [row["id"] for row in page1["sessions"]] == ["s3", "s2"] and page1["has_more"] is True
    page2 = client.get("/api/admin/sessions?limit=2&offset=2", headers=ADMIN).json()
    assert [row["id"] for row in page2["sessions"]] == ["s1"] and page2["has_more"] is False


def test_unknown_status_is_rejected(db):
    assert client.get("/api/admin/sessions?status=nope", headers=ADMIN).status_code == 422


# --- detail -------------------------------------------------------------------


def test_detail_shows_both_rooms_memory_and_safety(db):
    _seed(db)
    data = client.get("/api/admin/sessions/s1", headers=ADMIN).json()
    assert [m["content"] for m in data["rooms"]["user_a"]] == ["B went to Goa without me", "That sounds hurtful."]
    assert [m["content"] for m in data["rooms"]["user_b"]] == ["I did invite them", "they said no"]
    assert data["private_memories"]["user_b"]["notes"] == "B feels excluded too"
    assert data["state"]["safety"]["flags"]["B"]["severity"] == 2
    assert "invite_token_b" not in data["session"] and "mediation_state" not in data["session"]
    assert data["joint_summary"] is None
    assert data["joint"] == {"ideas": [], "responses": [], "agreement": None}


def test_every_view_is_recorded_with_the_admin(db):
    _seed(db)
    client.get("/api/admin/sessions/s1", headers=ADMIN)
    client.get("/api/admin/sessions/s1", headers=ADMIN)
    views = db.rows("mediation_audit_events", agent="ADMIN")
    assert len(views) == 2
    assert views[0]["payload"]["admin_email"] == "admin@example.com"
    assert views[0]["session_id"] == "s1"


def test_view_is_refused_if_it_cannot_be_recorded(db):
    _seed(db)
    db.failures[("mediation_audit_events", "insert")] = RuntimeError("db down")
    response = client.get("/api/admin/sessions/s1", headers=ADMIN)
    assert response.status_code == 503
    assert "rooms" not in response.json()


def test_unknown_session_is_404(db):
    assert client.get("/api/admin/sessions/missing", headers=ADMIN).status_code == 404
