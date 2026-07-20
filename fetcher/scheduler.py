"""APScheduler job definitions for daily data ingestion.

The scheduler runs as a long-lived process inside the Fetcher service.
It triggers the daily fetch job on weekdays at 18:00 UTC (after CME
regular-session close at 17:00 ET) and exposes a manual one-shot trigger
for operational use (e.g. backfilling a missed run).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.core.instruments import get_data_source
from app.db.session import AsyncSessionLocal
from fetcher.backup import run_backup
from fetcher.notifier import notify
from fetcher.pipeline import (
    flag_anomalies,
    refresh_continuous_aggregates,
    update_all_coverage,
    upsert_bars,
    validate,
)
from fetcher.sources.binance_source import BinanceSource
from fetcher.sources.yfinance_source import YFinanceSource

logger = logging.getLogger(__name__)
_settings = get_settings()
# One adapter per provider; the registry decides which an instrument uses.
_sources = {"yfinance": YFinanceSource(), "binance": BinanceSource()}


async def run_daily_fetch(instruments: list[str] | None = None) -> dict[str, dict]:
    """Fetch and persist bars for all configured instruments, then refresh CAs.

    Pipeline:
      Per instrument
        1. Fetch 7-day overlap of 1m bars from yfinance
        2. Validate and flag anomalies
        3. Upsert into kbars_1m (dedup via ON CONFLICT DO NOTHING)
        4. Refresh data_coverage for all timeframes
      After loop
        5. Refresh all higher-timeframe Continuous Aggregates once

    Higher-timeframe rollup is owned by TimescaleDB Continuous Aggregates;
    we only force a fresh refresh so the API sees the new data immediately.

    Args:
        instruments: Override the instrument list from settings (useful for tests).

    Returns:
        Per-instrument summary dict with keys: fetched, inserted, skipped.
    """
    targets = instruments or _settings.fetch_instruments
    end = datetime.now(UTC)
    start = end - timedelta(days=_settings.fetch_overlap_days)

    summary: dict[str, dict] = {}

    async with AsyncSessionLocal() as session:
        for instrument in targets:
            logger.info("Starting daily fetch for %s (%s → %s)", instrument, start, end)
            source = _sources[get_data_source(instrument)]
            try:
                df = source.fetch(instrument, start, end, timeframe="1m")
                df = validate(df)
                df = flag_anomalies(df, instrument)
                inserted, skipped = await upsert_bars(
                    session, df, instrument, source=source.source_name
                )
                await update_all_coverage(session, instrument, fetch_ok=True)
                summary[instrument] = {
                    "fetched": len(df),
                    "inserted": inserted,
                    "skipped": skipped,
                }
            except Exception:
                logger.exception("Daily fetch failed for %s", instrument)
                await update_all_coverage(session, instrument, fetch_ok=False)
                summary[instrument] = {"fetched": 0, "inserted": 0, "skipped": 0}

    # Refresh CAs once after all instruments are written. CAs cover all
    # instruments by design, so a single refresh covers everything. We
    # rely on the pipeline's default window (14 days) instead of deriving
    # one from fetch_overlap_days — the refresh window must enclose at
    # least one complete bucket of every CA's bucket size, and weekly
    # buckets need ≥ 7 days of headroom that fetch_overlap_days cannot
    # guarantee.
    try:
        await refresh_continuous_aggregates()
    except Exception:
        logger.exception("Continuous aggregate refresh failed")

    duration = (datetime.now(UTC) - end + timedelta(days=_settings.fetch_overlap_days)).total_seconds()
    all_ok = all(s["fetched"] > 0 for s in summary.values())
    notify(summary, success=all_ok, duration_seconds=abs(duration))

    logger.info("Daily fetch complete: %s", summary)

    # Back up right after ingestion: the new bars are the whole reason
    # the backup exists, and a failure here must not fail the fetch.
    try:
        await run_backup()
    except Exception:
        logger.exception("Off-site backup failed (data is still in the DB)")

    return summary


def build_scheduler() -> AsyncIOScheduler:
    """Construct and configure the APScheduler instance."""
    scheduler = AsyncIOScheduler(timezone="UTC")

    cron_parts = _settings.fetch_cron.split()
    trigger = CronTrigger(
        minute=cron_parts[0],
        hour=cron_parts[1],
        day_of_week=cron_parts[4] if len(cron_parts) > 4 else "*",
        timezone="UTC",
    )

    scheduler.add_job(
        run_daily_fetch,
        trigger=trigger,
        id="daily_fetch",
        name="Daily 1m bar ingestion + aggregation",
        max_instances=1,
        misfire_grace_time=3600,
    )

    return scheduler
