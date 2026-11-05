"""Walk-forward pairs backtest with portfolio aggregation (ADR-010 §2.5).

Structure:

1. `parameter_paths` — for every pair, the per-day α, β, half-life, z,
   p-value and qualification flag, each computed from data strictly
   before that day (`diagnostics.rolling_series`).
2. `run_backtest` — one loop over the master calendar. At each close the
   shared state machine (`signals.step`) decides; fills happen at the
   next day's open or close; P&L is marked daily in dollars from the
   actual leg prices and contract multipliers; costs are explicit.
3. Metrics, per-pair attribution, correlation of pair P&L streams, an
   optional sensitivity grid and the deflated Sharpe over its trials.

The engine is pure over price frames so the same run is reproducible
from its stored config and the tests can randomise the future to prove
nothing leaks backwards.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from app.pairs import metrics as m
from app.pairs.diagnostics import RollingSeries, rolling_series
from app.pairs.schemas import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    EquityPointModel,
    Event,
    ExitRule,
    PairAttribution,
    SensitivityCell,
    Side,
    TradeModel,
)
from app.pairs.screen import pair_name
from app.pairs.signals import EntryParams, Observation, PairState, step
from app.pairs.sizing import PositionSize, size_position
from app.pairs.universe import get_instrument

logger = logging.getLogger(__name__)

# EG p-values inside the engine are refreshed every N days; the series
# moves slowly and a daily ADF over thousands of days dominates runtime.
PVALUE_STEP = 5


# ---------------------------------------------------------------------------
# Parameter paths
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PairPath:
    """One pair's per-day parameters on the master calendar (NaN where absent)."""

    name: str
    y: str
    x: str
    log_y: np.ndarray
    log_x: np.ndarray
    series: RollingSeries
    qualified: np.ndarray  # bool per day


def parameter_paths(
    log_prices: pd.DataFrame, config: BacktestConfig, *, formation_window: int | None = None
) -> list[PairPath]:
    """Rolling parameters per pair, re-indexed onto the frame's calendar."""
    window = formation_window or config.formation_window
    paths: list[PairPath] = []
    rules = config.qualification
    for y, x in config.pairs:
        if y not in log_prices.columns or x not in log_prices.columns:
            logger.warning("pair %s/%s skipped: missing price column", y, x)
            continue
        pair = log_prices[[y, x]].dropna()
        if len(pair) <= window + 5:
            logger.warning("pair %s/%s skipped: %d rows < formation window %d", y, x, len(pair), window)
            continue
        ya = pair[y].to_numpy(dtype=float)
        xa = pair[x].to_numpy(dtype=float)
        rs = rolling_series(
            ya, xa, pd.DatetimeIndex(pair.index), formation_window=window,
            z_window_min=config.z_window_min, z_window_max=config.z_window_max,
            z_window_multiple=config.z_window_multiple, hedge_method=config.hedge_method, pvalue_step=PVALUE_STEP,
        )
        qualified = (
            (rs.pvalue < rules.eg_pvalue_max)
            & np.isfinite(rs.half_life)
            & (rs.half_life >= rules.half_life_min)
            & (rs.half_life <= rules.half_life_max)
            & ((rs.beta > 0) if rules.require_positive_beta else True)
        )
        # Re-index everything onto the master calendar.
        pos = log_prices.index.get_indexer(pair.index)
        n = len(log_prices.index)
        placed = RollingSeries(
            index=pd.DatetimeIndex(log_prices.index), spread=_place(rs.spread, pos, n),
            zscore=_place(rs.zscore, pos, n), alpha=_place(rs.alpha, pos, n), beta=_place(rs.beta, pos, n),
            half_life=_place(rs.half_life, pos, n), z_window=_place(rs.z_window, pos, n),
            mean=_place(rs.mean, pos, n), std=_place(rs.std, pos, n), pvalue=_place(rs.pvalue, pos, n),
        )
        q = np.zeros(n, dtype=bool)
        q[pos] = qualified
        paths.append(PairPath(pair_name(y, x), y, x, _place(ya, pos, n), _place(xa, pos, n), placed, q))
    return paths


