"""Shared value types for the backtest engine.

Kept in their own module so strategies and the engine can both import
them without a circular dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

Direction = Literal["long", "short"]

# `sl` also covers the touched-both-SL-and-TP bar (pessimistic tie rule,
# ADR-003 §2.1). `ambiguous` marks a bar that touched BOTH entry levels
# equidistantly from its open — unresolvable on 1m data, so no trade.
ExitReason = Literal["tp", "sl", "eod", "no_fill", "no_data", "ambiguous"]


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLC bar; `ts` is the bar's open timestamp, tz-aware UTC."""

    ts: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class DayResult:
    """One session's outcome — the row Monte Carlo / seasonality read."""

    session_date: date
    exit_reason: ExitReason
    direction: Direction | None = None
    entry_ts: datetime | None = None
    entry_price: float | None = None
    exit_ts: datetime | None = None
    exit_price: float | None = None
    pnl_points: float = 0.0
    pnl_usd: float = 0.0
    mae_points: float = 0.0
    mfe_points: float = 0.0
    range_high: float | None = None
    range_low: float | None = None
