"""Bars loading for strategy evaluation.

Reuses the kbars endpoint's fetch/adjustment helpers so a strategy is
evaluated on EXACTLY the series the chart displays — if the chart shows
ratio-adjusted prices, markers computed from raw prices would drift
apart at every contract roll.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.kbars import _TIMEFRAME_SOURCE, _fetch_bars, _fetch_rolls
from app.core.adjustment import apply_absolute_adjustment, apply_ratio_adjustment

# A strategy is scored over every bar in its range, so this ceiling exists
# only to bound a runaway request — it is not a display limit. It matches
# the backtest loader's, which is ~8 years of 1m CME bars. Hitting it raises
# rather than truncating: statistics computed over a silent subset of the
# range the caller asked for would be wrong without looking wrong.
MAX_BARS = 3_000_000


async def load_bars_df(
    db: AsyncSession,
    instrument: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    adjustment: str = "ratio",
) -> pd.DataFrame:
    """Fetch bars at the strategy's timeframe as a DataFrame."""
    source = _TIMEFRAME_SOURCE[timeframe]
    rows = await _fetch_bars(db, source, instrument, start, end, MAX_BARS + 1)
    if len(rows) > MAX_BARS:
        raise ValueError(
            f"range holds more than {MAX_BARS:,} {timeframe} bars — narrow it"
        )
    if adjustment != "raw" and rows:
        rolls = await _fetch_rolls(db, instrument, start, end)
        rows = (
            apply_ratio_adjustment(rows, rolls)
            if adjustment == "ratio"
            else apply_absolute_adjustment(rows, rolls)
        )
    if not rows:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    return pd.DataFrame(rows)
