"""DB persistence for strategy definitions (ADR-004).

Pure-SQL access via SQLAlchemy `text()`, mirroring app/ml/repository.py.
The definition column is JSONB — its shape is enforced by the Pydantic
StrategyDefinition at the API boundary, never by the database.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def insert_strategy(
    session: AsyncSession,
    *,
    name: str,
    description: str | None,
    definition: dict[str, Any],
) -> str:
    stmt = text(
        """
        INSERT INTO strategies (name, description, definition)
        VALUES (:name, :description, CAST(:definition AS JSONB))
        RETURNING id::text
        """
    )
    row = (
        await session.execute(
            stmt,
            {
                "name": name,
                "description": description,
                "definition": json.dumps(definition),
            },
        )
    ).scalar_one()
    await session.commit()
    return str(row)


async def list_strategies(session: AsyncSession, limit: int = 100) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT id::text AS id, created_at, updated_at, name, description, definition
        FROM strategies
        ORDER BY created_at DESC
        LIMIT :limit
        """
    )
    rows = (await session.execute(stmt, {"limit": limit})).fetchall()
    return [dict(row._mapping) for row in rows]


async def get_strategy(session: AsyncSession, strategy_id: str) -> dict[str, Any] | None:
    stmt = text(
        """
        SELECT id::text AS id, created_at, updated_at, name, description, definition
        FROM strategies
        WHERE id = CAST(:id AS UUID)
        """
    )
    row = (await session.execute(stmt, {"id": strategy_id})).fetchone()
    return dict(row._mapping) if row else None


async def update_strategy(
    session: AsyncSession,
    strategy_id: str,
    *,
    name: str,
    description: str | None,
    definition: dict[str, Any],
) -> bool:
    stmt = text(
        """
        UPDATE strategies
        SET name = :name, description = :description,
            definition = CAST(:definition AS JSONB), updated_at = NOW()
        WHERE id = CAST(:id AS UUID)
        """
    )
    result = await session.execute(
        stmt,
        {
            "id": strategy_id,
            "name": name,
            "description": description,
            "definition": json.dumps(definition),
        },
    )
    await session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def delete_strategy(session: AsyncSession, strategy_id: str) -> bool:
    stmt = text("DELETE FROM strategies WHERE id = CAST(:id AS UUID)")
    result = await session.execute(stmt, {"id": strategy_id})
    await session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]
