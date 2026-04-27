# ADR-002 — ML Workbench Architecture

**Status:** Accepted · 2026-04-27
**Context:** Period 1.5 / Period 2 bridge.

## Context

Period 2 of the project promises strategy research — signal development and
backtesting. To get there with a usable interface (rather than ad-hoc
notebooks), we are building a no-code ML workbench inside the existing
dashboard: pick data → engineer features → preprocess → choose model →
visualise results, all from a wizard form.

The workbench has to handle finance-specific pitfalls correctly (no
random shuffles on time series, no look-ahead leakage, walk-forward
validation), because those are exactly the things that make the
difference between a portfolio-grade tool and a toy.

## Decisions

### D1. Same service as the API

The ML training endpoints live inside the existing `api` (FastAPI)
service rather than a dedicated `ml` service. Rationale: a single Python
process, a single deployment, no inter-service plumbing. Sklearn fits
on the data sizes we work with (≤ 100k samples × 20 features) finish in
single-digit seconds, well below FastAPI's request budget.

If training time grows past ~20 s in practice, split out an `ml-worker`
service with a job queue. Until then, do not pre-pay that complexity.

### D2. CPU-only, no deep learning

The model catalogue is restricted to scikit-learn (linear, tree, SVM,
clustering, dim-reduction) plus XGBoost and LightGBM for boosted trees.
LSTMs, Transformers, and any GPU-required model are **out of scope** —
Railway lacks GPUs, and "make linear baselines work first" is the
correct discipline anyway.

### D3. Synchronous training endpoint

`POST /api/v1/ml/train` blocks until the model finishes fitting and
returns metrics + predictions + projections in the same response. No
job queue, no polling. Trade-off: long requests; mitigation: hard
runtime cap of 30 s with an explicit error if exceeded. When that limit
becomes the common case, revisit.

### D4. Time-series safety rails are non-negotiable

The wizard does **not** expose:
- Random train/test splits — only chronological splits and walk-forward
  CV are available.
- Forward-looking features — every lagged feature is shifted server-side
  so `t-k` data drives the prediction at time `t`.
- Standardiser fitted on the whole dataset — scalers are always fit on
  train only and applied to test.

The UI shows a permanent "Time-series ML mode" banner that names these
constraints, so the user (and any portfolio reviewer) can see they are
intentional.

### D5. Experiments are persisted to the same TimescaleDB

A new ordinary (non-hypertable) table `experiments` stores config +
metrics + selected artefacts as `JSONB`. This delivers experiment
tracking, reproducibility, and the comparison page without introducing
a new datastore.

```sql
CREATE TABLE experiments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    config      JSONB       NOT NULL,
    metrics     JSONB       NOT NULL,
    artefacts   JSONB,             -- predictions, importances, projections
    runtime_ms  INT         NOT NULL,
    notes       TEXT
);
CREATE INDEX experiments_created_at_idx ON experiments (created_at DESC);
```

`gen_random_uuid()` requires the `pgcrypto` extension; we add it in
the same schema migration.

### D6. Schema migrations: append-only SQL by hand for now

The `db/schema.sql` file is the source of truth for fresh deployments
(it bakes into the timescaledb Docker image). For the live database,
new tables are applied by hand:

```bash
railway connect timescaledb
\i /path/to/migrations/0001_experiments.sql
```

`alembic` is a project dependency but is **not** wired up; introducing
it would require backfilling a baseline revision against the current
schema, which is busy work for a 1-person project. Re-evaluate when
schema changes happen often enough that hand migrations become a
liability.

### D7. Models registered via a factory, not direct imports

`app/ml/models.py` exposes a `MODEL_REGISTRY: dict[str, ModelSpec]`
mapping the wizard's model name (e.g., `"random_forest_regressor"`) to
a constructor + supported hyperparameters + supported task type. The
endpoint validates the wizard config against the registry so the
front end never invokes an unsupported combination, and the registry
is the single place to add a new model.

## Consequences

**Positive**

- One PR delivers backend + experiments + wizard, no new infra.
- Time-series rails are visible — interview-grade design choice.
- Experiments table + comparison page demonstrates MLOps awareness.
- Period 2 (signal generation) inherits the same `/ml/train` plumbing
  with a different consumer; nothing here is scaffold-only.

**Negative**

- Sync training caps practical model size. Acceptable for now.
- `experiments.artefacts` as JSONB will outgrow row size on big
  predictions arrays; mitigation: cap stored arrays at 5k points,
  store full series as a CSV in object storage when that limit hits.
- Adding sklearn / xgboost / lightgbm grows the API image by ~70 MB.
  The Railway free tier has plenty of headroom; not an issue today.

**Neutral**

- The wizard intentionally does **not** do automatic feature search
  (Boruta, RFE, SHAP-driven selection). Every selected feature is the
  user's deliberate choice. This is a research tool, not an AutoML.

## Out of scope (for this iteration)

- Deep learning, GPU training, online learning.
- Hyperparameter search (GridSearch / RandomSearch / Optuna).
- Model serving (`/ml/predict` against a saved experiment) — design
  it once we know which experiments people actually keep.
- Backtesting on top of the trained model — Period 2 proper.
