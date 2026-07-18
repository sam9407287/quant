"""Integration tests: real PostgreSQL+TimescaleDB database required.

These tests verify the full data pipeline end-to-end, against a live
TimescaleDB instance:

    1m bars → upsert → CA refresh → coverage → API query

Run with:
    DATABASE_URL=postgresql+asyncpg://test:test@localhost:5433/quant_futures_test \
    pytest tests/test_integration.py -v -m integration
"""

from __future__ import annotations

import contextlib
import os
import re
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fetcher.pipeline import (
    CONTINUOUS_AGGREGATE_VIEWS,
    refresh_continuous_aggregates,
    update_all_coverage,
    upsert_bars,
    validate,
)

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_bars(_instrument: str, n: int = 10) -> pd.DataFrame:
    """Build a synthetic 1m OHLCV DataFrame starting from a fixed timestamp."""
    base = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
    return pd.DataFrame(
        {
            "ts": pd.to_datetime(
                [base + timedelta(minutes=i) for i in range(n)], utc=True
            ),
            "open":   [18000.0 + i for i in range(n)],
            "high":   [18050.0 + i for i in range(n)],
            "low":    [17950.0 + i for i in range(n)],
            "close":  [18020.0 + i for i in range(n)],
            "volume": [1000 + i * 10 for i in range(n)],
        }
    )


def _skip_if_no_db() -> None:
    url = os.environ.get("DATABASE_URL", "")
    looks_like_test = any(
        marker in url for marker in ("test", "localhost", "127.0.0.1")
    )
    if not url or not looks_like_test:
        pytest.skip("Requires DATABASE_URL pointing to a test database")


def _split_sql(raw: str) -> list[str]:
    """Split a multi-statement SQL string on bare semicolons.

    Strips comment lines and empty fragments. Doesn't try to handle dollar-
    quoted strings (the schema doesn't use any) — keep this dumb on purpose.
    """
    # Strip line comments first
    cleaned = "\n".join(
        line for line in raw.splitlines() if not line.strip().startswith("--")
    )
    parts = re.split(r";\s*\n", cleaned)
    return [p.strip() for p in parts if p.strip()]


async def _apply_schema(engine) -> None:
    """Apply db/schema.sql idempotently with AUTOCOMMIT semantics.

    AUTOCOMMIT is required because TimescaleDB helpers like
    `add_compression_policy` and `add_continuous_aggregate_policy` cannot
    run inside an explicit transaction.
    """
    schema_path = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")
    with open(schema_path) as f:
        raw = f.read()

    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for stmt in _split_sql(raw):
            with contextlib.suppress(Exception):
                await conn.execute(text(stmt))


async def _truncate_test_state(engine) -> None:
    """Wipe per-test state so each test starts from a clean slate.

    Truncates the kbars_1m hypertable, deletes data from every CA view
    (TimescaleDB allows DML on CAs since 2.7), and clears
    coverage / roll_calendar so tests don't interfere with each other.
    """
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("TRUNCATE kbars_1m"))
        for view in CONTINUOUS_AGGREGATE_VIEWS:
            with contextlib.suppress(Exception):
                await conn.execute(text(f"DELETE FROM {view}"))  # noqa: S608
        await conn.execute(
            text("UPDATE data_coverage SET earliest_ts=NULL, latest_ts=NULL, "
                 "bar_count=0, last_fetch_ts=NULL")
        )
        # backtest_trades cascades from backtest_runs.
        with contextlib.suppress(Exception):
            await conn.execute(text("TRUNCATE backtest_runs CASCADE"))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    """Provide both an engine and a clean session bound to it.

    Returning the engine alongside the session lets tests pass it explicitly
    to `refresh_continuous_aggregates`, which avoids the "Future attached to
    a different loop" error caused by reusing the module-level engine that
    was created on a different event loop.
    """
    _skip_if_no_db()
    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url, echo=False)

    await _apply_schema(engine)
    await _truncate_test_state(engine)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield engine, s

    await engine.dispose()


@pytest_asyncio.fixture
async def session(db):
    """Backwards-compatible alias for tests that only need the session."""
    _engine, s = db
    yield s


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline integration tests
# ─────────────────────────────────────────────────────────────────────────────

