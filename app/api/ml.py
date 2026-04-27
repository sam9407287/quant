"""ML workbench endpoints — train models and inspect past experiments.

See `docs/ADR-002-ml-workbench.md` for the architecture decisions
(synchronous training, sklearn-only, JSONB-backed experiment store).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.ml.pipeline import run_training
from app.ml.repository import (
    get_experiment as repo_get_experiment,
)
from app.ml.repository import (
    insert_experiment,
    list_experiments,
)
from app.ml.schemas import ExperimentRecord, TrainConfig, TrainResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])


@router.post(
    "/train",
    response_model=TrainResponse,
    summary="Train a model on the wizard config and persist the experiment",
)
async def train(
    cfg: TrainConfig,
    db: AsyncSession = Depends(get_db),
) -> TrainResponse:
    """Run a single training pipeline end-to-end and return results."""
    try:
        result = await run_training(db, cfg)
    except ValueError as e:
        # User-config errors → 400; pipeline-level invariants → 500.
        raise HTTPException(status_code=400, detail=str(e)) from e

    artefacts: dict[str, object] = {}
    if result.sample_predictions:
        artefacts["sample_predictions"] = result.sample_predictions
    if result.feature_importance:
        artefacts["feature_importance"] = result.feature_importance
    if result.projection:
        artefacts["projection"] = result.projection

    experiment_id = await insert_experiment(
        db,
        config=cfg.model_dump(mode="json"),
        metrics=result.metrics,
        artefacts=artefacts or None,
        runtime_ms=result.runtime_ms,
        notes=cfg.notes,
    )
    logger.info(
        "ml.train: id=%s task=%s model=%s runtime=%dms",
        experiment_id, cfg.task, cfg.model.name, result.runtime_ms,
    )

    return TrainResponse(
        experiment_id=experiment_id,
        runtime_ms=result.runtime_ms,
        metrics=result.metrics,
        sample_predictions=result.sample_predictions,
        feature_importance=result.feature_importance,
        projection=result.projection,
    )


@router.get(
    "/experiments",
    response_model=list[ExperimentRecord],
    summary="List recent experiments",
)
async def list_recent(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[ExperimentRecord]:
    rows = await list_experiments(db, limit=limit)
    return [ExperimentRecord(**r) for r in rows]


@router.get(
    "/experiments/{experiment_id}",
    response_model=ExperimentRecord,
    summary="Fetch one experiment by id",
)
async def get_one(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
) -> ExperimentRecord:
    row = await repo_get_experiment(db, experiment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return ExperimentRecord(**row)
