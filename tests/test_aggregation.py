"""Unit tests for Continuous Aggregate refresh logic.

Higher-timeframe rollup itself is owned by TimescaleDB CAs (declared in
db/schema.sql) and is exercised end-to-end in the integration suite.
These unit tests verify the thin Python layer that triggers refreshes.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fetcher.pipeline import (
    CONTINUOUS_AGGREGATE_VIEWS,
    refresh_continuous_aggregates,
    update_all_coverage,
)


class TestContinuousAggregateConstants:
    def test_all_six_higher_timeframes_present(self) -> None:
        """The CA view list must cover every higher timeframe the API exposes."""
        assert set(CONTINUOUS_AGGREGATE_VIEWS) == {
            "kbars_5m", "kbars_15m", "kbars_1h", "kbars_4h", "kbars_1d", "kbars_1w",
        }

    def test_views_are_ordered_shortest_to_longest(self) -> None:
        """Refreshing shortest-first reduces the work TSDB has to do for longer views."""
        assert CONTINUOUS_AGGREGATE_VIEWS == (
            "kbars_5m", "kbars_15m", "kbars_1h", "kbars_4h", "kbars_1d", "kbars_1w",
        )


class TestRefreshContinuousAggregates:
    @pytest.mark.asyncio
    @patch("app.db.session.engine")
    async def test_issues_one_call_per_view(self, mock_engine: MagicMock) -> None:
        """One CALL refresh_continuous_aggregate(...) per view, in order."""
        conn = AsyncMock()
        conn.execution_options = AsyncMock()
        conn.execute = AsyncMock()

        cm = AsyncMock()
        cm.__aenter__.return_value = conn
        cm.__aexit__.return_value = None
        mock_engine.connect.return_value = cm

        await refresh_continuous_aggregates(window=timedelta(days=2))

        assert conn.execute.call_count == len(CONTINUOUS_AGGREGATE_VIEWS)

    @pytest.mark.asyncio
    @patch("app.db.session.engine")
    async def test_runs_in_autocommit_mode(self, mock_engine: MagicMock) -> None:
        """Procedure CALLs cannot run inside a transaction → must be AUTOCOMMIT."""
        conn = AsyncMock()
        conn.execution_options = AsyncMock()
        conn.execute = AsyncMock()

        cm = AsyncMock()
        cm.__aenter__.return_value = conn
        cm.__aexit__.return_value = None
        mock_engine.connect.return_value = cm

        await refresh_continuous_aggregates()

        conn.execution_options.assert_awaited_once_with(isolation_level="AUTOCOMMIT")

    @pytest.mark.asyncio
    @patch("app.db.session.engine")
    async def test_each_call_targets_a_distinct_view(
        self, mock_engine: MagicMock
    ) -> None:
        """The SQL emitted for each call must reference its own view name."""
        conn = AsyncMock()
        conn.execution_options = AsyncMock()
        captured: list[str] = []

        async def capture_execute(stmt, params=None):
            captured.append(str(stmt))
            return MagicMock()

        conn.execute = capture_execute

        cm = AsyncMock()
        cm.__aenter__.return_value = conn
        cm.__aexit__.return_value = None
        mock_engine.connect.return_value = cm

        await refresh_continuous_aggregates()

        for view in CONTINUOUS_AGGREGATE_VIEWS:
            assert any(view in s for s in captured), \
                f"View {view} not referenced in any CALL statement"

    @pytest.mark.asyncio
    @patch("app.db.session.engine")
    async def test_window_is_passed_as_bind_param(self, mock_engine: MagicMock) -> None:
        """start/end timestamps must be parameter-bound, not formatted into SQL."""
        conn = AsyncMock()
        conn.execution_options = AsyncMock()
        captured_params: list[dict] = []

        async def capture(stmt, params=None):
            if params:
                captured_params.append(dict(params))
            return MagicMock()

        conn.execute = capture

        cm = AsyncMock()
        cm.__aenter__.return_value = conn
        cm.__aexit__.return_value = None
        mock_engine.connect.return_value = cm

        await refresh_continuous_aggregates(window=timedelta(days=3))

        assert all("start" in p and "end" in p for p in captured_params)
        # All six calls share the same window.
        starts = {p["start"] for p in captured_params}
        ends = {p["end"] for p in captured_params}
        assert len(starts) == 1
        assert len(ends) == 1


class TestUpdateAllCoverage:
    @pytest.mark.asyncio
    async def test_updates_all_seven_timeframes(self) -> None:
        """update_all_coverage must refresh all 7 timeframes (1m + 6 higher)."""
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()

        await update_all_coverage(session, "YM", fetch_ok=True)

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
