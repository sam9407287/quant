"""API tests for /api/v1/pairs (ADR-010 phase 4) with the DB and loaders mocked."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.auth.dependency import CurrentUser, get_current_user
from app.db.session import get_db
from app.main import app
from app.pairs.synthetic import cointegrated_pair, independent_walks, price_frame

USER = CurrentUser(id="00000000-0000-0000-0000-000000000001", email="u@example.com", role="user")
ADMIN = CurrentUser(id="00000000-0000-0000-0000-000000000002", email="a@example.com", role="admin")


@pytest.fixture
def session() -> MagicMock:
    s = MagicMock()
    s.execute = AsyncMock()
    s.commit = AsyncMock()
    return s


@pytest.fixture
def client(session: MagicMock):
    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: USER
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def prices() -> pd.DataFrame:
    # Same parameters as scripts/smoke_pairs.py, where NQ/ES qualifies at a 400-day window.
    y, x = cointegrated_pair(n=1400, beta=1.1, half_life=9.0, spread_sigma=0.008, seed=41)
    a, b = independent_walks(n=1400, seed=43)
    frame = price_frame({"NQ=F": y, "ES=F": x, "CL=F": a, "BZ=F": b})
    frame["NQ=F"] *= 100
    frame["ES=F"] *= 30
    return frame


class TestUniverseAndWatchlist:
    def test_universe_lists_specs(self, client: TestClient) -> None:
        res = client.get("/api/v1/pairs/universe")
        assert res.status_code == 200
        body = res.json()
        nq = next(i for i in body if i["ticker"] == "NQ=F")
        assert nq["registry_symbol"] == "NQ"
        assert {c["code"] for c in nq["contracts"]} == {"NQ", "MNQ"}
        assert any(i["kind"] == "etf" for i in body)

    def test_add_pair_rejects_unknown_ticker(self, client: TestClient) -> None:
        res = client.post("/api/v1/pairs/watchlist", json={"name": "X", "y_ticker": "NQ=F", "x_ticker": "NOPE"})
        assert res.status_code == 400
        assert "unknown pairs-universe ticker" in res.json()["detail"]

    def test_add_pair_rejects_same_legs(self, client: TestClient) -> None:
        res = client.post("/api/v1/pairs/watchlist", json={"name": "X", "y_ticker": "NQ=F", "x_ticker": "NQ=F"})
        assert res.status_code == 422

    def test_add_pair_persists(self, client: TestClient) -> None:
        row = {
            "id": "11111111-1111-1111-1111-111111111111", "name": "NQ/ES", "y_ticker": "NQ=F", "x_ticker": "ES=F",
            "enabled": True, "overrides": {}, "rationale": None, "created_at": datetime.now(UTC),
        }
        with patch("app.api.pairs.repo.add_watchlist", new=AsyncMock(return_value=row)) as add:
            res = client.post("/api/v1/pairs/watchlist", json={"name": "NQ/ES", "y_ticker": "NQ=F", "x_ticker": "ES=F"})
        assert res.status_code == 201 and res.json()["name"] == "NQ/ES"
        add.assert_awaited_once()

    def test_write_requires_auth(self, session: MagicMock) -> None:
        async def _db():
            yield session

        app.dependency_overrides[get_db] = _db
        try:
            res = TestClient(app).post("/api/v1/pairs/watchlist/defaults")
        finally:
            app.dependency_overrides.clear()
        assert res.status_code == 401

    def test_delete_missing_is_404(self, client: TestClient) -> None:
        with patch("app.api.pairs.repo.delete_watchlist", new=AsyncMock(return_value=False)):
            assert client.delete("/api/v1/pairs/watchlist/abc").status_code == 404


class TestScans:
    def test_scan_runs_and_persists(self, client: TestClient, prices: pd.DataFrame) -> None:
        with (
            patch("app.pairs.service.load_prices", new=AsyncMock(return_value=prices)),
            patch("app.pairs.service.repo.insert_scan", new=AsyncMock(return_value="scan-1")) as ins,
        ):
            res = client.post(
                "/api/v1/pairs/scans",
                json={"config": {"mode": "explicit", "pairs": [["NQ=F", "ES=F"], ["CL=F", "BZ=F"]], "formation_window": 400, "stability_step": 5}},
            )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["id"] == "scan-1" and body["pair_count"] == 2
        names = {r["pair_name"]: r for r in body["results"]}
        assert names["NQ/ES"]["qualified"] is True
        assert names["CL/BZ"]["qualified"] is False
        assert body["qualified_count"] == 1
        kwargs = ins.await_args.kwargs
        assert kwargs["trigger"] == "manual" and kwargs["universe_size"] == 4

    def test_scan_uses_db_watchlist(self, client: TestClient, prices: pd.DataFrame) -> None:
        watch = [{"y_ticker": "NQ=F", "x_ticker": "ES=F", "enabled": True}]
        with (
            patch("app.pairs.service.repo.list_watchlist", new=AsyncMock(return_value=watch)),
            patch("app.pairs.service.load_prices", new=AsyncMock(return_value=prices)),
            patch("app.pairs.service.repo.insert_scan", new=AsyncMock(return_value="scan-2")),
        ):
            res = client.post("/api/v1/pairs/scans", json={"config": {"mode": "watchlist", "formation_window": 400, "stability_step": 5}})
        assert res.status_code == 200
        assert [r["pair_name"] for r in res.json()["results"]] == ["NQ/ES"]

    def test_scan_without_data_is_400(self, client: TestClient) -> None:
        with patch("app.pairs.service.load_prices", new=AsyncMock(return_value=pd.DataFrame())):
            res = client.post("/api/v1/pairs/scans", json={"config": {"mode": "explicit", "pairs": [["NQ=F", "ES=F"]]}})
        assert res.status_code == 400 and "refresh" in res.json()["detail"]

    def test_scan_detail_404(self, client: TestClient) -> None:
        with patch("app.api.pairs.repo.get_scan", new=AsyncMock(return_value=None)):
            assert client.get("/api/v1/pairs/scans/nope").status_code == 404

    def test_latest_scan_none_when_empty(self, client: TestClient) -> None:
        with patch("app.api.pairs.repo.latest_scan_id", new=AsyncMock(return_value=None)):
            res = client.get("/api/v1/pairs/scans/latest")
        assert res.status_code == 200 and res.json() is None


class TestAnalysis:
    def test_series_and_buckets(self, client: TestClient, prices: pd.DataFrame) -> None:
        with (
            patch("app.pairs.service.load_prices", new=AsyncMock(return_value=prices[["NQ=F", "ES=F"]])),
            patch("app.api.pairs.equity_roll_dates", new=AsyncMock(return_value=[date(2020, 3, 12)])),
        ):
            res = client.get("/api/v1/pairs/analysis", params={"y": "NQ=F", "x": "ES=F", "formation_window": 300})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["pair_name"] == "NQ/ES"
        assert len(body["dates"]) == len(body["spread"]) == len(body["zscore"]) == len(prices)
        assert body["spread"][0] is None and body["zscore"][-1] is not None
        assert body["forward"] and {b["horizon"] for b in body["forward"]} <= {5, 10, 20}
        assert body["roll_dates"] == ["2020-03-12"]
        assert body["stats"]["qualified"] is True
        assert body["settlement_note"] is None

    def test_cross_group_settlement_note(self, client: TestClient, prices: pd.DataFrame) -> None:
        frame = prices[["NQ=F", "ES=F"]].rename(columns={"ES=F": "GC=F"})
        with (
            patch("app.pairs.service.load_prices", new=AsyncMock(return_value=frame)),
            patch("app.api.pairs.equity_roll_dates", new=AsyncMock(return_value=[])),
        ):
            res = client.get("/api/v1/pairs/analysis", params={"y": "NQ=F", "x": "GC=F", "formation_window": 300})
        assert res.status_code == 200
        assert "snapshot_1m" in res.json()["settlement_note"]

    def test_short_history_is_400(self, client: TestClient, prices: pd.DataFrame) -> None:
        with patch("app.pairs.service.load_prices", new=AsyncMock(return_value=prices.iloc[:100])):
            res = client.get("/api/v1/pairs/analysis", params={"y": "NQ=F", "x": "ES=F"})
        assert res.status_code == 400

    def test_bad_ticker_is_400(self, client: TestClient) -> None:
        assert client.get("/api/v1/pairs/analysis", params={"y": "NQ=F", "x": "ZZ"}).status_code == 400


class TestBacktests:
    def test_backtest_runs_and_persists(self, client: TestClient, prices: pd.DataFrame) -> None:
        opens = prices * 1.0005

        async def fake_load(db: Any, tickers: list[str], **kw: Any) -> pd.DataFrame:
            frame = opens if kw.get("field") == "open" else prices
            return frame[[t for t in tickers if t in frame.columns]]

        with (
            patch("app.pairs.service.load_prices", new=fake_load),
            patch("app.api.pairs.equity_roll_dates", new=AsyncMock(return_value=[])),
            patch("app.api.pairs.repo.insert_backtest_run", new=AsyncMock(return_value="run-1")) as ins,
        ):
            res = client.post(
                "/api/v1/pairs/backtests",
                json={"config": {"pairs": [["NQ=F", "ES=F"]], "formation_window": 300, "fill": "next_open"}, "notes": "t"},
            )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["id"] == "run-1" and body["metrics"]["trade_count"] > 0
        assert "equity" in body["result"] and "trades" in body["result"]
        assert ins.await_args.kwargs["owner_id"] == USER.id

    def test_backtest_without_data_is_400(self, client: TestClient) -> None:
        with patch("app.pairs.service.load_prices", new=AsyncMock(return_value=pd.DataFrame())):
            res = client.post("/api/v1/pairs/backtests", json={"config": {"pairs": [["NQ=F", "ES=F"]]}})
        assert res.status_code == 400

    def test_list_filters_by_owner(self, client: TestClient) -> None:
        with patch("app.api.pairs.repo.list_backtest_runs", new=AsyncMock(return_value=[])) as lst:
            assert client.get("/api/v1/pairs/backtests").json() == []
        assert lst.await_args.kwargs["owner_id"] == USER.id

    def test_detail_404(self, client: TestClient) -> None:
        with patch("app.api.pairs.repo.get_backtest_run", new=AsyncMock(return_value=None)):
            assert client.get("/api/v1/pairs/backtests/x").status_code == 404


class TestJobsAndState:
    def test_daily_job_requires_admin(self, client: TestClient) -> None:
        assert client.post("/api/v1/pairs/jobs/daily").status_code == 403

    def test_daily_job_as_admin_calls_runner(self, session: MagicMock) -> None:
        async def _db():
            yield session

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: ADMIN
        try:
            with patch("fetcher.pairs_job.run_pairs_job", new=AsyncMock(return_value={"status": "ok"})) as run:
                res = TestClient(app).post("/api/v1/pairs/jobs/daily", params={"dry_run": "true"})
        finally:
            app.dependency_overrides.clear()
        assert res.status_code == 200 and res.json() == {"status": "ok"}
        assert run.await_args.kwargs == {"dry_run": True, "trigger": "manual"}

    def test_state_and_signals_shape(self, client: TestClient) -> None:
        state_row = {
            "pair_name": "NQ/ES", "y_ticker": "NQ=F", "x_ticker": "ES=F", "side": "flat", "entered_on": None,
            "entry_params": None, "days_held": 0, "breakdown_days": 0, "cooldown_until": None, "last_z": 0.4,
            "as_of": date(2026, 11, 4), "updated_at": datetime.now(UTC),
        }
        sig_row = {
            "id": "s1", "signal_date": date(2026, 11, 4), "pair_name": "NQ/ES", "event": "entry", "side": "short_spread",
            "payload": {"z": 2.3}, "notified_at": None, "created_at": datetime.now(UTC),
        }
        with (
            patch("app.api.pairs.repo.load_states", new=AsyncMock(return_value=[state_row])),
            patch("app.api.pairs.repo.list_signals", new=AsyncMock(return_value=[sig_row])),
        ):
            assert client.get("/api/v1/pairs/state").json()[0]["side"] == "flat"
            assert client.get("/api/v1/pairs/signals").json()[0]["event"] == "entry"


class TestRollGaps:
    def test_counts_large_jumps_per_ticker(self) -> None:
        from app.pairs.service import roll_gap_counts

        idx = pd.bdate_range("2026-01-01", periods=6)
        wide = pd.DataFrame({"A": [100, 101, 140, 141, 142, 143], "B": [50, 50.5, 51, 51.2, 51.1, 51.3]}, index=idx)
        assert roll_gap_counts(wide, 6) == {"A": 1, "B": 0}
        assert roll_gap_counts(pd.DataFrame(), 6) == {}
        assert np.isfinite(wide.to_numpy()).all()
