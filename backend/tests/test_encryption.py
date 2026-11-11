"""Private text is stored encrypted, read back as plain text, and never shown to admins."""

from unittest.mock import patch

import pytest

from app import crypto
from app.config import get_settings
from app.encrypt_existing import encrypt_existing
from tests.fakes import FakeSupabase, opened
from tests.test_sessions import _session, agents, as_party, client, db  # noqa: F401 (fixtures)

OTHER_KEY = "b2Jvb2Jvb2Jvb2Jvb2Jvb2Jvb2Jvb2Jvb2Jvb2Jvb28="  # 32 bytes, base64


@pytest.fixture
def keys(monkeypatch):
    """Swap the encryption settings for one test."""

    def use(current: str, old: str = "") -> None:
        monkeypatch.setattr(get_settings(), "data_encryption_key", current)
        monkeypatch.setattr(get_settings(), "data_encryption_old_keys", old)
        crypto.reset_keys()

    original = get_settings().data_encryption_key
    yield use
    crypto.reset_keys()
    monkeypatch.setattr(get_settings(), "data_encryption_key", original)


# --- The helper -----------------------------------------------------------------


@pytest.mark.parametrize("text", ["I want my money back.", "मुझे बुरा लगा", "Mujhe bura laga 😞", ""])
def test_round_trip(text):
    sealed = crypto.seal(text, "ctx")
    assert sealed.startswith("enc1:") and (text == "" or text not in sealed)
    assert crypto.unseal(sealed, "ctx") == text


def test_same_text_encrypts_differently_each_time():
    assert crypto.seal("same", "ctx") != crypto.seal("same", "ctx")


def test_a_value_moved_to_another_room_or_field_will_not_open():
    sealed = crypto.seal("secret", crypto.message_context("room-1"))
    with pytest.raises(crypto.DecryptionError):
        crypto.unseal(sealed, crypto.message_context("room-2"))


def test_tampered_value_will_not_open():
    sealed = crypto.seal("secret", "ctx")
    flipped = sealed[:-6] + ("A" if sealed[-6] != "A" else "B") + sealed[-5:]
    with pytest.raises(crypto.DecryptionError):
        crypto.unseal(flipped, "ctx")


def test_rows_from_before_encryption_are_read_as_they_are():
    assert crypto.unseal("plain old text", "ctx") == "plain old text"
    assert crypto.unseal(None, "ctx") is None
    assert crypto.unseal_json({"positions": ["x"]}, "ctx") == {"positions": ["x"]}


def test_json_round_trip():
    value = {"positions": ["Pay me back"], "interests": ["respect"]}
    sealed = crypto.seal_json(value, "ctx")
    assert set(sealed) == {"enc1"} and "Pay me back" not in str(sealed)
    assert crypto.unseal_json(sealed, "ctx") == value


def test_after_a_key_rotation_old_rows_still_open(keys):
    original = get_settings().data_encryption_key
    old_row = crypto.seal("written with the old key", "ctx")
    keys(OTHER_KEY, old=original)
    assert crypto.unseal(old_row, "ctx") == "written with the old key"
    new_row = crypto.seal("new", "ctx")
    keys(OTHER_KEY)  # old key dropped
    assert crypto.unseal(new_row, "ctx") == "new"
    with pytest.raises(crypto.DecryptionError):
        crypto.unseal(old_row, "ctx")


@pytest.mark.parametrize("bad", ["", "   ", "not base64!!", "c2hvcnQ="])
def test_missing_or_malformed_key_stops_the_server(keys, bad):
    keys(bad)
    with pytest.raises(crypto.EncryptionKeyError):
        crypto.check_key()


def test_new_key_is_usable(keys):
    keys(crypto.new_key())
    assert crypto.unseal(crypto.seal("x", "c"), "c") == "x"


# --- Through the app -----------------------------------------------------------


def _stored_text(fake: FakeSupabase) -> str:
    return str(fake.tables)


