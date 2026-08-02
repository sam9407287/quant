"""Signal testing — measure an idea in isolation before backtesting it.

Per the CMT quantitative curriculum (Verdouw): a backtest bundles an
idea together with exits, stops, position size and starting capital, so
its result cannot tell you whether the *idea* has an edge — too many
degrees of freedom, path dependency, first-trade bias. A signal test
strips all of that away. It finds EVERY bar where the entry condition
fires, treats each as day 0, and measures the forward return at day
1..N across all signals. What survives is the honest question: on
average, does this signal capture a move in its direction, and how
reliably?

Outputs mirror the curriculum's signal-test report: probability of gain
(win rate), mean/median return, dispersion (std dev), the average
forward path, and a return distribution.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.strategies.engine import entry_signal
from app.strategies.schemas import StrategyDefinition


@dataclass(frozen=True, slots=True)
class SignalTestResult:
    """Aggregated forward-return profile of a strategy's entry signals."""

    signal_count: int
    horizon: int
    win_rate: float          # P(terminal return > 0) — "probability of gain"
    mean_return_pct: float   # average terminal return, %
    median_return_pct: float
    std_return_pct: float    # dispersion of terminal returns, %
    best_return_pct: float
    worst_return_pct: float
    # Average forward path: mean directional return at each day 0..horizon.
    avg_path_pct: list[float]
    # Terminal-return distribution: (bucket_center_pct, count).
    distribution: list[tuple[float, int]]


def _forward_returns(
    close: np.ndarray, idx: np.ndarray, sign: float, horizon: int
) -> np.ndarray:
    """Matrix [n_signals, horizon+1] of directional % returns from entry.

    Each row k is signal k's return at day 0..horizon relative to its
    entry close. `sign` is +1 for long signals, -1 for short, so a row
    is positive whenever price moved the way the signal predicted.
    """
    n = close.shape[0]
    rows = []
    for i in idx:
        if i + horizon >= n:
            continue  # not enough forward data — drop the tail signals
        base = close[i]
        if base == 0:
            continue
        fwd = (close[i : i + horizon + 1] - base) / base * 100.0 * sign
        rows.append(fwd)
    return np.array(rows) if rows else np.empty((0, horizon + 1))


def signal_test(
    df: pd.DataFrame, defn: StrategyDefinition, horizon: int = 21, bins: int = 21
) -> SignalTestResult:
    """Run a signal test over bars using the strategy's entry conditions.

    Both entry_long and entry_short fire signals; a short signal's
    forward return is negated so "win" always means the market moved in
    the signalled direction. No exits, stops or sizing are applied —
    that is the whole point.
    """
    if df.empty:
        return SignalTestResult(0, horizon, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, [], [])
    df = df.reset_index(drop=True)
    close = df["close"].astype(float).to_numpy()

    long_sig = entry_signal(df, defn, "long").to_numpy()
    short_sig = entry_signal(df, defn, "short").to_numpy()

    long_fwd = _forward_returns(close, np.flatnonzero(long_sig), 1.0, horizon)
    short_fwd = _forward_returns(close, np.flatnonzero(short_sig), -1.0, horizon)
    fwd = np.vstack([m for m in (long_fwd, short_fwd) if m.size]) if (
        long_fwd.size or short_fwd.size
    ) else np.empty((0, horizon + 1))

    if fwd.shape[0] == 0:
        return SignalTestResult(0, horizon, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, [], [])

    terminal = fwd[:, -1]
    avg_path = fwd.mean(axis=0).tolist()

    counts, edges = np.histogram(terminal, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2.0
    distribution = [(float(c), int(n)) for c, n in zip(centers, counts, strict=True)]

    return SignalTestResult(
        signal_count=int(fwd.shape[0]),
        horizon=horizon,
        win_rate=float((terminal > 0).mean()),
        mean_return_pct=float(terminal.mean()),
        median_return_pct=float(np.median(terminal)),
        std_return_pct=float(terminal.std(ddof=1)) if terminal.size > 1 else 0.0,
        best_return_pct=float(terminal.max()),
        worst_return_pct=float(terminal.min()),
        avg_path_pct=[float(x) for x in avg_path],
        distribution=distribution,
    )
