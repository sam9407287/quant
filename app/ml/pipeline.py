"""Training orchestrator.

Glues `features` + `models` together. Owned responsibilities:

* Load OHLCV from kbars and align target/features on a single index.
* Time-aware train/test split (chronological — never random).
* Optional standardisation (fit on train only, applied to test).
* Optional dimensionality reduction (PCA / t-SNE / UMAP, fit on train).
* Fit the chosen model and compute the metrics that match the task.
* Return a dataclass dense enough to drop straight into the response.

Everything below is deterministic for a given config + DB state, except
where the registered model itself is non-deterministic; we set
`random_state=0` whenever the underlying estimator accepts it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.features import build_feature_matrix, build_target
from app.ml.models import MODEL_REGISTRY, build_model
from app.ml.schemas import TrainConfig

_TIMEFRAME_TABLE: dict[str, str] = {
    "1m": "kbars_1m", "5m": "kbars_5m", "15m": "kbars_15m",
    "1h": "kbars_1h", "4h": "kbars_4h", "1d": "kbars_1d", "1w": "kbars_1w",
}

# Hard caps to keep training synchronous and JSON payloads sane.
MAX_SAMPLES = 100_000
MAX_RESPONSE_POINTS = 5_000


@dataclass
class TrainResult:
    runtime_ms: int
    metrics: dict[str, float]
    sample_predictions: list[dict[str, Any]]
    feature_importance: dict[str, float] | None
    projection: list[dict[str, Any]] | None


# ---------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------

async def load_bars(session: AsyncSession, cfg: TrainConfig) -> pd.DataFrame:
    """Fetch OHLCV from the appropriate kbars view."""
    table = _TIMEFRAME_TABLE[cfg.data.timeframe]
    stmt = text(
        f"SELECT ts, open::float, high::float, low::float, close::float, volume "  # noqa: S608
        f"FROM {table} "
        f"WHERE instrument = :instrument AND ts >= :start AND ts < :end "
        f"ORDER BY ts ASC LIMIT :lim"
    )
    rows = (await session.execute(stmt, {
        "instrument": cfg.data.instrument,
        "start": cfg.data.start,
        "end": cfg.data.end,
        "lim": MAX_SAMPLES,
    })).fetchall()
    df = pd.DataFrame([dict(r._mapping) for r in rows])
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts")


# ---------------------------------------------------------------------
# Splitting & preprocessing
# ---------------------------------------------------------------------

def chronological_split(
    X: pd.DataFrame, y: pd.Series, test_size: float
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """Split by time — first `1 - test_size` rows train, rest test."""
    n_train = int(len(X) * (1 - test_size))
    return X.iloc[:n_train], X.iloc[n_train:], y.iloc[:n_train], y.iloc[n_train:]


def standardize(
    X_train: pd.DataFrame, X_test: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Fit StandardScaler on train; apply to both. Returns the scaler too."""
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    Xt_arr = scaler.fit_transform(X_train.values)
    Xv_arr = scaler.transform(X_test.values)
    Xt = pd.DataFrame(Xt_arr, index=X_train.index, columns=X_train.columns)
    Xv = pd.DataFrame(Xv_arr, index=X_test.index, columns=X_test.columns)
    return Xt, Xv, {"mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist()}


def _project(
    X_train: np.ndarray[Any, Any], X_test: np.ndarray[Any, Any], kind: str, n: int,
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    """Return 2D / nD projection — fit on train, apply to test where possible."""
    if kind == "pca":
        from sklearn.decomposition import PCA
        proj = PCA(n_components=n, random_state=0).fit(X_train)
        return proj.transform(X_train), proj.transform(X_test)
    if kind == "tsne":
        # t-SNE has no transform — fit once on the union and re-split.
        # Acceptable because t-SNE is a visualisation tool, not a feature.
        from sklearn.manifold import TSNE
        joined = np.vstack([X_train, X_test])
        emb = TSNE(n_components=n, random_state=0, init="pca").fit_transform(joined)
        return emb[: len(X_train)], emb[len(X_train):]
    if kind == "umap":
        # UMAP is optional; raise a clear error if the user picked it
        # without the dependency installed (keeps requirements light).
        try:
            import umap
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "umap-learn is not installed; pick PCA or t-SNE instead."
            ) from exc
        proj = umap.UMAP(n_components=n, random_state=0).fit(X_train)
        return proj.transform(X_train), proj.transform(X_test)
    raise ValueError(f"unknown projection: {kind}")


# ---------------------------------------------------------------------
# Metric calculation
# ---------------------------------------------------------------------

def _regression_metrics(y_true: np.ndarray[Any, Any], y_pred: np.ndarray[Any, Any]) -> dict[str, float]:
    from sklearn.metrics import (
        mean_absolute_error,
        mean_squared_error,
        r2_score,
    )
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    return {
        "rmse": rmse,
        "mse": float(mean_squared_error(y_true, y_pred)),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "r2": float(r2_score(y_true, y_pred)),
    }


def _classification_metrics(y_true: np.ndarray[Any, Any], y_pred: np.ndarray[Any, Any]) -> dict[str, float]:
    from sklearn.metrics import accuracy_score, f1_score
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro")),
    }


