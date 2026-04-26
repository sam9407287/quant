"""Integration-style tests for FastAPI endpoints using a mocked DB session."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_db


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
        "earliest_ts": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "latest_ts": datetime(2024, 4, 1, tzinfo=timezone.utc),
        "bar_count": 100000,
        "gap_count": 0,
        "last_fetch_ts": datetime(2024, 4, 1, tzinfo=timezone.utc),
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
        ts = datetime(2024, 1, 2, 9, 0, tzinfo=timezone.utc)

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
        ts = datetime(2024, 1, 2, 9, 0, tzinfo=timezone.utc)
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

    def test_response_schema(
        self, client: TestClient, mock_db: AsyncMock
    ) -> None:
        ts = datetime(2024, 1, 2, 9, 0, tzinfo=timezone.utc)
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
