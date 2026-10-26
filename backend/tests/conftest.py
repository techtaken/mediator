import pytest


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
