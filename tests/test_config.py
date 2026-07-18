"""Unit tests for application settings."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.instruments import ALL_SYMBOLS


class TestSettings:
    def test_default_instruments(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pinned to the registry, not a hand-written list, so adding an
        # instrument (one registry entry + one Settings default entry)
        # cannot silently leave this test stale again. Isolated from the
        # ambient environment: a developer's .env / FETCH_INSTRUMENTS
        # override must not change what "default" means.
        monkeypatch.delenv("FETCH_INSTRUMENTS", raising=False)
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.fetch_instruments == list(ALL_SYMBOLS)

    def test_instruments_from_comma_string(self) -> None:
        s = Settings(fetch_instruments="NQ,ES")  # type: ignore[arg-type]
        assert s.fetch_instruments == ["NQ", "ES"]

    def test_instruments_uppercased(self) -> None:
        s = Settings(fetch_instruments="nq,es")  # type: ignore[arg-type]
        assert s.fetch_instruments == ["NQ", "ES"]

    def test_cors_origins_from_string(self) -> None:
        s = Settings(cors_origins="http://localhost:3000,http://localhost:5173")  # type: ignore[arg-type]
        assert len(s.cors_origins) == 2

    def test_overlap_days_default(self) -> None:
        s = Settings()
        assert s.fetch_overlap_days == 7
