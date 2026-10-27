from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable

from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError

from app.agents import telemetry
from app.agents.constitution import CONSTITUTION
from app.agents.prompts import ROLE_PROMPTS, TEMPERATURE, fill
from app.agents.schemas import validate_output
from app.config import get_settings
from app.gemini_client import get_client

logger = logging.getLogger(__name__)

JsonDict = dict[str, Any]
AgentCaller = Callable[[str, dict[str, str]], JsonDict]

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (0.5, 1.5)


def _extract_json(raw: str) -> JsonDict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        data = json.loads(match.group(0))
        if isinstance(data, dict):
            return data
    raise ValueError("Model did not return JSON")


class QuotaExceeded(RuntimeError):
    """Gemini returned 429 RESOURCE_EXHAUSTED. Not retried: it won't clear in seconds."""


def _error_kind(exc: Exception) -> tuple[str, bool]:
    """Classify an SDK error as (kind, retryable).

    Quota (429) and other client errors fail fast; server errors (5xx),
    timeouts and network errors are retried.
    """
    if isinstance(exc, genai_errors.APIError):
        code = int(getattr(exc, "code", 0) or 0)
        if code == 429 or "RESOURCE_EXHAUSTED" in str(exc):
            return "quota", False
        if code >= 500:
            return f"server_{code}", True
        if code == 408:
            return "timeout", True
        return f"client_{code}", False
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "timeout", True
    return "network", True


def call_agent(role: str, mapping: dict[str, str]) -> JsonDict:
    """Call one agent and return its validated JSON.

    Retries on server errors, timeouts, unparseable output and schema
    violations. A quota error (429) fails at once with QuotaExceeded. Raises
    RuntimeError when every attempt fails; callers decide the safe fallback.
    Each call is logged and recorded (see telemetry.py) with its latency,
    attempts and token usage.
    """
    settings = get_settings()
    prompt = fill(ROLE_PROMPTS[role], mapping)
    temperature = TEMPERATURE.get(role, 0.3)
    last_error: Exception | None = None
    kind = "unknown"
    started = time.monotonic()
    tokens = [0, 0, 0]
    seen_usage = False
    attempts = 0

    def finish(ok: bool, error: str | None = None) -> None:
        telemetry.record(
            telemetry.CallRecord(
                role=role,
                ok=ok,
                attempts=attempts,
                latency_ms=int((time.monotonic() - started) * 1000),
                model=settings.gemini_model,
                prompt_tokens=tokens[0] if seen_usage else None,
                output_tokens=tokens[1] if seen_usage else None,
                total_tokens=tokens[2] if seen_usage else None,
                error=error,
            )
        )

    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            time.sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])
        attempts = attempt + 1
        try:
            response = get_client().models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=CONSTITUTION,
                    temperature=temperature,
                    response_mime_type="application/json",
                ),
            )
        except Exception as exc:  # network / API errors from the SDK
            last_error = exc
            kind, retryable = _error_kind(exc)
            logger.warning("agent %s call failed (attempt %d, %s): %s", role, attempts, kind, exc)
            if not retryable:
                finish(False, kind)
                if kind == "quota":
                    raise QuotaExceeded(f"{role}: Gemini quota exhausted") from exc
                raise RuntimeError(f"{role} failed: {kind}") from exc
            continue
        usage = telemetry.usage_from(response)
        if any(value is not None for value in usage):
            seen_usage = True
            for index, value in enumerate(usage):
                tokens[index] += value or 0
        try:
            result = validate_output(role, _extract_json(response.text or ""))
        except (ValueError, json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            kind = "bad_output"
            logger.warning("agent %s returned bad output (attempt %d): %s", role, attempts, exc)
            continue
        finish(True)
        return result
    finish(False, kind)
    raise RuntimeError(f"{role} failed after {MAX_ATTEMPTS} attempts") from last_error


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)
