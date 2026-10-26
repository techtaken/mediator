from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable

from google.genai import types
from pydantic import ValidationError

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


def call_agent(role: str, mapping: dict[str, str]) -> JsonDict:
    """Call one agent and return its validated JSON.

    Retries on API errors, unparseable output and schema violations. Raises
    RuntimeError when every attempt fails; callers decide the safe fallback.
    """
    settings = get_settings()
    prompt = fill(ROLE_PROMPTS[role], mapping)
    temperature = TEMPERATURE.get(role, 0.3)
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            time.sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])
        started = time.monotonic()
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
            result = validate_output(role, _extract_json(response.text or ""))
        except (ValueError, json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            logger.warning("agent %s returned bad output (attempt %d): %s", role, attempt + 1, exc)
            continue
        except Exception as exc:  # network / API errors from the SDK
            last_error = exc
            logger.warning("agent %s call failed (attempt %d): %s", role, attempt + 1, exc)
            continue
        logger.info("agent %s ok in %.2fs (attempt %d)", role, time.monotonic() - started, attempt + 1)
        return result
    raise RuntimeError(f"{role} failed after {MAX_ATTEMPTS} attempts") from last_error


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)
