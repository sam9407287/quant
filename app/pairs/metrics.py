"""Performance statistics for a daily P&L stream (pure NumPy / SciPy).

Everything is expressed on simple daily returns of the running equity so
pairs, portfolios and the benchmark are comparable. Sharpe-type numbers
come with the honesty tools the brief asked for: a block-bootstrap
interval and the deflated Sharpe probability of Bailey & López de Prado,
which discounts the best of N trials.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

from app.pairs.stats import FloatArray

TRADING_DAYS = 252


@dataclass(frozen=True, slots=True)
class DrawdownStats:
    max_drawdown: float   # as a negative fraction of the running peak
    max_duration: int     # days from peak to recovery (or to the end)


def equity_from_pnl(pnl: FloatArray, capital: float) -> FloatArray:
    return capital + np.cumsum(pnl)


def daily_returns(equity: FloatArray, capital: float) -> FloatArray:
    prev = np.concatenate([[capital], equity[:-1]])
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(prev > 0, equity / prev - 1.0, 0.0)
    return r


def drawdown_curve(equity: FloatArray) -> FloatArray:
    peak = np.maximum.accumulate(equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(peak > 0, equity / peak - 1.0, 0.0)


def drawdown_stats(equity: FloatArray) -> DrawdownStats:
    if len(equity) == 0:
        return DrawdownStats(0.0, 0)
    dd = drawdown_curve(equity)
    max_dd = float(dd.min()) if len(dd) else 0.0
    longest = 0
    current = 0
    for v in dd:
        if v < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return DrawdownStats(max_drawdown=max_dd, max_duration=longest)


def annualised_return(total_return: float, n_days: int) -> float:
    if n_days <= 0 or total_return <= -1:
        return -1.0 if total_return <= -1 else 0.0
    return float((1.0 + total_return) ** (TRADING_DAYS / n_days) - 1.0)


def sharpe(returns: FloatArray) -> float | None:
    r = returns[np.isfinite(returns)]
    if len(r) < 2:
        return None
    sd = r.std(ddof=1)
    if sd <= 1e-15:
        return None
    return float(r.mean() / sd * math.sqrt(TRADING_DAYS))


def sortino(returns: FloatArray) -> float | None:
    r = returns[np.isfinite(returns)]
    if len(r) < 2:
        return None
    downside = np.minimum(r, 0.0)
    dd = math.sqrt((downside**2).mean())
    if dd <= 1e-15:
        return None
    return float(r.mean() / dd * math.sqrt(TRADING_DAYS))


def cvar(returns: FloatArray, level: float = 0.95) -> float:
    r = np.sort(returns[np.isfinite(returns)])
    if len(r) == 0:
        return 0.0
    k = max(1, int(math.floor((1 - level) * len(r))))
    return float(r[:k].mean())


def bootstrap_sharpe_ci(
    returns: FloatArray, *, n_boot: int = 500, block: int = 20, seed: int = 11
) -> tuple[float, float] | None:
    """5–95 % block-bootstrap interval of the annualised Sharpe."""
    r = returns[np.isfinite(returns)]
    n = len(r)
    if n < block * 3:
        return None
    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(n / block)
    out: list[float] = []
    for _ in range(n_boot):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        sample = np.concatenate([r[s : s + block] for s in starts])[:n]
        s = sharpe(sample)
        if s is not None:
            out.append(s)
    if len(out) < 20:
        return None
    lo, hi = np.percentile(out, [5, 95])
    return float(lo), float(hi)


def deflated_sharpe_probability(
    returns: FloatArray, *, n_trials: int = 1, trial_sharpes: FloatArray | None = None
) -> float | None:
    """Probability the true Sharpe exceeds the best-of-N null (Bailey & LdP 2014).

    With one trial this is the probabilistic Sharpe ratio against zero.
    With several, the benchmark is the expected maximum Sharpe of N
    independent zero-skill strategies whose dispersion is the observed
    spread of the trial Sharpes.
    """
    r = returns[np.isfinite(returns)]
    t = len(r)
    if t < 30:
        return None
    sd = r.std(ddof=1)
    if sd <= 1e-15:
        return None
    sr = float(r.mean() / sd)  # per period
    m3 = float(((r - r.mean()) ** 3).mean() / sd**3)
    m4 = float(((r - r.mean()) ** 4).mean() / sd**4)

    sr0 = 0.0
    if n_trials > 1:
        if trial_sharpes is not None and len(trial_sharpes) > 1:
            finite = trial_sharpes[np.isfinite(trial_sharpes)] / math.sqrt(TRADING_DAYS)
            var = float(finite.var(ddof=1)) if len(finite) > 1 else 0.0
        else:
            var = (1.0 + 0.5 * sr**2) / t
        gamma = 0.5772156649
        sr0 = math.sqrt(max(var, 0.0)) * (
            (1 - gamma) * norm.ppf(1 - 1.0 / n_trials) + gamma * norm.ppf(1 - 1.0 / (n_trials * math.e))
        )
    denom = math.sqrt(max(1 - m3 * sr + (m4 - 1) / 4.0 * sr**2, 1e-12))
    stat = (sr - sr0) * math.sqrt(t - 1) / denom
    return float(norm.cdf(stat))
