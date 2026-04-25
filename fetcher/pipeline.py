"""Data ingestion pipeline: validate, deduplicate, and persist bars.

The pipeline layer is intentionally kept free of business logic about
where data comes from. It accepts a normalised DataFrame and applies:
  1. Schema validation — reject rows missing required fields.
  2. Anomaly flagging — log bars with extreme price moves (> 5%).
  3. Upsert — INSERT … ON CONFLICT DO NOTHING to deduplicate safely.
  4. Coverage update — refresh the data_coverage tracking table.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Columns required in every incoming DataFrame
_REQUIRED_COLS = {"ts", "open", "high", "low", "close", "volume"}

# Single bar price change threshold above which we emit a warning
_ANOMALY_THRESHOLD = 0.05


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
    # Drop rows with null OHLCV
    df = df.dropna(subset=list(_REQUIRED_COLS))
    # Drop zero-volume rows (outside trading hours)
    df = df[df["volume"] > 0]
    # Ensure ts is UTC-aware
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
    """Log bars whose price change vs. previous bar exceeds the threshold."""
    if df.empty:
        return df
    pct_change = df["close"].pct_change().abs()
    anomalies = df[pct_change > _ANOMALY_THRESHOLD]
    for _, row in anomalies.iterrows():
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

    Uses a server-side COPY-equivalent via executemany for performance,
    falling back to INSERT … ON CONFLICT DO NOTHING for correctness.

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


async def update_coverage(
    session: AsyncSession,
    instrument: str,
    timeframe: str = "1m",
    fetch_ok: bool = True,
) -> None:
    """Refresh the data_coverage row for the given instrument/timeframe."""
    stmt = text(
        """
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
        FROM kbars_1m
        WHERE instrument = :instrument
        ON CONFLICT (instrument, timeframe) DO UPDATE SET
            earliest_ts   = EXCLUDED.earliest_ts,
            latest_ts     = EXCLUDED.latest_ts,
            bar_count     = EXCLUDED.bar_count,
            last_fetch_ts = EXCLUDED.last_fetch_ts,
            last_fetch_ok = EXCLUDED.last_fetch_ok,
            updated_at    = NOW()
        """
    )
    await session.execute(
        stmt,
        {"instrument": instrument, "timeframe": timeframe, "fetch_ok": fetch_ok},
    )
    await session.commit()
