"""DB persistence for strategy definitions (ADR-004, ownership ADR-005).

Pure-SQL access via SQLAlchemy `text()`, mirroring app/ml/repository.py.
Every read/write takes `owner_id`: a concrete id scopes the query to
that user's rows; None (admins) sees everything, including legacy rows
whose owner_id is NULL.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_OWNER_COND = "AND (CAST(:owner AS UUID) IS NULL OR s.owner_id = CAST(:owner AS UUID))"


async def insert_strategy(
    session: AsyncSession,
    *,
    name: str,
    description: str | None,
    definition: dict[str, Any],
    owner_id: str | None,
) -> str:
    stmt = text(
        """
        INSERT INTO strategies (name, description, definition, owner_id)
        VALUES (:name, :description, CAST(:definition AS JSONB), CAST(:owner AS UUID))
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
                "owner": owner_id,
            },
        )
    ).scalar_one()
    await session.commit()
    return str(row)


async def list_strategies(
    session: AsyncSession, limit: int = 100, owner_id: str | None = None
) -> list[dict[str, Any]]:
    stmt = text(
        f"""
        SELECT s.id::text AS id, s.created_at, s.updated_at, s.name,
               s.description, s.definition, u.email AS owner_email
        FROM strategies s
        LEFT JOIN users u ON u.id = s.owner_id
        WHERE TRUE {_OWNER_COND}
        ORDER BY s.created_at DESC
        LIMIT :limit
        """  # noqa: S608 — the condition is a fixed fragment, params bound
    )
    rows = (await session.execute(stmt, {"limit": limit, "owner": owner_id})).fetchall()
    return [dict(row._mapping) for row in rows]


async def get_strategy(
    session: AsyncSession, strategy_id: str, owner_id: str | None = None
) -> dict[str, Any] | None:
    stmt = text(
        f"""
        SELECT s.id::text AS id, s.created_at, s.updated_at, s.name,
               s.description, s.definition, u.email AS owner_email
        FROM strategies s
        LEFT JOIN users u ON u.id = s.owner_id
        WHERE s.id = CAST(:id AS UUID) {_OWNER_COND}
        """  # noqa: S608
    )
    row = (
        await session.execute(stmt, {"id": strategy_id, "owner": owner_id})
    ).fetchone()
    return dict(row._mapping) if row else None


async def update_strategy(
    session: AsyncSession,
    strategy_id: str,
    *,
    name: str,
    description: str | None,
    definition: dict[str, Any],
    owner_id: str | None = None,
) -> bool:
    stmt = text(
        f"""
        UPDATE strategies s
        SET name = :name, description = :description,
            definition = CAST(:definition AS JSONB), updated_at = NOW()
        WHERE s.id = CAST(:id AS UUID) {_OWNER_COND}
        """  # noqa: S608
    )
    result = await session.execute(
        stmt,
        {
            "id": strategy_id,
            "name": name,
            "description": description,
            "definition": json.dumps(definition),
            "owner": owner_id,
        },
    )
    await session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def delete_strategy(
    session: AsyncSession, strategy_id: str, owner_id: str | None = None
) -> bool:
    stmt = text(
        f"DELETE FROM strategies s WHERE s.id = CAST(:id AS UUID) {_OWNER_COND}"  # noqa: S608
    )
    result = await session.execute(stmt, {"id": strategy_id, "owner": owner_id})
    await session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]
