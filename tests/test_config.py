"""Unit tests for application settings."""

from __future__ import annotations

import pytest

from app.core.config import Settings


class TestSettings:
    def test_default_instruments(self) -> None:
        s = Settings()
        assert s.fetch_instruments == ["NQ", "ES", "YM", "RTY"]

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
