"""Per-call observability for agent calls.

Every call_agent logs one structured line (role, latency, attempts, tokens).
Inside `track_calls(session_id)` the records are also collected and written to
the agent_calls table when the block ends, so the admin page can show calls,
tokens and an estimated cost per session. Writing stats is best-effort: a
failure is logged and never fails the person's request.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any, Iterator

from app.db import get_supabase

logger = logging.getLogger("mediator.agent_calls")


@dataclass
class CallRecord:
    role: str
    ok: bool
    attempts: int
    latency_ms: int
    model: str = ""
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    # Short machine-readable kind only (e.g. "quota", "timeout", "bad_output"),
    # never the model's text or the prompt.
    error: str | None = None


_records: ContextVar[list[CallRecord] | None] = ContextVar("agent_call_records", default=None)


def usage_from(response: Any) -> tuple[int | None, int | None, int | None]:
    """Token counts from a Gemini response's usage_metadata, if it has any."""
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return None, None, None

    def count(name: str) -> int | None:
        value = getattr(usage, name, None)
        return int(value) if isinstance(value, (int, float)) else None

    prompt = count("prompt_token_count")
    output = count("candidates_token_count")
    thoughts = count("thoughts_token_count")
    if output is not None and thoughts:
        output += thoughts  # thinking tokens are billed as output
    total = count("total_token_count")
    return prompt, output, total


def record(entry: CallRecord) -> None:
    logger.info("agent_call %s", json.dumps(asdict(entry)))
    bucket = _records.get()
    if bucket is not None:
        bucket.append(entry)


@contextmanager
def track_calls(session_id: str) -> Iterator[list[CallRecord]]:
    bucket: list[CallRecord] = []
    token = _records.set(bucket)
    try:
        yield bucket
    finally:
        _records.reset(token)
        flush(session_id, bucket)


@contextmanager
def collect_calls() -> Iterator[list[CallRecord]]:
    """Collect call records without storing them (used by the eval runner)."""
    bucket: list[CallRecord] = []
    token = _records.set(bucket)
    try:
        yield bucket
    finally:
        _records.reset(token)


def flush(session_id: str, entries: list[CallRecord]) -> None:
    if not entries:
        return
    rows = [{"session_id": session_id, **asdict(entry)} for entry in entries]
    try:
        get_supabase().table("agent_calls").insert(rows).execute()
    except Exception:
        logger.exception("could not store %d agent call stats for %s", len(rows), session_id)


def summarize(rows: list[dict[str, Any]], price_in_per_m: float, price_out_per_m: float) -> dict[str, Any]:
    """Totals for the admin page. Cost is an estimate from configured prices."""
    by_role: dict[str, dict[str, Any]] = {}
    totals = {"calls": 0, "failed": 0, "attempts": 0, "prompt_tokens": 0, "output_tokens": 0, "latency_ms": 0}
    for row in rows:
        role = str(row.get("role") or "?")
        entry = by_role.setdefault(role, {"calls": 0, "failed": 0, "prompt_tokens": 0, "output_tokens": 0, "latency_ms": 0})
        for target in (totals, entry):
            target["calls"] += 1
            target["failed"] += 0 if row.get("ok") else 1
            target["prompt_tokens"] += int(row.get("prompt_tokens") or 0)
            target["output_tokens"] += int(row.get("output_tokens") or 0)
            target["latency_ms"] += int(row.get("latency_ms") or 0)
        totals["attempts"] += int(row.get("attempts") or 0)
    cost = totals["prompt_tokens"] / 1e6 * price_in_per_m + totals["output_tokens"] / 1e6 * price_out_per_m
    return {
        **totals,
        "avg_latency_ms": round(totals["latency_ms"] / totals["calls"]) if totals["calls"] else 0,
        "estimated_cost_usd": round(cost, 6),
        "price_per_m": {"input": price_in_per_m, "output": price_out_per_m},
        "by_role": dict(sorted(by_role.items())),
    }