def _place(arr: np.ndarray, pos: np.ndarray, n: int) -> np.ndarray:
    out = np.full(n, np.nan)
    out[pos] = arr
    return out


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

@dataclass
class _OpenPosition:
    side: Side
    size: PositionSize
    entry_index: int
    entry_date: date
    entry_z: float
    beta: float
    half_life: float | None
    gross: float = 0.0
    costs: float = 0.0
    last_y: float = 0.0
    last_x: float = 0.0
    days: int = 0


@dataclass
class _Pending:
    kind: str  # 'entry' | 'exit'
    side: Side
    event: Event
    z: float | None
    params: EntryParams | None = None


@dataclass
class _PairRun:
    path: PairPath
    state: PairState = field(default_factory=PairState)
    position: _OpenPosition | None = None
    pending: _Pending | None = None
    pnl: np.ndarray = field(default_factory=lambda: np.zeros(0))
    trades: list[TradeModel] = field(default_factory=list)


def _signs(side: Side) -> tuple[float, float]:
    """(dir_y, dir_x): long spread is long Y short X."""
    return (1.0, -1.0) if side == "long_spread" else (-1.0, 1.0)


def run_backtest(
    prices_close: pd.DataFrame,
    config: BacktestConfig,
    *,
    prices_open: pd.DataFrame | None = None,
    roll_dates: Mapping[str, set[date]] | None = None,
    n_trials: int = 1,
    trial_sharpes: np.ndarray | None = None,
    paths: list[PairPath] | None = None,
    include_daily_pnl: bool = False,
) -> BacktestResult:
    """Run the full walk-forward simulation and package the result document."""
    if config.fill == "next_open" and prices_open is None:
        raise ValueError("next_open fills need an open-price frame")
    log_prices = np.log(prices_close.where(prices_close > 0))
    pair_paths = paths if paths is not None else parameter_paths(log_prices, config)
    if not pair_paths:
        raise ValueError("no pair has enough aligned history for the formation window")

    index = pd.DatetimeIndex(prices_close.index)
    n = len(index)
    start_i = 0 if config.start is None else int(index.searchsorted(pd.Timestamp(config.start)))
    end_i = n - 1 if config.end is None else int(index.searchsorted(pd.Timestamp(config.end), side="right")) - 1
    if end_i <= start_i:
        raise ValueError("date range contains no trading days")

    close = prices_close.to_numpy(dtype=float)
    open_ = prices_open.reindex(index=index, columns=prices_close.columns).to_numpy(dtype=float) if prices_open is not None else close
    col = {c: i for i, c in enumerate(prices_close.columns)}
    dates = [d.date() for d in index]
    roll_dates = roll_dates or {}

    runs = [_PairRun(path=p, pnl=np.zeros(n)) for p in pair_paths]
    pcfg = config.portfolio
    per_pair_capital = pcfg.capital * pcfg.gross_leverage / max(1, len(runs))
    positions_count = np.zeros(n, dtype=int)

    for t in range(start_i, end_i + 1):
        today = dates[t]
        # 1. Execute fills decided at yesterday's close.
        for run in runs:
            if run.pending is None:
                continue
            py, px = _fill_prices(run.path, t, close, open_, col, config.fill)
            if py is None or px is None:
                continue  # price missing today → carry the order forward
            if run.pending.kind == "entry" and run.position is None:
                run.position = _open(run, t, today, py, px, close, col, config, per_pair_capital, runs)
            elif run.pending.kind == "exit" and run.position is not None:
                _close(run, t, today, py, px, close, col, config, run.pending)
            run.pending = None

        # 2. Mark open positions to today's close (incl. expected roll cost).
        n_open = 0
        for run in runs:
            pos = run.position
            if pos is None:
                continue
            n_open += 1
            cy, cx = close[t, col[run.path.y]], close[t, col[run.path.x]]
            if np.isfinite(cy) and np.isfinite(cx):
                _mark(run, t, cy, cx)
            pos.days += 1
            roll = _roll_cost(run.path, today, pos.size, config, roll_dates)
            pos.costs += roll
            run.pnl[t] -= roll
        positions_count[t] = n_open

        # 3. Decide at today's close for tomorrow.
        concurrent = sum(1 for r in runs if r.position is not None or (r.pending and r.pending.kind == "entry"))
        for run in runs:
            obs = _observe(run.path, t)
            if obs is None:
                continue
            if run.pending is not None:
                continue  # an order is already queued; decide again tomorrow
            transition = step(run.state, obs, config.rules)
            if transition.event == "entry":
                if concurrent >= pcfg.max_concurrent:
                    continue  # slot full: stay flat, state unchanged
                concurrent += 1
                run.pending = _Pending("entry", transition.state.side, "entry", transition.z_used, transition.state.entry_params)
            elif transition.event != "none":
                run.pending = _Pending("exit", run.state.side, transition.event, transition.z_used)
            run.state = transition.state

    # Force-close anything still open at the end so trades reconcile.
    last = end_i
    for run in runs:
        if run.position is not None:
            fy, fx = float(close[last, col[run.path.y]]), float(close[last, col[run.path.x]])
            if math.isfinite(fy) and math.isfinite(fx):
                _close(run, last, dates[last], fy, fx, close, col, config, _Pending("exit", run.state.side, "exit", None), final=True)

    return _package(runs, index, start_i, end_i, positions_count, config, n_trials, trial_sharpes, include_daily_pnl, prices_close)


