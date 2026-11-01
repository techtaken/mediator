"""Link + PIN: the invite link alone must never open the invited person's room.

These go through the real access check, with real headers, because that check
is what's being tested. Person A has the link too, so "holds the link" stands
in for both a stranger and Person A in a private window.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.routers.sessions as sessions_module
from app.main import app
from app.pin import hash_pin, verify_pin, weak_pin
from app.routers.admin import _session_summary
from tests.fakes import FakeSupabase

client = TestClient(app)
ROOM = "/api/sessions/sess_abc"
LINK = {"X-Invite-Token": "token_xyz"}
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
    for item in patches:
        item.start()
    yield fake
    for item in patches:
        item.stop()


def _iso(minutes: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _open_room(db, **overrides):
    return db.add_session(topic="The Goa trip", relationship_context=None, invite_expires_at=_iso(60), **overrides)


def _claim(pin: str = PIN) -> dict[str, str]:
    response = client.post(f"{ROOM}/claim", json={"pin": pin}, headers=LINK)
    assert response.status_code == 200, response.text
    return {"X-Room-Access": response.json()["access_token"]}


def _b_writes_privately(db) -> None:
    db.table("messages").insert(
        {"session_id": "sess_abc", "sender_role": "user_b", "audience_role": "user_b", "content": "my secret", "is_private": True}
    ).execute()
    db.table("private_memories").insert({"session_id": "sess_abc", "party_role": "user_b", "notes": "secret notes", "profile": {}}).execute()


# --- Before anyone has chosen a PIN -------------------------------------------------


def test_the_link_shows_only_what_someone_needs_to_decide_to_join(db):
    _open_room(db)
    data = client.get(ROOM, headers=LINK).json()
    assert data["needs_pin"] is True and data["topic"] == "The Goa trip" and data["party"] == "user_b"
    assert data["invite_link"] is None


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/messages", None),
        ("post", "/messages", {"content": "hello"}),
        ("post", "/consent", None),
        ("post", "/leave", None),
        ("post", "/human", None),
        ("post", "/delete-my-data", None),
        ("post", "/share/draft", None),
        ("get", "/events", None),
    ],
)
def test_the_link_alone_can_do_nothing_else(db, method, path, body):
    _open_room(db)
    kwargs = {"json": body} if body else {}
    assert getattr(client, method)(f"{ROOM}{path}", headers=LINK, **kwargs).status_code == 403


def test_an_expired_unused_link_cannot_be_claimed(db):
    db.add_session(topic="x", invite_expires_at=_iso(-1))
    assert client.post(f"{ROOM}/claim", json={"pin": PIN}, headers=LINK).status_code == 410


def test_a_stopped_room_cannot_be_claimed_or_tell_the_link_holder_why(db):
    _open_room(db, status="halted", halted_for="user_a", halt_kind="safety", halted_reason="safety")
    data = client.get(ROOM, headers=LINK).json()
    assert data["halt_view"] == "other" and data["halted_reason"] is None and data["helplines"] == []
    assert client.post(f"{ROOM}/claim", json={"pin": PIN}, headers=LINK).status_code == 409


# --- Choosing a PIN -----------------------------------------------------------------


def test_claiming_records_consent_and_stores_only_a_hash(db):
    row = _open_room(db)
    access = _claim()
    assert row["consented_b_at"] and row["b_pin_set_at"]
    assert PIN not in row["b_pin_hash"] and verify_pin(PIN, row["b_pin_hash"])
    token_row = db.rows("room_access_tokens")[0]
    assert access["X-Room-Access"] not in token_row.values()
    data = client.get(ROOM, headers=access).json()
    assert data["needs_pin"] is False and data["i_consented"] is True


@pytest.mark.parametrize("pin", ["123456", "654321", "111111", "121212", "123123", "150892", "081592", "920815", "567890"])
def test_easy_pins_are_refused(db, pin):
    _open_room(db)
    response = client.post(f"{ROOM}/claim", json={"pin": pin}, headers=LINK)
    assert response.status_code == 400 and "too easy" in response.json()["detail"]
    assert db.rows("sessions")[0].get("b_pin_hash") is None


@pytest.mark.parametrize("pin", ["12345", "1234567", "abcdef", "12 456", "٣٤٥٦٧٨"])
def test_only_six_plain_digits_are_a_pin(db, pin):
    _open_room(db)
    assert client.post(f"{ROOM}/claim", json={"pin": pin}, headers=LINK).status_code == 422


def test_weak_pin_lets_ordinary_pins_through():
    assert not weak_pin(PIN) and not weak_pin("840375")


def test_only_the_first_person_gets_the_room(db):
    row = _open_room(db)
    _claim()
    first_hash = row["b_pin_hash"]
    response = client.post(f"{ROOM}/claim", json={"pin": "840375"}, headers=LINK)
    assert response.status_code == 423
    assert row["b_pin_hash"] == first_hash


def test_a_claim_that_loses_the_race_gets_nothing(db):
    """Both requests passed the check before either had written the PIN."""
    row = _open_room(db)
    before = dict(row)

    def first_claim_lands(*_args, **_kwargs):
        row["b_pin_hash"] = hash_pin(PIN)
        return before, sessions_module.Actor("user_b", invite_token="token_xyz", limited=True)

    with patch.object(sessions_module, "resolve_actor", first_claim_lands):
        response = client.post(f"{ROOM}/claim", json={"pin": "840375"}, headers=LINK)
    assert response.status_code == 423
    assert verify_pin(PIN, row["b_pin_hash"])
    assert db.rows("room_access_tokens") == []


# --- After a PIN is set: the case that matters --------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "", None),
        ("get", "/messages", None),
        ("post", "/messages", {"content": "pretending to be them"}),
        ("post", "/leave", None),
        ("post", "/delete-my-data", None),
        ("post", "/share/approve", {"text": "pretending to be them"}),
        ("post", "/language", {"language": "hi"}),
        ("get", "/events", None),
        ("post", "/consent", None),
    ],
)
def test_someone_with_only_the_link_gets_nothing(db, method, path, body):
    _open_room(db)
    _claim()
    _b_writes_privately(db)
    kwargs = {"json": body} if body else {}
    response = getattr(client, method)(f"{ROOM}{path}", headers=LINK, **kwargs)
    assert response.status_code == 423
    assert "secret" not in response.text and "Goa" not in response.text
    assert len(db.rows("messages", audience_role="user_b")) == 1


def test_the_person_who_chose_the_pin_can_read_their_chat(db):
    _open_room(db)
    access = _claim()
    _b_writes_privately(db)
    assert "my secret" in client.get(f"{ROOM}/messages", headers=access).text


def test_person_a_stays_person_a_and_cannot_claim_with_the_link(db):
    _open_room(db)
    with patch("app.auth._decode_user", return_value="user_123"):
        headers = {"Authorization": "Bearer a", **LINK}
        assert client.get(ROOM, headers=headers).json()["party"] == "user_a"
        assert client.post(f"{ROOM}/claim", json={"pin": PIN}, headers=headers).status_code == 403
    assert db.rows("sessions")[0].get("b_pin_hash") is None


def test_the_pin_hash_never_leaves_the_server(db):
    row = _open_room(db)
    access = _claim()
    assert "b_pin_hash" not in client.get(ROOM, headers=access).json()
    assert "b_pin_hash" not in _session_summary(row)
    assert "b_pin_failed_attempts" in _session_summary(row)


# --- Access tokens ------------------------------------------------------------------


def test_a_token_only_opens_its_own_room(db):
    _open_room(db)
    access = _claim()
    db.add_session(id="other_room", invite_token_b="other", invite_expires_at=_iso(60))
    assert client.get("/api/sessions/other_room/messages", headers=access).status_code == 403


def test_an_expired_token_asks_for_the_pin_again(db):
    _open_room(db)
    access = _claim()
    db.rows("room_access_tokens")[0]["expires_at"] = _iso(-1)
    assert client.get(ROOM, headers={**access, **LINK}).status_code == 423
    assert client.get(ROOM, headers=access).status_code == 403


def test_a_made_up_token_opens_nothing(db):
    _open_room(db)
    _claim()
    assert client.get(ROOM, headers={"X-Room-Access": "made-up"}).status_code == 403


def test_tokens_last_as_configured_and_old_ones_are_tidied_up(db):
    _open_room(db)
    _claim()
    db.rows("room_access_tokens")[0]["expires_at"] = _iso(-1)
    client.post(f"{ROOM}/unlock", json={"pin": PIN}, headers=LINK)
    rows = db.rows("room_access_tokens")
    assert len(rows) == 1 and _iso(100) < rows[0]["expires_at"] < _iso(130)


# --- Entering the PIN ---------------------------------------------------------------


def _unlock(pin: str = PIN, headers: dict | None = None):
    return client.post(f"{ROOM}/unlock", json={"pin": pin}, headers=LINK if headers is None else headers)


def test_link_and_pin_open_the_room_from_a_new_device(db):
    _open_room(db)
    _claim()
    _b_writes_privately(db)
    response = _unlock()
    assert response.status_code == 200
    assert "my secret" in client.get(f"{ROOM}/messages", headers={"X-Room-Access": response.json()["access_token"]}).text


def test_the_pin_without_the_link_opens_nothing(db):
    _open_room(db)
    _claim()
    assert _unlock(headers={}).status_code == 403
    assert _unlock(headers={"X-Invite-Token": "wrong"}).status_code == 403


def test_wrong_pins_count_down_then_lock_even_the_right_pin(db):
    _open_room(db)
    _claim()
    details = [_unlock("840375").json()["detail"] for _ in range(4)]
    assert details[0] == "That PIN isn't right. 4 tries left."
    assert details[3] == "That PIN isn't right. 1 try left."
    last = _unlock("840375")
    assert last.status_code == 429 and "15 minutes" in last.json()["detail"]
    locked = _unlock()
    assert locked.status_code == 429 and "Retry-After" in locked.headers


def test_the_lock_wears_off_and_a_right_pin_clears_the_count(db):
    row = _open_room(db)
    _claim()
    for _ in range(5):
        _unlock("840375")
    row["b_pin_locked_until"] = _iso(-1)
    _unlock("840375")
    assert row["b_pin_failed_attempts"] == 1
    assert _unlock().status_code == 200
    assert row["b_pin_failed_attempts"] == 0 and row["b_pin_locked_until"] is None


def test_guessing_in_parallel_cannot_skip_the_count(db):
    """A request that read the count before another's guess is refused unchecked."""
    row = _open_room(db)
    _claim()
    stale = dict(row)
    row["b_pin_failed_attempts"] = 1

    with patch.object(sessions_module, "load_session", return_value=stale), patch.object(
        sessions_module, "verify_pin", side_effect=AssertionError("must not check the PIN")
    ):
        assert _unlock("840375").status_code == 409
    assert row["b_pin_failed_attempts"] == 1


