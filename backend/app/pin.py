"""The invited person's PIN, and the short-lived access tokens it unlocks.

The invite link can't be the key to their private room, because the person who
invited them has the link too. Only hashes are stored, here and in the database.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

WEAK_PIN_DETAIL = "That PIN is too easy to guess. Avoid dates, birthdays and patterns like 123456."

_ASCENDING = "01234567890"
_DESCENDING = "09876543210"


def _day_and_month(day: int, month: int) -> bool:
    return 1 <= day <= 31 and 1 <= month <= 12


def weak_pin(pin: str) -> bool:
    """Patterns and dates. The person most likely to guess this PIN is family,
    who know the birthdays."""
    if len(set(pin)) <= 2 or pin[:3] == pin[3:] or pin in _ASCENDING or pin in _DESCENDING:
        return True
    first, second, third = int(pin[:2]), int(pin[2:4]), int(pin[4:])
    return _day_and_month(first, second) or _day_and_month(second, first) or _day_and_month(third, second)


def _scrypt(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1)


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${salt.hex()}${_scrypt(pin, salt).hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        return hmac.compare_digest(_scrypt(pin, bytes.fromhex(salt)), bytes.fromhex(digest))
    except ValueError:
        return False


def new_access_token() -> str:
    return secrets.token_urlsafe(32)


def hash_access_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
