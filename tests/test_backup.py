"""Unit tests for the R2 backup module (ADR-006)."""

from __future__ import annotations

import csv
import gzip
import io
from datetime import date

import pytest

from fetcher.backup import _gzip_csv, _months_between, run_backup


class TestMonthPartitioning:
    def test_single_month(self) -> None:
        assert _months_between(date(2026, 7, 20), date(2026, 7, 31)) == [(2026, 7)]

    def test_spans_year_boundary(self) -> None:
        assert _months_between(date(2026, 11, 5), date(2027, 2, 1)) == [
            (2026, 11), (2026, 12), (2027, 1), (2027, 2),
        ]

    def test_same_day(self) -> None:
        assert _months_between(date(2026, 7, 20), date(2026, 7, 20)) == [(2026, 7)]


class TestCsvSerialisation:
    def test_roundtrip(self) -> None:
        blob = _gzip_csv(["a", "b"], [(1, "x"), (2, "y")])
        text = gzip.decompress(blob).decode()
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[0] == ["a", "b"]
        assert rows[1] == ["1", "x"]
        assert rows[2] == ["2", "y"]

    def test_empty_rows_still_writes_header(self) -> None:
        text = gzip.decompress(_gzip_csv(["a"], [])).decode()
        assert text.strip() == "a"


class TestConfigurationGate:
    @pytest.mark.asyncio
    async def test_unconfigured_r2_is_a_no_op(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Missing credentials must skip quietly — an unconfigured backup
        # may never break the daily fetch that calls it.
        from app.core.config import Settings, get_settings

        get_settings.cache_clear()
        monkeypatch.setattr(
            "fetcher.backup.get_settings",
            lambda: Settings(r2_bucket="", r2_access_key_id=""),
        )
        assert await run_backup() == {}
