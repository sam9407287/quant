"""Walk-forward engine tests (ADR-010 phase 3) on synthetic prices."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.pairs import metrics as m
from app.pairs.backtest import parameter_paths, run_backtest, run_with_sensitivity
from app.pairs.schemas import BacktestConfig, CostModel, PortfolioConfig, SignalRules
from app.pairs.synthetic import cointegrated_pair, independent_walks, price_frame


@pytest.fixture(scope="module")
def prices() -> pd.DataFrame:
    y, x = cointegrated_pair(n=1300, beta=1.1, half_life=8.0, spread_sigma=0.008, seed=31)
    a, b = cointegrated_pair(n=1300, beta=0.9, half_life=15.0, spread_sigma=0.01, seed=32)
    r1, r2 = independent_walks(n=1300, seed=33)
    # Scale into plausible price levels for the real tickers used.
    frame = price_frame({"NQ=F": y, "ES=F": x, "GC=F": a, "SI=F": b, "CL=F": r1, "BZ=F": r2})
    frame["NQ=F"] *= 100
    frame["ES=F"] *= 30
    frame["GC=F"] *= 15
    frame["SI=F"] *= 0.2
    frame["CL=F"] *= 0.5
    frame["BZ=F"] *= 0.5
    return frame


def cfg(**over: object) -> BacktestConfig:
    base: dict[str, object] = {
        "pairs": [("NQ=F", "ES=F")],
        "formation_window": 300,
        "fill": "next_close",
        "costs": CostModel(commission_per_contract=0.0, slippage_ticks=0.0, roll_cost_per_contract=0.0),
    }
    base.update(over)
    return BacktestConfig(**base)  # type: ignore[arg-type]


class TestParameterPaths:
    def test_paths_cover_calendar_and_gate(self, prices: pd.DataFrame) -> None:
        paths = parameter_paths(np.log(prices), cfg(pairs=[("NQ=F", "ES=F"), ("CL=F", "BZ=F")]))
        assert [p.name for p in paths] == ["NQ/ES", "CL/BZ"]
        good, bad = paths
        assert len(good.series.zscore) == len(prices)
        assert good.qualified[400:].mean() > 0.6
        assert bad.qualified.mean() < 0.3

    def test_missing_column_and_short_history_are_skipped(self, prices: pd.DataFrame) -> None:
        assert parameter_paths(np.log(prices), cfg(pairs=[("NQ=F", "ZZ")])) == []
        assert parameter_paths(np.log(prices.iloc[:200]), cfg()) == []


class TestEngine:
    def test_cointegrated_pair_is_profitable_without_costs(self, prices: pd.DataFrame) -> None:
        res = run_backtest(prices, cfg())
        mt = res.metrics
        assert mt.trade_count >= 10
        assert mt.total_return > 0
        assert mt.sharpe is not None and mt.sharpe > 1.0
        assert mt.win_rate is not None and mt.win_rate > 0.5
        assert -1 <= mt.max_drawdown <= 0
        assert 0 < mt.time_in_market < 1
        assert set(mt.exit_mix) <= {"exit", "stop", "time_stop", "breakdown", "none"}
        assert mt.deflated_sharpe_p is not None and 0 <= mt.deflated_sharpe_p <= 1
        assert mt.benchmark_return is not None
        assert len(res.equity) == len(prices)

    def test_equity_reconciles_with_trades(self, prices: pd.DataFrame) -> None:
        res = run_backtest(prices, cfg())
        net = sum(t.net_pnl for t in res.trades)
        assert res.equity[-1].equity - 1_000_000 == pytest.approx(net, abs=1e-6)
        assert all(t.exit_date is not None and t.exit_date >= t.entry_date for t in res.trades)
        assert all(t.days_held >= 1 for t in res.trades)

    def test_no_lookahead_future_randomised(self, prices: pd.DataFrame) -> None:
        base = run_backtest(prices, cfg())
        cut = 900
        perturbed = prices.copy()
        rng = np.random.default_rng(5)
        perturbed.iloc[cut + 1 :] = perturbed.iloc[cut + 1 :].to_numpy() * np.exp(rng.normal(0, 0.05, perturbed.iloc[cut + 1 :].shape))
        other = run_backtest(perturbed, cfg())
        cutoff = prices.index[cut].date()
        a = [(t.entry_date, t.exit_date, t.side, t.net_pnl) for t in base.trades if t.exit_date is not None and t.exit_date <= cutoff]
        b = [(t.entry_date, t.exit_date, t.side, t.net_pnl) for t in other.trades if t.exit_date is not None and t.exit_date <= cutoff]
        assert a == b and len(a) > 3
        ea = [p.equity for p in base.equity[: cut + 1]]
        eb = [p.equity for p in other.equity[: cut + 1]]
        assert ea == pytest.approx(eb)

    def test_costs_reduce_pnl_monotonically(self, prices: pd.DataFrame) -> None:
        free = run_backtest(prices, cfg())
        cheap = run_backtest(prices, cfg(costs=CostModel(commission_per_contract=1.0, slippage_ticks=1.0, roll_cost_per_contract=1.0)))
        dear = run_backtest(prices, cfg(costs=CostModel(commission_per_contract=50.0, slippage_ticks=10.0, roll_cost_per_contract=50.0)))
        assert free.metrics.total_return > cheap.metrics.total_return > dear.metrics.total_return
        assert all(t.costs > 0 for t in cheap.trades)

    def test_fill_modes_differ_but_both_run(self, prices: pd.DataFrame) -> None:
        opens = prices * 1.001
        at_close = run_backtest(prices, cfg(fill="next_close"))
        at_open = run_backtest(prices, cfg(fill="next_open"), prices_open=opens)
        assert at_open.metrics.trade_count == at_close.metrics.trade_count
        assert at_open.metrics.total_return != at_close.metrics.total_return
        with pytest.raises(ValueError, match="open-price"):
            run_backtest(prices, cfg(fill="next_open"))

    def test_integer_sizing_runs_and_reports_rounding(self, prices: pd.DataFrame) -> None:
        res = run_backtest(prices, cfg(portfolio=PortfolioConfig(sizing="integer", capital=2_000_000)))
        assert res.trades
        assert all(float(t.y_qty).is_integer() and float(t.x_qty).is_integer() for t in res.trades)
        assert all(t.rounding_error_pct is not None for t in res.trades)
        assert {t.y_contract for t in res.trades} <= {"MNQ", "NQ"}

    def test_portfolio_of_pairs_and_correlation(self, prices: pd.DataFrame) -> None:
        res = run_backtest(prices, cfg(pairs=[("NQ=F", "ES=F"), ("GC=F", "SI=F"), ("CL=F", "BZ=F")]), include_daily_pnl=True)
        names = [a.pair_name for a in res.attribution]
        assert names == ["NQ/ES", "GC/SI", "CL/BZ"]
        assert res.correlation["pairs"] == names
        mat = np.array(res.correlation["matrix"])
        assert mat.shape == (3, 3) and np.allclose(np.diag(mat), 1.0)
        assert res.daily_pnl_by_pair is not None
        total = sum(sum(v) for v in res.daily_pnl_by_pair.values())
        assert res.equity[-1].equity - 1_000_000 == pytest.approx(total, abs=1e-6)
        cl = next(a for a in res.attribution if a.pair_name == "CL/BZ")
        assert cl.qualified_days < cl.total_days * 0.3

    def test_max_concurrent_caps_open_positions(self, prices: pd.DataFrame) -> None:
        pairs = [("NQ=F", "ES=F"), ("GC=F", "SI=F")]
        free = run_backtest(prices, cfg(pairs=pairs, portfolio=PortfolioConfig(max_concurrent=2)))
        capped = run_backtest(prices, cfg(pairs=pairs, portfolio=PortfolioConfig(max_concurrent=1)))
        assert max(p.positions for p in capped.equity) == 1
        assert 1 <= max(p.positions for p in free.equity) <= 2
        assert capped.metrics.trade_count <= free.metrics.trade_count
        # Both pairs do trade; the cap only governs overlap.
        assert {a.pair_name for a in capped.attribution if a.trade_count > 0} == {"NQ/ES", "GC/SI"}

    def test_date_range_restricts_trading(self, prices: pd.DataFrame) -> None:
        start, end = date(2021, 1, 4), date(2021, 12, 31)
        res = run_backtest(prices, cfg(start=start, end=end))
        assert res.equity[0].date >= start and res.equity[-1].date <= end
        assert all(start <= t.entry_date <= end for t in res.trades)
        with pytest.raises(ValueError):
            run_backtest(prices, cfg(start=date(2030, 1, 1)))

    def test_inverse_vol_weights_run(self, prices: pd.DataFrame) -> None:
        res = run_backtest(prices, cfg(pairs=[("NQ=F", "ES=F"), ("GC=F", "SI=F")], portfolio=PortfolioConfig(weight_scheme="inverse_vol")))
        assert res.metrics.trade_count > 0

    def test_qualification_gate_off_trades_more(self, prices: pd.DataFrame) -> None:
        gated = run_backtest(prices, cfg(pairs=[("CL=F", "BZ=F")]))
        open_ = run_backtest(prices, cfg(pairs=[("CL=F", "BZ=F")], rules=SignalRules(require_qualified=False)))
        assert open_.metrics.trade_count >= gated.metrics.trade_count

    def test_roll_dates_charge_only_on_those_days(self, prices: pd.DataFrame) -> None:
        costs = CostModel(commission_per_contract=0.0, slippage_ticks=0.0, roll_cost_per_contract=100.0)
        proxy = run_backtest(prices, cfg(costs=costs))
        none = run_backtest(prices, cfg(costs=costs), roll_dates={"NQ=F": set(), "ES=F": set()})
        assert none.metrics.total_return > proxy.metrics.total_return
        assert all(t.costs == 0 for t in none.trades)


class TestSensitivity:
    def test_grid_and_deflated_sharpe(self, prices: pd.DataFrame) -> None:
        res = run_with_sensitivity(
            prices,
            cfg(sensitivity=True, sensitivity_entry_z=[1.5, 2.0], sensitivity_formation=[252, 300]),
        )
        assert len(res.sensitivity) == 2 * 2 * 2
        assert {c.exit_rule for c in res.sensitivity} == {"threshold", "cross_zero"}
        assert res.metrics.trials == 8
        assert res.metrics.deflated_sharpe_p is not None
        assert res.metrics.tradeability_tax is None

    def test_tradeability_tax_in_integer_mode(self, prices: pd.DataFrame) -> None:
        res = run_with_sensitivity(prices, cfg(portfolio=PortfolioConfig(sizing="integer", capital=2_000_000)))
        assert res.metrics.tradeability_tax is not None
        assert res.sensitivity == [] and res.metrics.trials == 1


class TestMetrics:
    def test_drawdown_and_returns(self) -> None:
        eq = np.array([100.0, 110.0, 99.0, 104.5, 121.0])
        st = m.drawdown_stats(eq)
        assert st.max_drawdown == pytest.approx(-0.1)
        assert st.max_duration == 2
        r = m.daily_returns(eq, 100.0)
        assert r[0] == 0.0 and r[1] == pytest.approx(0.1)
        assert m.annualised_return(0.21, 252) == pytest.approx(0.21)
        assert m.cvar(np.array([-0.05, 0.01, 0.02, -0.01, 0.03] * 4)) <= -0.05

    def test_sharpe_family_edge_cases(self) -> None:
        assert m.sharpe(np.zeros(10)) is None
        assert m.sortino(np.array([0.01, 0.02])) is None  # no downside
        assert m.bootstrap_sharpe_ci(np.array([0.01] * 10)) is None
        rng = np.random.default_rng(0)
        r = rng.normal(0.001, 0.01, 500)
        ci = m.bootstrap_sharpe_ci(r)
        s = m.sharpe(r)
        assert ci is not None and s is not None and ci[0] < s < ci[1]

    def test_deflated_sharpe_decreases_with_trials(self) -> None:
        rng = np.random.default_rng(1)
        r = rng.normal(0.0008, 0.01, 600)
        one = m.deflated_sharpe_probability(r, n_trials=1)
        many = m.deflated_sharpe_probability(r, n_trials=50)
        assert one is not None and many is not None
        assert many < one
        assert m.deflated_sharpe_probability(r[:10]) is None
