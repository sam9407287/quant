"""Feature engineering for the ML workbench.

Every helper here:
  * takes an OHLCV DataFrame indexed by an ascending UTC timestamp,
  * never reaches forward in time (look-ahead leakage is an instant
    disqualifier in time-series ML),
  * returns a single Series whose index matches the input.

The orchestrator in `pipeline.py` composes these into the final
feature matrix, then drops the warm-up rows where any window has
not yet filled.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.ml.schemas import FeatureSpec, TargetSpec

# ---------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------

def build_target(df: pd.DataFrame, spec: TargetSpec) -> pd.Series:
    """Materialise the prediction target.

    Targets are forward-looking by definition (we predict the future),
    so this is the *only* place where a positive shift is allowed.
    Every feature must look strictly backwards.
    """
    close = df["close"].astype(float)

    if spec.kind == "log_return":
        # log return from t to t+horizon
        future = close.shift(-spec.horizon)
        target = np.log(future / close)
    elif spec.kind == "simple_return":
        future = close.shift(-spec.horizon)
        target = (future - close) / close
    elif spec.kind == "direction":
        future = close.shift(-spec.horizon)
        ret = (future - close) / close
        deadband = spec.deadband_bps / 1e4
        # Start from `ret` itself so NaN at the tail propagates — without
        # this, the last horizon rows get the default fill and contaminate
        # the train set with synthetic neutral labels.
        target = ret.where(ret.isna(), other=0.0).astype(float)
        target[ret > deadband] = 1.0
        target[ret < -deadband] = -1.0
    elif spec.kind == "volatility":
        # Realised vol over the next `vol_window` bars.
        # Built from forward log returns then std-aggregated, so this
        # is unambiguously a future quantity.
        log_ret = np.log(close / close.shift(1))
        target = log_ret.rolling(spec.vol_window).std().shift(-spec.vol_window)
    else:  # pragma: no cover — exhausted by Literal
        raise ValueError(f"unknown target kind: {spec.kind}")

    return target.rename(f"target_{spec.kind}_h{spec.horizon}")


# ---------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------

def _log_return(close: pd.Series, lag: int) -> pd.Series:
    """Backward log return: ln(close_{t-lag+1} / close_{t-lag})."""
    # log_return at time t describes the move ending at t. To prevent
    # leakage we want the *most recent* observable return, which means
    # we use shift(lag-1) on the raw 1-step log return.
    one_step = np.log(close / close.shift(1))
    return one_step.shift(lag - 1)


def _rsi(close: pd.Series, window: int) -> pd.Series:
    """Relative Strength Index over `window` bars (Wilder smoothing)."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def build_feature(df: pd.DataFrame, spec: FeatureSpec) -> pd.Series:
    """Materialise one feature according to its spec."""
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)
    w = spec.window
    name_suffix = f"_{w}" if w > 1 else ""

    if spec.kind == "lag_return":
        return _log_return(close, w).rename(f"lag_return_{w}")
    if spec.kind == "rolling_mean":
        return close.rolling(w).mean().rename(f"rolling_mean{name_suffix}")
    if spec.kind == "rolling_std":
        return close.rolling(w).std().rename(f"rolling_std{name_suffix}")
    if spec.kind == "rolling_min":
        return close.rolling(w).min().rename(f"rolling_min{name_suffix}")
    if spec.kind == "rolling_max":
        return close.rolling(w).max().rename(f"rolling_max{name_suffix}")
    if spec.kind == "rsi":
        return _rsi(close, w).rename(f"rsi_{w}")
    if spec.kind == "ema":
        return close.ewm(span=w, adjust=False).mean().rename(f"ema_{w}")
    if spec.kind == "sma":
        return close.rolling(w).mean().rename(f"sma_{w}")
    if spec.kind == "volume_ratio":
        # current volume / rolling mean volume — a normalised liquidity
        # signal that is comparable across instruments.
        avg = volume.rolling(w).mean()
        return (volume / avg).rename(f"volume_ratio_{w}")
    if spec.kind == "high_low_spread":
        return ((high - low) / close).rename(f"hl_spread{name_suffix}")
    raise ValueError(f"unknown feature kind: {spec.kind}")


def build_feature_matrix(
    df: pd.DataFrame, feature_specs: list[FeatureSpec]
) -> pd.DataFrame:
    """Compose all requested features into a single aligned DataFrame.

    The result has the same index as `df`. Rows containing NaNs from
    warm-up windows are intentionally **not** dropped here — the
    orchestrator drops them after assembling target + features so the
    target's own warm-up is also accounted for in one pass.
    """
    series = [build_feature(df, spec) for spec in feature_specs]
    return pd.concat(series, axis=1)
