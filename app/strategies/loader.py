"""Bars loading for strategy evaluation.

Selects EXACTLY the rows the chart endpoint selects (`bars_stmt`), so a
strategy is scored on the series the chart draws — markers computed from
raw prices would drift from ratio-adjusted candles at every contract roll.

Where this differs from the chart's loader is shape, not content: bars go
straight from the driver's rows into numpy columns, never through a list of
per-bar dicts. At the chart's 50 000-bar ceiling that choice is invisible;
at the ten million a full-history backtest may ask for, a dict per bar is
gigabytes of garbage and the `Decimal` adjustment is minutes of arithmetic.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.kbars import _TIMEFRAME_SOURCE, _fetch_rolls, bars_stmt
from app.core.adjustment import adjustment_offsets

# A strategy is scored over every bar in its range, so this ceiling exists
# only to bound a runaway request — it is not a display limit. Ten million
# 1m bars is roughly 27 years of CME futures; 18 years of purchased history
# would be about seven. At that size a run costs roughly 10 s of CPU and
# 1.9 GB of peak memory (see `_stream_frame`), so this is a memory budget as
# much as a row count. Hitting it raises rather than truncating: statistics
# computed over a silent subset of the range the caller asked for would be
# wrong without looking wrong.
MAX_BARS = 10_000_000

_COLUMNS = ("ts", "open", "high", "low", "close", "volume")

# Rows held in memory at once while streaming. Large enough that the
# per-partition overhead is noise, small enough that the transient is.
_PARTITION = 100_000


async def load_bars_df(
    db: AsyncSession,
    instrument: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    adjustment: str = "ratio",
) -> pd.DataFrame:
    """Fetch bars at the strategy's timeframe as a DataFrame."""
    df = await _stream_frame(db, timeframe, instrument, start, end)
    if df.empty:
        return df

    if adjustment == "raw":
        return df
    rolls = await _fetch_rolls(db, instrument, start, end)
    if not rolls:
        return df

    factors = adjustment_offsets(
        df["ts"].to_numpy(dtype="datetime64[ns]"), rolls, adjustment
    )
    for col in ("open", "high", "low", "close"):
        values = df[col].to_numpy()
        adjusted = values * factors if adjustment == "ratio" else values + factors
        # Same 4-decimal quantum the reference implementation rounds to.
        df[col] = np.round(adjusted, 4)
    return df


async def _stream_frame(
    db: AsyncSession,
    timeframe: str,
    instrument: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """Read the range in partitions, converting each to columns as it lands.

    Two things were holding hundreds of bytes per bar that the finished
    frame does not need: the whole result set as driver rows, and every
    timestamp as a Python datetime (56 bytes each against the 8 a
    datetime64 column stores). Both now live only for one partition —
    timestamps are folded to int64 nanoseconds on arrival — so peak memory
    tracks the finished columns rather than the row count.

    Measured over two million synthetic bars: ~450 B/bar before, ~190 after,
    of which 48 is the frame itself and most of the rest is the transient
    copy that concatenating the partitions makes. Ten million bars is
    therefore ~1.9 GB — comfortable on a 4 GB container, not on 1 GB. If a
    run ever OOMs, that is the number to lower MAX_BARS against.
    """
    times: list[np.ndarray] = []
    cols: list[tuple[np.ndarray, ...]] = []
    tz: object = None
    total = 0

    result = await db.stream(
        bars_stmt(_TIMEFRAME_SOURCE[timeframe]),
        {"instrument": instrument, "start": start, "end": end, "limit": MAX_BARS + 1},
    )
    async for rows in result.partitions(_PARTITION):
        total += len(rows)
        if total > MAX_BARS:
            await result.close()
            raise ValueError(
                f"range holds more than {MAX_BARS:,} {timeframe} bars — narrow it"
            )
        ts, o, h, low, c, vol = zip(*rows, strict=True)
        # as_unit pins the resolution: `asi8` is whatever unit the index
        # carries, and a timestamptz column arrives as microseconds — read
        # as nanoseconds that put every bar in 1970.
        index = pd.DatetimeIndex(ts).as_unit("ns")
        tz = index.tz
        times.append(index.asi8)
        cols.append(
            (
                np.asarray(o, dtype=float),
                np.asarray(h, dtype=float),
                np.asarray(low, dtype=float),
                np.asarray(c, dtype=float),
                np.asarray(vol, dtype="int64"),
            )
        )
        del rows, ts, index

    if not cols:
        return pd.DataFrame(columns=list(_COLUMNS))

    stamps = pd.DatetimeIndex(np.concatenate(times).view("datetime64[ns]"))
    return pd.DataFrame(
        {
            "ts": stamps.tz_localize("UTC").tz_convert(tz) if tz is not None else stamps,
            **{
                name: np.concatenate([c[k] for c in cols])
                for k, name in enumerate(("open", "high", "low", "close", "volume"))
            },
        }
    )
