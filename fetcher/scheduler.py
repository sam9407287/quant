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
from app.db.session import AsyncSessionLocal
from fetcher.pipeline import flag_anomalies, update_coverage, upsert_bars, validate
from fetcher.sources.yfinance_source import YFinanceSource

logger = logging.getLogger(__name__)
_settings = get_settings()
_source = YFinanceSource()


async def run_daily_fetch(instruments: list[str] | None = None) -> dict[str, dict]:
    """Fetch and persist the latest 1m bars for all configured instruments.

    Uses a 7-day overlap window to guard against yfinance gaps; the
    upsert deduplication ensures overlapping bars are silently skipped.

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
            try:
                df = _source.fetch(instrument, start, end, timeframe="1m")
                df = validate(df)
                df = flag_anomalies(df, instrument)
                inserted, skipped = await upsert_bars(
                    session, df, instrument, source=_source.source_name
                )
                await update_coverage(session, instrument, timeframe="1m", fetch_ok=True)
                summary[instrument] = {
                    "fetched": len(df),
                    "inserted": inserted,
                    "skipped": skipped,
                }
            except Exception:
                logger.exception("Daily fetch failed for %s", instrument)
                await update_coverage(session, instrument, timeframe="1m", fetch_ok=False)
                summary[instrument] = {"fetched": 0, "inserted": 0, "skipped": 0}

    logger.info("Daily fetch complete: %s", summary)
    return summary


def build_scheduler() -> AsyncIOScheduler:
    """Construct and configure the APScheduler instance."""
    scheduler = AsyncIOScheduler(timezone="UTC")

    # Parse cron expression from settings (default: weekdays at 18:00 UTC)
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
        name="Daily 1m bar ingestion",
        max_instances=1,       # prevent overlapping runs
        misfire_grace_time=3600,
    )

    return scheduler