def _fill_prices(
    path: PairPath, t: int, close: np.ndarray, open_: np.ndarray, col: dict[str, int], fill: str
) -> tuple[float | None, float | None]:
    src = open_ if fill == "next_open" else close
    py, px = src[t, col[path.y]], src[t, col[path.x]]
    if not (np.isfinite(py) and np.isfinite(px)):
        return None, None
    return float(py), float(px)


def _observe(path: PairPath, t: int) -> Observation | None:
    s = path.series
    if not (np.isfinite(path.log_y[t]) and np.isfinite(path.log_x[t]) and np.isfinite(s.beta[t])):
        return None
    params = EntryParams(
        alpha=float(s.alpha[t]), beta=float(s.beta[t]), mean=float(s.mean[t]), std=float(s.std[t]),
        half_life=float(s.half_life[t]) if np.isfinite(s.half_life[t]) else None,
        z_window=int(s.z_window[t]) if np.isfinite(s.z_window[t]) else 0,
    )
    return Observation(
        log_y=float(path.log_y[t]), log_x=float(path.log_x[t]),
        z_live=float(s.zscore[t]) if np.isfinite(s.zscore[t]) else None,
        pvalue=float(s.pvalue[t]) if np.isfinite(s.pvalue[t]) else None,
        qualified=bool(path.qualified[t]), live_params=params,
    )


def _open(
    run: _PairRun, t: int, today: date, py: float, px: float, close: np.ndarray, col: dict[str, int],
    config: BacktestConfig, per_pair_capital: float, runs: list[_PairRun],
) -> _OpenPosition | None:
    pending = run.pending
    assert pending is not None and pending.params is not None
    params = pending.params
    if params.beta <= 0:
        run.state = PairState()
        return None
    notional = per_pair_capital
    if config.portfolio.weight_scheme == "inverse_vol":
        notional = _inverse_vol_notional(run, runs, t, config)
    size = size_position(
        run.path.y, run.path.x, price_y=py, price_x=px, beta=params.beta, gross_notional=notional,
        mode=config.portfolio.sizing, prefer_micro=config.portfolio.prefer_micro, spread_std=params.std,
    )
    if not size.feasible:
        run.state = PairState()  # could not trade it → back to flat, no cooldown
        return None
    pos = _OpenPosition(
        side=pending.side, size=size, entry_index=t, entry_date=today, entry_z=pending.z or 0.0,
        beta=params.beta, half_life=params.half_life, last_y=py, last_x=px,
    )
    fee = _fill_cost(size, config)
    pos.costs += fee
    run.pnl[t] -= fee
    # Fill-to-close mark for the entry day (zero when filling at the close).
    cy, cx = close[t, col[run.path.y]], close[t, col[run.path.x]]
    if np.isfinite(cy) and np.isfinite(cx):
        _mark(run, t, float(cy), float(cx), pos)
    return pos


