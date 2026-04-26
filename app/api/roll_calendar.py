"""REST endpoint for querying the contract roll calendar."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter(prefix="/api/v1", tags=["roll-calendar"])


class RollRecord(BaseModel):
    instrument: str
    old_contract: str
    new_contract: str
    roll_date: date
    price_diff: float | None
    price_ratio: float | None


@router.get(
    "/roll-calendar",
    response_model=list[RollRecord],
    summary="Contract roll schedule",
)
async def get_roll_calendar(
    instrument: Annotated[str, Query(description="Futures symbol")],
    year: Annotated[int | None, Query(description="Filter by year")] = None,
    db: AsyncSession = Depends(get_db),
) -> list[RollRecord]:
    """Return the quarterly contract roll schedule for an instrument.

    When price_diff and price_ratio are null the roll date is in the future
    and the actual adjustment factors are not yet known.
    """
    if year is not None:
        stmt = text(
            """
            SELECT instrument, old_contract, new_contract, roll_date,
                   price_diff::float, price_ratio::float
            FROM roll_calendar
            WHERE instrument = :instrument
              AND EXTRACT(YEAR FROM roll_date) = :year
            ORDER BY roll_date
            """
        )
        result = await db.execute(
            stmt, {"instrument": instrument.upper(), "year": year}
        )
    else:
        stmt = text(
            """
            SELECT instrument, old_contract, new_contract, roll_date,
                   price_diff::float, price_ratio::float
            FROM roll_calendar
            WHERE instrument = :instrument
            ORDER BY roll_date
            """
        )
        result = await db.execute(stmt, {"instrument": instrument.upper()})

    return [RollRecord(**dict(row._mapping)) for row in result.fetchall()]