def test_chat_is_stored_encrypted_and_read_back_plain(db, as_party, agents):
    _session(db)
    sent = client.post("/api/sessions/sess_abc/messages", json={"content": "I want my money back."})
    assert sent.status_code == 200
    mine, reply = sent.json()
    assert mine["content"] == "I want my money back."

    stored = _stored_text(db)
    assert "I want my money back" not in stored
    assert reply["content"][:30] not in stored
    assert "Pay me back now" not in stored  # the mediator's private notes on this person
    assert all(row["content"].startswith("enc1:") for row in db.rows("messages"))

    listed = client.get("/api/sessions/sess_abc/messages").json()
    assert [m["content"] for m in listed] == [mine["content"], reply["content"]]
    assert opened("private_memories", db.rows("private_memories")[0])["profile"]["positions"] == ["Pay me back now"]


def test_share_text_is_stored_encrypted(db, as_party, agents):
    _session(db)
    client.post("/api/sessions/sess_abc/messages", json={"content": "I want my money back."})
    draft = client.post("/api/sessions/sess_abc/share/draft").json()["draft"]
    assert draft and draft not in _stored_text(db)
    assert client.get("/api/sessions/sess_abc/share").json()["draft"] == draft


def test_messages_from_before_encryption_still_show(db, as_party):
    _session(db)
    db.table("messages").insert(
        {"session_id": "sess_abc", "sender_role": "user_a", "audience_role": "user_a", "content": "written last year"}
    ).execute()
    assert [m["content"] for m in client.get("/api/sessions/sess_abc/messages").json()] == ["written last year"]


# --- Encrypting rows written before this change --------------------------------


def test_encrypt_existing_seals_old_rows_once():
    fake = FakeSupabase()
    fake.table("messages").insert(
        [
            {"session_id": "s1", "sender_role": "user_a", "audience_role": "user_a", "content": "old secret"},
            {"session_id": "s1", "sender_role": "ai", "audience_role": "user_a",
             "content": crypto.seal("already sealed", crypto.message_context("s1"))},
        ]
    ).execute()
    fake.table("private_memories").insert(
        {"session_id": "s1", "party_role": "user_a", "notes": "old notes", "profile": {"positions": ["x"]}}
    ).execute()
    fake.table("party_shares").insert(
        {"session_id": "s1", "party_role": "user_a", "draft_text": "old draft", "approved_text": None}
    ).execute()
    fake.table("mediation_audit_events").insert(
        [
            {"session_id": "s1", "agent": "CAUCUS_A", "reason": "A is hurt", "reason_scrubbed": False,
             "payload": {"seq": 1, "agent": "CAUCUS_A", "reason": "A is hurt"}},
            {"session_id": "s1", "agent": None, "reason": "session viewed by admin x", "reason_scrubbed": False,
             "payload": {"type": "admin_view", "admin_user_id": "u1"}},
        ]
    ).execute()

    with patch("app.encrypt_existing.get_supabase", return_value=fake):
        assert encrypt_existing() == {"messages": 1, "private_memories": 1, "party_shares": 1, "mediation_audit_events": 1}
        assert encrypt_existing() == {"messages": 0, "private_memories": 0, "party_shares": 0, "mediation_audit_events": 0}

    stored = str(fake.tables)
    for secret in ("old secret", "old notes", "old draft", "A is hurt"):
        assert secret not in stored
    assert [opened("messages", row)["content"] for row in fake.rows("messages")] == ["old secret", "already sealed"]
    memory = opened("private_memories", fake.rows("private_memories")[0])
    assert memory["notes"] == "old notes" and memory["profile"] == {"positions": ["x"]}
    assert opened("party_shares", fake.rows("party_shares")[0])["draft_text"] == "old draft"
    agent_event, admin_event = fake.rows("mediation_audit_events")
    assert opened("mediation_audit_events", agent_event)["reason"] == "A is hurt"
    assert agent_event["payload"]["agent"] == "CAUCUS_A"
    assert admin_event["reason"] == "session viewed by admin x"
