import json
from functools import lru_cache
from typing import Any

from google import genai
from google.genai import types

from app.config import get_settings
from app.prompts import INTAKE_TURN, SUMMARY_PROMPT, SYSTEM_INSTRUCTION


@lru_cache
def _client() -> genai.Client:
    settings = get_settings()
    return genai.Client(api_key=settings.gemini_api_key)


def generate_intake_reply(
    *,
    party: str,
    relationship_context: str,
    user_input: str,
) -> str:
    settings = get_settings()
    party_label = "Person A (the one who opened the room)" if party == "user_a" else "Person B (invited)"
    prompt = INTAKE_TURN.format(
        party_label=party_label,
        relationship_context=relationship_context or "Not specified",
        user_input=user_input,
    )
    response = _client().models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.4,
        ),
    )
    text = (response.text or "").strip()
    return text or "I heard you. Say a little more about what you need to feel settled."


def generate_joint_summary(
    *,
    relationship_context: str,
    transcript_a: str,
    transcript_b: str,
) -> dict[str, Any]:
    settings = get_settings()
    prompt = SUMMARY_PROMPT.format(
        relationship_context=relationship_context or "Not specified",
        transcript_a=transcript_a or "(no messages)",
        transcript_b=transcript_b or "(no messages)",
    )
    response = _client().models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.3,
            response_mime_type="application/json",
        ),
    )
    raw = (response.text or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {
            "user_a_perspective": "Both of you want the household to feel fair and respectful.",
            "user_b_perspective": "Both of you want the household to feel fair and respectful.",
            "compromises": [
                "Write a weekly chore split on paper and review it every Sunday for 15 minutes.",
                "Agree visiting hours for relatives so neither person is ambushed.",
                "Use a shared note for money and decisions so nobody is the only messenger.",
            ],
        }
    compromises = data.get("compromises") or []
    if isinstance(compromises, str):
        compromises = [compromises]
    compromises = [str(item).strip() for item in compromises if str(item).strip()][:3]
    while len(compromises) < 2:
        compromises.append("Pause the argument for 24 hours, then talk with a written list of needs, not accusations.")
    return {
        "user_a_perspective": str(data.get("user_a_perspective") or "").strip()
        or "Party A wants to feel heard and fairly treated.",
        "user_b_perspective": str(data.get("user_b_perspective") or "").strip()
        or "Party B wants to feel heard and fairly treated.",
        "compromises": compromises,
    }
