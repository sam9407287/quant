"""REST endpoint for querying OHLCV bars at any supported timeframe."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.adjustment import (
    RollEvent,
    apply_absolute_adjustment,
    apply_ratio_adjustment,
)
from app.core.instruments import Symbol as Instrument
from app.db.session import get_db

router = APIRouter(prefix="/api/v1", tags=["kbars"])

# Timeframe → SQL source (view name or base table)
_TIMEFRAME_SOURCE: dict[str, str] = {
    "1m":  "kbars_1m",
    "5m":  "kbars_5m",
    "15m": "kbars_15m",
    "1h":  "kbars_1h",
    "4h":  "kbars_4h",
    "1d":  "kbars_1d",
    "1w":  "kbars_1w",
}

Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
Adjustment = Literal["raw", "ratio", "absolute"]


class KBar(BaseModel):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class KBarsResponse(BaseModel):
    instrument: str
    timeframe: str
    adjustment: str
    count: int
    data: list[KBar]


@router.get("/kbars", response_model=KBarsResponse, summary="Query OHLCV bars")
async def get_kbars(
    instrument: Annotated[Instrument, Query(description="Futures symbol")],
    start: Annotated[datetime, Query(description="Range start (UTC)")],
    end: Annotated[datetime, Query(description="Range end (UTC)")],
    timeframe: Annotated[Timeframe, Query(description="Bar timeframe")] = "1h",
    adjustment: Annotated[Adjustment, Query(description="Price adjustment method")] = "ratio",
    limit: Annotated[int, Query(ge=1, le=50000)] = 5000,
    db: AsyncSession = Depends(get_db),
) -> KBarsResponse:
    """Return OHLCV bars for an instrument with optional price adjustment.

    The adjustment parameter controls how contract roll gaps are handled:
    - raw: unadjusted prices as stored in the database
    - ratio: multiply prior bars by new_open/old_close (recommended for TA)
    - absolute: add price_diff to prior bars (preserves dollar moves)
    """
    source = _TIMEFRAME_SOURCE[timeframe]

    rows = await _fetch_bars(db, source, instrument, start, end, limit)

    if adjustment == "raw":
        return KBarsResponse(
            instrument=instrument,
            timeframe=timeframe,
            adjustment=adjustment,
            count=len(rows),
            data=[KBar(**r) for r in rows],
        )

    rolls = await _fetch_rolls(db, instrument, start, end)
    if adjustment == "ratio":
        rows = apply_ratio_adjustment(rows, rolls)
    else:
        rows = apply_absolute_adjustment(rows, rolls)

    return KBarsResponse(
        instrument=instrument,
        timeframe=timeframe,
        adjustment=adjustment,
        count=len(rows),
        data=[KBar(**r) for r in rows],
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

async def _fetch_bars(
    db: AsyncSession,
    source: str,
    instrument: str,
    start: datetime,
    end: datetime,
    limit: int,
) -> list[dict]:
    """Query bars from the appropriate table or continuous aggregate view."""
    stmt = text(
        f"""
        SELECT ts, open::float, high::float, low::float, close::float, volume
        FROM {source}
        WHERE instrument = :instrument
          AND ts >= :start
          AND ts < :end
        ORDER BY ts ASC
        LIMIT :limit
        """  # noqa: S608 — source is from a hardcoded dict, not user input
    )
    result = await db.execute(
        stmt,
        {"instrument": instrument, "start": start, "end": end, "limit": limit},
    )
    return [dict(row._mapping) for row in result.fetchall()]


async def _fetch_rolls(
    db: AsyncSession,
    instrument: str,
    start: datetime,
    end: datetime,
) -> list[RollEvent]:
    """Fetch roll events that fall within or after the query range."""
    from decimal import Decimal

    stmt = text(
        """
        SELECT instrument, roll_date, price_diff, price_ratio
        FROM roll_calendar
        WHERE instrument = :instrument
          AND roll_date >= :start_date
          AND roll_date <= :end_date
          AND price_diff IS NOT NULL
        ORDER BY roll_date ASC
        """
    )
    result = await db.execute(
        stmt,
        {
            "instrument": instrument,
            "start_date": start.date(),
            "end_date": end.date(),
        },
    )
    return [
        RollEvent(
            instrument=row.instrument,
            roll_date=row.roll_date,
            price_diff=Decimal(str(row.price_diff)),
            price_ratio=Decimal(str(row.price_ratio)),
        )
        for row in result.fetchall()
    ]
