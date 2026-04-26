"""Data ingestion pipeline: validate, deduplicate, persist, and aggregate bars.

The pipeline layer is intentionally kept free of business logic about
where data comes from. It accepts a normalised DataFrame and applies:
  1. Schema validation — reject rows missing required fields.
  2. Anomaly flagging — log bars with extreme price moves (> 5%).
  3. Upsert — INSERT … ON CONFLICT DO NOTHING to deduplicate safely.
  4. Aggregation — recompute higher timeframe tables from kbars_1m.
  5. Coverage update — refresh the data_coverage tracking table.
"""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_REQUIRED_COLS = {"ts", "open", "high", "low", "close", "volume"}
_ANOMALY_THRESHOLD = 0.05

# Timeframe → (target table, SQL bucket expression)
# PostgreSQL date_trunc only supports fixed unit strings, so sub-hour buckets
# use arithmetic on epoch seconds instead.
_TIMEFRAME_BUCKETS: dict[str, tuple[str, str]] = {
    "5m":  ("kbars_5m",  "epoch_300"),    # 300  seconds
    "15m": ("kbars_15m", "epoch_900"),    # 900  seconds
    "1h":  ("kbars_1h",  "hour"),
    "4h":  ("kbars_4h",  "epoch_14400"), # 14400 seconds
    "1d":  ("kbars_1d",  "day"),
    "1w":  ("kbars_1w",  "week"),
}


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and clean an OHLCV DataFrame.

    Args:
        df: Raw DataFrame from a DataSource.

    Returns:
        Cleaned DataFrame with only valid rows.

    Raises:
        ValueError: If required columns are missing.
    """
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    before = len(df)
    df = df.dropna(subset=list(_REQUIRED_COLS))
    df = df[df["volume"] > 0]
    if df["ts"].dt.tz is None:
        df = df.copy()
        df["ts"] = df["ts"].dt.tz_localize("UTC")
    else:
        df = df.copy()
        df["ts"] = df["ts"].dt.tz_convert("UTC")

    dropped = before - len(df)
    if dropped:
        logger.debug("Dropped %d invalid rows during validation", dropped)
    return df.reset_index(drop=True)


def flag_anomalies(df: pd.DataFrame, instrument: str) -> pd.DataFrame:
    """Log bars whose close-to-close change exceeds the anomaly threshold."""
    if df.empty:
        return df
    pct_change = df["close"].pct_change().abs()
    for _, row in df[pct_change > _ANOMALY_THRESHOLD].iterrows():
        logger.warning(
            "Anomaly detected in %s at %s: close=%s (%.1f%% move)",
            instrument,
            row["ts"],
            row["close"],
            pct_change.loc[row.name] * 100,
        )
    return df


async def upsert_bars(
    session: AsyncSession,
    df: pd.DataFrame,
    instrument: str,
    source: str,
) -> tuple[int, int]:
    """Bulk-upsert bars into kbars_1m, skipping duplicates.

    Args:
        session:    Active async SQLAlchemy session.
        df:         Validated DataFrame.
        instrument: e.g. 'NQ'.
        source:     Data source identifier, e.g. 'yfinance'.

    Returns:
        (rows_inserted, rows_skipped) tuple.
    """
    if df.empty:
        return 0, 0

    rows = [
        {
            "instrument": instrument,
            "ts": row["ts"].to_pydatetime(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"]),
            "source": source,
        }
        for _, row in df.iterrows()
    ]

    stmt = text(
        """
        INSERT INTO kbars_1m (instrument, ts, open, high, low, close, volume, source)
        VALUES (:instrument, :ts, :open, :high, :low, :close, :volume, :source)
        ON CONFLICT (instrument, ts) DO NOTHING
        """
    )

    result = await session.execute(stmt, rows)
    await session.commit()

    inserted = result.rowcount if result.rowcount >= 0 else len(rows)
    skipped = len(rows) - inserted
    logger.info(
        "%s: fetched=%d inserted=%d skipped=%d source=%s",
        instrument, len(rows), inserted, skipped, source,
    )
    return inserted, skipped


async def aggregate_higher_timeframes(
    session: AsyncSession,
    instrument: str,
) -> None:
    """Recompute all higher timeframe tables from kbars_1m for one instrument.

    Uses INSERT … ON CONFLICT DO UPDATE so that re-running is idempotent:
    existing bars are refreshed with the latest aggregated values, and new
    bars are inserted. This handles partial bars (e.g. the current day's
    incomplete 1d bar) correctly — they are updated on each run.

    Args:
        session:    Active async SQLAlchemy session.
        instrument: e.g. 'NQ'.
    """
    for tf, (table, bucket) in _TIMEFRAME_BUCKETS.items():
        # Build the bucket expression based on the bucket type.
        # Sub-hour buckets use epoch-seconds arithmetic; others use date_trunc.
        if bucket.startswith("epoch_"):
            secs = int(bucket.split("_")[1])
            bucket_expr = (
                f"TO_TIMESTAMP(FLOOR(EXTRACT(EPOCH FROM ts) / {secs}) * {secs})"
                f" AT TIME ZONE 'UTC'"
            )
            group_expr = bucket_expr
        else:
            bucket_expr = f"date_trunc('{bucket}', ts)"
            group_expr  = f"date_trunc('{bucket}', ts)"

        stmt = text(
            f"""
            INSERT INTO {table} (instrument, ts, open, high, low, close, volume, source)
            SELECT
                instrument,
                {bucket_expr}                                   AS ts,
                (array_agg(open  ORDER BY ts ASC))[1]          AS open,
                MAX(high)                                       AS high,
                MIN(low)                                        AS low,
                (array_agg(close ORDER BY ts DESC))[1]         AS close,
                SUM(volume)                                     AS volume,
                'aggregate'                                     AS source
            FROM kbars_1m
            WHERE instrument = :instrument
            GROUP BY instrument, {group_expr}
            ON CONFLICT (instrument, ts) DO UPDATE SET
                open   = EXCLUDED.open,
                high   = EXCLUDED.high,
                low    = EXCLUDED.low,
                close  = EXCLUDED.close,
                volume = EXCLUDED.volume
            """  # noqa: S608
        )
        await session.execute(stmt, {"instrument": instrument})
        await session.commit()
        logger.debug("Aggregated 1m → %s for %s", tf, instrument)

    logger.info("%s: higher timeframe aggregation complete", instrument)


async def update_coverage(
    session: AsyncSession,
    instrument: str,
    timeframe: str = "1m",
    fetch_ok: bool = True,
) -> None:
    """Refresh the data_coverage row for the given instrument/timeframe."""
    # Determine source table for bar count
    table = "kbars_1m" if timeframe == "1m" else f"kbars_{timeframe}"

    stmt = text(
        f"""
        INSERT INTO data_coverage
            (instrument, timeframe, earliest_ts, latest_ts, bar_count,
             last_fetch_ts, last_fetch_ok, updated_at)
        SELECT
            :instrument,
            :timeframe,
            MIN(ts),
            MAX(ts),
            COUNT(*),
            NOW(),
            :fetch_ok,
            NOW()
        FROM {table}
        WHERE instrument = :instrument
        ON CONFLICT (instrument, timeframe) DO UPDATE SET
            earliest_ts   = EXCLUDED.earliest_ts,
            latest_ts     = EXCLUDED.latest_ts,
            bar_count     = EXCLUDED.bar_count,
            last_fetch_ts = EXCLUDED.last_fetch_ts,
            last_fetch_ok = EXCLUDED.last_fetch_ok,
            updated_at    = NOW()
        """  # noqa: S608
    )
    await session.execute(
        stmt,
        {"instrument": instrument, "timeframe": timeframe, "fetch_ok": fetch_ok},
    )
    await session.commit()


async def update_all_coverage(
    session: AsyncSession,
    instrument: str,
    fetch_ok: bool = True,
) -> None:
    """Refresh data_coverage for all timeframes of one instrument."""
    all_timeframes = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
    for tf in all_timeframes:
        await update_coverage(session, instrument, timeframe=tf, fetch_ok=fetch_ok)
