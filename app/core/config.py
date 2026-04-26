"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Fetcher
    fetch_instruments: list[str] = ["NQ", "ES", "YM", "RTY"]
    fetch_overlap_days: int = 7
    fetch_cron: str = "0 18 * * 1-5"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000"]

    # Security
    api_secret_key: str = "changeme"

    # Notifications (optional — leave empty to disable)
    notify_webhook_url: str = ""

    @field_validator("fetch_instruments", mode="before")
    @classmethod
    def split_instruments(cls, v: str | list[str]) -> list[str]:
        """Accept comma-separated string or a list."""
        if isinstance(v, str):
            return [s.strip().upper() for s in v.split(",") if s.strip()]
        return [s.upper() for s in v]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, v: str | list[str]) -> list[str]:
        """Accept comma-separated string or a list."""
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return list(v)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()
