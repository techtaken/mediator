import threading
from functools import lru_cache

from google import genai
from google.genai import types

from app.config import get_settings

# Agent calls run side by side, so the first two can ask for the client at the
# same moment. Without the lock both would build one, and the copy that isn't
# kept closes its connection while its call is still using it.
_LOCK = threading.Lock()


@lru_cache
def _build_client() -> genai.Client:
    settings = get_settings()
    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(timeout=settings.gemini_timeout_ms),
    )


def get_client() -> genai.Client:
    with _LOCK:
        return _build_client()
