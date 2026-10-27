import os
from pathlib import Path

import pytest

# Settings require these at import. Tests never use real services, so harmless
# placeholders are enough; real keys in the environment or backend/.env are
# left alone for the live tests.
DUMMY_GEMINI_KEY = "test-dummy-gemini-key"
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
_env_text = _ENV_FILE.read_text() if _ENV_FILE.exists() else ""
for _name, _value in (
    ("SUPABASE_URL", "https://test-project.supabase.co"),
    ("SUPABASE_SECRET_KEY", "test-dummy-secret"),
    ("GEMINI_API_KEY", DUMMY_GEMINI_KEY),
):
    # An environment variable would override backend/.env, so only fill gaps.
    if _name not in os.environ and f"{_name}=" not in _env_text:
        os.environ[_name] = _value


def has_real_gemini_key() -> bool:
    """True only for a real key from the environment or backend/.env."""
    from app.config import get_settings

    try:
        key = get_settings().gemini_api_key
    except Exception:
        return False
    return bool(key) and key != DUMMY_GEMINI_KEY


@pytest.fixture(autouse=True)
def _no_real_supabase(monkeypatch):
    """Fail loudly if a test reaches the real database.

    Modules import get_supabase by name, so each test patches those names with
    an in-memory fake. Any module a test forgets to patch ends up here instead
    of using the real project and secret key from backend/.env.
    """

    def refuse(*_args, **_kwargs):
        raise RuntimeError("Tests must not connect to Supabase: patch get_supabase in the module under test.")

    monkeypatch.setattr("app.db.create_client", refuse)


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    from app import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()
