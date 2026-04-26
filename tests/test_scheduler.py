"""Unit tests for the scheduler and bootstrap script helpers."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from fetcher.scheduler import run_daily_fetch


class TestRunDailyFetch:
    @pytest.mark.asyncio
    async def test_calls_fetch_for_each_instrument(self) -> None:
        """run_daily_fetch should call the data source once per instrument."""
        with (
            patch("fetcher.scheduler._source") as mock_source,
            patch("fetcher.scheduler.AsyncSessionLocal") as mock_session_cls,
            patch("fetcher.scheduler.validate") as mock_validate,
            patch("fetcher.scheduler.flag_anomalies") as mock_flag,
            patch("fetcher.scheduler.upsert_bars", new_callable=AsyncMock) as mock_upsert,
            patch("fetcher.scheduler.update_coverage", new_callable=AsyncMock),
        ):
            # Build a tiny valid DataFrame
            df = pd.DataFrame({
                "ts": pd.to_datetime(["2024-01-01 09:00"], utc=True),
                "open": [18000.0], "high": [18050.0],
                "low": [17950.0], "close": [18020.0], "volume": [1000],
            })
            mock_source.fetch.return_value = df
            mock_source.source_name = "yfinance"
            mock_validate.return_value = df
            mock_flag.return_value = df
            mock_upsert.return_value = (1, 0)

            # Mock async context manager for session
            session_mock = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=session_mock)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            summary = await run_daily_fetch(instruments=["NQ", "ES"])

        assert set(summary.keys()) == {"NQ", "ES"}
        assert mock_source.fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_source_exception_gracefully(self) -> None:
        """A failed fetch for one instrument should not crash the whole job."""
        with (
            patch("fetcher.scheduler._source") as mock_source,
            patch("fetcher.scheduler.AsyncSessionLocal") as mock_session_cls,
            patch("fetcher.scheduler.update_coverage", new_callable=AsyncMock),
        ):
            mock_source.fetch.side_effect = RuntimeError("network failure")
            mock_source.source_name = "yfinance"

            session_mock = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=session_mock)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            summary = await run_daily_fetch(instruments=["NQ"])

        assert summary["NQ"]["inserted"] == 0

    @pytest.mark.asyncio
    async def test_summary_contains_correct_counts(self) -> None:
        with (
            patch("fetcher.scheduler._source") as mock_source,
            patch("fetcher.scheduler.AsyncSessionLocal") as mock_session_cls,
            patch("fetcher.scheduler.validate") as mock_validate,
            patch("fetcher.scheduler.flag_anomalies") as mock_flag,
            patch("fetcher.scheduler.upsert_bars", new_callable=AsyncMock) as mock_upsert,
            patch("fetcher.scheduler.update_coverage", new_callable=AsyncMock),
        ):
            df = pd.DataFrame({
                "ts": pd.to_datetime(["2024-01-01 09:00", "2024-01-01 09:01"], utc=True),
                "open": [18000.0, 18010.0], "high": [18050.0, 18060.0],
                "low": [17950.0, 17960.0], "close": [18020.0, 18030.0],
                "volume": [1000, 1100],
            })
            mock_source.fetch.return_value = df
            mock_source.source_name = "yfinance"
            mock_validate.return_value = df
            mock_flag.return_value = df
            mock_upsert.return_value = (2, 0)

            session_mock = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=session_mock)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            summary = await run_daily_fetch(instruments=["NQ"])

        assert summary["NQ"]["fetched"] == 2
        assert summary["NQ"]["inserted"] == 2
        assert summary["NQ"]["skipped"] == 0


class TestBootstrapCSV:
    def test_find_csv_matches_pattern(self, tmp_path: Path) -> None:
        """find_csv should locate a file matching the instrument's pattern."""
        from scripts.bootstrap_csv import find_csv

        csv_file = tmp_path / "NQ_continuous_ratio_adjusted.csv"
        csv_file.touch()

        result = find_csv(tmp_path, "NQ")
        assert result == csv_file

    def test_find_csv_returns_none_when_missing(self, tmp_path: Path) -> None:
        from scripts.bootstrap_csv import find_csv

        assert find_csv(tmp_path, "NQ") is None

    def test_load_firstrate_csv_converts_to_utc(self, tmp_path: Path) -> None:
        """Timestamps in ET should be stored as UTC after loading."""
        from scripts.bootstrap_csv import load_firstrate_csv

        csv_content = (
            "DateTime,Open,High,Low,Close,Volume\n"
            "2024-01-02 09:30:00,18000,18100,17900,18050,1000\n"
            "2024-01-02 09:31:00,18050,18150,17950,18100,1100\n"
        )
        csv_path = tmp_path / "NQ_test.csv"
        csv_path.write_text(csv_content)

        df = load_firstrate_csv(csv_path, "NQ")
        assert len(df) == 2
        assert str(df["ts"].dt.tz) == "UTC"
        # 09:30 ET = 14:30 UTC in winter
        assert df["ts"].iloc[0].hour == 14

    def test_load_firstrate_csv_drops_zero_volume(self, tmp_path: Path) -> None:
        from scripts.bootstrap_csv import load_firstrate_csv

        csv_content = (
            "DateTime,Open,High,Low,Close,Volume\n"
            "2024-01-02 09:30:00,18000,18100,17900,18050,0\n"
            "2024-01-02 09:31:00,18050,18150,17950,18100,1100\n"
        )
        csv_path = tmp_path / "NQ_test.csv"
        csv_path.write_text(csv_content)

        df = load_firstrate_csv(csv_path, "NQ")
        assert len(df) == 1
