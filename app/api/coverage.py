"""REST endpoints for data coverage and gap reporting."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter(prefix="/api/v1", tags=["coverage"])


class CoverageRecord(BaseModel):
    instrument: str
    timeframe: str
    earliest_ts: datetime | None
    latest_ts: datetime | None
    bar_count: int
    gap_count: int
    last_fetch_ts: datetime | None
    last_fetch_ok: bool


class GapRecord(BaseModel):
    gap_start: datetime
    gap_end: datetime
    missing_bar_count: int


@router.get(
    "/coverage",
    response_model=list[CoverageRecord],
    summary="Data availability summary",
)
async def get_coverage(
    instrument: Annotated[str, Query(description="Symbol or 'all'")] = "all",
    db: AsyncSession = Depends(get_db),
) -> list[CoverageRecord]:
    """Return coverage statistics for each instrument and timeframe.

    Pass instrument=all to retrieve all four symbols at once.
    """
    if instrument.lower() == "all":
        stmt = text(
            """
            SELECT instrument, timeframe, earliest_ts, latest_ts,
                   bar_count, gap_count, last_fetch_ts, last_fetch_ok
            FROM data_coverage
            ORDER BY instrument, timeframe
            """
        )
        result = await db.execute(stmt)
    else:
        stmt = text(
            """
            SELECT instrument, timeframe, earliest_ts, latest_ts,
                   bar_count, gap_count, last_fetch_ts, last_fetch_ok
            FROM data_coverage
            WHERE instrument = :instrument
            ORDER BY timeframe
            """
        )
        result = await db.execute(stmt, {"instrument": instrument.upper()})

    return [CoverageRecord(**dict(row._mapping)) for row in result.fetchall()]


@router.get(
    "/coverage/gaps",
    response_model=list[GapRecord],
    summary="Detect missing bars in a date range",
)
async def get_gaps(
    instrument: Annotated[str, Query(description="Futures symbol")],
    start: Annotated[date, Query(description="Start date (inclusive)")],
    end: Annotated[date, Query(description="End date (inclusive)")],
    db: AsyncSession = Depends(get_db),
) -> list[GapRecord]:
    """Return time windows where 1m bars are missing within trading hours.

    This uses a generate_series approach to enumerate expected 1-minute
    intervals within normal CME Globex trading sessions and returns gaps
    where no bar exists in kbars_1m.

    Note: gaps during the 17:00-18:00 ET daily settlement break are excluded.
    """
    # Generate expected 1-minute timestamps within CME trading hours and
    # find which ones have no corresponding bar in kbars_1m.
    stmt = text(
        """
        WITH expected AS (
            SELECT gs::timestamptz AS expected_ts
            FROM generate_series(
                :start_ts::timestamptz,
                :end_ts::timestamptz,
                '1 minute'::interval
            ) AS gs
            WHERE
                -- Exclude Saturday (6) and Sunday before 18:00 ET
                EXTRACT(DOW FROM gs AT TIME ZONE 'America/New_York') NOT IN (6)
                AND NOT (
                    EXTRACT(DOW FROM gs AT TIME ZONE 'America/New_York') = 0
                    AND EXTRACT(HOUR FROM gs AT TIME ZONE 'America/New_York') < 18
                )
                -- Exclude daily settlement break 17:00–18:00 ET
                AND NOT (
                    EXTRACT(HOUR FROM gs AT TIME ZONE 'America/New_York') = 17
                )
        ),
        missing AS (
            SELECT e.expected_ts
            FROM expected e
            LEFT JOIN kbars_1m k
                ON k.ts = e.expected_ts AND k.instrument = :instrument
            WHERE k.ts IS NULL
        ),
        grouped AS (
            SELECT
                expected_ts,
                expected_ts - (ROW_NUMBER() OVER (ORDER BY expected_ts) * INTERVAL '1 minute') AS grp
            FROM missing
        )
        SELECT
            MIN(expected_ts)  AS gap_start,
            MAX(expected_ts)  AS gap_end,
            COUNT(*)::int     AS missing_bar_count
        FROM grouped
        GROUP BY grp
        HAVING COUNT(*) >= 2
        ORDER BY gap_start
        """
    )
    result = await db.execute(
        stmt,
        {
            "instrument": instrument.upper(),
            "start_ts": datetime(start.year, start.month, start.day),
            "end_ts": datetime(end.year, end.month, end.day, 23, 59),
        },
    )
    return [GapRecord(**dict(row._mapping)) for row in result.fetchall()]