class TestUpsertBars:
    @pytest.mark.asyncio
    async def test_inserts_new_bars(self, session: AsyncSession) -> None:
        df = validate(_make_bars("NQ", n=5))
        inserted, skipped = await upsert_bars(session, df, "NQ", "test")

        result = await session.execute(
            text("SELECT COUNT(*) FROM kbars_1m WHERE instrument = 'NQ'")
        )
        count = result.scalar()
        assert count == 5
        assert inserted == 5
        assert skipped == 0

    @pytest.mark.asyncio
    async def test_deduplicates_on_second_upsert(self, session: AsyncSession) -> None:
        df = validate(_make_bars("ES", n=5))
        await upsert_bars(session, df, "ES", "test")
        inserted2, skipped2 = await upsert_bars(session, df, "ES", "test")

        assert inserted2 == 0
        assert skipped2 == 5

    @pytest.mark.asyncio
    async def test_empty_dataframe_returns_zeros(self, session: AsyncSession) -> None:
        empty = validate(_make_bars("YM", n=0).iloc[0:0])
        inserted, skipped = await upsert_bars(session, empty, "YM", "test")
        assert inserted == 0
        assert skipped == 0


class TestContinuousAggregates:
    """Verify TimescaleDB Continuous Aggregates produce correct rollups.

    The window passed to refresh_continuous_aggregates must cover the
    synthetic 2024-01-02 timestamps used by `_make_bars`, so we use a
    wide window here.
    """

    _WIDE_WINDOW = timedelta(days=365 * 5)

    @pytest.mark.asyncio
    async def test_5m_aggregation_produces_correct_buckets(self, db) -> None:
        engine, session = db
        # 10 x 1m bars at minutes 0-9 → 2 x 5m buckets ([0,5) and [5,10))
        df = validate(_make_bars("NQ", n=10))
        await upsert_bars(session, df, "NQ", "test")
        await refresh_continuous_aggregates(window=self._WIDE_WINDOW, engine=engine)

        result = await session.execute(
            text("SELECT COUNT(*) FROM kbars_5m WHERE instrument = 'NQ'")
        )
        count = result.scalar()
        assert count == 2

    @pytest.mark.asyncio
    async def test_1h_aggregation_produces_single_bar(self, db) -> None:
        engine, session = db
        # 10 x 1m bars all within a single hour → 1 x 1h bar
        df = validate(_make_bars("ES", n=10))
        await upsert_bars(session, df, "ES", "test")
        await refresh_continuous_aggregates(window=self._WIDE_WINDOW, engine=engine)

        result = await session.execute(
            text("SELECT COUNT(*) FROM kbars_1h WHERE instrument = 'ES'")
        )
        count = result.scalar()
        assert count == 1

    @pytest.mark.asyncio
    async def test_aggregated_high_is_max_of_1m_highs(self, db) -> None:
        engine, session = db
        df = validate(_make_bars("NQ", n=5))
        expected_high = float(df["high"].max())
        await upsert_bars(session, df, "NQ", "test")
        await refresh_continuous_aggregates(window=self._WIDE_WINDOW, engine=engine)

        result = await session.execute(
            text("SELECT high FROM kbars_1h WHERE instrument = 'NQ' LIMIT 1")
        )
        actual_high = float(result.scalar())
        assert actual_high == expected_high

    @pytest.mark.asyncio
    async def test_rerun_refresh_is_idempotent(self, db) -> None:
        engine, session = db
        df = validate(_make_bars("YM", n=10))
        await upsert_bars(session, df, "YM", "test")
        await refresh_continuous_aggregates(window=self._WIDE_WINDOW, engine=engine)
        await refresh_continuous_aggregates(window=self._WIDE_WINDOW, engine=engine)

        result = await session.execute(
            text("SELECT COUNT(*) FROM kbars_5m WHERE instrument = 'YM'")
        )
        assert result.scalar() == 2  # same count, not doubled


class TestCoverageUpdate:
    @pytest.mark.asyncio
    async def test_coverage_reflects_inserted_bars(
        self, session: AsyncSession
    ) -> None:
        df = validate(_make_bars("RTY", n=5))
        await upsert_bars(session, df, "RTY", "test")
        await update_all_coverage(session, "RTY", fetch_ok=True)

        result = await session.execute(
            text(
                "SELECT bar_count, last_fetch_ok FROM data_coverage "
                "WHERE instrument = 'RTY' AND timeframe = '1m'"
            )
        )
        row = result.fetchone()
        assert row is not None
        assert row.bar_count == 5
        assert row.last_fetch_ok is True


# ─────────────────────────────────────────────────────────────────────────────
# API integration tests
# ─────────────────────────────────────────────────────────────────────────────

class TestKbarsAPI:
    @pytest.mark.asyncio
    async def test_kbars_endpoint_returns_inserted_data(
        self, session: AsyncSession
    ) -> None:
        from app.db.session import get_db
        from app.main import app

        df = validate(_make_bars("NQ", n=5))
        await upsert_bars(session, df, "NQ", "test")

        app.dependency_overrides[get_db] = lambda: session

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/kbars",
                params={
                    "instrument": "NQ",
                    "timeframe": "1m",
                    "start": "2024-01-02T00:00:00Z",
                    "end": "2024-01-03T00:00:00Z",
                    "adjustment": "raw",
                },
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 5
        assert body["instrument"] == "NQ"


