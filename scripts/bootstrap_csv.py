"""One-time historical data import from FirstRate Data CSV files.

Usage:
    python scripts/bootstrap_csv.py --data-dir data/firstrate/
    python scripts/bootstrap_csv.py --data-dir data/firstrate/ --instrument NQ

FirstRate Data delivers one ZIP per instrument containing a CSV with columns:
    DateTime, Open, High, Low, Close, Volume
Timestamps are in US/Eastern time and must be converted to UTC on import.

This script is intentionally idempotent: re-running it is safe because the
pipeline layer uses INSERT … ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_BATCH_SIZE = 10_000

# Maps instrument symbol to expected filename patterns
_FILE_PATTERNS: dict[str, list[str]] = {
    "NQ":  ["NQ_continuous_*.csv", "NQ_*.csv", "NQcont*.csv"],
    "ES":  ["ES_continuous_*.csv", "ES_*.csv", "EScont*.csv"],
    "YM":  ["YM_continuous_*.csv", "YM_*.csv", "YMcont*.csv"],
    "RTY": ["RTY_continuous_*.csv", "RTY_*.csv", "RTYcont*.csv"],
}


def find_csv(data_dir: Path, instrument: str) -> Path | None:
    """Locate the CSV file for the given instrument in data_dir."""
    for pattern in _FILE_PATTERNS.get(instrument, []):
        matches = list(data_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def load_firstrate_csv(path: Path, instrument: str) -> pd.DataFrame:
    """Parse a FirstRate Data CSV into a normalised UTC DataFrame."""
    logger.info("Loading %s from %s", instrument, path)

    df = pd.read_csv(
        path,
        names=["ts", "open", "high", "low", "close", "volume"],
        parse_dates=["ts"],
        header=0,
    )

    # Convert Eastern → UTC
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize(_ET).dt.tz_convert("UTC")

    # Drop rows with any null in OHLCV
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    df = df[df["volume"] > 0]

    logger.info("Loaded %d rows for %s", len(df), instrument)
    return df.reset_index(drop=True)


async def import_instrument(
    instrument: str,
    df: pd.DataFrame,
) -> None:
    """Batch-upsert all rows for one instrument into kbars_1m."""
    from app.db.session import AsyncSessionLocal
    from fetcher.pipeline import update_coverage, upsert_bars

    total_inserted = 0
    total_skipped = 0

    async with AsyncSessionLocal() as session:
        for i in range(0, len(df), _BATCH_SIZE):
            batch = df.iloc[i : i + _BATCH_SIZE]
            inserted, skipped = await upsert_bars(
                session, batch, instrument, source="firstrate"
            )
            total_inserted += inserted
            total_skipped += skipped
            logger.info(
                "%s batch %d/%d: inserted=%d skipped=%d",
                instrument,
                i // _BATCH_SIZE + 1,
                (len(df) - 1) // _BATCH_SIZE + 1,
                inserted,
                skipped,
            )

        await update_coverage(session, instrument, timeframe="1m", fetch_ok=True)

    logger.info(
        "%s import complete: total_inserted=%d total_skipped=%d",
        instrument, total_inserted, total_skipped,
    )


async def main(data_dir: Path, instruments: list[str]) -> None:
    for instrument in instruments:
        csv_path = find_csv(data_dir, instrument)
        if csv_path is None:
            logger.warning("No CSV found for %s in %s — skipping", instrument, data_dir)
            continue
        df = load_firstrate_csv(csv_path, instrument)
        await import_instrument(instrument, df)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import FirstRate Data CSV files")
    parser.add_argument("--data-dir", type=Path, required=True, help="Directory with CSV/ZIP files")
    parser.add_argument(
        "--instrument",
        choices=["NQ", "ES", "YM", "RTY"],
        help="Import a single instrument (default: all four)",
    )
    args = parser.parse_args()

    targets = [args.instrument] if args.instrument else ["NQ", "ES", "YM", "RTY"]

    if not args.data_dir.exists():
        logger.error("Directory not found: %s", args.data_dir)
        sys.exit(1)

    asyncio.run(main(args.data_dir, targets))
