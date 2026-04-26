"""Data coverage verification and gap detection script.

Usage:
    python scripts/verify_coverage.py
    python scripts/verify_coverage.py --instrument NQ --start 2024-01-01 --end 2024-12-31

Prints a summary table of coverage per instrument, and lists any detected
gaps in normal trading hours. Exits with code 1 if any gaps are found,
making it suitable for use in CI pipelines or health checks.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, date, datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_INSTRUMENTS = ["NQ", "ES", "YM", "RTY"]


async def print_coverage_summary() -> None:
    """Print the data_coverage table for all instruments."""
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT instrument, timeframe, earliest_ts, latest_ts,
                       bar_count, gap_count, last_fetch_ts, last_fetch_ok
                FROM data_coverage
                WHERE timeframe = '1m'
                ORDER BY instrument
                """
            )
        )
        rows = result.fetchall()

    if not rows:
        print("No coverage data found. Run bootstrap first.")
        return

    print("\n── Data Coverage (1m) ──────────────────────────────────────")
    print(f"{'Symbol':<8} {'Earliest':<22} {'Latest':<22} {'Bars':>10} {'OK':<5}")
    print("-" * 70)
    for row in rows:
        ok = "✓" if row.last_fetch_ok else "✗"
        earliest = row.earliest_ts.strftime("%Y-%m-%d %H:%M") if row.earliest_ts else "—"
        latest = row.latest_ts.strftime("%Y-%m-%d %H:%M") if row.latest_ts else "—"
        print(f"{row.instrument:<8} {earliest:<22} {latest:<22} {row.bar_count:>10,} {ok}")
    print()


async def check_gaps(
    instrument: str,
    start: date,
    end: date,
) -> int:
    """Query the DB for missing 1m bars and print a gap report.

    Returns the number of gaps found.
    """
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                WITH expected AS (
                    SELECT gs::timestamptz AS expected_ts
                    FROM generate_series(
                        :start_ts::timestamptz,
                        :end_ts::timestamptz,
                        '1 minute'::interval
                    ) AS gs
                    WHERE
                        EXTRACT(DOW FROM gs AT TIME ZONE 'America/New_York') NOT IN (6)
                        AND NOT (
                            EXTRACT(DOW FROM gs AT TIME ZONE 'America/New_York') = 0
                            AND EXTRACT(HOUR FROM gs AT TIME ZONE 'America/New_York') < 18
                        )
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
                    MIN(expected_ts) AS gap_start,
                    MAX(expected_ts) AS gap_end,
                    COUNT(*)::int    AS missing_bars
                FROM grouped
                GROUP BY grp
                HAVING COUNT(*) >= 2
                ORDER BY gap_start
                LIMIT 50
                """
            ),
            {
                "instrument": instrument,
                "start_ts": datetime(start.year, start.month, start.day, tzinfo=UTC),
                "end_ts": datetime(end.year, end.month, end.day, 23, 59, tzinfo=UTC),
            },
        )
        gaps = result.fetchall()

    if not gaps:
        print(f"  {instrument}: no gaps found ✓")
        return 0

    print(f"\n  {instrument}: {len(gaps)} gap(s) detected:")
    for g in gaps:
        print(f"    {g.gap_start} → {g.gap_end}  ({g.missing_bars} bars)")
    return len(gaps)


async def main(instruments: list[str], start: date, end: date) -> int:
    await print_coverage_summary()

    print(f"── Gap Analysis ({start} → {end}) ──────────────────────────")
    total_gaps = 0
    for instrument in instruments:
        total_gaps += await check_gaps(instrument, start, end)

    print()
    if total_gaps:
        print(f"⚠  Total gaps found: {total_gaps}")
        return 1
    print("✓  No gaps detected across all instruments.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify data coverage and detect gaps")
    parser.add_argument("--instrument", choices=_INSTRUMENTS, help="Check a single instrument")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    targets = [args.instrument] if args.instrument else _INSTRUMENTS
    exit_code = asyncio.run(main(targets, args.start, args.end))
    sys.exit(exit_code)
