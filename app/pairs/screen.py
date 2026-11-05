"""Scan a set of ordered pairs and decide which qualify (ADR-010 §2.3).

Pure over an aligned log-price matrix: the API and the daily job load
prices, call `scan_pairs`, and persist what comes back. Point-in-time
statistics run for every pair; the expensive rolling stability test runs
only for pairs that pass the cheap filters, which is what keeps a
full-universe scan (≈1.8k ordered pairs) within seconds-to-minutes.
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Iterable, Sequence
from datetime import date

import numpy as np
import pandas as pd

from app.pairs import stats
from app.pairs.schemas import PairStatsModel, QualificationRules, ScanConfig
from app.pairs.universe import DEFAULT_PAIRS, UNIVERSE

logger = logging.getLogger(__name__)


def pair_name(y: str, x: str) -> str:
    """Display name: tickers without the yfinance futures suffix."""
    return f"{y.removesuffix('=F')}/{x.removesuffix('=F')}"


def candidate_pairs(config: ScanConfig, watchlist: Sequence[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    """Resolve the config's mode into the ordered (y, x) pairs to scan."""
    if config.mode == "explicit":
        pairs = list(config.pairs)
    elif config.mode == "watchlist":
        pairs = list(watchlist) if watchlist is not None else [(p.y, p.x) for p in DEFAULT_PAIRS]
    else:
        tickers = config.tickers or list(UNIVERSE)
        pairs = [(y, x) for y, x in itertools.permutations(tickers, 2)]
    return pairs[: config.max_pairs]


def pair_window(logp: pd.DataFrame, y: str, x: str, as_of: date | None, window: int) -> pd.DataFrame | None:
    """The last `window` aligned rows at or before `as_of`, or None if short."""
    if y not in logp.columns or x not in logp.columns:
        return None
    frame = logp[[y, x]].dropna()
    if as_of is not None:
        frame = frame[frame.index <= pd.Timestamp(as_of)]
    if len(frame) < max(stats.MIN_POINTS, min(window, 120)):
        return None
    return frame.iloc[-window:]


def evaluate_pair(
    logp: pd.DataFrame,
    y: str,
    x: str,
    config: ScanConfig,
    *,
    roll_gap_days: int = 0,
    quality_flags: Iterable[str] = (),
    stability: bool = True,
) -> PairStatsModel | None:
    """Full statistics for one ordered pair as of the config's date."""
    frame = pair_window(logp, y, x, config.as_of, config.formation_window)
    if frame is None:
        return None
    ya = frame[y].to_numpy(dtype=float)
    xa = frame[x].to_numpy(dtype=float)
    as_of = frame.index[-1].date()

    fit = stats.ols_hedge(ya, xa) if config.hedge_method == "ols" else stats.tls_hedge(ya, xa)
    tls = stats.tls_hedge(ya, xa)
    evidence = stats.cointegration_evidence(ya, xa)
    hl = stats.half_life_with_ci(fit.spread)
    z_window = stats.zscore_window(
        hl.half_life, lower=config.z_window_min, upper=config.z_window_max, multiple=config.z_window_multiple
    )
    zs = stats.rolling_zscore(fit.spread, z_window)
    z_last = float(zs[-1]) if np.isfinite(zs[-1]) else None
    tail = fit.spread[-z_window:]
    try:
        beta_j = stats.johansen_hedge(ya, xa)
    except (ValueError, np.linalg.LinAlgError):
        beta_j = None

    ret_y = np.diff(ya[-61:])
    ret_x = np.diff(xa[-61:])
    corr = float(np.corrcoef(ret_y, ret_x)[0, 1]) if len(ret_y) >= 20 else None

    rules = config.rules
    reasons = _point_in_time_reasons(evidence, hl, fit.beta, rules)

    stability_ratio: float | None = None
    beta_cv: float | None = None
    if stability and not reasons:
        # Only pairs that pass the cheap filters pay for the rolling tests.
        full = logp[[y, x]].dropna()
        if config.as_of is not None:
            full = full[full.index <= pd.Timestamp(config.as_of)]
        yf = full[y].to_numpy(dtype=float)
        xf = full[x].to_numpy(dtype=float)
        pvals = stats.rolling_eg_pvalues(
            yf, xf, window=config.formation_window, lookback=rules.stability_lookback, step=config.stability_step
        )
        finite = pvals[np.isfinite(pvals)]
        if len(finite):
            stability_ratio = float((finite < rules.eg_pvalue_max).mean())
        betas = stats.rolling_beta(yf, xf, window=config.formation_window, lookback=rules.stability_lookback)
        beta_cv = stats.coefficient_of_variation(betas)
        if stability_ratio is None or stability_ratio < rules.stability_min_ratio:
            reasons.append(f"stability {stability_ratio if stability_ratio is not None else 'n/a'} < {rules.stability_min_ratio}")
        if beta_cv is not None and np.isfinite(beta_cv) and beta_cv > rules.beta_cv_max:
            reasons.append(f"beta cv {beta_cv:.2f} > {rules.beta_cv_max}")

    return PairStatsModel(
        pair_name=pair_name(y, x),
        y_ticker=y,
        x_ticker=x,
        as_of=as_of,
        n_obs=len(frame),
        alpha=fit.alpha,
        beta=fit.beta,
        beta_tls=tls.beta,
        beta_johansen=beta_j,
        eg_pvalue=evidence.eg_pvalue,
        eg_pvalue_reverse=evidence.eg_pvalue_reverse,
        adf_pvalue=_nan_to_none(evidence.adf_pvalue),
        johansen_trace=evidence.johansen_trace,
        johansen_crit_95=evidence.johansen_crit_95,
        johansen_pass=evidence.johansen_pass,
        hurst=evidence.hurst,
        half_life=hl.half_life,
        half_life_ci_low=hl.ci_low,
        half_life_ci_high=hl.ci_high,
        z_window=z_window,
        z=z_last,
        spread_last=float(fit.spread[-1]),
        spread_mean=float(tail.mean()),
        spread_std=float(tail.std(ddof=1)) if len(tail) > 1 else None,
        stability_ratio=stability_ratio,
        beta_cv=_nan_to_none(beta_cv),
        corr_returns_60d=corr,
        qualified=not reasons,
        reasons=reasons,
        roll_gap_days=roll_gap_days,
        quality_flags=list(quality_flags),
    )


