"""Fetcher service entry point.

Run as:
    python fetcher/main.py              # starts the scheduler (runs forever)
    python fetcher/main.py --once       # one-shot fetch then exit
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)


async def _run_scheduler() -> None:
    """Start APScheduler and block until the process is interrupted."""
    from fetcher.scheduler import build_scheduler

    scheduler = build_scheduler()
    scheduler.start()
    logger.info("Scheduler started. Waiting for jobs…")
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler stopped.")


async def _run_once() -> None:
    """Fetch data for all instruments immediately and exit."""
    from fetcher.scheduler import run_daily_fetch

    logger.info("Running one-shot fetch…")
    summary = await run_daily_fetch()
    for instrument, stats in summary.items():
        logger.info(
            "%s: fetched=%d inserted=%d skipped=%d",
            instrument,
            stats["fetched"],
            stats["inserted"],
            stats["skipped"],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Quant Futures data fetcher")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single fetch immediately then exit",
    )
    args = parser.parse_args()

    if args.once:
        asyncio.run(_run_once())
    else:
        asyncio.run(_run_scheduler())


if __name__ == "__main__":
    main()
