"""Cointegration and mean-reversion statistics for one pair (pure NumPy / statsmodels).

Every function here takes arrays in and returns plain values or small
dataclasses — no DB, no dates, no config objects — so each statistic can
be pinned with synthetic data and cross-checked against an independent
implementation. Conventions:

* Inputs are **log prices** aligned on the same trading days.
* `y` is the dependent leg, `x` the hedge leg: `log Y = α + β log X + ε`.
* The spread is the OLS residual `s_t = log Y_t − α − β log X_t`.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from statsmodels.tsa.stattools import adfuller, coint
from statsmodels.tsa.vector_ar.vecm import coint_johansen

FloatArray = NDArray[np.float64]

# OU regressions on fewer points than this are noise; callers treat the
# result as "not estimable" rather than trading on it.
MIN_POINTS = 30


# ---------------------------------------------------------------------------
# Hedge ratio
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class HedgeFit:
    """Intercept, slope and residual spread of one hedge regression."""

    alpha: float
    beta: float
    spread: FloatArray
    method: str  # 'ols' | 'tls'


def ols_hedge(y: FloatArray, x: FloatArray) -> HedgeFit:
    """Ordinary least squares `y = α + β x` (the Engle-Granger first stage)."""
    _check_pair(y, x)
    design = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    alpha, beta = float(coef[0]), float(coef[1])
    return HedgeFit(alpha=alpha, beta=beta, spread=y - alpha - beta * x, method="ols")


def tls_hedge(y: FloatArray, x: FloatArray) -> HedgeFit:
    """Total least squares (orthogonal regression) hedge ratio.

    OLS treats x as error-free, which is why β(Y on X) ≠ 1/β(X on Y). TLS
    minimises perpendicular distance and is symmetric: the same line comes
    out whichever leg is called Y. Reported next to OLS, never instead.
    """
    _check_pair(y, x)
    xm, ym = x.mean(), y.mean()
    cov = np.cov(np.vstack([x - xm, y - ym]), bias=True)
    sxx, syy, sxy = cov[0, 0], cov[1, 1], cov[0, 1]
    if abs(sxy) < 1e-18:
        beta = 0.0
    else:
        beta = float((syy - sxx + math.sqrt((syy - sxx) ** 2 + 4 * sxy**2)) / (2 * sxy))
    alpha = float(ym - beta * xm)
    return HedgeFit(alpha=alpha, beta=beta, spread=y - alpha - beta * x, method="tls")


def _check_pair(y: FloatArray, x: FloatArray) -> None:
    if y.shape != x.shape or y.ndim != 1:
        raise ValueError("y and x must be 1-D arrays of equal length")
    if len(y) < 3:
        raise ValueError("need at least 3 observations")
    if not (np.isfinite(y).all() and np.isfinite(x).all()):
        raise ValueError("inputs contain NaN or inf")


# ---------------------------------------------------------------------------
# Cointegration evidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CointegrationEvidence:
    """Every test the lab runs on one ordered pair, reported side by side."""

    eg_pvalue: float          # Engle-Granger, y regressed on x
    eg_pvalue_reverse: float  # Engle-Granger, x regressed on y
    adf_pvalue: float         # ADF on the OLS spread (no trend, AIC lags)
    johansen_trace: float
    johansen_crit_95: float
    johansen_pass: bool
    hurst: float | None


def engle_granger_pvalue(y: FloatArray, x: FloatArray) -> float:
    """p-value of the Engle-Granger cointegration test (statsmodels `coint`)."""
    _check_pair(y, x)
    _, pvalue, _ = coint(y, x, trend="c", autolag="aic")
    return float(pvalue)


def adf_pvalue(series: FloatArray) -> float:
    """ADF p-value of a spread (constant, no trend). NaN if degenerate."""
    if len(series) < MIN_POINTS or np.std(series) < 1e-12:
        return float("nan")
    try:
        result = adfuller(series, regression="c", autolag="aic")
    except (ValueError, np.linalg.LinAlgError):
        return float("nan")
    return float(result[1])


def _johansen(y: FloatArray, x: FloatArray) -> object:
    # statsmodels occasionally solves the eigenproblem in complex arithmetic
    # with a zero imaginary part and warns when it casts back; the real
    # part is the statistic, so the warning is noise here.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=np.exceptions.ComplexWarning)
        return coint_johansen(np.column_stack([y, x]), det_order=0, k_ar_diff=1)


def johansen_trace(y: FloatArray, x: FloatArray) -> tuple[float, float]:
    """Johansen trace statistic for rank 0 and its 95 % critical value."""
    _check_pair(y, x)
    res = _johansen(y, x)
    return float(np.real(res.lr1[0])), float(res.cvt[0, 1])  # type: ignore[attr-defined]


def johansen_hedge(y: FloatArray, x: FloatArray) -> float | None:
    """Hedge ratio implied by the first Johansen eigenvector (−v_x / v_y)."""
    _check_pair(y, x)
    res = _johansen(y, x)
    v = np.real(res.evec[:, 0])  # type: ignore[attr-defined]
    if abs(v[0]) < 1e-12:
        return None
    return float(-v[1] / v[0])


def hurst_exponent(series: FloatArray, max_lag: int = 20) -> float | None:
    """Variance-of-differences Hurst estimate; < 0.5 means mean reverting.

    The classic `log(std(Δ_τ)) ~ H log τ` regression over τ = 2..max_lag.
    It is a rough, scale-dependent estimate, which is why it is one voice in
    the evidence table rather than a gate.
    """
    n = len(series)
    if n < max_lag * 4:
        return None
    lags = np.arange(2, max_lag + 1)
    tau = np.array([np.std(series[lag:] - series[:-lag]) for lag in lags])
    if (tau <= 0).any():
        return None
    slope = np.polyfit(np.log(lags), np.log(tau), 1)[0]
    return float(slope)


def cointegration_evidence(y: FloatArray, x: FloatArray) -> CointegrationEvidence:
    """Run the full evidence stack on one ordered pair."""
    fit = ols_hedge(y, x)
    trace, crit = johansen_trace(y, x)
    return CointegrationEvidence(
        eg_pvalue=engle_granger_pvalue(y, x),
        eg_pvalue_reverse=engle_granger_pvalue(x, y),
        adf_pvalue=adf_pvalue(fit.spread),
        johansen_trace=trace,
        johansen_crit_95=crit,
        johansen_pass=trace > crit,
        hurst=hurst_exponent(fit.spread),
    )


# ---------------------------------------------------------------------------
# Half-life (Ornstein-Uhlenbeck)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class HalfLife:
    """OU mean-reversion speed and the half-life it implies."""

    lam: float             # slope of Δs_t on s_{t−1}; < 0 means reverting
    half_life: float | None  # None when λ ≥ 0 (no reversion)
    ci_low: float | None
    ci_high: float | None


def half_life(spread: FloatArray) -> HalfLife:
    """Estimate `Δs_t = λ s_{t−1} + c`; HL = −ln 2 / λ when λ < 0."""
    if len(spread) < MIN_POINTS:
        return HalfLife(lam=float("nan"), half_life=None, ci_low=None, ci_high=None)
    lam = _ou_lambda(spread)
    return HalfLife(lam=lam, half_life=_hl_from_lambda(lam), ci_low=None, ci_high=None)


def half_life_with_ci(
    spread: FloatArray, *, n_boot: int = 200, block: int = 20, seed: int = 7
) -> HalfLife:
    """Half-life plus a block-bootstrap 90 % interval.

    Point estimates of HL on two years of data are wide; the interval keeps
    "HL = 8" from being read as a precise number. Blocks preserve the serial
    dependence that makes the estimate noisy in the first place.
    """
    base = half_life(spread)
    if base.half_life is None or len(spread) < block * 3:
        return base
    rng = np.random.default_rng(seed)
    n = len(spread)
    n_blocks = math.ceil(n / block)
    samples: list[float] = []
    for _ in range(n_boot):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        boot = np.concatenate([spread[s : s + block] for s in starts])[:n]
        hl = _hl_from_lambda(_ou_lambda(boot))
        if hl is not None and np.isfinite(hl):
            samples.append(hl)
    if len(samples) < 20:
        return base
    lo, hi = np.percentile(samples, [5, 95])
    return HalfLife(lam=base.lam, half_life=base.half_life, ci_low=float(lo), ci_high=float(hi))


def _ou_lambda(spread: FloatArray) -> float:
    lagged = spread[:-1]
    delta = np.diff(spread)
    design = np.column_stack([lagged, np.ones_like(lagged)])
    coef, *_ = np.linalg.lstsq(design, delta, rcond=None)
    return float(coef[0])


def _hl_from_lambda(lam: float) -> float | None:
    if not np.isfinite(lam) or lam >= 0:
        return None
    return float(-math.log(2) / lam)


# ---------------------------------------------------------------------------
# z-score
# ---------------------------------------------------------------------------

def zscore_window(hl: float | None, *, lower: int = 10, upper: int = 60) -> int:
    """`clip(round(2·HL), lower, upper)`; the upper bound when HL is unknown."""
    if hl is None or not np.isfinite(hl):
        return upper
    return int(min(max(round(2 * hl), lower), upper))


def rolling_zscore(spread: FloatArray, window: int) -> FloatArray:
    """z of each point against the trailing `window` points **including** it.

    Callers wanting strict t−1 information shift the result by one; the
    walk-forward engine does exactly that so the convention lives in one
    place.
    """
    n = len(spread)
    out = np.full(n, np.nan)
    if window < 2 or n < window:
        return out
    cs = np.cumsum(np.insert(spread, 0, 0.0))
    cs2 = np.cumsum(np.insert(spread**2, 0, 0.0))
    idx = np.arange(window, n + 1)
    mean = (cs[idx] - cs[idx - window]) / window
    var = (cs2[idx] - cs2[idx - window]) / window - mean**2
    std = np.sqrt(np.maximum(var, 0.0)) * math.sqrt(window / (window - 1))
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (spread[window - 1 :] - mean) / std
    out[window - 1 :] = np.where(std > 1e-12, z, np.nan)
    return out


def ewma_zscore(spread: FloatArray, span: int) -> FloatArray:
    """z against an exponentially weighted mean and std (alternative view)."""
    n = len(spread)
    out = np.full(n, np.nan)
    if n < 3:
        return out
    alpha = 2.0 / (span + 1)
    mean = spread[0]
    var = 0.0
    for i in range(1, n):
        diff = spread[i] - mean
        mean += alpha * diff
        var = (1 - alpha) * (var + alpha * diff * diff)
        if i >= span - 1 and var > 1e-18:
            out[i] = (spread[i] - mean) / math.sqrt(var)
    return out


def frozen_zscore(spread_value: float, mean: float, std: float) -> float:
    """z of a new spread value against parameters frozen at entry."""
    if std <= 1e-12 or not np.isfinite(std):
        return float("nan")
    return float((spread_value - mean) / std)


# ---------------------------------------------------------------------------
# Multiple testing
# ---------------------------------------------------------------------------

def benjamini_hochberg(pvalues: FloatArray) -> FloatArray:
    """BH-adjusted q-values; NaN inputs stay NaN and are excluded from m."""
    p = np.asarray(pvalues, dtype=float)
    out = np.full(p.shape, np.nan)
    mask = np.isfinite(p)
    m = int(mask.sum())
    if m == 0:
        return out
    vals = p[mask]
    order = np.argsort(vals)
    ranked = vals[order] * m / (np.arange(m) + 1)
    # Enforce monotonicity from the largest rank down, cap at 1.
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    q = np.minimum(q, 1.0)
    adjusted = np.empty(m)
    adjusted[order] = q
    out[mask] = adjusted
    return out


# ---------------------------------------------------------------------------
# Stability of the relationship over time
# ---------------------------------------------------------------------------

def rolling_eg_pvalues(
    y: FloatArray, x: FloatArray, *, window: int, lookback: int, step: int = 1
) -> FloatArray:
    """EG p-value at each of the last `lookback` days using a trailing window.

    Expensive (one regression + ADF per day), so screening only calls it
    for pairs that already pass the point-in-time filters. Returns NaN
    where the window does not fit.
    """
    n = len(y)
    out = np.full(lookback, np.nan)
    for k in range(0, lookback, step):
        end = n - (lookback - 1 - k)
        start = end - window
        if start < 0 or end - start < MIN_POINTS:
            continue
        try:
            out[k] = engle_granger_pvalue(y[start:end], x[start:end])
        except (ValueError, np.linalg.LinAlgError):
            out[k] = np.nan
    if step > 1:
        # Fill the skipped days with the most recent computed value.
        last = np.nan
        for k in range(lookback):
            if np.isfinite(out[k]):
                last = out[k]
            else:
                out[k] = last
    return out


def rolling_beta(y: FloatArray, x: FloatArray, *, window: int, lookback: int) -> FloatArray:
    """OLS β at each of the last `lookback` days over a trailing window."""
    n = len(y)
    out = np.full(lookback, np.nan)
    for k in range(lookback):
        end = n - (lookback - 1 - k)
        start = end - window
        if start < 0:
            continue
        out[k] = ols_hedge(y[start:end], x[start:end]).beta
    return out


def coefficient_of_variation(values: FloatArray) -> float:
    """|std / mean| of a β path; NaN when the mean is ~0 or nothing finite."""
    v = values[np.isfinite(values)]
    if len(v) < 2 or abs(v.mean()) < 1e-12:
        return float("nan")
    return float(abs(v.std(ddof=1) / v.mean()))
