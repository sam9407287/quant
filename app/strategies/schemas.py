"""Typed strategy-definition contract (ADR-004).

A strategy is one JSONB document: entry/exit signal conditions built
from a small operand algebra, plus an optional SL/TP bracket. The form
builder, the DB row, and the evaluation engine all share this schema —
keep it literal-typed so an impossible strategy fails validation at the
API boundary, not mid-evaluation.
"""

from __future__ import annotations

from datetime import time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w"]

# Operand kinds and how each reads its fields:
#   price/const               — structural (const uses `value`)
#   ema/sma/rsi               — single `window`
#   highest_high/lowest_low   — Donchian extremes of the PRIOR `window`
#                               bars (shifted so a breakout compares
#                               against a channel that excludes today)
#   macd/macd_signal          — `window` = fast, `window2` = slow
#                               (signal line = 9-EMA of the MACD line)
#   atr/roc                   — single `window`
#   bollinger_upper/_lower    — SMA(`window`) ± `value` standard deviations
#   session_high/session_low  — extreme of the intraday window
#                               [`time_start`, `time_end`) within the
#                               current session; NaN until that window
#                               closes, so a forming range is unreadable.
#                               Requires the strategy to declare a session.
OperandKind = Literal[
    "price", "const", "ema", "sma", "rsi", "highest_high", "lowest_low",
    "macd", "macd_signal", "atr", "roc", "bollinger_upper", "bollinger_lower",
    "session_high", "session_low",
]

SESSION_OPERANDS = ("session_high", "session_low")

ConditionOp = Literal["cross_above", "cross_below", "gt", "lt"]


class Operand(BaseModel):
    kind: OperandKind
    window: int = Field(default=14, ge=1, le=500)
    window2: int = Field(default=26, ge=1, le=500)  # macd slow period
    value: float | None = None  # const value, or bollinger std multiple
    time_start: time | None = None  # session_high/low window
    time_end: time | None = None

    @model_validator(mode="after")
    def _validate(self) -> Operand:
        if self.kind == "const" and self.value is None:
            raise ValueError("const operand requires a value")
        if self.kind in ("bollinger_upper", "bollinger_lower") and self.value is None:
            # Standard-deviation multiple; default to the classic 2.0.
            object.__setattr__(self, "value", 2.0)
        if self.kind in SESSION_OPERANDS:
            if self.time_start is None or self.time_end is None:
                raise ValueError(f"{self.kind} requires time_start and time_end")
            if self.time_start == self.time_end:
                raise ValueError(f"{self.kind} window is empty")
        return self


class SessionSpec(BaseModel):
    """The trading session an intraday strategy lives inside.

    `close` is also the forced-flat time: a position still open on the
    session's last bar is closed there rather than carried overnight.
    Windows may wrap midnight (an Asia session read from New York), so no
    ordering is imposed between open and close; equal times mean 24h.
    """

    tz: str = "America/New_York"
    open: time
    close: time

    @field_validator("tz")
    @classmethod
    def _tz_exists(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown IANA timezone: {v!r}") from exc
        return v

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)


class StopEntry(BaseModel):
    """Two resting orders bracketing a level pair, first touch wins.

    This is the order-driven counterpart to the signal-driven
    `entry_long`/`entry_short`: rather than a condition firing at a close
    and entering at the next open, orders rest at price levels and fill
    the moment a bar trades through them. It is what an ICT killzone
    needs and what a cross-condition cannot express.

    `upper_level`/`lower_level` are usually `session_high`/`session_low`,
    pushed out by `offset`. Which side is the long depends on the mode:
    breakout buys the upper break, fade sells it.
    """

    upper_level: Operand | None = None
    lower_level: Operand | None = None
    mode: Literal["breakout", "fade"] = "breakout"
    offset_mode: Literal["points", "pct", "atr"] = "points"
    offset_value: float = Field(default=0.0, ge=0)
    atr_period: int = Field(default=14, ge=1, le=500)
    # Orders rest only from this local time — an ICT setup places them at
    # the killzone's close, not the moment the session opens.
    active_from: time | None = None
    # One fill cancels the other side. Off ⇒ the second level can still
    # fill later in the session (subject to max_trades_per_session).
    oco: bool = True

    @model_validator(mode="after")
    def _validate(self) -> StopEntry:
        if self.upper_level is None and self.lower_level is None:
            raise ValueError("stop entry needs at least one of upper_level/lower_level")
        return self


class Condition(BaseModel):
    op: ConditionOp
    left: Operand
    right: Operand


class Bracket(BaseModel):
    mode: Literal["pct", "points"]
    value: float = Field(gt=0)


class StrategyDefinition(BaseModel):
    timeframe: Timeframe
    default_lookback_days: int = Field(default=180, ge=1, le=3650)
    entry_long: Condition | None = None
    entry_short: Condition | None = None
    exit_long: Condition | None = None
    exit_short: Condition | None = None
    # Filter rules gate EVERY entry signal: an entry only fires when all
    # filters are also true. Unlike a trigger (a discrete cross), a
    # filter is a standing condition — e.g. "only go long while price is
    # above the 200 SMA" (CMT curriculum: trigger vs filter rules).
    filters: list[Condition] = Field(default_factory=list)
    sl: Bracket | None = None
    tp: Bracket | None = None
    # Intraday scaffolding. A strategy without a session is the original
    # continuous one: no forced flat, no per-session limits, and session
    # operands unavailable.
    session: SessionSpec | None = None
    stop_entry: StopEntry | None = None
    max_trades_per_session: int | None = Field(default=None, ge=1, le=100)

    def operands(self) -> list[Operand]:
        """Every operand referenced anywhere in the definition."""
        conds = [self.entry_long, self.entry_short, self.exit_long, self.exit_short]
        found = [side for c in conds + self.filters if c for side in (c.left, c.right)]
        if self.stop_entry:
            found += [o for o in (self.stop_entry.upper_level, self.stop_entry.lower_level) if o]
        return found

    @model_validator(mode="after")
    def _validate(self) -> StrategyDefinition:
        if self.entry_long is None and self.entry_short is None and self.stop_entry is None:
            raise ValueError(
                "a strategy needs an entry: entry_long, entry_short, or stop_entry"
            )
        if self.session is None:
            offenders = {o.kind for o in self.operands() if o.kind in SESSION_OPERANDS}
            if offenders:
                raise ValueError(
                    f"{'/'.join(sorted(offenders))} requires the strategy to define a session"
                )
            if self.max_trades_per_session is not None:
                raise ValueError("max_trades_per_session requires a session")
            if self.stop_entry is not None and self.stop_entry.active_from is not None:
                raise ValueError("stop_entry.active_from requires a session")
        return self
