"""Data ingestion pipeline: validate, deduplicate, persist, and refresh aggregates.

The pipeline is intentionally agnostic about where data comes from. It accepts
a normalised DataFrame and applies, in order:

  1. Schema validation     — reject rows missing required fields.
  2. Anomaly flagging      — log bars with extreme price moves (> 5%).
  3. Upsert                — INSERT … ON CONFLICT DO NOTHING for safe dedup.
  4. CA refresh            — incrementally refresh Continuous Aggregates so the
                             higher-timeframe views reflect the new 1m bars.
  5. Coverage update       — refresh the data_coverage tracking table.

Aggregation itself is owned by TimescaleDB Continuous Aggregates (see
db/schema.sql). The pipeline only triggers the refresh window after each
write — it never recomputes aggregates manually.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

logger = logging.getLogger(__name__)

_REQUIRED_COLS = {"ts", "open", "high", "low", "close", "volume"}
_ANOMALY_THRESHOLD = 0.05

# Continuous Aggregate views — refreshed after each daily fetch.
CONTINUOUS_AGGREGATE_VIEWS: tuple[str, ...] = (
    "kbars_5m",
    "kbars_15m",
    "kbars_1h",
    "kbars_4h",
    "kbars_1d",
    "kbars_1w",
)


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

    # asyncpg's executemany doesn't report rowcount reliably, so we compute
    # `inserted` by diffing the row count before vs after the upsert. This
    # also avoids any ambiguity with ON CONFLICT DO NOTHING semantics.
    count_stmt = text(
        "SELECT COUNT(*) FROM kbars_1m "
        "WHERE instrument = :instrument AND ts >= :ts_min AND ts <= :ts_max"
    )
    ts_values = [r["ts"] for r in rows]
    count_params = {
        "instrument": instrument,
        "ts_min": min(ts_values),
        "ts_max": max(ts_values),
    }
    pre_count = (await session.execute(count_stmt, count_params)).scalar() or 0

    stmt = text(
        """
        INSERT INTO kbars_1m (instrument, ts, open, high, low, close, volume, source)
        VALUES (:instrument, :ts, :open, :high, :low, :close, :volume, :source)
        ON CONFLICT (instrument, ts) DO NOTHING
        """
    )
    await session.execute(stmt, rows)
    await session.commit()

    post_count = (await session.execute(count_stmt, count_params)).scalar() or 0
    inserted = post_count - pre_count
    skipped = len(rows) - inserted

    logger.info(
        "%s: fetched=%d inserted=%d skipped=%d source=%s",
        instrument, len(rows), inserted, skipped, source,
    )
    return inserted, skipped


async def refresh_continuous_aggregates(
    window: timedelta = timedelta(days=8),
    engine: AsyncEngine | None = None,
) -> None:
    """Force-refresh all higher-timeframe Continuous Aggregates over a window.

    CAs are also refreshed by their own background policies (see schema.sql),
    but those run on a schedule. This call ensures fresh data is visible
    immediately after a fetch — important because the API reads directly
    from the CA views.

    `CALL refresh_continuous_aggregate(...)` is a procedure and cannot run
    inside an existing transaction, so we open a dedicated AUTOCOMMIT
    connection from the engine pool.

    Args:
        window: How far back to refresh. Defaults to 8 days (covers the
                7-day fetcher overlap plus a safety margin).
        engine: Optional engine override. Tests pass their fixture-bound
                engine here so the refresh runs on the same event loop as
                the rest of the test; production callers leave this None
                and the module-level engine is used.
    """
    if engine is None:
        # Lazy import so this module can be imported without app.core wired
        # up (e.g. unit tests that fully mock the DB layer).
        from app.db.session import engine as default_engine
        engine = default_engine

    end = datetime.now(UTC)
    start = end - window

    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for view in CONTINUOUS_AGGREGATE_VIEWS:
            # Explicit CAST(... AS TIMESTAMPTZ) because the procedure is
            # overloaded — without it asyncpg raises IndeterminateDatatypeError.
            # PostgreSQL's `::` cast syntax can't be used here: SQLAlchemy
            # mistakes the second colon for a bind-param marker.
            stmt = text(
                f"CALL refresh_continuous_aggregate("  # noqa: S608
                f"'{view}', "
                f"CAST(:start AS TIMESTAMPTZ), "
                f"CAST(:end AS TIMESTAMPTZ))"
            )
            await conn.execute(stmt, {"start": start, "end": end})
            logger.debug("Refreshed CA %s over [%s, %s]", view, start, end)

    logger.info(
        "Continuous aggregates refreshed for window [%s, %s]", start, end
    )


async def update_coverage(
    session: AsyncSession,
    instrument: str,
    timeframe: str = "1m",
    fetch_ok: bool = True,
) -> None:
    """Refresh the data_coverage row for the given instrument/timeframe."""
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
