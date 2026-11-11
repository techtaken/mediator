"""Encryption at rest for people's private text.

Private chat messages, the mediator's private notes, share drafts and agents'
free-text reasoning are stored encrypted (AES-256-GCM). The key lives only in
the server's environment (DATA_ENCRYPTION_KEY), never in the database, so a
database dump, a backup or the Supabase dashboard shows scrambled text.

What this does not do: the server holds the key, so code running on the
server can still read the text (it has to, to run the mediator).

Stored form: ``enc1:<key id>:<base64(nonce + ciphertext)>``. The key id lets
an old key (DATA_ENCRYPTION_OLD_KEYS) keep opening older rows after a
rotation. Each value is bound to its room and field, so a value copied into
another room or column won't open. Rows written before encryption was added
are plain text and are returned as they are.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from functools import lru_cache
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

PREFIX = "enc1:"
_NONCE_BYTES = 12
# Marks an encrypted JSON value stored in a jsonb column.
JSON_KEY = "enc1"


class EncryptionKeyError(RuntimeError):
    """DATA_ENCRYPTION_KEY is missing or malformed."""


class DecryptionError(RuntimeError):
    """A stored value couldn't be opened (wrong key, tampered, or moved)."""


def _decode_key(text: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(text.strip() + "=" * (-len(text.strip()) % 4))
    except (binascii.Error, ValueError) as exc:
        raise EncryptionKeyError("DATA_ENCRYPTION_KEY must be base64") from exc
    if len(raw) != 32:
        raise EncryptionKeyError("DATA_ENCRYPTION_KEY must be 32 bytes (44 base64 characters)")
    return raw


def _key_id(raw: bytes) -> str:
    return hashlib.sha256(b"mediator-key-id:" + raw).hexdigest()[:8]


@lru_cache
def _keys() -> tuple[str, dict[str, AESGCM]]:
    """(current key id, every usable key by id)."""
    settings = get_settings()
    if not settings.data_encryption_key.strip():
        raise EncryptionKeyError("DATA_ENCRYPTION_KEY is not set")
    current = _decode_key(settings.data_encryption_key)
    keys = {_key_id(current): AESGCM(current)}
    for old in settings.data_encryption_old_keys.split(","):
        if old.strip():
            raw = _decode_key(old)
            keys.setdefault(_key_id(raw), AESGCM(raw))
    return _key_id(current), keys


def reset_keys() -> None:
    """Forget cached keys (tests, or after changing settings)."""
    _keys.cache_clear()


def check_key() -> None:
    """Fail fast at startup when the key is missing or malformed."""
    _keys()


def new_key() -> str:
    """A fresh key, in the form DATA_ENCRYPTION_KEY expects."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def _aad(context: str) -> bytes:
    return context.encode()


def is_sealed(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def seal(text: str | None, context: str) -> str | None:
    """Encrypt text for storage. ``context`` (e.g. "messages.content:<room id>")
    must be given again to open it."""
    if text is None:
        return None
    key_id, keys = _keys()
    nonce = os.urandom(_NONCE_BYTES)
    sealed = keys[key_id].encrypt(nonce, text.encode(), _aad(context))
    return f"{PREFIX}{key_id}:{base64.b64encode(nonce + sealed).decode()}"


def unseal(value: Any, context: str) -> Any:
    """Decrypt a stored value. Plain (pre-encryption) values pass through."""
    if not is_sealed(value):
        return value
    try:
        key_id, body = value[len(PREFIX) :].split(":", 1)
        blob = base64.b64decode(body)
    except (ValueError, binascii.Error) as exc:
        raise DecryptionError("malformed encrypted value") from exc
    key = _keys()[1].get(key_id)
    if key is None:
        raise DecryptionError(f"no key with id {key_id}; is DATA_ENCRYPTION_OLD_KEYS missing one?")
    try:
        return key.decrypt(blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], _aad(context)).decode()
    except Exception as exc:
        raise DecryptionError("encrypted value could not be opened") from exc


def seal_json(value: Any, context: str) -> dict[str, str] | None:
    """Encrypt a JSON value for a jsonb column."""
    if value is None:
        return None
    return {JSON_KEY: seal(json.dumps(value, ensure_ascii=False), context)}


def unseal_json(value: Any, context: str) -> Any:
    """Open a value from seal_json. Plain (pre-encryption) JSON passes through."""
    if isinstance(value, dict) and set(value) == {JSON_KEY} and is_sealed(value[JSON_KEY]):
        return json.loads(unseal(value[JSON_KEY], context))
    return value


# Contexts, one per stored field, bound to the room.
def message_context(session_id: str) -> str:
    return f"messages.content:{session_id}"


def memory_context(session_id: str, party_role: str, field: str) -> str:
    return f"private_memories.{field}:{session_id}:{party_role}"


def share_context(session_id: str, party_role: str, field: str) -> str:
    return f"party_shares.{field}:{session_id}:{party_role}"


def audit_context(session_id: str) -> str:
    return f"mediation_audit_events:{session_id}"
