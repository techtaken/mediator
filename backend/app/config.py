from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        extra="ignore",
    )

    supabase_url: str
    supabase_secret_key: str
    supabase_publishable_key: str | None = None
    supabase_jwks_url: str | None = None
    gemini_api_key: str
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_ms: int = 30000
    cors_origins: str = "http://localhost:3000"
    frontend_base_url: str = "http://localhost:3000"

    @property
    def jwks_url(self) -> str:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
