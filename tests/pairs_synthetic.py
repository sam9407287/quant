"""Synthetic series generators shared by the pairs-lab tests and the smoke script.

Two worlds: a genuinely cointegrated pair with known β and OU half-life,
and two independent random walks that must *not* pass. Deterministic by
seed so failures reproduce.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def cointegrated_pair(
    n: int = 1500,
    *,
    beta: float = 1.3,
    alpha: float = 0.2,
    half_life: float = 10.0,
    spread_sigma: float = 0.01,
    x_sigma: float = 0.01,
    seed: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """log X is a random walk; log Y = α + β log X + OU spread with the given HL."""
    rng = np.random.default_rng(seed)
    x = np.cumsum(rng.normal(0, x_sigma, n)) + 5.0
    phi = math.exp(-math.log(2) / half_life)
    s = np.empty(n)
    s[0] = 0.0
    eps = rng.normal(0, spread_sigma, n)
    for t in range(1, n):
        s[t] = phi * s[t - 1] + eps[t]
    y = alpha + beta * x + s
    return y, x


def independent_walks(n: int = 1500, *, seed: int = 2) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    y = np.cumsum(rng.normal(0, 0.01, n)) + 4.0
    x = np.cumsum(rng.normal(0, 0.01, n)) + 5.0
    return y, x


def business_index(n: int, start: str = "2018-01-02") -> pd.DatetimeIndex:
    return pd.bdate_range(start=start, periods=n)


def log_price_frame(columns: dict[str, np.ndarray], start: str = "2018-01-02") -> pd.DataFrame:
    n = len(next(iter(columns.values())))
    return pd.DataFrame(columns, index=business_index(n, start))


def price_frame(columns: dict[str, np.ndarray], start: str = "2018-01-02") -> pd.DataFrame:
    """exp() of log series — the shape `load_wide_prices` returns."""
    return np.exp(log_price_frame(columns, start))
