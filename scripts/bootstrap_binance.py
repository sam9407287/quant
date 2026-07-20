"""Bulk-load crypto 1m history from Binance monthly archives (ADR-007).

Walks every month from a pair's listing date to today, downloads the
public archive, and upserts into kbars_1m. Safe to re-run: the upsert
dedupes on (instrument, ts), so an interrupted load resumes by simply
running again.

Usage (inside the fetcher container or locally with DATABASE_URL set):
    python -m scripts.bootstrap_binance                # all crypto
    python -m scripts.bootstrap_binance BTC ETH        # selected symbols
    python -m scripts.bootstrap_binance --purge BTC    # wipe first
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.instruments import INSTRUMENT_REGISTRY, get_binance_pair
from app.db.session import AsyncSessionLocal
from fetcher.pipeline import (
    refresh_continuous_aggregates,
    update_all_coverage,
    upsert_bars,
    validate,
)
from fetcher.sources.binance_source import BinanceSource

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

# Binance listing months — walking from an earlier date just wastes 404s.
_LISTED_FROM: dict[str, tuple[int, int]] = {
    "BTC": (2017, 8),
    "ETH": (2017, 8),
    "BNB": (2017, 11),
    "ADA": (2018, 4),
    "DOGE": (2019, 7),
    "SOL": (2020, 8),
}


def _months(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    out, (y, m) = [], start
    while (y, m) <= end:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


async def _month_already_loaded(symbol: str, year: int, month: int) -> bool:
    """True when this month already holds bars — used to make re-runs cheap.

    Each check takes its own short-lived session: a single connection
    held across a multi-year load is exactly what Railway drops.
    """
    lo = datetime(year, month, 1, tzinfo=UTC)
    hi = datetime(year + 1, 1, 1, tzinfo=UTC) if month == 12 else datetime(year, month + 1, 1, tzinfo=UTC)
    async with AsyncSessionLocal() as db:
        count = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM kbars_1m "
                    "WHERE instrument = :i AND ts >= :lo AND ts < :hi"
                ),
                {"i": symbol, "lo": lo, "hi": hi},
            )
        ).scalar_one()
    return bool(count)


async def load_symbol(symbol: str, purge: bool, resume: bool = True) -> int:
    """Load one symbol's full archive history; return rows inserted."""
    pair = get_binance_pair(symbol)
    if pair is None:
        logger.error("%s has no Binance pair mapped — skipped", symbol)
        return 0

    source = BinanceSource()
    today = datetime.now(UTC)
    start = _LISTED_FROM.get(symbol, (2017, 8))
    total = 0

    if purge:
        # Used when a symbol switches provider: old rows carry a
        # different venue's prices and must not be interleaved.
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("DELETE FROM kbars_1m WHERE instrument = :i"), {"i": symbol}
            )
            await db.commit()
            logger.info("%s: purged %s existing rows", symbol, result.rowcount)  # type: ignore[attr-defined]

    current = (today.year, today.month)
    for year, month in _months(start, current):
        # The current month is still growing, so never skip it.
        if resume and not purge and (year, month) != current:
            try:
                if await _month_already_loaded(symbol, year, month):
                    continue
            except Exception:
                logger.warning("%s %04d-%02d: resume check failed, loading anyway",
                               symbol, year, month)
        try:
            df = source.iter_month(symbol, year, month)
        except Exception:
            logger.exception("%s %04d-%02d: download failed", symbol, year, month)
            continue
        if df.empty:
            continue
        df = validate(df)
        # One session per month: a dropped connection costs one month,
        # not the whole multi-year run.
        for attempt in (1, 2, 3):
            try:
                async with AsyncSessionLocal() as db:
                    inserted, skipped = await upsert_bars(db, df, symbol, source="binance")
                total += inserted
                logger.info(
                    "%s %04d-%02d: +%d (skipped %d)", symbol, year, month, inserted, skipped
                )
                break
            except Exception:
                if attempt == 3:
                    logger.exception("%s %04d-%02d: write failed after 3 tries",
                                     symbol, year, month)
                else:
                    await asyncio.sleep(2 * attempt)

    async with AsyncSessionLocal() as db:
        # coverage is otherwise only refreshed by the daily fetcher, so a
        # bulk load would stay invisible on the dashboard until tomorrow.
        await update_all_coverage(db, symbol, fetch_ok=True)

    logger.info("%s: %d rows inserted", symbol, total)
    return total


async def main_async(symbols: list[str], purge: bool, resume: bool = True) -> None:
    for symbol in symbols:
        await load_symbol(symbol, purge, resume)

    # Higher timeframes are Continuous Aggregates; a decade of new 1m
    # bars needs a refresh window that spans the whole load, not the
    # 14-day default the daily fetch uses.
    logger.info("Refreshing continuous aggregates over the full history…")
    await refresh_continuous_aggregates(window=timedelta(days=365 * 12))
    logger.info("Done.")


def main() -> None:
    crypto = [
        s for s, m in INSTRUMENT_REGISTRY.items() if m.asset_class == "crypto"
    ]
    parser = argparse.ArgumentParser(description="Load Binance 1m history")
    parser.add_argument("symbols", nargs="*", default=None, help="default: all crypto")
    parser.add_argument(
        "--purge",
        action="store_true",
        help="delete existing rows for each symbol first (provider switch)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="re-download months that already hold bars",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args.symbols or crypto, args.purge, not args.no_resume))


if __name__ == "__main__":
    main()
