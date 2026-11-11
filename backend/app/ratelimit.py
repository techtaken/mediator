"""Simple in-process rate limits.

Sliding-window counters kept in memory, so each backend instance counts on
its own. That is enough to stop a runaway script or one person hammering the
model; put a shared store (Redis, the database) behind `hit` if the backend
runs on several instances.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException

from app.config import get_settings

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)

SLOW_DOWN = "You're going a little fast. Please wait a moment and try again."


def reset() -> None:
    with _lock:
        _hits.clear()


def hit(key: str, limit: int, window_seconds: float, now: float | None = None) -> None:
    """Count one request for `key`; raise 429 if it is over `limit` per window."""
    if limit <= 0 or not get_settings().rate_limit_enabled:
        return
    now = time.monotonic() if now is None else now
    with _lock:
        bucket = _hits[key]
        while bucket and bucket[0] <= now - window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(bucket[0] + window_seconds - now) + 1)
            raise HTTPException(status_code=429, detail=SLOW_DOWN, headers={"Retry-After": str(retry_after)})
        bucket.append(now)


def limit_session_creation(user_id: str) -> None:
    hit(f"create:{user_id}", get_settings().rate_limit_sessions_per_hour, 3600)


def limit_messages(session_id: str, party: str) -> None:
    hit(f"msg:{session_id}:{party}", get_settings().rate_limit_messages_per_minute, 60)


def limit_writes(session_id: str, party: str) -> None:
    """Shares, ideas, answers, agreements and other writes that may call a model."""
    hit(f"write:{session_id}:{party}", get_settings().rate_limit_writes_per_minute, 60)
