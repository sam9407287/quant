"""Pydantic schemas for the wizard config that drives `/api/v1/ml/train`.

Every supported choice the front-end can make is enumerated here so the
endpoint can validate the entire request in one pass before any heavy
work happens. Keep these literal-typed — string-only fields invite typos
and silent test mode.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

# Mirrors app/api/kbars.py — kept as separate Literals so the workbench
# can evolve independently of the kbars endpoint surface.
Instrument = Literal["NQ", "ES", "YM", "RTY"]
Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w"]

TaskType = Literal["regression", "classification", "clustering"]

TargetKind = Literal[
    "log_return",        # ln(p_t / p_{t-1})  — preferred for time-series
    "simple_return",     # (p_t - p_{t-1}) / p_{t-1}
    "direction",         # sign of next return — classification
    "volatility",        # rolling realised vol
]

# A "feature spec" is an atomic feature — name + window. The frontend
# emits a list of these; the backend materialises them in order.
FeatureKind = Literal[
    "lag_return",
    "rolling_mean",
    "rolling_std",
    "rolling_min",
    "rolling_max",
    "rsi",
    "ema",
    "sma",
    "volume_ratio",
    "high_low_spread",
]


class FeatureSpec(BaseModel):
    """One feature column to engineer from kbars."""

    kind: FeatureKind
    window: Annotated[int, Field(ge=1, le=500)] = 1


class DataSpec(BaseModel):
    instrument: Instrument
    timeframe: Timeframe
    start: datetime
    end: datetime


class TargetSpec(BaseModel):
    kind: TargetKind
    horizon: Annotated[int, Field(ge=1, le=50)] = 1
    # Direction-classifier needs a deadband so the bucket "≈ 0" is real.
    # Returns inside ±deadband_bps map to neutral (label 0). Ignored when
    # `kind != "direction"`.
    deadband_bps: Annotated[float, Field(ge=0, le=500)] = 0
    # Volatility target needs its own window (the rolling-std window).
    vol_window: Annotated[int, Field(ge=2, le=500)] = 20


class PreprocessSpec(BaseModel):
    standardize: bool = True
    test_size: Annotated[float, Field(gt=0, lt=0.5)] = 0.2
    walk_forward_folds: Annotated[int, Field(ge=0, le=10)] = 0  # 0 = off
    dim_reduction: Literal["none", "pca", "tsne", "umap"] = "none"
    dim_reduction_components: Annotated[int, Field(ge=2, le=20)] = 2
    downsample_stride: Annotated[int, Field(ge=1, le=100)] = 1


# Model selection ---------------------------------------------------------

# Allow-list per task. The endpoint cross-checks (model, task) against
# `MODEL_REGISTRY` in `app/ml/models.py`.
RegressionModel = Literal[
    "linear", "ridge", "lasso", "elasticnet",
    "random_forest", "gradient_boosting", "xgboost", "lightgbm",
    "svr", "knn",
]
ClassificationModel = Literal[
    "logistic", "svm", "random_forest", "gradient_boosting",
    "xgboost", "lightgbm", "knn",
]
ClusteringModel = Literal[
    "kmeans", "dbscan", "gaussian_mixture", "agglomerative",
]


class ModelSpec(BaseModel):
    name: str
    hyperparameters: dict[str, float | int | str | bool] = Field(default_factory=dict)


class TrainConfig(BaseModel):
    """Full wizard payload."""

    data: DataSpec
    target: TargetSpec
    features: list[FeatureSpec] = Field(min_length=1)
    preprocess: PreprocessSpec = PreprocessSpec()
    task: TaskType
    model: ModelSpec
    notes: str | None = None

    @model_validator(mode="after")
    def _check_target_for_task(self) -> TrainConfig:
        if self.task == "classification" and self.target.kind != "direction":
            raise ValueError(
                "classification requires target.kind='direction'"
            )
        if self.task == "clustering" and self.target.kind not in (
            "log_return", "simple_return", "volatility",
        ):
            # Clustering doesn't really need a target, but we still
            # need a numeric column to colour the projection by.
            raise ValueError(
                "clustering requires target.kind in "
                "{log_return, simple_return, volatility} for colouring"
            )
        return self


# Response shapes ---------------------------------------------------------


class TrainResponse(BaseModel):
    experiment_id: str
    runtime_ms: int
    metrics: dict[str, float]
    # Capped sample of (timestamp, predicted, actual) for the result chart.
    # Length bound enforced server-side to keep payload sane.
    sample_predictions: list[dict[str, float | str]] = Field(default_factory=list)
    feature_importance: dict[str, float] | None = None
    # 2D projection points for clustering / dim-red visualisation:
    # [{x, y, label?, target?, ts?}, ...]
    projection: list[dict[str, float | int | str]] | None = None


class ExperimentRecord(BaseModel):
    id: str
    created_at: datetime
    config: dict[str, object]
    metrics: dict[str, float]
    runtime_ms: int
    notes: str | None = None