def _point_in_time_reasons(
    evidence: stats.CointegrationEvidence, hl: stats.HalfLife, beta: float, rules: QualificationRules
) -> list[str]:
    reasons: list[str] = []
    if not (evidence.eg_pvalue < rules.eg_pvalue_max):
        reasons.append(f"EG p {evidence.eg_pvalue:.3f} >= {rules.eg_pvalue_max}")
    if hl.half_life is None:
        reasons.append("no mean reversion (lambda >= 0)")
    elif not (rules.half_life_min <= hl.half_life <= rules.half_life_max):
        reasons.append(f"half-life {hl.half_life:.1f}d outside [{rules.half_life_min}, {rules.half_life_max}]")
    if rules.require_positive_beta and beta <= 0:
        reasons.append(f"beta {beta:.3f} <= 0")
    if rules.require_johansen and not evidence.johansen_pass:
        reasons.append("Johansen trace below 95% critical value")
    return reasons


def scan_pairs(
    logp: pd.DataFrame,
    pairs: Sequence[tuple[str, str]],
    config: ScanConfig,
    *,
    roll_gaps: dict[str, int] | None = None,
    quality_flags: dict[str, list[str]] | None = None,
) -> list[PairStatsModel]:
    """Evaluate every pair, attach BH q-values, sort qualified first by |z|."""
    results: list[PairStatsModel] = []
    for y, x in pairs:
        try:
            gaps = (roll_gaps or {}).get(y, 0) + (roll_gaps or {}).get(x, 0)
            flags = (quality_flags or {}).get(y, []) + (quality_flags or {}).get(x, [])
            res = evaluate_pair(logp, y, x, config, roll_gap_days=gaps, quality_flags=flags)
        except (ValueError, np.linalg.LinAlgError) as exc:
            logger.warning("pair %s/%s skipped: %s", y, x, exc)
            continue
        if res is not None:
            results.append(res)

    if results:
        q = stats.benjamini_hochberg(np.array([r.eg_pvalue for r in results]))
        results = [r.model_copy(update={"eg_qvalue": _nan_to_none(float(qv))}) for r, qv in zip(results, q, strict=True)]

    results.sort(key=lambda r: (not r.qualified, -abs(r.z) if r.z is not None else 0.0))
    return results


def _nan_to_none(v: float | None) -> float | None:
    if v is None:
        return None
    return None if not np.isfinite(v) else float(v)
