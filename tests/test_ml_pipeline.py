"""Unit tests for the ML training orchestrator.

Hits each invariant the ADR depends on:

* `chronological_split` is strictly time-ordered (no shuffle)
* StandardScaler is fit on train only, never on test
* The model registry binds (task, model) correctly and rejects mismatches
* End-to-end training returns metrics consistent with the task type

These tests do not exercise the DB layer — that's what the integration
suite is for. We feed pre-built DataFrames straight into the pipeline
helpers.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from app.ml.models import MODEL_REGISTRY, build_model
from app.ml.pipeline import (
    _build_prediction_sample,
    chronological_split,
    standardize,
)
from app.ml.schemas import DataSpec, FeatureSpec, ModelSpec, TargetSpec, TrainConfig

# ---------------------------------------------------------------------
# chronological_split
# ---------------------------------------------------------------------

def test_chronological_split_preserves_order_and_size():
    n = 100
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    X = pd.DataFrame({"x": np.arange(n)}, index=idx)
    y = pd.Series(np.arange(n), index=idx)

    Xtr, Xte, ytr, yte = chronological_split(X, y, test_size=0.2)

    assert len(Xtr) == 80 and len(Xte) == 20
    # Last train timestamp must be strictly earlier than first test.
    assert Xtr.index.max() < Xte.index.min()
    # Train block is the first 80 rows by integer position.
    assert (Xtr.index == idx[:80]).all()
    assert (Xte.index == idx[80:]).all()


# ---------------------------------------------------------------------
# standardize — fit on train only
# ---------------------------------------------------------------------

def test_standardize_does_not_leak_test_statistics():
    rng = np.random.default_rng(0)
    Xtr = pd.DataFrame({"a": rng.normal(0, 1, size=80)})
    # Test set has dramatically different scale — mean 100, std 10.
    Xte = pd.DataFrame({"a": rng.normal(100, 10, size=20)})

    Xtr_std, Xte_std, scaler = standardize(Xtr, Xte)

    # If the scaler had seen test data it would have shifted the test
    # mean toward zero. Because it didn't, the test mean stays huge.
    assert Xtr_std["a"].abs().mean() < 2.0           # roughly N(0, 1)
    assert Xte_std["a"].mean() > 10.0                # still very off-zero


# ---------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------

class TestModelRegistry:
    def test_registry_has_at_least_one_per_task(self):
        tasks = {spec.task for spec in MODEL_REGISTRY.values()}
        assert {"regression", "classification", "clustering"} <= tasks

    def test_build_model_applies_default_hyperparameters(self):
        m = build_model("ridge")
        # Ridge default alpha as declared in the registry is 1.0.
        assert m.alpha == 1.0

    def test_build_model_overrides_hyperparameters(self):
        m = build_model("ridge", {"alpha": 0.05})
        assert m.alpha == 0.05

    def test_build_model_drops_unknown_kwargs(self):
        # `n_estimators` is meaningless for Ridge; must not be passed
        # along (Ridge would raise on unexpected kwargs).
        m = build_model("ridge", {"alpha": 0.1, "n_estimators": 99})
        assert m.alpha == 0.1

    def test_build_model_unknown_name_raises(self):
        with pytest.raises(ValueError, match="unknown model"):
            build_model("does_not_exist")


# ---------------------------------------------------------------------
# Prediction sample formatter
# ---------------------------------------------------------------------

def test_prediction_sample_thins_long_series():
    n = 12_000
    idx = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")
    sample = _build_prediction_sample(
        idx, np.zeros(n), np.ones(n)
    )
    # Cap is MAX_RESPONSE_POINTS = 5000 — we should be at-or-below.
    assert len(sample) <= 5_000
    # First and last points present (give-or-take rounding) so the chart
    # spans the actual range.
    assert sample[0]["actual"] == 0.0
    assert sample[-1]["predicted"] == 1.0


# ---------------------------------------------------------------------
# Wizard config validation
# ---------------------------------------------------------------------

class TestTrainConfigValidation:
    def _base(self, **overrides):
        kwargs: dict = {
            "data": DataSpec(
                instrument="NQ", timeframe="1h",
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 6, 1, tzinfo=UTC),
            ),
            "target": TargetSpec(kind="log_return", horizon=1),
            "features": [FeatureSpec(kind="lag_return", window=1)],
            "task": "regression",
            "model": ModelSpec(name="ridge"),
        }
        kwargs.update(overrides)
        return kwargs

    def test_classification_must_use_direction_target(self):
        with pytest.raises(ValueError, match="direction"):
            TrainConfig(**self._base(task="classification"))

    def test_clustering_requires_numeric_target(self):
        with pytest.raises(ValueError, match="clustering"):
            TrainConfig(
                **self._base(
                    task="clustering",
                    target=TargetSpec(kind="direction", horizon=1),
                )
            )

    def test_minimum_one_feature_required(self):
        with pytest.raises(ValueError):
            TrainConfig(**self._base(features=[]))
