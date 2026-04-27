"""DB persistence for ML experiments.

Pure-SQL access via SQLAlchemy `text()` — no ORM model is declared
because the row shape is fluid (config / metrics / artefacts are JSONB)
and a Pydantic schema already enforces the public surface.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def insert_experiment(
    session: AsyncSession,
    *,
    config: dict[str, Any],
    metrics: dict[str, float],
    artefacts: dict[str, Any] | None,
    runtime_ms: int,
    notes: str | None,
) -> str:
    """Insert a row, return the assigned UUID as a string."""
    stmt = text(
        """
        INSERT INTO experiments (config, metrics, artefacts, runtime_ms, notes)
        VALUES (CAST(:config AS JSONB),
                CAST(:metrics AS JSONB),
                CAST(:artefacts AS JSONB),
                :runtime_ms,
                :notes)
        RETURNING id::text
        """
    )
    row = (await session.execute(stmt, {
        "config":     json.dumps(config),
        "metrics":    json.dumps(metrics),
        "artefacts":  json.dumps(artefacts) if artefacts is not None else None,
        "runtime_ms": runtime_ms,
        "notes":      notes,
    })).scalar_one()
    await session.commit()
    return str(row)


async def list_experiments(
    session: AsyncSession, limit: int = 50,
) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT id::text AS id, created_at, config, metrics, runtime_ms, notes
        FROM experiments
        ORDER BY created_at DESC
        LIMIT :limit
        """
    )
    rows = (await session.execute(stmt, {"limit": limit})).fetchall()
    return [dict(row._mapping) for row in rows]


async def get_experiment(
    session: AsyncSession, experiment_id: str,
) -> dict[str, Any] | None:
    stmt = text(
        """
        SELECT id::text AS id, created_at, config, metrics, artefacts,
               runtime_ms, notes
        FROM experiments
        WHERE id = CAST(:id AS UUID)
        """
    )
    row = (await session.execute(stmt, {"id": experiment_id})).fetchone()
    return dict(row._mapping) if row else None
