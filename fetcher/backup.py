"""Off-site backup of irreplaceable data to Cloudflare R2 (ADR-006).

Why this exists: the self-hosted TimescaleDB has no managed backups
(ADR-001 trade-off). Purchased history can always be re-loaded from the
vendor's CSVs, but every bar the daily fetcher accumulates is
unrecoverable once written — yfinance only serves ~7 days of 1m bars.

Design: CSV-over-pg_dump. Backups are plain gzipped CSV uploaded with
the S3 API, so a restore needs no pg_dump version match — apply
db/schema.sql, then COPY the files back in. Bars are written as monthly
partitions: the current month is re-uploaded every run, earlier months
are already complete and are skipped unless --rewrite-all is passed.
Small relational tables are snapshotted whole on every run.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import io
import logging
from datetime import UTC, date, datetime
from typing import Any

import boto3
from botocore.config import Config
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Tables snapshotted in full on every run — all small and all
# unrecoverable if lost (user accounts, saved strategies, run history).
_SNAPSHOT_TABLES = (
    "users",
    "strategies",
    "backtest_runs",
    "backtest_trades",
    "roll_calendar",
    "experiments",
)


def _client(settings: Any) -> Any:  # boto3 has no static client type
    """S3 client pointed at the R2 endpoint for this account."""
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def _gzip_csv(header: list[str], rows: list[tuple[Any, ...]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return gzip.compress(buf.getvalue().encode())


def _months_between(start: date, end: date) -> list[tuple[int, int]]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


async def run_backup(rewrite_all: bool = False) -> dict[str, int]:
    """Upload bar partitions and table snapshots; return bytes per key."""
    settings = get_settings()
    if not settings.r2_bucket or not settings.r2_access_key_id:
        logger.warning("R2 not configured (R2_BUCKET/R2_ACCESS_KEY_ID unset) — skipping backup")
        return {}

    s3 = _client(settings)
    today = datetime.now(UTC).date()
    since = date.fromisoformat(settings.backup_since)
    uploaded: dict[str, int] = {}

    async with AsyncSessionLocal() as db:
        # ── Bars: one gzipped CSV per calendar month ─────────────────
        for year, month in _months_between(since, today):
            is_current = (year, month) == (today.year, today.month)
            if not is_current and not rewrite_all:
                # Past months never change once written. Skip re-upload
                # unless explicitly asked (e.g. after a history load).
                key = f"kbars_1m/{year:04d}-{month:02d}.csv.gz"
                try:
                    s3.head_object(Bucket=settings.r2_bucket, Key=key)
                    continue
                except Exception:  # noqa: BLE001 — any miss means "upload it"
                    pass
            lo = max(date(year, month, 1), since)
            hi = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            rows = (
                await db.execute(
                    text(
                        "SELECT instrument, ts, open, high, low, close, volume, source "
                        "FROM kbars_1m WHERE ts >= :lo AND ts < :hi "
                        "ORDER BY instrument, ts"
                    ),
                    {"lo": lo, "hi": hi},
                )
            ).fetchall()
            if not rows:
                continue
            blob = _gzip_csv(
                ["instrument", "ts", "open", "high", "low", "close", "volume", "source"],
                [tuple(r) for r in rows],
            )
            key = f"kbars_1m/{year:04d}-{month:02d}.csv.gz"
            s3.put_object(Bucket=settings.r2_bucket, Key=key, Body=blob)
            uploaded[key] = len(blob)
            logger.info("backup: %s (%d rows, %d KB)", key, len(rows), len(blob) // 1024)

        # ── Small tables: full snapshot, one prefix per day ──────────
        for table in _SNAPSHOT_TABLES:
            try:
                result = await db.execute(text(f"SELECT * FROM {table}"))  # noqa: S608
                rows = result.fetchall()
                header = list(result.keys())
            except Exception:
                logger.warning("backup: table %s not present — skipped", table)
                continue
            blob = _gzip_csv(header, [tuple(r) for r in rows])
            key = f"tables/{today.isoformat()}/{table}.csv.gz"
            s3.put_object(Bucket=settings.r2_bucket, Key=key, Body=blob)
            uploaded[key] = len(blob)
            logger.info("backup: %s (%d rows)", key, len(rows))

    total_kb = sum(uploaded.values()) // 1024
    logger.info("backup complete: %d objects, %d KB", len(uploaded), total_kb)
    return uploaded


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Back up bars and tables to R2")
    parser.add_argument(
        "--rewrite-all",
        action="store_true",
        help="Re-upload every month, not just the current one (use after a history load)",
    )
    args = parser.parse_args()
    asyncio.run(run_backup(rewrite_all=args.rewrite_all))


if __name__ == "__main__":
    main()
