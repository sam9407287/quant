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

    @pytest.mark.asyncio
    @patch("app.db.session.engine")
    async def test_default_window_covers_at_least_one_weekly_bucket(
        self, mock_engine: MagicMock
    ) -> None:
        """The default window must be ≥ 14 days so kbars_1w always has a full bucket.

        TimescaleDB rejects refreshes whose window doesn't cover at least one
        complete bucket of the CA's bucket size. For weekly buckets that means
        the window must span at least one full Monday–Sunday — only ≥ 14 days
        guarantees that regardless of when the refresh runs.
        """
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

        await refresh_continuous_aggregates()

        params = captured_params[0]
        actual_window = params["end"] - params["start"]
        assert actual_window >= timedelta(days=14)

    @pytest.mark.asyncio
    @patch("app.db.session.engine")
    async def test_single_view_failure_does_not_halt_loop(
        self, mock_engine: MagicMock
    ) -> None:
        """If one view's refresh raises, the remaining views must still run.

        Without per-view error handling, a single misaligned bucket (typically
        kbars_1w) would block every later view in the tuple from refreshing,
        leaving the API serving stale data until the next background policy run.
        """
        conn = AsyncMock()
        conn.execution_options = AsyncMock()
        attempted: list[str] = []

        async def execute_with_one_failure(stmt, params=None):
            sql = str(stmt)
            for v in CONTINUOUS_AGGREGATE_VIEWS:
                if v in sql:
                    attempted.append(v)
                    if v == "kbars_15m":
                        raise RuntimeError("simulated bucket alignment error")
            return MagicMock()

        conn.execute = execute_with_one_failure

        cm = AsyncMock()
        cm.__aenter__.return_value = conn
        cm.__aexit__.return_value = None
        mock_engine.connect.return_value = cm

        # Must not raise — the function swallows per-view failures.
        await refresh_continuous_aggregates()

        # All six views were attempted, including ones after the failing one.
        assert attempted == list(CONTINUOUS_AGGREGATE_VIEWS)


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
