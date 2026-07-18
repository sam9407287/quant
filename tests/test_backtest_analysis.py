"""Unit tests for the backtest analysis layer (ADR-003 B3)."""

from __future__ import annotations

from datetime import date

import pytest

from app.backtest.analysis import (
    BucketStats,
    equity_curve,
    max_drawdown,
    monte_carlo,
    seasonality,
    summarize,
)
from app.backtest.types import DayResult, ExitReason


def day(d: date, pnl: float, reason: ExitReason = "tp") -> DayResult:
    return DayResult(session_date=d, exit_reason=reason, pnl_usd=pnl)


RESULTS = [
    day(date(2026, 1, 5), 100.0),                    # Mon, Jan, win
    day(date(2026, 1, 6), -50.0, "sl"),              # Tue, Jan, loss
    day(date(2026, 2, 3), 30.0, "eod"),              # Tue, Feb, win
    day(date(2026, 2, 4), 0.0, "no_fill"),           # played, no exposure
    day(date(2026, 2, 5), 0.0, "no_data"),           # excluded everywhere
    day(date(2026, 3, 2), -20.0, "sl"),              # Mon, Mar, loss
]


class TestSummary:
    def test_counts_and_totals(self) -> None:
        s = summarize(RESULTS)
        assert s.session_count == 5          # no_data excluded, no_fill kept
        assert s.trade_count == 4
        assert s.win_count == 2
        assert s.loss_count == 2
        assert s.win_rate == pytest.approx(0.5)
        assert s.total_pnl_usd == pytest.approx(60.0)
        assert s.expectancy_usd == pytest.approx(15.0)
        assert s.profit_factor == pytest.approx(130.0 / 70.0)
        assert s.best_day_usd == 100.0
        assert s.worst_day_usd == -50.0

    def test_profit_factor_none_without_losses(self) -> None:
        s = summarize([day(date(2026, 1, 5), 10.0)])
        assert s.profit_factor is None
        assert s.sharpe_annualized is None  # single day: no variance

    def test_equity_curve_and_drawdown(self) -> None:
        curve = equity_curve(RESULTS)
        assert [v for _, v in curve] == pytest.approx([100.0, 50.0, 80.0, 80.0, 60.0])
        assert curve[0][0] == "2026-01-05"
        # peak 100 → trough 50 is the deepest excursion
        assert max_drawdown([v for _, v in curve]) == pytest.approx(50.0)

    def test_drawdown_starts_from_flat(self) -> None:
        # A losing start draws down from 0, not from the first value.
        assert max_drawdown([-30.0, -10.0, -40.0]) == pytest.approx(40.0)


class TestSeasonality:
    def test_month_buckets(self) -> None:
        by_month = {b.bucket: b for b in seasonality(RESULTS, "month")}
        assert set(by_month) == {1, 2, 3}
        assert by_month[1].total_pnl_usd == pytest.approx(50.0)
        assert by_month[1].trade_count == 2
        assert by_month[2].trade_count == 1  # no_fill day is not a trade
        assert by_month[3].win_rate == 0.0

    def test_weekday_buckets(self) -> None:
        by_wd = {b.bucket: b for b in seasonality(RESULTS, "weekday")}
        assert set(by_wd) == {0, 1}  # Mondays and Tuesdays only
        assert by_wd[0].total_pnl_usd == pytest.approx(80.0)
        assert by_wd[1].total_pnl_usd == pytest.approx(-20.0)

    def test_unknown_bucket_rejected(self) -> None:
        with pytest.raises(ValueError, match="bucket"):
            seasonality(RESULTS, "hour")

    def test_bucketstats_is_frozen(self) -> None:
        b = BucketStats(bucket=1, trade_count=1, total_pnl_usd=1.0, mean_pnl_usd=1.0, win_rate=1.0)
        with pytest.raises(AttributeError):
            b.bucket = 2  # type: ignore[misc]


class TestMonteCarlo:
    DAILY = [100.0, -50.0, 30.0, -20.0, 10.0]

    def test_seeded_reproducibility(self) -> None:
        a = monte_carlo(self.DAILY, n_sims=500, seed=7)
        b = monte_carlo(self.DAILY, n_sims=500, seed=7)
        assert a == b

    def test_percentiles_ordered_and_shapes(self) -> None:
        r = monte_carlo(self.DAILY, n_sims=1000)
        t = r.terminal_pnl_percentiles
        assert t[5] <= t[25] <= t[50] <= t[75] <= t[95]
        d = r.max_drawdown_percentiles
        assert d[5] <= d[95]
        assert 0.0 <= r.prob_terminal_loss <= 1.0
        assert r.prob_ruin is None

    def test_permutation_preserves_total(self) -> None:
        r = monte_carlo(self.DAILY, n_sims=200, method="permutation")
        total = sum(self.DAILY)
        # Every permutation has the same terminal P&L.
        assert r.terminal_pnl_percentiles[5] == pytest.approx(total)
        assert r.terminal_pnl_percentiles[95] == pytest.approx(total)

    def test_permutation_rejects_custom_horizon(self) -> None:
        with pytest.raises(ValueError, match="horizon"):
            monte_carlo(self.DAILY, method="permutation", horizon_days=10)

    def test_ruin_probability_with_capital(self) -> None:
        r = monte_carlo(self.DAILY, n_sims=500, initial_capital=1.0)
        assert r.prob_ruin is not None and r.prob_ruin > 0.0
        deep = monte_carlo(self.DAILY, n_sims=500, initial_capital=1e9)
        assert deep.prob_ruin == 0.0

    def test_bootstrap_horizon_extends(self) -> None:
        r = monte_carlo(self.DAILY, n_sims=100, horizon_days=50)
        assert r.horizon_days == 50

    def test_empty_series_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            monte_carlo([])

    def test_unknown_method_rejected(self) -> None:
        with pytest.raises(ValueError, match="method"):
            monte_carlo(self.DAILY, method="jackknife")
