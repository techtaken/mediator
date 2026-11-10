"""Person B can save a room to their account. Asked, not automatic, and the PIN
is still needed to open it."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.fakes import FakeSupabase

client = TestClient(app)
ROOM = "/api/sessions/sess_abc"
LINK = {"X-Invite-Token": "token_xyz"}
PIN = "739182"
A = {"Authorization": "Bearer a"}
B = {"Authorization": "Bearer b"}
SISTER = {"Authorization": "Bearer sister"}
USERS = {"Bearer a": "user_a_id", "Bearer b": "user_b_id", "Bearer sister": "sister_id"}

PATCHED_MODULES = (
    "app.routers.sessions.get_supabase",
    "app.joint_store.get_supabase",
    "app.agents.store.get_supabase",
    "app.agents.telemetry.get_supabase",
    "app.auth.get_supabase",
    "app.retention.get_supabase",
    "app.followup_store.get_supabase",
)


@pytest.fixture
def db():
    fake = FakeSupabase()
    patches = [patch(name, return_value=fake) for name in PATCHED_MODULES]
    patches.append(patch("app.auth._decode_user", side_effect=lambda value: USERS.get(value)))
    for item in patches:
        item.start()
    yield fake
    for item in patches:
        item.stop()


def _room(db, **overrides):
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    return db.add_session(
        created_by="user_a_id", name_a="nk", invited_as="anu", topic="Jokes", invite_expires_at=expires, **overrides
    )


def _join(headers: dict | None = None) -> dict[str, str]:
    response = client.post(f"{ROOM}/claim", json={"pin": PIN, "name": "Anu"}, headers={**LINK, **(headers or {})})
    assert response.status_code == 200, response.text
    return {"X-Room-Access": response.json()["access_token"]}


def _save(access: dict, who: dict = B):
    return client.post(f"{ROOM}/save", headers={**access, **who})


# --- Saving -------------------------------------------------------------------------


def test_b_signed_in_can_save_the_room(db):
    row = _room(db)
    access = _join()
    assert client.get(ROOM, headers={**access, **B}).json()["saved_to"] is None
    response = _save(access)
    assert response.status_code == 200 and response.json()["saved_to"] == "you"
    assert row["user_b_id"] == "user_b_id" and row["b_saved_at"]


def test_saving_needs_a_sign_in(db):
    _room(db)
    access = _join()
    response = client.post(f"{ROOM}/save", headers=access)
    assert response.status_code == 401


def test_saving_needs_the_pin_not_just_the_link(db):
    _room(db)
    assert client.post(f"{ROOM}/save", headers={**LINK, **B}).status_code == 403
    _join()
    assert client.post(f"{ROOM}/save", headers={**LINK, **B}).status_code == 423


def test_signing_in_before_joining_does_not_save_by_itself(db):
    row = _room(db)
    access = _join(B)
    assert row.get("user_b_id") is None
    assert client.get(ROOM, headers={**access, **B}).json()["saved_to"] is None


def test_person_a_cannot_save_as_b(db):
    _room(db)
    assert client.post(f"{ROOM}/save", headers=A).status_code == 403


def test_only_the_first_account_gets_it(db):
    row = _room(db)
    access = _join()
    _save(access)
    response = _save(access, SISTER)
    assert response.status_code == 409 and "another account" in response.json()["detail"]
    assert row["user_b_id"] == "user_b_id"
    assert client.get(ROOM, headers={**access, **SISTER}).json()["saved_to"] == "another account"


def test_saving_twice_is_fine(db):
    _room(db)
    access = _join()
    _save(access)
    assert _save(access).status_code == 200


def test_a_new_account_takes_the_name_given_in_the_room(db):
    _room(db)
    _save(_join())
    assert db.rows("profiles", user_id="user_b_id")[0]["name"] == "Anu"


def test_an_existing_profile_name_is_kept(db):
    db.table("profiles").insert({"user_id": "user_b_id", "name": "Anushka"}).execute()
    _room(db)
    _save(_join())
    assert [row["name"] for row in db.rows("profiles", user_id="user_b_id")] == ["Anushka"]


def test_a_is_never_told(db):
    _room(db)
    _save(_join())
    data = client.get(ROOM, headers=A).json()
    assert data["saved_to"] is None and "user_b_id" not in data
    assert client.get("/api/sessions", headers=A).json()[0]["role"] == "opened"


# --- Their chats --------------------------------------------------------------------


def test_a_saved_room_shows_in_b_chats(db):
    _room(db)
    assert client.get("/api/sessions", headers=B).json() == []
    _save(_join())
    (room,) = client.get("/api/sessions", headers=B).json()
    assert room["role"] == "invited" and room["other_name"] == "nk"
    assert room["other_joined"] is True and room["invite_expired"] is False


def test_chats_list_both_kinds_newest_first(db):
    db.add_session(id="mine", created_by="user_b_id", created_at="2026-07-01T00:00:00Z", name_a="Anu")
    _room(db, created_at="2026-06-01T00:00:00Z")
    _save(_join())
    rooms = client.get("/api/sessions", headers=B).json()
    assert [(room["id"], room["role"]) for room in rooms] == [("mine", "opened"), ("sess_abc", "invited")]


def test_the_account_replaces_the_link_but_not_the_pin(db):
    _room(db)
    _save(_join())
    # A new device: signed in, no link, no access token.
    assert client.get(ROOM, headers=B).status_code == 423
    assert client.post(f"{ROOM}/unlock", json={"pin": "840375"}, headers=B).status_code == 401
    unlocked = client.post(f"{ROOM}/unlock", json={"pin": PIN}, headers=B)
    assert unlocked.status_code == 200
    access = {"X-Room-Access": unlocked.json()["access_token"]}
    assert client.get(ROOM, headers={**access, **B}).json()["saved_to"] == "you"


def test_another_account_cannot_unlock_without_the_link(db):
    _room(db)
    _save(_join())
    assert client.get(ROOM, headers=SISTER).status_code == 403
    assert client.post(f"{ROOM}/unlock", json={"pin": PIN}, headers=SISTER).status_code == 403


# --- Removing -----------------------------------------------------------------------


def test_b_can_remove_it_from_their_chats(db):
    row = _room(db)
    access = _join()
    _save(access)
    response = client.delete(f"{ROOM}/save", headers=access)
    assert response.status_code == 200 and response.json()["saved_to"] is None
    assert row["user_b_id"] is None
    assert client.get("/api/sessions", headers=B).json() == []


def test_a_wrong_save_can_be_undone_with_the_pin(db):
    """Saved on a browser signed in as someone else: B fixes it with link + PIN."""
    row = _room(db)
    access = _join()
    _save(access, SISTER)
    assert client.delete(f"{ROOM}/save", headers=access).status_code == 200
    assert row["user_b_id"] is None and _save(access).status_code == 200


def test_resetting_the_invite_removes_the_save(db):
    row = _room(db)
    _save(_join())
    assert client.post(f"{ROOM}/invite/rotate", headers=A).status_code == 200
    assert row["user_b_id"] is None
    assert client.get("/api/sessions", headers=B).json() == []


def test_deleting_my_data_removes_the_save(db):
    row = _room(db)
    access = _join()
    _save(access)
    client.post(f"{ROOM}/delete-my-data", headers=access)
    assert row["user_b_id"] is None