def _clustering_metrics(X: np.ndarray[Any, Any], labels: np.ndarray[Any, Any]) -> dict[str, float]:
    from sklearn.metrics import silhouette_score
    metrics: dict[str, float] = {"n_clusters": float(len(set(labels)) - (1 if -1 in labels else 0))}
    # silhouette undefined for < 2 clusters; guard.
    valid_labels = labels != -1
    unique = set(labels[valid_labels])
    if len(unique) >= 2 and valid_labels.sum() > 1:
        metrics["silhouette"] = float(silhouette_score(X[valid_labels], labels[valid_labels]))
    return metrics


# ---------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------

async def run_training(session: AsyncSession, cfg: TrainConfig) -> TrainResult:
    """End-to-end training driven by a wizard config.

    The function is a single straight-line read top-to-bottom by design —
    each stage is its own helper so the orchestrator stays auditable.
    """
    t0 = time.perf_counter()

    bars = await load_bars(session, cfg)
    if bars.empty or len(bars) < 50:
        raise ValueError(
            f"insufficient bars for the requested range "
            f"({len(bars)} loaded — need ≥ 50)."
        )

    # 1. Build the (target, feature matrix) pair on the same index.
    target = build_target(bars, cfg.target)
    features = build_feature_matrix(bars, cfg.features)
    aligned = pd.concat([target, features], axis=1).dropna()
    if aligned.empty:
        raise ValueError(
            "after dropping warm-up rows, no samples remain. "
            "Reduce window sizes or widen the date range."
        )

    # Optional downsampling — useful when a user picks 1m timeframe and
    # only wants every Nth bar (correlations don't need every minute).
    if cfg.preprocess.downsample_stride > 1:
        aligned = aligned.iloc[::cfg.preprocess.downsample_stride]

    y = aligned.iloc[:, 0]
    X = aligned.iloc[:, 1:]
    feature_names = X.columns.tolist()

    # 2. Validate (task, model) against registry.
    model_spec = MODEL_REGISTRY.get(cfg.model.name)
    if model_spec is None:
        raise ValueError(f"unknown model: {cfg.model.name!r}")
    if model_spec.task != cfg.task:
        raise ValueError(
            f"model {cfg.model.name!r} is registered for "
            f"task={model_spec.task!r}, not {cfg.task!r}"
        )

    if cfg.task == "clustering":
        return _run_clustering(t0, cfg, X, y, feature_names)

    return _run_supervised(t0, cfg, X, y, feature_names)


# ---------------------------------------------------------------------
# Supervised path
# ---------------------------------------------------------------------

