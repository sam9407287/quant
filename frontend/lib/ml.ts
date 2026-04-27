/**
 * ML workbench types and API helpers.
 *
 * Mirrors the Pydantic schemas in `app/ml/schemas.py`. The two are kept
 * aligned by hand because the surface is small enough that an OpenAPI
 * codegen step would add a build dependency for marginal safety wins.
 */

import type { Instrument, Timeframe } from "./types";

export type TaskType = "regression" | "classification" | "clustering";

export type TargetKind =
  | "log_return"
  | "simple_return"
  | "direction"
  | "volatility";

export type FeatureKind =
  | "lag_return"
  | "rolling_mean"
  | "rolling_std"
  | "rolling_min"
  | "rolling_max"
  | "rsi"
  | "ema"
  | "sma"
  | "volume_ratio"
  | "high_low_spread";

export interface FeatureSpec {
  kind: FeatureKind;
  window: number;
}

export interface DataSpec {
  instrument: Instrument;
  timeframe: Timeframe;
  start: string; // ISO
  end: string;
}

export interface TargetSpec {
  kind: TargetKind;
  horizon: number;
  deadband_bps?: number;
  vol_window?: number;
}

export interface PreprocessSpec {
  standardize: boolean;
  test_size: number;
  walk_forward_folds?: number;
  dim_reduction?: "none" | "pca" | "tsne" | "umap";
  dim_reduction_components?: number;
  downsample_stride?: number;
}

export interface ModelSpec {
  name: string;
  hyperparameters?: Record<string, number | string | boolean>;
}

export interface TrainConfig {
  data: DataSpec;
  target: TargetSpec;
  features: FeatureSpec[];
  preprocess?: PreprocessSpec;
  task: TaskType;
  model: ModelSpec;
  notes?: string;
}

export interface PredictionPoint {
  ts: string;
  actual: number;
  predicted: number;
}

export interface ProjectionPoint {
  x: number;
  y: number;
  label: number;
  target: number;
  ts: string;
}

export interface TrainResponse {
  experiment_id: string;
  runtime_ms: number;
  metrics: Record<string, number>;
  sample_predictions: PredictionPoint[];
  feature_importance: Record<string, number> | null;
  projection: ProjectionPoint[] | null;
}

export interface ExperimentRecord {
  id: string;
  created_at: string;
  config: TrainConfig;
  metrics: Record<string, number>;
  runtime_ms: number;
  notes: string | null;
}

// ---------------------------------------------------------------------
// Catalogues — keep in sync with `app/ml/models.py::MODEL_REGISTRY`
// ---------------------------------------------------------------------

export const MODELS_BY_TASK: Record<TaskType, { name: string; label: string }[]> = {
  regression: [
    { name: "linear",                       label: "Linear" },
    { name: "ridge",                        label: "Ridge" },
    { name: "lasso",                        label: "Lasso" },
    { name: "elasticnet",                   label: "ElasticNet" },
    { name: "random_forest_regressor",      label: "Random Forest" },
    { name: "gradient_boosting_regressor",  label: "Gradient Boosting" },
    { name: "xgboost_regressor",            label: "XGBoost" },
    { name: "lightgbm_regressor",           label: "LightGBM" },
    { name: "svr",                          label: "SVR" },
    { name: "knn_regressor",                label: "KNN" },
  ],
  classification: [
    { name: "logistic",                       label: "Logistic" },
    { name: "svm",                            label: "SVM" },
    { name: "random_forest_classifier",       label: "Random Forest" },
    { name: "gradient_boosting_classifier",   label: "Gradient Boosting" },
    { name: "xgboost_classifier",             label: "XGBoost" },
    { name: "lightgbm_classifier",            label: "LightGBM" },
    { name: "knn_classifier",                 label: "KNN" },
  ],
  clustering: [
    { name: "kmeans",            label: "KMeans" },
    { name: "dbscan",            label: "DBSCAN" },
    { name: "gaussian_mixture",  label: "Gaussian Mixture" },
    { name: "agglomerative",     label: "Agglomerative" },
  ],
};

export const FEATURE_CATALOGUE: { kind: FeatureKind; label: string; defaultWindow: number }[] = [
  { kind: "lag_return",      label: "Lagged log return",  defaultWindow: 1  },
  { kind: "rolling_mean",    label: "Rolling mean",       defaultWindow: 10 },
  { kind: "rolling_std",     label: "Rolling std",        defaultWindow: 10 },
  { kind: "rolling_min",     label: "Rolling min",        defaultWindow: 10 },
  { kind: "rolling_max",     label: "Rolling max",        defaultWindow: 10 },
  { kind: "rsi",             label: "RSI",                defaultWindow: 14 },
  { kind: "ema",             label: "EMA",                defaultWindow: 20 },
  { kind: "sma",             label: "SMA",                defaultWindow: 20 },
  { kind: "volume_ratio",    label: "Volume ratio",       defaultWindow: 20 },
  { kind: "high_low_spread", label: "High–Low spread",    defaultWindow: 1  },
];

// ---------------------------------------------------------------------
// API
// ---------------------------------------------------------------------

const DEFAULT_API_URL = "https://quant-production-d645.up.railway.app";
function apiUrl(path: string): string {
  const base = process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL;
  return new URL(path, base).toString();
}

export async function trainModel(cfg: TrainConfig): Promise<TrainResponse> {
  const res = await fetch(apiUrl("/api/v1/ml/train"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(cfg),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`POST /ml/train → ${res.status}\n${body}`);
  }
  return (await res.json()) as TrainResponse;
}

export async function listExperiments(limit = 50): Promise<ExperimentRecord[]> {
  const url = new URL(apiUrl("/api/v1/ml/experiments"));
  url.searchParams.set("limit", String(limit));
  const res = await fetch(url.toString(), {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`GET /ml/experiments → ${res.status}`);
  return (await res.json()) as ExperimentRecord[];
}

export async function getExperiment(id: string): Promise<ExperimentRecord> {
  const res = await fetch(apiUrl(`/api/v1/ml/experiments/${id}`), {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`GET /ml/experiments/${id} → ${res.status}`);
  return (await res.json()) as ExperimentRecord;
}
