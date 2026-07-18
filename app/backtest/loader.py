"""kbars_1m → engine-ready sessions (ADR-003 B2).

The grouping and ATR math are pure functions so they are unit-testable
without a database; `load_sessions` is the thin async shell that runs
the one SQL fetch and delegates to them.

Session convention: a bar belongs to session date D when its wall-clock
timestamp (in the params' timezone) falls in (D-1 eod_flat, D eod_flat].
Concretely: bars at or after `eod_flat` roll forward to the next
calendar date. This puts an evening reference range (e.g. an Asia
session viewed from New York) into the *following* day's session — the
one whose killzone it seeds.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.params import BacktestParams
from app.backtest.types import Bar

# One fetch upper bound. 1 year of 1m CME bars is ~360k rows; this cap
# allows multi-year runs while keeping a runaway request bounded.
MAX_BARS = 3_000_000

# Calendar days fetched before params.start: 2 cover the tz spill of the
# first session; ATR warm-up needs `atr_period` *trading* days, so over-
# fetch generously (weekends/holidays) rather than under-deliver.
_TZ_SPILL_DAYS = 2


def group_sessions(
    bars: Sequence[Bar], params: BacktestParams
) -> list[tuple[date, list[Bar]]]:
    """Group UTC bars into (session_date, bars) using the params clock."""
    zone = params.clock.zone
    eod = params.clock.eod_flat
    grouped: dict[date, list[Bar]] = {}
    for bar in bars:
        local = bar.ts.astimezone(zone)
        session_date = local.date()
        if local.time() >= eod:
            session_date += timedelta(days=1)
        grouped.setdefault(session_date, []).append(bar)
    return sorted(grouped.items())


def session_atr(
    sessions: Sequence[tuple[date, Sequence[Bar]]], period: int
) -> dict[date, float]:
    """ATR per session from *prior* sessions only — no lookahead.

    True range uses each session's aggregate OHLC against the previous
    session's close; the ATR assigned to session i is the simple mean of
    the `period` TRs strictly before i. Sessions inside the warm-up
    window get no entry, which the engine reports as no_data.
    """
    closes: list[float] = []
    trs: list[float] = []
    atr: dict[date, float] = {}
    for i, (session_date, bars) in enumerate(sessions):
        if i >= period and len(trs) >= period:
            window = trs[-period:]
            atr[session_date] = sum(window) / period
        high = max(b.high for b in bars)
        low = min(b.low for b in bars)
        close = bars[-1].close
        if closes:
            prev_close = closes[-1]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        else:
            tr = high - low
        trs.append(tr)
        closes.append(close)
    return atr


async def load_sessions(
    db: AsyncSession, params: BacktestParams
) -> tuple[list[tuple[date, list[Bar]]], dict[date, float] | None]:
    """Fetch 1m bars and return ([sessions in range], atr_by_date | None)."""
    warmup_days = (
        params.atr_period * 2 + 14 if params.uses_atr else 0
    ) + _TZ_SPILL_DAYS
    fetch_start = datetime.combine(
        params.start - timedelta(days=warmup_days), datetime.min.time(), tzinfo=params.clock.zone
    )
    fetch_end = datetime.combine(
        params.end + timedelta(days=_TZ_SPILL_DAYS), datetime.min.time(), tzinfo=params.clock.zone
    )

    stmt = text(
        """
        SELECT ts, open::float AS open, high::float AS high,
               low::float AS low, close::float AS close
        FROM kbars_1m
        WHERE instrument = :instrument
          AND ts >= :start AND ts < :end
        ORDER BY ts ASC
        LIMIT :limit
        """
    )
    rows: Sequence[Any] = (
        await db.execute(
            stmt,
            {
                "instrument": params.instrument,
                "start": fetch_start,
                "end": fetch_end,
                "limit": MAX_BARS + 1,
            },
        )
    ).fetchall()
    if len(rows) > MAX_BARS:
        raise ValueError(
            f"date range yields more than {MAX_BARS:,} 1m bars — narrow the range"
        )

    bars = [Bar(ts=r.ts, open=r.open, high=r.high, low=r.low, close=r.close) for r in rows]
    all_sessions = group_sessions(bars, params)

    atr_by_date = (
        session_atr(all_sessions, params.atr_period) if params.uses_atr else None
    )
    in_range = [
        (d, bs) for d, bs in all_sessions if params.start <= d <= params.end
    ]
    return in_range, atr_by_date