def test_a_room_with_no_pin_cannot_be_unlocked(db):
    _open_room(db)
    assert _unlock().status_code == 409


# --- Person A resets the invite -----------------------------------------------------


def _as_a():
    return patch("app.auth._decode_user", return_value="user_123")


A = {"Authorization": "Bearer a"}


def test_reset_deletes_their_side_and_gives_a_an_empty_new_link(db):
    row = _open_room(db)
    access = _claim()
    _b_writes_privately(db)
    db.table("messages").insert(
        {"session_id": "sess_abc", "sender_role": "user_a", "audience_role": "user_a", "content": "a's own chat", "is_private": True}
    ).execute()
    db.table("party_shares").insert({"session_id": "sess_abc", "party_role": "user_b", "draft_text": "secret draft"}).execute()

    with _as_a():
        response = client.post(f"{ROOM}/invite/rotate", headers=A)
    assert response.status_code == 200
    assert "secret" not in response.text
    new_token = row["invite_token_b"]
    assert new_token != "token_xyz" and response.json()["invite_link"].endswith(f"?token={new_token}")
    assert response.json()["other_joined"] is False

    assert db.rows("messages", audience_role="user_b") == []
    assert db.rows("private_memories", party_role="user_b") == []
    assert db.rows("party_shares", party_role="user_b") == []
    assert db.rows("room_access_tokens") == []
    assert [m["content"] for m in db.rows("messages", audience_role="user_a")] == ["a's own chat"]
    assert row["b_pin_hash"] is None and row["consented_b_at"] is None

    # The old link and the old token are dead.
    assert client.get(ROOM, headers=LINK).status_code == 403
    assert client.get(ROOM, headers=access).status_code == 403
    assert _unlock().status_code == 403

    # The new link starts clean, and whoever uses it finds nothing of theirs.
    new_link = {"X-Invite-Token": new_token}
    assert client.get(ROOM, headers=new_link).json()["needs_pin"] is True
    claimed = client.post(f"{ROOM}/claim", json={"pin": "840375"}, headers=new_link)
    messages = client.get(f"{ROOM}/messages", headers={"X-Room-Access": claimed.json()["access_token"]})
    assert "secret" not in messages.text


