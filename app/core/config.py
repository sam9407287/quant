"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.instruments import ALL_SYMBOLS as _ALL_SYMBOLS


def _parse_list_str(raw: str) -> list[str]:
    """Parse a list from an env-var string in either JSON or CSV form.

    JSON form    : '["NQ","ES","YM","RTY"]'  (Railway dashboard default)
    CSV form     : 'NQ,ES,YM,RTY'             (more readable in .env files)
    Whitespace and empty entries are stripped from both forms.
    """
    s = raw.strip()
    if s.startswith("[") and s.endswith("]"):
        import json
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    return [item.strip() for item in s.split(",") if item.strip()]


class Settings(BaseSettings):
    """Central configuration validated at startup via Pydantic."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = (
        "postgresql+asyncpg://dev:dev@localhost:5432/quant_futures"
    )

    # Fetcher.
    # NoDecode tells pydantic-settings to skip its built-in JSON decoder for
    # complex types — without it the comma-separated env-file form (used by
    # local .env) would be rejected before our validator runs. Railway sets
    # the same vars as JSON arrays; both shapes are normalised below.
    # Default = every registry symbol; narrow via FETCH_INSTRUMENTS env.
    fetch_instruments: Annotated[list[str], NoDecode] = list(_ALL_SYMBOLS)
    fetch_overlap_days: int = 7
    fetch_cron: str = "0 0 * * 1-5"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    # "production" hides the interactive docs / OpenAPI schema and is the
    # signal for any prod-only hardening. Set ENVIRONMENT=production on
    # the Railway api service.
    environment: str = "development"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    # Security
    api_secret_key: str = "changeme"
    # Google Sign-In: the OAuth Web client ID the frontend obtains ID
    # tokens for. Empty string = auth endpoints answer 503 (unconfigured).
    google_oauth_client_id: str = ""
    # Emails granted the admin role on sign-in (see-everything access).
    admin_emails: Annotated[list[str], NoDecode] = ["sam9407287@gmail.com"]
    # Shared secret letting an automated client authenticate as a dedicated
    # account, for end-to-end testing of the signed-in surface. Empty — the
    # default — means the code path does not exist and Google is the only
    # way in. Unsetting the variable revokes it; nothing else to undo.
    #
    # The account it maps to is an ORDINARY user, not an admin: everything
    # worth testing (strategies, backtests, signal tests) works without
    # admin, and a leaked secret then buys a sandbox rather than read/write
    # over everyone's data. Add SERVICE_TOKEN_EMAIL to ADMIN_EMAILS if you
    # ever deliberately want more.
    service_token: str = ""
    service_token_email: str = "service-bot@quant.local"

    # Notifications (optional — leave empty to disable)
    notify_webhook_url: str = ""
    # Resend API key for sharing emails. Empty = in-app notification only;
    # the send is logged and skipped rather than failing the request.
    resend_api_key: str = ""
    # Verified sender, e.g. "quant.futures <noreply@yourdomain.com>".
    notify_from_email: str = ""
    # Absolute base used to build links inside those emails.
    frontend_base_url: str = "https://frontend-production-d637.up.railway.app"

    # Off-site backup to Cloudflare R2 (ADR-006). Empty credentials
    # disable the backup job rather than failing the fetcher.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    # Bars before this date come from the purchased vendor history and
    # are re-loadable from those CSVs; bars from this date on are
    # crawler-accumulated and unrecoverable, so they are what we back up.
    backup_since: str = "2026-07-20"

    @field_validator("fetch_instruments", mode="before")
    @classmethod
    def split_instruments(cls, v: str | list[str]) -> list[str]:
        """Accept comma-separated string, JSON array string, or a list."""
        if isinstance(v, str):
            return [s.upper() for s in _parse_list_str(v)]
        return [s.upper() for s in v]

    @field_validator("cors_origins", "admin_emails", mode="before")
    @classmethod
    def split_origins(cls, v: str | list[str]) -> list[str]:
        """Accept comma-separated string, JSON array string, or a list."""
        if isinstance(v, str):
            return _parse_list_str(v)
        return list(v)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()
