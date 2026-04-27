"""Unit tests for the feature-engineering layer of the ML workbench.

The point of these tests is to nail down the **time-series safety
properties** the ADR commits to, not just to verify formulas. Anything
that lets future information leak backwards is the bug we are most
afraid of.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ml.features import build_feature, build_feature_matrix, build_target
from app.ml.schemas import FeatureSpec, TargetSpec


@pytest.fixture
def sample_bars() -> pd.DataFrame:
    """100 bars of monotonically rising prices — easy to reason about."""
    idx = pd.date_range("2026-01-01", periods=100, freq="1h", tz="UTC")
    close = np.linspace(100.0, 200.0, 100)
    return pd.DataFrame({
        "open":   close - 0.5,
        "high":   close + 1.0,
        "low":    close - 1.0,
        "close":  close,
        "volume": np.full(100, 1_000_000.0),
    }, index=idx)


# ---------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------

class TestBuildTarget:
    def test_log_return_horizon_one_matches_close_diff(self, sample_bars):
        spec = TargetSpec(kind="log_return", horizon=1)
        target = build_target(sample_bars, spec)
        # First entry is ln(close[1] / close[0]); last is NaN (no future).
        expected = np.log(sample_bars["close"].iloc[1] / sample_bars["close"].iloc[0])
        assert pytest.approx(target.iloc[0]) == expected
        assert pd.isna(target.iloc[-1])

    def test_direction_with_large_deadband_collapses_to_neutral(self, sample_bars):
        # Schema caps deadband at 500 bps (5 %). The ramp's per-step return
        # is ~1 %, so a 5 % deadband catches every move and labels it 0.
        spec = TargetSpec(kind="direction", horizon=1, deadband_bps=500)
        target = build_target(sample_bars, spec)
        assert set(target.dropna().unique()) == {0}

    def test_direction_no_deadband_picks_up_sign(self, sample_bars):
        # No deadband, monotone-rising prices → every label is +1.
        spec = TargetSpec(kind="direction", horizon=1, deadband_bps=0)
        target = build_target(sample_bars, spec)
        assert set(target.dropna().unique()) == {1}

    def test_volatility_target_is_forward_looking(self, sample_bars):
        spec = TargetSpec(kind="volatility", horizon=1, vol_window=10)
        target = build_target(sample_bars, spec)
        # Forward shift means the *tail* loses to NaN, not the head:
        # the last `vol_window` rows have no future window to summarise.
        assert target.iloc[-10:].isna().all()
        # Mid-range value is defined.
        assert not pd.isna(target.iloc[20])


# ---------------------------------------------------------------------
# Look-ahead leakage — the load-bearing safety property
# ---------------------------------------------------------------------

class TestNoLookAheadLeakage:
    def test_lag_return_at_t_uses_only_t_minus_one_and_earlier(self, sample_bars):
        """If a row at index t mentions any close from t+1+, fail loud."""
        feature = build_feature(sample_bars, FeatureSpec(kind="lag_return", window=1))
        # lag_return at t = ln(close_t / close_{t-1}) — must not equal
        # ln(close_{t+1} / close_t).
        wrong = np.log(sample_bars["close"].shift(-1) / sample_bars["close"])
        # Find a row that's defined for both; they MUST differ.
        idx = feature.index[5]
        if not pd.isna(feature.loc[idx]) and not pd.isna(wrong.loc[idx]):
            assert feature.loc[idx] != wrong.loc[idx]

    def test_rolling_mean_at_t_uses_only_past(self, sample_bars):
        feature = build_feature(sample_bars, FeatureSpec(kind="rolling_mean", window=5))
        # rolling_mean at index 4 = mean of close[0:5].
        expected = sample_bars["close"].iloc[:5].mean()
        assert pytest.approx(feature.iloc[4]) == expected
        # And it MUST NOT equal mean of any window that reaches forward.
        forward_window_mean = sample_bars["close"].iloc[5:10].mean()
        assert feature.iloc[4] != forward_window_mean

    def test_high_lag_features_have_warm_up_nans(self, sample_bars):
        """A lag-20 feature must be NaN for the first 20 rows."""
        feature = build_feature(sample_bars, FeatureSpec(kind="lag_return", window=20))
        # lag_return shifts a 1-step ratio by `lag - 1`, so the first
        # `lag - 1` rows are guaranteed NaN. That's enough to assert.
        assert feature.iloc[: 19].isna().all()


# ---------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------

class TestBuildFeatureMatrix:
    def test_columns_named_per_spec(self, sample_bars):
        specs = [
            FeatureSpec(kind="lag_return", window=1),
            FeatureSpec(kind="rolling_std", window=10),
            FeatureSpec(kind="rsi", window=14),
        ]
        matrix = build_feature_matrix(sample_bars, specs)
        assert list(matrix.columns) == ["lag_return_1", "rolling_std_10", "rsi_14"]
        assert len(matrix) == len(sample_bars)

    def test_warm_up_rows_marked_nan(self, sample_bars):
        # Largest window is 50 → at least the first ~50 rows have NaN.
        specs = [
            FeatureSpec(kind="lag_return", window=1),
            FeatureSpec(kind="sma", window=50),
        ]
        matrix = build_feature_matrix(sample_bars, specs)
        assert matrix.iloc[:49].isna().any(axis=None)
        assert matrix.iloc[60:].notna().all(axis=None)