def test_reset_keeps_safety_flags(db):
    row = _open_room(db)
    _claim()
    row["mediation_state"] = {"dispute_id": "sess_abc", "safety": {"flags": {"B": {"severity": 2}}, "joint_blocked_by": ["B"]}}
    with _as_a():
        assert client.post(f"{ROOM}/invite/rotate", headers=A).status_code == 200
    assert row["mediation_state"]["safety"]["joint_blocked_by"] == ["B"]


def test_reset_is_refused_once_they_have_shared(db):
    row = _open_room(db, user_b_ready=True)
    _claim()
    _b_writes_privately(db)
    with _as_a():
        response = client.post(f"{ROOM}/invite/rotate", headers=A)
    assert response.status_code == 409 and "delete this room" in response.json()["detail"]
    assert verify_pin(PIN, row["b_pin_hash"]) and len(db.rows("messages", audience_role="user_b")) == 1


def test_only_person_a_can_reset(db):
    _open_room(db)
    access = _claim()
    assert client.post(f"{ROOM}/invite/rotate", headers=access).status_code == 403


def test_a_reply_still_being_written_is_not_saved_after_a_reset(db):
    """Otherwise the next person through the new link could read it."""
    row = _open_room(db)
    access = _claim()

    def fake_turn(**_kwargs):
        row["invite_token_b"] = "new_token"
        return object()

    with patch.object(sessions_module, "handle_party_turn", fake_turn), patch.object(
        sessions_module, "persist_turn", side_effect=AssertionError("must not save")
    ):
        response = client.post(f"{ROOM}/messages", json={"content": "hello"}, headers=access)
    assert response.status_code == 409
    assert db.rows("messages", audience_role="user_b", sender_role="ai") == []
    assert db.rows("private_memories", party_role="user_b") == []
