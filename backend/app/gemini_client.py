from functools import lru_cache

from google import genai
from google.genai import types

from app.config import get_settings


@lru_cache
def get_client() -> genai.Client:
    settings = get_settings()
    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(timeout=settings.gemini_timeout_ms),
    )