def _close(
    run: _PairRun, t: int, today: date, py: float, px: float, close: np.ndarray, col: dict[str, int],
    config: BacktestConfig, pending: _Pending, *, final: bool = False,
) -> None:
    pos = run.position
    assert pos is not None
    # Mark from yesterday's close (or entry) to the fill price.
    if not final:
        _mark(run, t, py, px, pos)
    fee = _fill_cost(pos.size, config)
    pos.costs += fee
    run.pnl[t] -= fee
    net = pos.gross - pos.costs
    run.trades.append(
        TradeModel(
            pair_name=run.path.name, side=pos.side, entry_date=pos.entry_date, exit_date=today,
            entry_z=pos.entry_z, exit_z=pending.z, exit_reason=pending.event, beta=pos.beta,
            half_life=pos.half_life, days_held=pos.days, y_qty=pos.size.y.qty, x_qty=pos.size.x.qty,
            y_contract=pos.size.y.contract, x_contract=pos.size.x.contract, gross_pnl=pos.gross,
            costs=pos.costs, net_pnl=net, notional=pos.size.gross_notional,
            rounding_error_pct=pos.size.rounding_error_pct,
        )
    )
    run.position = None
    if final:
        run.state = PairState()


def _mark(run: _PairRun, t: int, py: float, px: float, pos: _OpenPosition | None = None) -> None:
    pos = pos or run.position
    assert pos is not None
    dy, dx = _signs(pos.side)
    pnl = (
        pos.size.y.qty * pos.size.y.multiplier * (py - pos.last_y) * dy
        + pos.size.x.qty * pos.size.x.multiplier * (px - pos.last_x) * dx
    )
    pos.gross += pnl
    run.pnl[t] += pnl
    pos.last_y, pos.last_x = py, px


def _fill_cost(size: PositionSize, config: BacktestConfig) -> float:
    c = config.costs
    legs = (size.y, size.x)
    commission = sum(c.commission_per_contract * leg.contracts for leg in legs)
    slippage = sum(c.slippage_ticks * leg.tick_size * leg.multiplier * leg.contracts for leg in legs)
    return float(commission + slippage)


def _roll_cost(
    path: PairPath, today: date, size: PositionSize, config: BacktestConfig, roll_dates: Mapping[str, set[date]]
) -> float:
    """Roll cost per leg: on calendar dates when known, else a daily expectation."""
    total = 0.0
    for ticker, leg in ((path.y, size.y), (path.x, size.x)):
        inst = get_instrument(ticker)
        if inst.roll_months_per_year == 0:
            continue
        per_roll = config.costs.roll_cost_per_contract * leg.contracts
        if ticker in roll_dates:
            if today in roll_dates[ticker]:
                total += per_roll
        else:
            total += per_roll * inst.roll_months_per_year / m.TRADING_DAYS
    return total


def _inverse_vol_notional(run: _PairRun, runs: list[_PairRun], t: int, config: BacktestConfig) -> float:
    """Capital share ∝ 1/σ of the trailing spread, normalised over pairs with a σ today."""
    sigmas = {r.path.name: r.path.series.std[t] for r in runs}
    inv = {k: 1.0 / v for k, v in sigmas.items() if np.isfinite(v) and v > 0}
    if run.path.name not in inv:
        return config.portfolio.capital * config.portfolio.gross_leverage / max(1, len(runs))
    weight = float(inv[run.path.name] / sum(inv.values()))
    return config.portfolio.capital * config.portfolio.gross_leverage * weight


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------

