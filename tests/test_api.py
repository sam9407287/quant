"""Integration-style tests for FastAPI endpoints using a mocked DB session."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app

# ---------------------------------------------------------------------------
# Helpers to build mock DB rows
# ---------------------------------------------------------------------------

def _mock_bar_row(ts: datetime, o: float = 18000.0) -> MagicMock:
    row = MagicMock()
    row._mapping = {
        "ts": ts,
        "open": o,
        "high": o + 50,
        "low": o - 50,
        "close": o + 20,
        "volume": 1000,
    }
    return row


def _mock_coverage_row(instrument: str = "NQ", timeframe: str = "1m") -> MagicMock:
    row = MagicMock()
    row._mapping = {
        "instrument": instrument,
        "timeframe": timeframe,
        "earliest_ts": datetime(2024, 1, 1, tzinfo=UTC),
        "latest_ts": datetime(2024, 4, 1, tzinfo=UTC),
        "bar_count": 100000,
        "gap_count": 0,
        "last_fetch_ts": datetime(2024, 4, 1, tzinfo=UTC),
        "last_fetch_ok": True,
    }
    return row


def _mock_roll_row() -> MagicMock:
    row = MagicMock()
    row._mapping = {
        "instrument": "NQ",
        "old_contract": "NQH24",
        "new_contract": "NQM24",
        "roll_date": datetime(2024, 3, 14).date(),
        "price_diff": 50.0,
        "price_ratio": 1.00278,
    }
    return row


def _sqlite_backed(table: str, bars: list[tuple[datetime, float]]):
    """Execute the endpoint's real SQL against an in-memory SQLite table.

    Asserting on the query string would only prove the SQL was *written* a
    certain way; running it proves which rows come back. Postgres' `::float`
    casts are the one dialect difference and are stripped.
    """
    import re
    import sqlite3

    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.execute(
        f"CREATE TABLE {table} (instrument TEXT, ts TEXT, open REAL, "
        "high REAL, low REAL, close REAL, volume INT)"
    )
    con.executemany(
        f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?)",
        [("NQ", ts.isoformat(), o, o + 50, o - 50, o + 20, 1000) for ts, o in bars],
    )

    cols = ("ts", "open", "high", "low", "close", "volume")

    async def run(stmt, params):  # noqa: ANN001, ANN202
        sql = re.sub(r"::float", "", str(stmt))
        bound = {
            k: (v.isoformat() if isinstance(v, datetime) else v)
            for k, v in params.items()
        }
        rows = con.execute(sql, bound).fetchall()
        out = []
        for r in rows:
            row = MagicMock()
            row._mapping = dict(zip(cols, r, strict=True))
            out.append(row)
        result = MagicMock()
        result.fetchall.return_value = out
        return result

    return run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = []
    session.execute.return_value = result
    return session


@pytest.fixture
def client(mock_db: AsyncMock) -> TestClient:
    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# /api/v1/kbars
# ---------------------------------------------------------------------------

class TestGetKbars:
    def test_missing_required_params_returns_422(self, client: TestClient) -> None:
        resp = client.get("/api/v1/kbars")
        assert resp.status_code == 422

    def test_invalid_instrument_returns_422(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/kbars",
            params={
                "instrument": "XX",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-02T00:00:00Z",
            },
        )
        assert resp.status_code == 422

    def test_valid_request_returns_200(
        self, client: TestClient, mock_db: AsyncMock
    ) -> None:
        ts = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)

        # First call returns bars; second call (rolls) returns empty
        bars_result = MagicMock()
        bars_result.fetchall.return_value = [_mock_bar_row(ts)]
        rolls_result = MagicMock()
        rolls_result.fetchall.return_value = []
        mock_db.execute.side_effect = [bars_result, rolls_result]

        resp = client.get(
            "/api/v1/kbars",
            params={
                "instrument": "NQ",
                "timeframe": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-02T00:00:00Z",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["instrument"] == "NQ"
        assert body["timeframe"] == "1h"
        assert body["count"] >= 0

    def test_raw_adjustment_skips_roll_lookup(
        self, client: TestClient, mock_db: AsyncMock
    ) -> None:
        ts = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
        result = MagicMock()
        result.fetchall.return_value = [_mock_bar_row(ts)]
        mock_db.execute.return_value = result

        resp = client.get(
            "/api/v1/kbars",
            params={
                "instrument": "ES",
                "timeframe": "1m",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-02T00:00:00Z",
                "adjustment": "raw",
            },
        )
        assert resp.status_code == 200
        # With raw adjustment, execute is called once (bars only, no rolls)
        assert mock_db.execute.call_count == 1

    def test_limit_keeps_the_newest_bars_not_the_oldest(
        self, client: TestClient, mock_db: AsyncMock
    ) -> None:
        """A range holding more bars than the limit returns its recent end.

        Ordering ascending before the LIMIT truncated the *newest* bars, so
        the chart silently stopped short of the data it asked for — and once
        it began stitching history chunks together, a truncated chunk left a
        hole between itself and the bars already drawn.
        """
        hours = [datetime(2024, 1, 1, h, tzinfo=UTC) for h in range(10)]
        mock_db.execute.side_effect = _sqlite_backed(
            "kbars_1h",
            [(ts, 18000.0 + i) for i, ts in enumerate(hours)],
        )

        resp = client.get(
            "/api/v1/kbars",
            params={
                "instrument": "NQ",
                "timeframe": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-02T00:00:00Z",
                "adjustment": "raw",
                "limit": 3,
            },
        )
        assert resp.status_code == 200
        got = [datetime.fromisoformat(b["ts"]) for b in resp.json()["data"]]
        # The last three hours, still ascending.
        assert got == hours[-3:]

    def test_response_schema(
        self, client: TestClient, mock_db: AsyncMock
    ) -> None:
        ts = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
        result = MagicMock()
        result.fetchall.return_value = [_mock_bar_row(ts, 18000.0)]
        mock_db.execute.return_value = result

        resp = client.get(
            "/api/v1/kbars",
            params={
                "instrument": "NQ",
                "timeframe": "1d",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-01T00:00:00Z",
                "adjustment": "raw",
            },
        )
        bar = resp.json()["data"][0]
        assert set(bar.keys()) == {"ts", "open", "high", "low", "close", "volume"}


# ---------------------------------------------------------------------------
# /api/v1/coverage
# ---------------------------------------------------------------------------

class TestGetCoverage:
    def test_all_instruments(
        self, client: TestClient, mock_db: AsyncMock
    ) -> None:
        result = MagicMock()
        result.fetchall.return_value = [
            _mock_coverage_row("NQ", "1m"),
            _mock_coverage_row("ES", "1m"),
        ]
        mock_db.execute.return_value = result

        resp = client.get("/api/v1/coverage", params={"instrument": "all"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_single_instrument(
        self, client: TestClient, mock_db: AsyncMock
    ) -> None:
        result = MagicMock()
        result.fetchall.return_value = [_mock_coverage_row("NQ", "1m")]
        mock_db.execute.return_value = result

        resp = client.get("/api/v1/coverage", params={"instrument": "NQ"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /api/v1/roll-calendar
# ---------------------------------------------------------------------------

class TestGetRollCalendar:
    def test_returns_roll_records(
        self, client: TestClient, mock_db: AsyncMock
    ) -> None:
        result = MagicMock()
        result.fetchall.return_value = [_mock_roll_row()]
        mock_db.execute.return_value = result

        resp = client.get(
            "/api/v1/roll-calendar",
            params={"instrument": "NQ", "year": 2024},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["old_contract"] == "NQH24"
        assert data[0]["new_contract"] == "NQM24"