# ─────────────────────────────────────────────────────────────────────────────
# Backtest API integration tests (ADR-003 B2/B4)
# ─────────────────────────────────────────────────────────────────────────────

def _backtest_session_bars() -> pd.DataFrame:
    """One hand-crafted NY session (2024-01-02, EST = UTC-5).

    Range window 09:00–09:30 NY → high 18100 / low 18000. The 09:30 bar
    touches the high (fade short entry @18100); the 09:31 bar trades down
    through the 18000 take-profit (sl 50 pts × rrr 2 = 100 pts).
    """
    rows = [
        # 09:00 NY = 14:00 UTC — the range bar
        ("2024-01-02T14:00:00Z", 18050.0, 18100.0, 18000.0, 18050.0),
        # 09:30 NY — killzone opens, touches range high → short entry
        ("2024-01-02T14:30:00Z", 18080.0, 18100.0, 18070.0, 18090.0),
        # 09:31 NY — drops through TP at 18000
        ("2024-01-02T14:31:00Z", 18090.0, 18095.0, 17995.0, 18010.0),
    ]
    return pd.DataFrame(
        {
            "ts": pd.to_datetime([r[0] for r in rows], utc=True),
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
            "volume": [1000] * len(rows),
        }
    )


_BACKTEST_PARAMS = {
    "instrument": "NQ",
    "start": "2024-01-02",
    "end": "2024-01-02",
    "clock": {
        "tz": "America/New_York",
        "range_start": "09:00",
        "range_end": "09:30",
        "orders_place": "09:30",
        "eod_flat": "16:00",
    },
    "direction_mode": "fade",
    "sl_mode": "points",
    "sl_value": 50.0,
    "rrr": 2.0,
}


class TestBacktestAPI:
    @pytest.mark.asyncio
    async def test_run_persist_and_read_back(self, session: AsyncSession) -> None:
        from app.db.session import get_db
        from app.main import app

        df = validate(_backtest_session_bars())
        await upsert_bars(session, df, "NQ", "test")

        app.dependency_overrides[get_db] = lambda: session
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/backtest/runs",
                    json={"params": _BACKTEST_PARAMS, "notes": "integration"},
                )
                assert resp.status_code == 200, resp.text
                body = resp.json()
                run_id = body["run_id"]
                # Short @18100, TP 100 pts below → +100 pts × $2 MNQ = $200.
                assert body["metrics"]["trade_count"] == 1
                assert body["metrics"]["total_pnl_usd"] == pytest.approx(200.0)
                assert body["trades"][0]["exit_reason"] == "tp"
                assert body["trades"][0]["direction"] == "short"
                assert body["equity_curve"] == [
                    {"date": "2024-01-02", "equity_usd": 200.0}
                ]

                listed = await client.get("/api/v1/backtest/runs")
                assert run_id in [r["id"] for r in listed.json()]

                detail = await client.get(f"/api/v1/backtest/runs/{run_id}")
                assert detail.status_code == 200
                dbody = detail.json()
                assert dbody["params"]["sl_value"] == 50.0
                assert dbody["trades"][0]["pnl_usd"] == pytest.approx(200.0)
                assert dbody["metrics"]["total_pnl_usd"] == pytest.approx(200.0)

                season = await client.get(
                    f"/api/v1/backtest/runs/{run_id}/seasonality",
                    params={"bucket": "month"},
                )
                assert season.status_code == 200
                buckets = season.json()["buckets"]
                assert buckets == [
                    {
                        "bucket": 1,
                        "trade_count": 1,
                        "total_pnl_usd": 200.0,
                        "mean_pnl_usd": 200.0,
                        "win_rate": 1.0,
                    }
                ]

                mc = await client.get(
                    f"/api/v1/backtest/runs/{run_id}/montecarlo",
                    params={"n_sims": 200},
                )
                assert mc.status_code == 200
                mcb = mc.json()
                # A single +$200 day: every bootstrap path ends at +200.
                assert mcb["terminal_pnl_percentiles"]["50"] == pytest.approx(200.0)
                assert mcb["prob_terminal_loss"] == 0.0
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_run_with_no_data_is_400(self, session: AsyncSession) -> None:
        from app.db.session import get_db
        from app.main import app

        app.dependency_overrides[get_db] = lambda: session
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                params = dict(_BACKTEST_PARAMS, start="2030-01-06", end="2030-01-07")
                resp = await client.post(
                    "/api/v1/backtest/runs", json={"params": params}
                )
                assert resp.status_code == 400
                assert "no 1m bars" in resp.json()["detail"]

                missing = await client.get(
                    "/api/v1/backtest/runs/00000000-0000-0000-0000-000000000000"
                )
                assert missing.status_code == 404
        finally:
            app.dependency_overrides.clear()