def _package(
    runs: list[_PairRun], index: pd.DatetimeIndex, start_i: int, end_i: int, positions: np.ndarray,
    config: BacktestConfig, n_trials: int, trial_sharpes: np.ndarray | None, include_daily_pnl: bool,
    prices_close: pd.DataFrame,
) -> BacktestResult:
    sl = slice(start_i, end_i + 1)
    capital = config.portfolio.capital
    total_pnl = np.sum([r.pnl[sl] for r in runs], axis=0) if runs else np.zeros(end_i - start_i + 1)
    equity = m.equity_from_pnl(total_pnl, capital)
    returns = m.daily_returns(equity, capital)
    dd = m.drawdown_curve(equity)
    dstats = m.drawdown_stats(equity)
    trades = [t for r in runs for t in r.trades]
    trades.sort(key=lambda t: (t.entry_date, t.pair_name))

    total_return = float(equity[-1] / capital - 1.0)
    n_days = len(equity)
    annual = m.annualised_return(total_return, n_days)
    sr = m.sharpe(returns)
    ci = m.bootstrap_sharpe_ci(returns)
    wins = [t.net_pnl for t in trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in trades if t.net_pnl <= 0]
    exit_mix: dict[str, int] = {}
    for t in trades:
        exit_mix[t.exit_reason or "none"] = exit_mix.get(t.exit_reason or "none", 0) + 1
    bench_ret, bench_dd = _benchmark(prices_close, config, index[sl])

    metrics = BacktestMetrics(
        total_return=total_return,
        annual_return=annual,
        annual_vol=float(np.nanstd(returns, ddof=1) * math.sqrt(m.TRADING_DAYS)) if n_days > 1 else 0.0,
        sharpe=sr,
        sortino=m.sortino(returns),
        calmar=(annual / abs(dstats.max_drawdown)) if dstats.max_drawdown < 0 else None,
        max_drawdown=dstats.max_drawdown,
        max_drawdown_days=dstats.max_duration,
        cvar_95=m.cvar(returns),
        trade_count=len(trades),
        win_rate=(len(wins) / len(trades)) if trades else None,
        profit_factor=(sum(wins) / abs(sum(losses))) if losses and sum(losses) < 0 else (None if not wins else float("inf")),
        avg_hold_days=(sum(t.days_held for t in trades) / len(trades)) if trades else None,
        avg_win=(sum(wins) / len(wins)) if wins else None,
        avg_loss=(sum(losses) / len(losses)) if losses else None,
        exit_mix=exit_mix,
        time_in_market=float((positions[sl] > 0).mean()) if n_days else 0.0,
        sharpe_ci_low=ci[0] if ci else None,
        sharpe_ci_high=ci[1] if ci else None,
        deflated_sharpe_p=m.deflated_sharpe_probability(returns, n_trials=n_trials, trial_sharpes=trial_sharpes),
        trials=n_trials,
        benchmark_return=bench_ret,
        benchmark_max_drawdown=bench_dd,
    )
    if metrics.profit_factor is not None and math.isinf(metrics.profit_factor):
        metrics = metrics.model_copy(update={"profit_factor": None})

    equity_points = [
        EquityPointModel(date=d.date(), equity=float(e), drawdown=float(x), positions=int(p))
        for d, e, x, p in zip(index[sl], equity, dd, positions[sl], strict=True)
    ]

    attribution: list[PairAttribution] = []
    pair_pnl: dict[str, np.ndarray] = {}
    for r in runs:
        pnl = r.pnl[sl]
        pair_pnl[r.path.name] = pnl
        eq = m.equity_from_pnl(pnl, capital)
        tr = r.trades
        w = [t for t in tr if t.net_pnl > 0]
        attribution.append(
            PairAttribution(
                pair_name=r.path.name, net_pnl=float(pnl.sum()), trade_count=len(tr),
                win_rate=(len(w) / len(tr)) if tr else None, sharpe=m.sharpe(m.daily_returns(eq, capital)),
                max_drawdown=m.drawdown_stats(eq).max_drawdown,
                qualified_days=int(r.path.qualified[sl].sum()), total_days=int(np.isfinite(r.path.log_y[sl]).sum()),
            )
        )

    correlation: dict[str, object] = {"pairs": [], "matrix": []}
    if len(pair_pnl) >= 2:
        names = list(pair_pnl)
        with np.errstate(invalid="ignore", divide="ignore"):
            # A pair that never traded has zero variance; its row is reported as 0.
            mat = np.corrcoef(np.vstack([pair_pnl[k] for k in names]))
        mat = np.nan_to_num(mat, nan=0.0)
        correlation = {"pairs": names, "matrix": [[round(float(v), 4) for v in row] for row in mat]}

    return BacktestResult(
        metrics=metrics, equity=equity_points, trades=trades, attribution=attribution,
        correlation=correlation, sensitivity=[],
        daily_pnl_by_pair={k: [float(v) for v in arr] for k, arr in pair_pnl.items()} if include_daily_pnl else None,
    )


