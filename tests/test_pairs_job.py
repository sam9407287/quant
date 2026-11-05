"""Daily job and notifier tests (ADR-010 phase 5): mocked session, no network."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from app.core.config import Settings
from app.pairs import notify
from app.pairs.schemas import PairStatsModel, RefreshResponse, ScanResponse
from app.pairs.signals import PairState
from fetcher import pairs_job
from fetcher.scheduler import build_scheduler

AS_OF = date(2026, 11, 4)  # a Wednesday


def stats(pair: str = "NQ/ES", *, z: float = 2.4, qualified: bool = True, y: str = "NQ=F", x: str = "ES=F") -> PairStatsModel:
    return PairStatsModel(
        pair_name=pair, y_ticker=y, x_ticker=x, as_of=AS_OF, n_obs=504, alpha=0.1, beta=1.1, eg_pvalue=0.01,
        eg_pvalue_reverse=0.02, johansen_trace=20.0, johansen_crit_95=15.0, johansen_pass=True, half_life=8.0,
        z_window=32, z=z, spread_last=0.02, spread_mean=0.0, spread_std=0.01, stability_ratio=0.9, qualified=qualified,
        reasons=[] if qualified else ["EG p 0.3 >= 0.05"],
    )


def scan_response(rows: list[PairStatsModel]) -> ScanResponse:
    from datetime import UTC, datetime

    return ScanResponse(
        id="scan-1", created_at=datetime.now(UTC), as_of=AS_OF, trigger="daily", universe_size=2, pair_count=len(rows),
        qualified_count=sum(r.qualified for r in rows), runtime_ms=5, config={}, results=rows,
    )


def settings(**over: Any) -> Settings:
    base: dict[str, Any] = {"pairs_webhook_url": "https://discord.test/hook", "pairs_dry_run": False}
    base.update(over)
    return Settings(**base)


@pytest.fixture
def session() -> MagicMock:
    s = MagicMock()
    s.execute = AsyncMock()
    s.commit = AsyncMock()
    return s


WATCH = [{"y_ticker": "NQ=F", "x_ticker": "ES=F", "enabled": True, "overrides": {}}]
PRICES = pd.DataFrame({"NQ=F": [20000.0, 20100.0], "ES=F": [5000.0, 5010.0]}, index=pd.to_datetime(["2026-11-03", "2026-11-04"]))


def _patches(rows: list[PairStatsModel], *, states: list[dict[str, Any]] | None = None, latest: date | None = AS_OF,
             insert_id: str | None = "sig-1", pending: list[dict[str, Any]] | None = None):
    refreshed = RefreshResponse(tickers=2, rows_written=4, issues=[], latest_date=latest, runtime_ms=1)
    return (
        patch("fetcher.pairs_job.repo.list_watchlist", new=AsyncMock(return_value=WATCH)),
        patch("fetcher.pairs_job.refresh_daily_bars", new=AsyncMock(return_value=refreshed)),
        patch("fetcher.pairs_job.latest_trading_date", new=AsyncMock(return_value=latest)),
        patch("fetcher.pairs_job.run_scan", new=AsyncMock(return_value=(scan_response(rows), PRICES))),
        patch("fetcher.pairs_job.repo.load_states", new=AsyncMock(return_value=states or [])),
        patch("fetcher.pairs_job.repo.upsert_state", new=AsyncMock()),
        patch("fetcher.pairs_job.repo.insert_signal", new=AsyncMock(return_value=insert_id)),
        patch("fetcher.pairs_job.repo.unnotified_signals", new=AsyncMock(return_value=pending or [])),
        patch("fetcher.pairs_job.repo.mark_notified", new=AsyncMock()),
        patch("fetcher.pairs_job.notify.post", return_value=True),
    )


class TestExecute:
    @pytest.mark.asyncio
    async def test_entry_signal_is_recorded_with_sizing_and_pushed(self, session: MagicMock) -> None:
        pending = [{"id": "sig-1", "pair_name": "NQ/ES", "event": "entry", "side": "short_spread",
                    "payload": {"stats": stats().model_dump(mode="json"), "sizing": {"y_qty": 2, "y_contract": "MNQ", "x_qty": 9, "x_contract": "MES", "rounding_error_pct": 3.0}}}]
        patches = _patches([stats()], pending=pending)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as upsert, patches[6] as ins, patches[7], patches[8] as mark, patches[9] as post:
            summary = await pairs_job.execute(session, settings=settings(pairs_daily_digest=False), today=AS_OF, dry_run=False, trigger="scheduled")
        assert summary["status"] == "ok"
        assert summary["events"] == [{"pair": "NQ/ES", "event": "entry", "side": "short_spread", "new": True}]
        state: PairState = upsert.await_args.kwargs["state"]
        assert state.side == "short_spread" and state.entry_params is not None
        payload = ins.await_args.kwargs["payload"]
        assert payload["sizing"]["y_contract"] == "MNQ" and payload["sizing"]["feasible"] is True
        assert summary["pushed"] == 1
        mark.assert_awaited_once_with(session, "sig-1")
        embed = post.call_args.args[1]
        assert "SHORT spread" in embed["embeds"][0]["title"]

    @pytest.mark.asyncio
    async def test_rerun_same_day_does_not_advance_state_or_push(self, session: MagicMock) -> None:
        current = [{"pair_name": "NQ/ES", "side": "short_spread", "as_of": AS_OF, "days_held": 1, "breakdown_days": 0,
                    "entry_params": {"alpha": 0.1, "beta": 1.1, "mean": 0.0, "std": 0.01, "half_life": 8.0, "z_window": 32}}]
        patches = _patches([stats()], states=current, insert_id=None)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as upsert, patches[6], patches[7], patches[8], patches[9] as post:
            summary = await pairs_job.execute(session, settings=settings(), today=AS_OF, dry_run=False, trigger="scheduled")
        assert summary["state_skipped_as_current"] == 1
        upsert.assert_not_awaited()
        assert summary["events"] == []
        post.assert_not_called()  # nothing pending → nothing pushed

    @pytest.mark.asyncio
    async def test_dry_run_persists_but_does_not_push(self, session: MagicMock) -> None:
        pending = [{"id": "sig-1", "pair_name": "NQ/ES", "event": "entry", "side": "short_spread", "payload": {}}]
        patches = _patches([stats()], pending=pending)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6] as ins, patches[7], patches[8] as mark, patches[9] as post:
            summary = await pairs_job.execute(session, settings=settings(), today=AS_OF, dry_run=True, trigger="manual")
        ins.assert_awaited()
        post.assert_not_called()
        mark.assert_not_awaited()
        assert summary["pushed"] == 0 and summary["dry_run"] is True

    @pytest.mark.asyncio
    async def test_no_new_bar_short_circuits(self, session: MagicMock) -> None:
        patches = _patches([stats()], latest=date(2026, 11, 3))
        with patches[0], patches[1], patches[2], patches[3] as scan, patches[4], patches[5], patches[6], patches[7], patches[8], patches[9] as post:
            summary = await pairs_job.execute(session, settings=settings(), today=AS_OF, dry_run=False, trigger="scheduled")
        assert summary["status"] == "no_data" and summary["expected"] == AS_OF
        scan.assert_not_awaited()
        post.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_data_notice_is_opt_in(self, session: MagicMock) -> None:
        patches = _patches([stats()], latest=None)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9] as post:
            await pairs_job.execute(session, settings=settings(pairs_notify_no_data=True), today=AS_OF, dry_run=False, trigger="scheduled")
        assert post.called and "No new daily bar" in post.call_args.args[1]["embeds"][0]["description"]

    @pytest.mark.asyncio
    async def test_exit_event_uses_previous_side(self, session: MagicMock) -> None:
        prev = [{"pair_name": "NQ/ES", "side": "short_spread", "as_of": date(2026, 11, 3), "days_held": 3, "breakdown_days": 0,
                 "entered_on": date(2026, 10, 30), "cooldown_until": None,
                 "entry_params": {"alpha": 0.1, "beta": 1.1, "mean": 0.0, "std": 0.01, "half_life": 8.0, "z_window": 32, "entry_z": 2.2}}]
        # spread_last 0.002 → frozen z = 0.2 → threshold exit
        row = stats(z=0.2).model_copy(update={"spread_last": 0.002})
        patches = _patches([row], states=prev)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as upsert, patches[6] as ins, patches[7], patches[8], patches[9]:
            summary = await pairs_job.execute(session, settings=settings(pairs_daily_digest=False), today=AS_OF, dry_run=True, trigger="scheduled")
        assert summary["events"][0]["event"] == "exit" and summary["events"][0]["side"] == "short_spread"
        assert upsert.await_args.kwargs["state"].side == "flat"
        assert upsert.await_args.kwargs["entered_on"] is None
        assert ins.await_args.kwargs["payload"]["days_held"] == 4

    @pytest.mark.asyncio
    async def test_digest_is_recorded_as_a_signal(self, session: MagicMock) -> None:
        patches = _patches([stats(z=0.5)])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6] as ins, patches[7], patches[8], patches[9]:
            await pairs_job.execute(session, settings=settings(pairs_daily_digest=True), today=AS_OF, dry_run=True, trigger="scheduled")
        kinds = [c.kwargs["event"] for c in ins.await_args_list]
        assert kinds == ["digest"]  # z=0.5 → no trade event, digest only


class TestRunPairsJob:
    @pytest.mark.asyncio
    async def test_failure_is_recorded_and_reported(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        with (
            patch("fetcher.pairs_job.AsyncSessionLocal") as factory,
            patch("fetcher.pairs_job.ensure_schema", new=AsyncMock()),
            patch("fetcher.pairs_job.repo.start_job_run", new=AsyncMock(return_value="job-1")),
            patch("fetcher.pairs_job.repo.finish_job_run", new=AsyncMock()) as finish,
            patch("fetcher.pairs_job.execute", new=AsyncMock(side_effect=RuntimeError("boom"))),
            patch("fetcher.pairs_job.get_settings", return_value=settings()),
            patch("fetcher.pairs_job.notify.post", return_value=True) as post,
        ):
            factory.return_value.__aenter__ = AsyncMock(return_value=session)
            factory.return_value.__aexit__ = AsyncMock(return_value=False)
            summary = await pairs_job.run_pairs_job(dry_run=False, today=AS_OF)
        assert summary["status"] == "error" and "boom" in summary["error"]
        assert finish.await_args.kwargs["status"] == "error"
        assert post.called


class TestHelpers:
    def test_expected_trading_date_skips_weekends(self) -> None:
        assert pairs_job.expected_trading_date(date(2026, 11, 7)) == date(2026, 11, 6)  # Sat → Fri
        assert pairs_job.expected_trading_date(date(2026, 11, 8)) == date(2026, 11, 6)  # Sun → Fri
        assert pairs_job.expected_trading_date(AS_OF) == AS_OF

    def test_state_round_trip_cooldown(self) -> None:
        row = {"side": "flat", "entry_params": None, "days_held": 0, "breakdown_days": 0, "cooldown_until": date(2026, 11, 11)}
        st = pairs_job.state_from_row(row, AS_OF)
        assert st.cooldown_remaining == 5  # five business days Nov 4 → Nov 11
        assert pairs_job.state_from_row(None, AS_OF) == PairState()
        assert pairs_job._cooldown_until(PairState(cooldown_remaining=5), AS_OF) == date(2026, 11, 11)
        assert pairs_job._cooldown_until(PairState(), AS_OF) is None

    def test_rules_from_overrides_ignore_unknown_keys(self) -> None:
        rules = pairs_job.rules_for({"overrides": {"entry_z": 1.5, "formation_window": 252}}, MagicMock())
        assert rules.entry_z == 1.5 and rules.exit_z == 0.5

    def test_scheduler_has_both_jobs(self) -> None:
        jobs = {j.id for j in build_scheduler().get_jobs()}
        assert jobs == {"daily_fetch", "pairs_daily"}


class TestNotifyPayloads:
    def test_entry_embed_contents(self) -> None:
        sizing = {"y_qty": 3, "y_contract": "MCL", "x_qty": 3, "x_contract": "BZ", "rounding_error_pct": 2.1, "adverse_2sigma_usd": -420.0}
        embed = notify.entry_embed(signal_date=AS_OF, stats=stats("CL/BZ", y="CL=F", x="BZ=F"), side="long_spread", sizing=sizing, base_url="https://q.test/")
        e = embed["embeds"][0]
        assert e["title"].startswith("🟢 CL/BZ — LONG spread")
        assert "3 MCL / 3 BZ" in e["description"] and "$-420" in e["description"]
        assert e["url"] == "https://q.test/research/pairs/analyze?y=CL=F&x=BZ=F"
        assert e["color"] == 0x2ECC71

    def test_exit_and_digest_and_error(self) -> None:
        ex = notify.exit_embed(signal_date=AS_OF, stats=stats(), event="breakdown", side_before="short_spread", days_held=6, base_url="https://q.test")
        assert "broke down" in ex["embeds"][0]["description"] and ex["embeds"][0]["color"] == 0xF1C40F
        dg = notify.digest_embed(signal_date=AS_OF, rows=[stats(), stats("CL/BZ", z=-0.3, qualified=False)], base_url="https://q.test")
        desc = dg["embeds"][0]["description"]
        assert desc.index("NQ/ES") < desc.index("CL/BZ") and "✅" in desc
        er = notify.error_embed(signal_date=AS_OF, message="x" * 5000)
        assert len(er["embeds"][0]["description"]) <= 3900

    def test_post_handles_failures_quietly(self) -> None:
        assert notify.post("", {}) is False
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            assert notify.post("https://x.test", {"a": 1}) is False
