"""Unit tests for higher timeframe aggregation logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from fetcher.pipeline import (
    _TIMEFRAME_BUCKETS,
    aggregate_higher_timeframes,
    update_all_coverage,
)


class TestAggregateHigherTimeframes:
    @pytest.mark.asyncio
    async def test_runs_once_per_timeframe(self) -> None:
        """aggregate_higher_timeframes should execute one SQL per timeframe."""
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()

        await aggregate_higher_timeframes(session, "NQ")

        # 6 timeframes → 6 execute + 6 commit calls
        assert session.execute.call_count == len(_TIMEFRAME_BUCKETS)
        assert session.commit.call_count == len(_TIMEFRAME_BUCKETS)

    @pytest.mark.asyncio
    async def test_all_six_timeframes_covered(self) -> None:
        """All six higher timeframes must be included."""
        assert set(_TIMEFRAME_BUCKETS.keys()) == {"5m", "15m", "1h", "4h", "1d", "1w"}

    @pytest.mark.asyncio
    async def test_sql_contains_correct_table_names(self) -> None:
        """Each SQL statement must target the correct table."""
        session = AsyncMock()
        captured_stmts: list[str] = []

        async def capture_execute(stmt, *args, **kwargs):
            captured_stmts.append(str(stmt))
            return MagicMock()

        session.execute = capture_execute
        session.commit = AsyncMock()

        await aggregate_higher_timeframes(session, "ES")

        for _tf, (table, _) in _TIMEFRAME_BUCKETS.items():
            assert any(table in s for s in captured_stmts), \
                f"Table {table} not found in any SQL statement"

    @pytest.mark.asyncio
    async def test_instrument_passed_to_all_queries(self) -> None:
        """The instrument parameter must appear in every query's bind params."""
        session = AsyncMock()
        captured_params: list[dict] = []

        async def capture(stmt, params=None, *args, **kwargs):
            if params:
                captured_params.append(params)
            return MagicMock()

        session.execute = capture
        session.commit = AsyncMock()

        await aggregate_higher_timeframes(session, "RTY")

        assert all(p.get("instrument") == "RTY" for p in captured_params)


class TestUpdateAllCoverage:
    @pytest.mark.asyncio
    async def test_updates_all_seven_timeframes(self) -> None:
        """update_all_coverage must refresh all 7 timeframes."""
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()

        await update_all_coverage(session, "YM", fetch_ok=True)

        # 7 timeframes (1m + 6 higher)
        assert session.execute.call_count == 7

    @pytest.mark.asyncio
    async def test_fetch_ok_false_propagates(self) -> None:
        """fetch_ok=False must be passed to all coverage updates."""
        session = AsyncMock()
        captured: list[dict] = []

        async def capture(stmt, params=None, *args, **kwargs):
            if params:
                captured.append(dict(params))
            return MagicMock()

        session.execute = capture
        session.commit = AsyncMock()

        await update_all_coverage(session, "NQ", fetch_ok=False)

        assert all(not p.get("fetch_ok") for p in captured if "fetch_ok" in p)
