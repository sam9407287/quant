"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    fetch_instruments: Annotated[list[str], NoDecode] = [
        "NQ", "ES", "YM", "RTY",   # equity indices
        "GC", "SI", "HG",           # metals
        "CL", "NG",                 # energy
    ]
    fetch_overlap_days: int = 7
    fetch_cron: str = "0 0 * * 1-5"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # Security
    api_secret_key: str = "changeme"

    # Notifications (optional — leave empty to disable)
    notify_webhook_url: str = ""

    @field_validator("fetch_instruments", mode="before")
    @classmethod
    def split_instruments(cls, v: str | list[str]) -> list[str]:
        """Accept comma-separated string, JSON array string, or a list."""
        if isinstance(v, str):
            return [s.upper() for s in _parse_list_str(v)]
        return [s.upper() for s in v]

    @field_validator("cors_origins", mode="before")
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
