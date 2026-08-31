"""An omitted date range means "every bar the database holds".

The point of these is that the resolution reads the *bars*, so history
backfilled later widens a run with no code or client change — and that the
resolved span is what gets persisted, so a saved run stays reproducible.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.backtest import _with_resolved_dates
from app.api.kbars import bars_span
from app.api.strategies import _resolve_span
from app.backtest.params import BacktestParams, SessionClock

LO = datetime(2026, 4, 19, 22, 0, tzinfo=UTC)
HI = datetime(2026, 8, 27, 23, 0, tzinfo=UTC)


def _db(lo: datetime | None = LO, hi: datetime | None = HI) -> AsyncMock:
    row = MagicMock(lo=lo, hi=hi) if lo is not None else None
    result = MagicMock()
    result.first.return_value = row
    db = AsyncMock()
    db.execute.return_value = result
    return db


def _params(**kw) -> BacktestParams:
    return BacktestParams(
        instrument="NQ",
        clock=SessionClock(
            range_start="09:00", range_end="09:30",
            orders_place="09:30", eod_flat="15:55",
        ),
        **kw,
    )


class TestBarsSpan:
    @pytest.mark.asyncio
    async def test_returns_the_stored_edges(self) -> None:
        assert await bars_span(_db(), "kbars_1h", "NQ") == (LO, HI)

    @pytest.mark.asyncio
    async def test_returns_none_when_nothing_is_stored(self) -> None:
        assert await bars_span(_db(lo=None, hi=None), "kbars_1h", "NQ") is None


class TestResolveSpan:
    @pytest.mark.asyncio
    async def test_both_edges_omitted_covers_everything(self) -> None:
        start, end = await _resolve_span(_db(), "1h", "NQ", None, None)
        assert start == LO
        # Past the newest bar: _fetch_bars' interval is half-open, so an end
        # of exactly HI would drop the very last bar of a full-history run.
        assert end > HI

    @pytest.mark.asyncio
    async def test_one_edge_omitted_fills_only_that_edge(self) -> None:
        asked = datetime(2026, 7, 1, tzinfo=UTC)
        assert (await _resolve_span(_db(), "1h", "NQ", asked, None))[0] == asked
        assert (await _resolve_span(_db(), "1h", "NQ", None, asked))[1] == asked

    @pytest.mark.asyncio
    async def test_an_explicit_range_does_not_touch_the_database(self) -> None:
        db = _db()
        lo = datetime(2026, 7, 1, tzinfo=UTC)
        hi = datetime(2026, 7, 8, tzinfo=UTC)
        assert await _resolve_span(db, "1h", "NQ", lo, hi) == (lo, hi)
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_stored_bars_is_a_400_not_a_silent_empty_run(self) -> None:
        with pytest.raises(HTTPException) as exc:
            await _resolve_span(_db(lo=None, hi=None), "1h", "NQ", None, None)
        assert exc.value.status_code == 400


class TestBacktestDateResolution:
    @pytest.mark.asyncio
    async def test_unset_dates_resolve_to_the_stored_span(self) -> None:
        resolved = await _with_resolved_dates(_db(), _params())
        # NY local dates: 04-19 22:00Z is 18:00 on the 19th, 08-27 23:00Z is
        # 19:00 on the 27th.
        assert resolved.start == date(2026, 4, 19)
        assert resolved.end == date(2026, 8, 27)

    @pytest.mark.asyncio
    async def test_resolution_is_recorded_in_the_persisted_params(self) -> None:
        dumped = (await _with_resolved_dates(_db(), _params())).model_dump(mode="json")
        # A stored run must say what it covered — "everything" is a request,
        # not a span that stays the same once more history lands.
        assert dumped["start"] == "2026-04-19"
        assert dumped["end"] == "2026-08-27"

    @pytest.mark.asyncio
    async def test_explicit_dates_are_left_alone(self) -> None:
        p = _params(start=date(2026, 6, 1), end=date(2026, 6, 30))
        db = _db()
        assert await _with_resolved_dates(db, p) == p
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_bars_raises(self) -> None:
        with pytest.raises(ValueError, match="no 1m bars"):
            await _with_resolved_dates(_db(lo=None, hi=None), _params())

    def test_end_before_start_is_still_rejected(self) -> None:
        with pytest.raises(ValueError, match="end date must be"):
            _params(start=date(2026, 6, 30), end=date(2026, 6, 1))


class TestLoaderCap:
    """The cap bounds a runaway request; it must never quietly shrink a run.

    Metrics computed over a silent subset of the requested range are wrong
    without looking wrong, which is the one failure mode a backtest cannot
    afford.
    """

    @pytest.mark.asyncio
    async def test_exceeding_the_cap_raises_instead_of_truncating(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.strategies import loader

        monkeypatch.setattr(loader, "MAX_BARS", 3)
        db = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = [
            MagicMock(_mapping={"ts": LO, "open": 1.0, "high": 2.0,
                                "low": 0.5, "close": 1.5, "volume": 10})
            for _ in range(4)
        ]
        db.execute.return_value = result

        with pytest.raises(ValueError, match="more than 3"):
            await loader.load_bars_df(db, "NQ", "1h", LO, HI, "raw")

    @pytest.mark.asyncio
    async def test_at_the_cap_is_fine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.strategies import loader

        monkeypatch.setattr(loader, "MAX_BARS", 3)
        db = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = [
            MagicMock(_mapping={"ts": LO, "open": 1.0, "high": 2.0,
                                "low": 0.5, "close": 1.5, "volume": 10})
            for _ in range(3)
        ]
        db.execute.return_value = result

        assert len(await loader.load_bars_df(db, "NQ", "1h", LO, HI, "raw")) == 3


class TestEvaluateEndpointWiring:
    """The endpoint must actually hand the resolved span to the loader.

    The resolution logic is tested above in isolation; this covers the wiring
    that would let a full-history request quietly load a default window
    instead.
    """

    @pytest.fixture
    def client_and_calls(self, monkeypatch: pytest.MonkeyPatch):
        import pandas as pd
        from fastapi.testclient import TestClient

        from app.api import strategies as mod
        from app.auth.dependency import CurrentUser, get_current_user
        from app.db.session import get_db
        from app.main import app

        calls: list[dict] = []

        async def fake_get_strategy(db, sid, owner_ids=None):  # noqa: ANN001, ANN202
            return {
                "id": sid,
                "definition": {
                    "timeframe": "1h",
                    "entry_long": {
                        "op": "gt",
                        "left": {"kind": "price"},
                        "right": {"kind": "const", "value": 0.0},
                    },
                    "sl": {"mode": "points", "value": 100.0},
                },
            }

        async def fake_load(db, instrument, tf, start, end, adjustment):  # noqa: ANN001, ANN202
            calls.append({"start": start, "end": end})
            return pd.DataFrame(
                [{"ts": LO, "open": 1.0, "high": 2.0, "low": 0.5,
                  "close": 1.5, "volume": 10}]
            )

        monkeypatch.setattr(mod, "get_strategy", fake_get_strategy)
        monkeypatch.setattr(mod, "load_bars_df", fake_load)
        monkeypatch.setattr(mod, "_readable_owners", AsyncMock(return_value=[]))

        app.dependency_overrides[get_db] = lambda: _db()
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id="u1", email="t@test.io", role="admin"
        )
        with TestClient(app) as c:
            yield c, calls
        app.dependency_overrides.clear()

    def test_no_dates_loads_the_whole_stored_span(self, client_and_calls) -> None:
        client, calls = client_and_calls
        resp = client.post(
            "/api/v1/strategies/s1/evaluate", json={"instrument": "NQ"}
        )
        assert resp.status_code == 200, resp.text
        assert calls[0]["start"] == LO
        assert calls[0]["end"] > HI
        # And the response says so, rather than leaving the caller to guess.
        assert resp.json()["start"].startswith("2026-04-19")

    def test_explicit_dates_are_passed_through_untouched(
        self, client_and_calls
    ) -> None:
        client, calls = client_and_calls
        resp = client.post(
            "/api/v1/strategies/s1/evaluate",
            json={
                "instrument": "NQ",
                "start": "2026-06-01T00:00:00Z",
                "end": "2026-06-30T00:00:00Z",
            },
        )
        assert resp.status_code == 200, resp.text
        assert calls[0]["start"] == datetime(2026, 6, 1, tzinfo=UTC)
        assert calls[0]["end"] == datetime(2026, 6, 30, tzinfo=UTC)
