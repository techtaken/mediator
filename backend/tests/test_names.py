"""Both people give a name: Person A in their profile, Person B when joining."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.agents.state import party_view
from app.agents.store import load_state
from app.main import app
from app.names import clean_name
from app.routers.sessions import welcome_b
from tests.fakes import FakeSupabase

client = TestClient(app)
ROOM = "/api/sessions/sess_abc"
LINK = {"X-Invite-Token": "token_xyz"}
A = {"Authorization": "Bearer a"}
PIN = "739182"

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
    patches.append(patch("app.auth._decode_user", side_effect=lambda value: "user_123" if value else None))
    for item in patches:
        item.start()
    yield fake
    for item in patches:
        item.stop()


def _iso(minutes: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _open_room(db, **overrides):
    overrides.setdefault("name_a", "Rahul")
    return db.add_session(topic="The Goa trip", relationship_context=None, invite_expires_at=_iso(60), **overrides)


def _claim(name: str = "Priya") -> dict[str, str]:
    response = client.post(f"{ROOM}/claim", json={"pin": PIN, "name": name}, headers=LINK)
    assert response.status_code == 200, response.text
    return {"X-Room-Access": response.json()["access_token"]}


# --- What counts as a name ----------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("Rahul", "Rahul"),
        ("  Priya   Sharma ", "Priya Sharma"),
        ("प्रिया", "प्रिया"),
        ("O'Brien", "O'Brien"),
        ("Dr. Anand", "Dr. Anand"),
        ("Anne-Marie", "Anne-Marie"),
        ("A" * 40, "A" * 40),
    ],
)
def test_real_names_are_kept(given, kept):
    assert clean_name(given) == kept


@pytest.mark.parametrize(
    "given",
    ["", "   ", "12345", "Rahul123", "a" * 41, "http://x.co", "rahul@mail.com", "<b>Rahul</b>", "{{CONSTITUTION}}", "- ."],
)
def test_anything_else_is_refused(given):
    assert clean_name(given) is None


def test_a_name_is_always_one_line():
    assert clean_name("Rahul\nKumar") == "Rahul Kumar"


# --- Person A's profile -------------------------------------------------------------


def test_a_has_no_name_until_they_give_one(db):
    assert client.get("/api/me", headers=A).json() == {"name": None}
    assert client.put("/api/me", json={"name": "  Rahul "}, headers=A).json() == {"name": "Rahul"}
    assert client.get("/api/me", headers=A).json() == {"name": "Rahul"}


def test_changing_a_name_keeps_one_profile(db):
    client.put("/api/me", json={"name": "Rahl"}, headers=A)
    client.put("/api/me", json={"name": "Rahul"}, headers=A)
    assert [row["name"] for row in db.rows("profiles")] == ["Rahul"]


def test_a_bad_name_is_refused_with_a_clear_message(db):
    response = client.put("/api/me", json={"name": "rahul123"}, headers=A)
    assert response.status_code == 400 and "just your name" in response.json()["detail"]
    assert db.rows("profiles") == []


def test_the_profile_needs_a_sign_in(db):
    assert client.get("/api/me").status_code == 401
    assert client.put("/api/me", json={"name": "Rahul"}).status_code == 401


def test_a_cannot_open_a_room_without_a_name(db):
    response = client.post("/api/sessions", json={"topic": "Rent split", "invited_name": "Priya"}, headers=A)
    assert response.status_code == 409 and "name" in response.json()["detail"]
    assert db.rows("sessions") == []


def test_a_new_room_carries_a_name(db):
    client.put("/api/me", json={"name": "Rahul"}, headers=A)
    data = client.post("/api/sessions", json={"topic": "Rent split", "invited_name": "Priya"}, headers=A).json()
    assert data["my_name"] == "Rahul" and data["other_name"] == "Priya"
    assert db.rows("sessions")[0]["name_a"] == "Rahul"


def test_fixing_a_name_updates_open_rooms_but_not_finished_ones(db):
    _open_room(db, name_a="Rahl")
    db.add_session(id="done", status="resolved", name_a="Rahl")
    client.put("/api/me", json={"name": "Rahul"}, headers=A)
    assert db.rows("sessions", id="sess_abc")[0]["name_a"] == "Rahul"
    assert db.rows("sessions", id="done")[0]["name_a"] == "Rahl"


# --- Person B joining ---------------------------------------------------------------


def test_b_sees_who_invited_them_before_joining(db):
    _open_room(db)
    data = client.get(ROOM, headers=LINK).json()
    assert data["other_name"] == "Rahul" and data["my_name"] is None


def test_b_must_give_a_name_to_join(db):
    row = _open_room(db)
    assert client.post(f"{ROOM}/claim", json={"pin": PIN}, headers=LINK).status_code == 422
    response = client.post(f"{ROOM}/claim", json={"pin": PIN, "name": "12345"}, headers=LINK)
    assert response.status_code == 400 and "just your name" in response.json()["detail"]
    assert row.get("b_pin_hash") is None and row.get("name_b") is None


def test_joining_saves_the_name_with_the_pin(db):
    row = _open_room(db)
    access = _claim(" Priya ")
    assert row["name_b"] == "Priya" and row["b_pin_hash"]
    data = client.get(ROOM, headers=access).json()
    assert data["my_name"] == "Priya" and data["other_name"] == "Rahul"


def test_a_sees_b_name_once_they_join(db):
    _open_room(db)
    assert client.get(ROOM, headers=A).json()["other_name"] is None
    _claim()
    assert client.get(ROOM, headers=A).json()["other_name"] == "Priya"
    assert client.get("/api/sessions", headers=A).json()[0]["other_name"] == "Priya"


def test_a_second_person_cannot_replace_the_name(db):
    row = _open_room(db)
    _claim()
    assert client.post(f"{ROOM}/claim", json={"pin": "840375", "name": "Stranger"}, headers=LINK).status_code == 423
    assert row["name_b"] == "Priya"


def test_the_link_alone_shows_no_names_once_someone_has_joined(db):
    _open_room(db)
    _claim()
    response = client.get(ROOM, headers=LINK)
    assert response.status_code == 423
    assert "Rahul" not in response.text and "Priya" not in response.text


# --- Removing names -----------------------------------------------------------------


def test_resetting_the_invite_removes_b_name(db):
    row = _open_room(db)
    _claim()
    assert client.post(f"{ROOM}/invite/rotate", headers=A).status_code == 200
    assert row["name_b"] is None
    assert client.get(ROOM, headers=A).json()["other_name"] is None
    assert load_state(row)["parties"]["B"]["name"] is None


def test_deleting_my_data_removes_my_name_from_the_room(db):
    row = _open_room(db)
    access = _claim()
    assert client.post(f"{ROOM}/delete-my-data", headers=access).status_code == 200
    assert row["name_b"] is None and row["name_a"] == "Rahul"


# --- Welcome message ----------------------------------------------------------------


def test_b_welcome_names_the_person_who_invited_them(db):
    _open_room(db)
    client.get(ROOM, headers=LINK)
    (welcome,) = db.rows("messages", audience_role="user_b")
    assert "Rahul can't read it" in welcome["content"]
    assert 'Rahul opened this room about: "The Goa trip"' in welcome["content"]


@pytest.mark.parametrize(
    ("language", "expected"),
    [("hinglish", "Rahul ne yeh room"), ("hi", "Rahul ने यह कमरा"), (None, "Rahul opened this room")],
)
def test_the_welcome_uses_the_name_in_every_language(language, expected):
    assert expected in welcome_b("The Goa trip", language, "Rahul")


def test_the_welcome_still_reads_well_without_a_name():
    welcome = welcome_b("The Goa trip")
    assert "The person who invited you can't read it" in welcome and "They opened this room about" in welcome


def test_changing_language_keeps_the_name_in_the_welcome(db):
    _open_room(db)
    client.get(ROOM, headers=LINK)
    client.post(f"{ROOM}/language", json={"language": "hinglish"}, headers=LINK)
    (welcome,) = db.rows("messages", audience_role="user_b")
    assert "Rahul ne yeh room" in welcome["content"]


# --- The mediator -------------------------------------------------------------------


def test_the_mediator_gets_names_from_the_room(db):
    row = _open_room(db, name_b="Priya")
    state = load_state(row)
    assert state["parties"]["A"]["name"] == "Rahul" and state["parties"]["B"]["name"] == "Priya"
    assert party_view(state, "A")["parties"]["B"]["name"] == "Priya"


def test_rooms_without_names_still_load(db):
    row = _open_room(db, name_a=None)
    assert load_state(row)["parties"]["A"]["name"] is None


# --- Who A is inviting --------------------------------------------------------------


def _invite_bhaiya(db, **overrides):
    return _open_room(db, invited_as="Bhaiya", **overrides)


def test_a_must_say_who_they_are_inviting(db):
    client.put("/api/me", json={"name": "Rahul"}, headers=A)
    assert client.post("/api/sessions", json={"topic": "Rent split"}, headers=A).status_code == 422
    response = client.post("/api/sessions", json={"topic": "Rent split", "invited_name": "12345"}, headers=A)
    assert response.status_code == 400 and "just their name" in response.json()["detail"]
    assert db.rows("sessions") == []


def test_a_sees_what_they_wrote_until_b_joins_then_b_own_name(db):
    _invite_bhaiya(db)
    data = client.get(ROOM, headers=A).json()
    assert data["other_name"] == "Bhaiya" and data["invited_as"] == "Bhaiya" and data["other_joined"] is False
    assert client.get("/api/sessions", headers=A).json()[0]["other_name"] == "Bhaiya"

    _claim("Amit")
    data = client.get(ROOM, headers=A).json()
    assert data["other_name"] == "Amit" and data["invited_as"] == "Bhaiya" and data["other_joined"] is True
    assert client.get("/api/sessions", headers=A).json()[0]["other_name"] == "Amit"


def test_the_mediator_uses_what_a_wrote_until_b_joins(db):
    row = _invite_bhaiya(db)
    assert load_state(row)["parties"]["B"]["name"] == "Bhaiya"
    _claim("Amit")
    assert load_state(row)["parties"]["B"]["name"] == "Amit"


def test_someone_opening_the_link_can_tell_who_it_is_for(db):
    _invite_bhaiya(db)
    assert client.get(ROOM, headers=LINK).json()["invited_as"] == "Bhaiya"


def test_once_b_has_joined_they_no_longer_see_what_a_wrote(db):
    _invite_bhaiya(db)
    access = _claim("Amit")
    data = client.get(ROOM, headers=access).json()
    assert data["invited_as"] is None and data["my_name"] == "Amit"


def test_the_link_alone_shows_nothing_of_it_after_joining(db):
    _invite_bhaiya(db)
    _claim("Amit")
    assert "Bhaiya" not in client.get(ROOM, headers=LINK).text


def test_resetting_the_invite_goes_back_to_what_a_wrote(db):
    row = _invite_bhaiya(db)
    _claim("Stranger")
    client.post(f"{ROOM}/invite/rotate", headers=A)
    assert client.get(ROOM, headers=A).json()["other_name"] == "Bhaiya"
    assert load_state(row)["parties"]["B"]["name"] == "Bhaiya"


def test_deleting_my_data_removes_what_a_wrote_too(db):
    row = _invite_bhaiya(db)
    access = _claim("Amit")
    client.post(f"{ROOM}/delete-my-data", headers=access)
    assert row["invited_as"] is None and row["name_b"] is None
    assert load_state(row)["parties"]["B"]["name"] is None

