"""Model registry — single source of truth for what the wizard supports.

Adding a new model is a 3-line entry here plus a unit test confirming
the constructor works. The endpoint validates `(task, model_name)`
combinations against this registry, so the front end can never drive
the backend into an unsupported state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sklearn.cluster import DBSCAN, AgglomerativeClustering, KMeans
from sklearn.ensemble import (
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.linear_model import (
    ElasticNet,
    Lasso,
    LinearRegression,
    LogisticRegression,
    Ridge,
)
from sklearn.mixture import GaussianMixture
from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
from sklearn.svm import SVC, SVR


@dataclass(frozen=True)
class ModelSpec:
    """How to instantiate a model from a wizard-supplied hyperparameter dict."""

    task: str  # "regression" | "classification" | "clustering"
    factory: Callable[..., Any]
    # Hyperparameter name → (kind, default). `kind` is informational only
    # for now (the schema validates types via Pydantic at the entry point);
    # kept for the future "advanced" UI panel.
    hyperparameters: dict[str, tuple[str, Any]] = field(default_factory=dict)


def _xgb_regressor(**kw: Any) -> Any:
    # Lazy import — xgboost imports a sizable native lib and we want
    # `from app.ml.models import MODEL_REGISTRY` to stay cheap.
    from xgboost import XGBRegressor
    return XGBRegressor(tree_method="hist", n_jobs=-1, **kw)


def _xgb_classifier(**kw: Any) -> Any:
    from xgboost import XGBClassifier
    return XGBClassifier(tree_method="hist", n_jobs=-1, **kw)


def _lgbm_regressor(**kw: Any) -> Any:
    from lightgbm import LGBMRegressor
    return LGBMRegressor(n_jobs=-1, verbose=-1, **kw)


def _lgbm_classifier(**kw: Any) -> Any:
    from lightgbm import LGBMClassifier
    return LGBMClassifier(n_jobs=-1, verbose=-1, **kw)


MODEL_REGISTRY: dict[str, ModelSpec] = {
    # ── Regression ────────────────────────────────────────────────
    "linear":            ModelSpec("regression", LinearRegression),
    "ridge":             ModelSpec("regression", Ridge,
                                   {"alpha": ("float", 1.0)}),
    "lasso":             ModelSpec("regression", Lasso,
                                   {"alpha": ("float", 0.001)}),
    "elasticnet":        ModelSpec("regression", ElasticNet,
                                   {"alpha": ("float", 0.001),
                                    "l1_ratio": ("float", 0.5)}),
    "random_forest_regressor":
        ModelSpec("regression", RandomForestRegressor,
                  {"n_estimators": ("int", 200),
                   "max_depth": ("int", 10),
                   "min_samples_leaf": ("int", 5)}),
    "gradient_boosting_regressor":
        ModelSpec("regression", GradientBoostingRegressor,
                  {"n_estimators": ("int", 200),
                   "max_depth": ("int", 3),
                   "learning_rate": ("float", 0.05)}),
    "xgboost_regressor": ModelSpec("regression", _xgb_regressor,
                                   {"n_estimators": ("int", 300),
                                    "max_depth": ("int", 5),
                                    "learning_rate": ("float", 0.05)}),
    "lightgbm_regressor": ModelSpec("regression", _lgbm_regressor,
                                    {"n_estimators": ("int", 300),
                                     "num_leaves": ("int", 31),
                                     "learning_rate": ("float", 0.05)}),
    "svr":               ModelSpec("regression", SVR,
                                   {"C": ("float", 1.0),
                                    "kernel": ("str", "rbf")}),
    "knn_regressor":     ModelSpec("regression", KNeighborsRegressor,
                                   {"n_neighbors": ("int", 5)}),

    # ── Classification ───────────────────────────────────────────
    "logistic":          ModelSpec("classification", LogisticRegression,
                                   {"C": ("float", 1.0),
                                    "max_iter": ("int", 1000)}),
    "svm":               ModelSpec("classification", SVC,
                                   {"C": ("float", 1.0),
                                    "kernel": ("str", "rbf"),
                                    "probability": ("bool", True)}),
    "random_forest_classifier":
        ModelSpec("classification", RandomForestClassifier,
                  {"n_estimators": ("int", 200),
                   "max_depth": ("int", 10),
                   "min_samples_leaf": ("int", 5)}),
    "gradient_boosting_classifier":
        ModelSpec("classification", GradientBoostingClassifier,
                  {"n_estimators": ("int", 200),
                   "max_depth": ("int", 3),
                   "learning_rate": ("float", 0.05)}),
    "xgboost_classifier": ModelSpec("classification", _xgb_classifier,
                                    {"n_estimators": ("int", 300),
                                     "max_depth": ("int", 5),
                                     "learning_rate": ("float", 0.05)}),
    "lightgbm_classifier": ModelSpec("classification", _lgbm_classifier,
                                     {"n_estimators": ("int", 300),
                                      "num_leaves": ("int", 31),
                                      "learning_rate": ("float", 0.05)}),
    "knn_classifier":    ModelSpec("classification", KNeighborsClassifier,
                                   {"n_neighbors": ("int", 5)}),

    # ── Clustering ───────────────────────────────────────────────
    "kmeans":            ModelSpec("clustering", KMeans,
                                   {"n_clusters": ("int", 4),
                                    "n_init": ("int", 10),
                                    "random_state": ("int", 0)}),
    "dbscan":            ModelSpec("clustering", DBSCAN,
                                   {"eps": ("float", 0.5),
                                    "min_samples": ("int", 5)}),
    "gaussian_mixture":  ModelSpec("clustering", GaussianMixture,
                                   {"n_components": ("int", 4),
                                    "random_state": ("int", 0)}),
    "agglomerative":     ModelSpec("clustering", AgglomerativeClustering,
                                   {"n_clusters": ("int", 4)}),
}


def build_model(name: str, hyperparameters: dict[str, Any] | None = None) -> Any:
    """Instantiate a model by registry name with safe-defaulted kwargs.

    Wizard-supplied hyperparameters override the registry defaults, but
    only the keys the registry knows about are passed through — anything
    else is dropped silently (defence-in-depth against the front end
    sending stale fields after a registry change).
    """
    if name not in MODEL_REGISTRY:
        raise ValueError(f"unknown model: {name!r}")
    spec = MODEL_REGISTRY[name]
    kwargs: dict[str, Any] = {k: v for k, (_, v) in spec.hyperparameters.items()}
    if hyperparameters:
        for k, v in hyperparameters.items():
            if k in spec.hyperparameters:
                kwargs[k] = v
    return spec.factory(**kwargs)
