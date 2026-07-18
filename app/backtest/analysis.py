"""Post-run analytics over DayResult series (ADR-003 B3).

Everything here is a pure function of a result list — no DB, no RNG
state outside the seeded generator — so the same run row always
reproduces the same report. Monte Carlo is bootstrap/permutation over
the *daily* P&L series: session-level resampling is the right unit for
a one-trade-per-day strategy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt

import numpy as np

from app.backtest.types import DayResult

# Sessions where the strategy actually had market exposure. no_fill days
# are part of the played calendar (0 P&L by construction); no_data and
# ambiguous days are excluded everywhere — the strategy never ran.
_PLAYED = frozenset({"tp", "sl", "eod", "no_fill"})
_TRADED = frozenset({"tp", "sl", "eod"})

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class SummaryMetrics:
    """Headline numbers for one backtest run."""

    session_count: int
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float
    total_pnl_usd: float
    profit_factor: float | None  # None when there are no losing trades
    expectancy_usd: float
    max_drawdown_usd: float
    sharpe_annualized: float | None  # None when daily P&L has no variance
    best_day_usd: float
    worst_day_usd: float


@dataclass(frozen=True, slots=True)
class BucketStats:
    """Aggregate P&L stats for one seasonality bucket (month/weekday)."""

    bucket: int
    trade_count: int
    total_pnl_usd: float
    mean_pnl_usd: float
    win_rate: float


@dataclass(frozen=True, slots=True)
class MonteCarloReport:
    """Distribution summary of resampled equity paths."""

    n_sims: int
    horizon_days: int
    method: str
    terminal_pnl_percentiles: dict[int, float]  # {5: ..., 25: ..., 50: ...}
    max_drawdown_percentiles: dict[int, float]
    prob_terminal_loss: float
    prob_ruin: float | None  # None when no capital was given


def played_daily_pnl(results: Sequence[DayResult]) -> list[tuple[DayResult, float]]:
    """(result, daily P&L) for every session the strategy actually played."""
    return [(r, r.pnl_usd) for r in results if r.exit_reason in _PLAYED]


def equity_curve(results: Sequence[DayResult]) -> list[tuple[str, float]]:
    """Cumulative P&L per played session, ISO date keyed for the API/UI."""
    curve: list[tuple[str, float]] = []
    total = 0.0
    for r, pnl in played_daily_pnl(results):
        total += pnl
        curve.append((r.session_date.isoformat(), total))
    return curve


def max_drawdown(equity: Sequence[float]) -> float:
    """Largest peak-to-trough drop of a cumulative-P&L series, as a
    positive number. The peak starts at 0 (flat before the first day)."""
    peak = 0.0
    worst = 0.0
    for v in equity:
        peak = max(peak, v)
        worst = max(worst, peak - v)
    return worst


def summarize(results: Sequence[DayResult]) -> SummaryMetrics:
    """Headline metrics; trade stats count only sessions with exposure."""
    played = played_daily_pnl(results)
    daily = np.array([pnl for _, pnl in played], dtype=np.float64)
    trades = [r for r, _ in played if r.exit_reason in _TRADED]
    trade_pnl = np.array([t.pnl_usd for t in trades], dtype=np.float64)

    wins = trade_pnl[trade_pnl > 0]
    losses = trade_pnl[trade_pnl < 0]
    gross_win = float(wins.sum())
    gross_loss = float(-losses.sum())

    equity = list(np.cumsum(daily)) if daily.size else []
    std = float(daily.std(ddof=1)) if daily.size > 1 else 0.0

    return SummaryMetrics(
        session_count=len(played),
        trade_count=len(trades),
        win_count=int(wins.size),
        loss_count=int(losses.size),
        win_rate=float(wins.size / trade_pnl.size) if trade_pnl.size else 0.0,
        total_pnl_usd=float(daily.sum()) if daily.size else 0.0,
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else None,
        expectancy_usd=float(trade_pnl.mean()) if trade_pnl.size else 0.0,
        max_drawdown_usd=max_drawdown(equity),
        sharpe_annualized=(
            float(daily.mean() / std * sqrt(TRADING_DAYS_PER_YEAR)) if std > 0 else None
        ),
        best_day_usd=float(daily.max()) if daily.size else 0.0,
        worst_day_usd=float(daily.min()) if daily.size else 0.0,
    )


def seasonality(results: Sequence[DayResult], bucket: str) -> list[BucketStats]:
    """Group traded sessions' P&L by calendar bucket.

    bucket="month" → 1..12; bucket="weekday" → 0..6 (Monday=0). Only
    buckets that actually contain trades are returned — the UI decides
    how to render gaps.
    """
    if bucket not in {"month", "weekday"}:
        raise ValueError(f"unknown seasonality bucket: {bucket!r}")

    groups: dict[int, list[float]] = {}
    for r, pnl in played_daily_pnl(results):
        if r.exit_reason not in _TRADED:
            continue
        key = r.session_date.month if bucket == "month" else r.session_date.weekday()
        groups.setdefault(key, []).append(pnl)

    out: list[BucketStats] = []
    for key in sorted(groups):
        vals = np.array(groups[key], dtype=np.float64)
        out.append(
            BucketStats(
                bucket=key,
                trade_count=int(vals.size),
                total_pnl_usd=float(vals.sum()),
                mean_pnl_usd=float(vals.mean()),
                win_rate=float((vals > 0).sum() / vals.size),
            )
        )
    return out


_PERCENTILES = (5, 25, 50, 75, 95)


def monte_carlo(
    daily_pnl: Sequence[float],
    n_sims: int = 10_000,
    method: str = "bootstrap",
    seed: int = 42,
    horizon_days: int | None = None,
    initial_capital: float | None = None,
) -> MonteCarloReport:
    """Resample the daily P&L series into `n_sims` alternate histories.

    method="bootstrap" draws with replacement (varies the mix of days);
    method="permutation" shuffles the observed days (same P&L total,
    varies only the ordering — isolates drawdown/sequence risk). Seeded
    so a stored report is reproducible.
    """
    if method not in {"bootstrap", "permutation"}:
        raise ValueError(f"unknown monte carlo method: {method!r}")
    base = np.asarray(daily_pnl, dtype=np.float64)
    if base.size == 0:
        raise ValueError("daily_pnl is empty — nothing to resample")
    if method == "permutation" and horizon_days not in (None, base.size):
        raise ValueError("permutation keeps the observed horizon; do not set horizon_days")

    horizon = horizon_days or base.size
    rng = np.random.default_rng(seed)

    if method == "bootstrap":
        draws = rng.choice(base, size=(n_sims, horizon), replace=True)
    else:
        draws = rng.permuted(np.tile(base, (n_sims, 1)), axis=1)

    equity = np.cumsum(draws, axis=1)
    terminal = equity[:, -1]
    peaks = np.maximum.accumulate(np.maximum(equity, 0.0), axis=1)
    drawdowns = (peaks - equity).max(axis=1)

    ruin: float | None = None
    if initial_capital is not None:
        ruin = float((drawdowns >= initial_capital).mean())

    return MonteCarloReport(
        n_sims=n_sims,
        horizon_days=horizon,
        method=method,
        terminal_pnl_percentiles={
            p: float(np.percentile(terminal, p)) for p in _PERCENTILES
        },
        max_drawdown_percentiles={
            p: float(np.percentile(drawdowns, p)) for p in _PERCENTILES
        },
        prob_terminal_loss=float((terminal < 0).mean()),
        prob_ruin=ruin,
    )
