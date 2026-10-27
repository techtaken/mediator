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
    # Estimated USD price per million tokens, only used for the admin cost
    # estimate. Check current Gemini pricing for the model you run.
    gemini_price_input_per_m: float = 0.10
    gemini_price_output_per_m: float = 0.40
    cors_origins: str = "http://localhost:3000"
    # Comma-separated emails allowed into /api/admin. Empty means no admins.
    admin_emails: str = ""
    frontend_base_url: str = "http://localhost:3000"

    # Abuse protection: in-process limits, per instance. 0 disables a limit.
    rate_limit_enabled: bool = True
    rate_limit_sessions_per_hour: int = 10
    rate_limit_messages_per_minute: int = 12
    rate_limit_writes_per_minute: int = 30
    # An unused invite link stops working after this many days.
    invite_ttl_days: int = 14

    # Data retention. 0 disables the purge.
    retention_days: int = 180
    # Free-text agent reasoning in the audit table is cleared after this many days.
    audit_reason_retention_days: int = 30
    # Shared secret a scheduler sends as X-Job-Token to call /api/jobs/*. Empty
    # means only signed-in admins can run jobs.
    job_token: str = ""

    # Default days until the post-agreement check-in.
    followup_default_days: int = 14
    # Longest a live-update stream stays open before the browser reconnects.
    sse_max_seconds: int = 300

    @property
    def admin_email_set(self) -> set[str]:
        return {email.strip().lower() for email in self.admin_emails.split(",") if email.strip()}

    @property
    def jwks_url(self) -> str:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