def _run_supervised(
    t0: float, cfg: TrainConfig, X: pd.DataFrame, y: pd.Series,
    feature_names: list[str],
) -> TrainResult:
    X_train, X_test, y_train, y_test = chronological_split(
        X, y, cfg.preprocess.test_size,
    )
    if len(X_train) < 20 or len(X_test) < 5:
        raise ValueError("split produced fewer than 20 train / 5 test rows.")

    if cfg.preprocess.standardize:
        X_train, X_test, _ = standardize(X_train, X_test)

    model = build_model(cfg.model.name, cfg.model.hyperparameters)
    model.fit(X_train.values, y_train.values)
    y_pred = model.predict(X_test.values)

    if cfg.task == "regression":
        metrics = _regression_metrics(y_test.values, y_pred)
    else:
        metrics = _classification_metrics(y_test.values, y_pred)

    importance = _extract_feature_importance(model, feature_names)
    sample = _build_prediction_sample(X_test.index, y_test.values, y_pred)
    runtime_ms = int((time.perf_counter() - t0) * 1000)
    return TrainResult(runtime_ms, metrics, sample, importance, None)


def _extract_feature_importance(
    model: Any, names: list[str],
) -> dict[str, float] | None:
    if hasattr(model, "feature_importances_"):
        return dict(zip(
            names,
            [float(v) for v in model.feature_importances_],
            strict=False,
        ))
    if hasattr(model, "coef_"):
        coef = np.atleast_1d(np.asarray(model.coef_)).ravel()[: len(names)]
        return dict(zip(names, [float(v) for v in coef], strict=False))
    return None


def _build_prediction_sample(
    idx: pd.Index, y_true: np.ndarray[Any, Any], y_pred: np.ndarray[Any, Any],
) -> list[dict[str, Any]]:
    n = len(idx)
    if n <= MAX_RESPONSE_POINTS:
        sel: list[int] = list(range(n))
    else:
        # Even thinning preserves the time axis without bias.
        step = n / MAX_RESPONSE_POINTS
        sel = [int(i * step) for i in range(MAX_RESPONSE_POINTS)]
    return [
        {
            "ts": idx[i].isoformat() if hasattr(idx[i], "isoformat") else str(idx[i]),
            "actual": float(y_true[i]),
            "predicted": float(y_pred[i]),
        }
        for i in sel
    ]


# ---------------------------------------------------------------------
# Clustering path
# ---------------------------------------------------------------------

def _run_clustering(
    t0: float, cfg: TrainConfig, X: pd.DataFrame, y: pd.Series,
    feature_names: list[str],
) -> TrainResult:
    # Even clustering benefits from standardisation when distances matter.
    Xs = X.copy()
    if cfg.preprocess.standardize:
        from sklearn.preprocessing import StandardScaler
        Xs = pd.DataFrame(
            StandardScaler().fit_transform(X.values),
            index=X.index, columns=X.columns,
        )

    model = build_model(cfg.model.name, cfg.model.hyperparameters)
    if hasattr(model, "fit_predict"):
        labels = model.fit_predict(Xs.values)
    else:  # GaussianMixture etc.
        model.fit(Xs.values)
        labels = model.predict(Xs.values)

    metrics = _clustering_metrics(Xs.values, labels)

    # Always project to 2D for the visualisation, regardless of the
    # `dim_reduction` setting (which controls whether the model itself
    # was fed projected features). For viz we use PCA — fast, stable.
    from sklearn.decomposition import PCA
    points2d = PCA(n_components=2, random_state=0).fit_transform(Xs.values)

    n = len(labels)
    sel = (
        range(n) if n <= MAX_RESPONSE_POINTS
        else [int(i * (n / MAX_RESPONSE_POINTS)) for i in range(MAX_RESPONSE_POINTS)]
    )
    projection = [
        {
            "x": float(points2d[i, 0]),
            "y": float(points2d[i, 1]),
            "label": int(labels[i]),
            "target": float(y.iloc[i]),
            "ts": X.index[i].isoformat() if hasattr(X.index[i], "isoformat")
            else str(X.index[i]),
        }
        for i in sel
    ]

    runtime_ms = int((time.perf_counter() - t0) * 1000)
    return TrainResult(runtime_ms, metrics, [], None, projection)
