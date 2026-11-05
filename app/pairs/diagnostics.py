"""Chart series and conditional forward-return analysis for one pair.

The forward-return table is the lab's most informative diagnostic: it
answers "when z is in this bucket, what happens to the spread over the
next k days?" without assuming any trading rule. Every statistic here is
computed from information available at the bucketed day, with the spread
parameters re-estimated on a trailing window, so the picture is honest
about look-ahead.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.pairs import stats
from app.pairs.schemas import ForwardBucket

FloatArray = stats.FloatArray

# Half-open [lo, hi) bins over z. Labels are what the UI shows.
DEFAULT_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("z < -3", -np.inf, -3.0),
    ("[-3, -2.5)", -3.0, -2.5),
    ("[-2.5, -2)", -2.5, -2.0),
    ("[-2, -1.5)", -2.0, -1.5),
    ("[-1.5, -1)", -1.5, -1.0),
    ("[-1, 1)", -1.0, 1.0),
    ("[1, 1.5)", 1.0, 1.5),
    ("[1.5, 2)", 1.5, 2.0),
    ("[2, 2.5)", 2.0, 2.5),
    ("[2.5, 3)", 2.5, 3.0),
    ("z >= 3", 3.0, np.inf),
)
DEFAULT_HORIZONS: tuple[int, ...] = (5, 10, 20)


@dataclass(frozen=True, slots=True)
class RollingSeries:
    """Per-day parameters over the pair's aligned history, all from data before t.

    `mean` / `std` are the trailing z-window moments of the in-window
    spread; together with `alpha` / `beta` they are exactly the parameters
    a trade entered at t would freeze.
    """

    index: pd.DatetimeIndex
    spread: FloatArray
    zscore: FloatArray
    alpha: FloatArray
    beta: FloatArray
    half_life: FloatArray
    z_window: FloatArray
    mean: FloatArray
    std: FloatArray
    pvalue: FloatArray


def rolling_series(
    y: FloatArray,
    x: FloatArray,
    index: pd.DatetimeIndex,
    *,
    formation_window: int,
    z_window_min: int,
    z_window_max: int,
    z_window_multiple: float = 4.0,
    hedge_method: str = "ols",
    pvalue_step: int = 5,
) -> RollingSeries:
    """Walk the history once, re-estimating α/β/HL on the trailing window.

    Parameters at day t use rows [t−W, t) — strictly before t — so the
    spread and z at t are what a trader could have known at t's close.
    p-values are stepped (`pvalue_step`) because an ADF per day over
    thousands of days is slow and the series moves slowly.
    """
    n = len(y)
    spread = np.full(n, np.nan)
    z = np.full(n, np.nan)
    alpha = np.full(n, np.nan)
    beta = np.full(n, np.nan)
    hl_arr = np.full(n, np.nan)
    zwin = np.full(n, np.nan)
    mean = np.full(n, np.nan)
    std_arr = np.full(n, np.nan)
    pval = np.full(n, np.nan)
    hedge = stats.ols_hedge if hedge_method == "ols" else stats.tls_hedge

    last_p = np.nan
    for t in range(formation_window, n):
        ywin = y[t - formation_window : t]
        xwin = x[t - formation_window : t]
        if not (np.isfinite(ywin).all() and np.isfinite(xwin).all() and np.isfinite(y[t]) and np.isfinite(x[t])):
            continue
        fit = hedge(ywin, xwin)
        alpha[t] = fit.alpha
        beta[t] = fit.beta
        spread[t] = y[t] - fit.alpha - fit.beta * x[t]
        hl = stats.half_life(fit.spread)
        if hl.half_life is not None:
            hl_arr[t] = hl.half_life
        w = stats.zscore_window(hl.half_life, lower=z_window_min, upper=z_window_max, multiple=z_window_multiple)
        zwin[t] = w
        tail = fit.spread[-w:]
        std = tail.std(ddof=1) if len(tail) > 1 else 0.0
        mean[t] = tail.mean()
        std_arr[t] = std
        if std > 1e-12:
            z[t] = (spread[t] - mean[t]) / std
        if (t - formation_window) % pvalue_step == 0:
            try:
                last_p = stats.engle_granger_pvalue(ywin, xwin)
            except (ValueError, np.linalg.LinAlgError):
                last_p = np.nan
        pval[t] = last_p
    return RollingSeries(
        index=index, spread=spread, zscore=z, alpha=alpha, beta=beta, half_life=hl_arr,
        z_window=zwin, mean=mean, std=std_arr, pvalue=pval,
    )


def forward_buckets(
    spread: FloatArray,
    zscore: FloatArray,
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    buckets: tuple[tuple[str, float, float], ...] = DEFAULT_BUCKETS,
    min_count: int = 5,
) -> list[ForwardBucket]:
    """Future spread change by z bucket and horizon.

    `hit_rate` is the share of cases where the spread moved back toward
    its trailing mean (the direction a mean-reversion trade would want),
    so a bucket with hit rate ≈ 0.5 says "no edge" regardless of the mean.
    """
    out: list[ForwardBucket] = []
    n = len(spread)
    for horizon in horizons:
        if n <= horizon:
            continue
        fwd = spread[horizon:] - spread[:-horizon]
        z_now = zscore[:-horizon]
        ok = np.isfinite(fwd) & np.isfinite(z_now)
        for label, lo, hi in buckets:
            mask = ok & (z_now >= lo) & (z_now < hi)
            count = int(mask.sum())
            if count < min_count:
                continue
            moves = fwd[mask]
            # "Toward" means the spread moved against the sign of z, i.e.
            # back toward its trailing mean — what a reversion trade needs.
            toward = np.sign(moves) == -np.sign(z_now[mask])
            out.append(
                ForwardBucket(
                    bucket=label,
                    z_low=float(lo) if np.isfinite(lo) else -9.0,
                    z_high=float(hi) if np.isfinite(hi) else 9.0,
                    horizon=horizon,
                    count=count,
                    mean=float(moves.mean()),
                    median=float(np.median(moves)),
                    p25=float(np.percentile(moves, 25)),
                    p75=float(np.percentile(moves, 75)),
                    hit_rate=float(toward.mean()),
                )
            )
    return out


def to_list(values: FloatArray) -> list[float | None]:
    """NaN-safe JSON list for chart payloads."""
    return [float(v) if np.isfinite(v) else None for v in values]
