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
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.instruments import INSTRUMENT_REGISTRY, get_binance_pair
from app.db.session import AsyncSessionLocal
from fetcher.pipeline import upsert_bars, validate
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


async def load_symbol(symbol: str, purge: bool) -> int:
    """Load one symbol's full archive history; return rows inserted."""
    pair = get_binance_pair(symbol)
    if pair is None:
        logger.error("%s has no Binance pair mapped — skipped", symbol)
        return 0

    source = BinanceSource()
    today = datetime.now(UTC)
    start = _LISTED_FROM.get(symbol, (2017, 8))
    total = 0

    async with AsyncSessionLocal() as db:
        if purge:
            # Used when a symbol switches provider: old rows carry a
            # different venue's prices and must not be interleaved.
            result = await db.execute(
                text("DELETE FROM kbars_1m WHERE instrument = :i"), {"i": symbol}
            )
            await db.commit()
            logger.info("%s: purged %s existing rows", symbol, result.rowcount)  # type: ignore[attr-defined]

        for year, month in _months(start, (today.year, today.month)):
            try:
                df = source.iter_month(symbol, year, month)
            except Exception:
                logger.exception("%s %04d-%02d: download failed", symbol, year, month)
                continue
            if df.empty:
                continue
            df = validate(df)
            inserted, skipped = await upsert_bars(db, df, symbol, source="binance")
            total += inserted
            logger.info(
                "%s %04d-%02d: +%d (skipped %d)", symbol, year, month, inserted, skipped
            )

    logger.info("%s: %d rows inserted", symbol, total)
    return total


async def main_async(symbols: list[str], purge: bool) -> None:
    for symbol in symbols:
        await load_symbol(symbol, purge)


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
    args = parser.parse_args()
    asyncio.run(main_async(args.symbols or crypto, args.purge))


if __name__ == "__main__":
    main()