def _benchmark(prices_close: pd.DataFrame, config: BacktestConfig, span: pd.DatetimeIndex) -> tuple[float | None, float | None]:
    """Equal-weight buy-and-hold of the Y legs over the traded span."""
    ys = [y for y, _ in config.pairs if y in prices_close.columns]
    if not ys or len(span) < 2:
        return None, None
    block = prices_close.loc[span, ys].ffill().dropna(axis=1, how="all")
    if block.empty:
        return None, None
    rel = block / block.iloc[0]
    curve = rel.mean(axis=1).to_numpy(dtype=float)
    curve = curve[np.isfinite(curve)]
    if len(curve) < 2:
        return None, None
    return float(curve[-1] - 1.0), m.drawdown_stats(curve).max_drawdown


# ---------------------------------------------------------------------------
# Sensitivity grid + top-level entry
# ---------------------------------------------------------------------------

def run_with_sensitivity(
    prices_close: pd.DataFrame,
    config: BacktestConfig,
    *,
    prices_open: pd.DataFrame | None = None,
    roll_dates: Mapping[str, set[date]] | None = None,
) -> BacktestResult:
    """Main run plus (optionally) the entry-z × formation × exit-rule grid.

    The grid's Sharpe dispersion feeds the deflated Sharpe of the main
    run, so the headline number already pays for the search that found it.
    In integer sizing mode the fractional twin is also run to report the
    tradeability tax.
    """
    log_prices = np.log(prices_close.where(prices_close > 0))
    path_cache: dict[int, list[PairPath]] = {config.formation_window: parameter_paths(log_prices, config)}

    cells: list[SensitivityCell] = []
    trial_sharpes: list[float] = []
    if config.sensitivity:
        exit_rules: tuple[ExitRule, ...] = ("threshold", "cross_zero")
        for window in config.sensitivity_formation:
            if window not in path_cache:
                path_cache[window] = parameter_paths(log_prices, config, formation_window=window)
            for entry_z in config.sensitivity_entry_z:
                for rule in exit_rules:
                    if entry_z >= config.rules.stop_z or entry_z <= config.rules.exit_z:
                        continue
                    variant = config.model_copy(
                        update={
                            "formation_window": window, "sensitivity": False,
                            "rules": config.rules.model_copy(update={"entry_z": entry_z, "exit_rule": rule}),
                        }
                    )
                    try:
                        res = run_backtest(prices_close, variant, prices_open=prices_open, roll_dates=roll_dates, paths=path_cache[window])
                    except ValueError as exc:
                        logger.info("sensitivity cell skipped (%s, %s, %s): %s", entry_z, window, rule, exc)
                        continue
                    cells.append(
                        SensitivityCell(
                            entry_z=entry_z, formation_window=window, exit_rule=rule, sharpe=res.metrics.sharpe,
                            total_return=res.metrics.total_return, trade_count=res.metrics.trade_count,
                            max_drawdown=res.metrics.max_drawdown,
                        )
                    )
                    if res.metrics.sharpe is not None:
                        trial_sharpes.append(res.metrics.sharpe)

    n_trials = max(1, len(cells)) if config.sensitivity else 1
    main = run_backtest(
        prices_close, config, prices_open=prices_open, roll_dates=roll_dates, n_trials=n_trials,
        trial_sharpes=np.array(trial_sharpes) if trial_sharpes else None, paths=path_cache[config.formation_window],
    )
    tax: float | None = None
    if config.portfolio.sizing == "integer":
        frac_cfg = config.model_copy(update={"portfolio": config.portfolio.model_copy(update={"sizing": "fractional"})})
        frac = run_backtest(prices_close, frac_cfg, prices_open=prices_open, roll_dates=roll_dates, paths=path_cache[config.formation_window])
        tax = frac.metrics.total_return - main.metrics.total_return
    return main.model_copy(update={"sensitivity": cells, "metrics": main.metrics.model_copy(update={"tradeability_tax": tax})})
