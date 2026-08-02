"""Typed strategy-definition contract (ADR-004).

A strategy is one JSONB document: entry/exit signal conditions built
from a small operand algebra, plus an optional SL/TP bracket. The form
builder, the DB row, and the evaluation engine all share this schema —
keep it literal-typed so an impossible strategy fails validation at the
API boundary, not mid-evaluation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

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
OperandKind = Literal[
    "price", "const", "ema", "sma", "rsi", "highest_high", "lowest_low",
    "macd", "macd_signal", "atr", "roc", "bollinger_upper", "bollinger_lower",
]

ConditionOp = Literal["cross_above", "cross_below", "gt", "lt"]


class Operand(BaseModel):
    kind: OperandKind
    window: int = Field(default=14, ge=1, le=500)
    window2: int = Field(default=26, ge=1, le=500)  # macd slow period
    value: float | None = None  # const value, or bollinger std multiple

    @model_validator(mode="after")
    def _validate(self) -> Operand:
        if self.kind == "const" and self.value is None:
            raise ValueError("const operand requires a value")
        if self.kind in ("bollinger_upper", "bollinger_lower") and self.value is None:
            # Standard-deviation multiple; default to the classic 2.0.
            object.__setattr__(self, "value", 2.0)
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

    @model_validator(mode="after")
    def _validate(self) -> StrategyDefinition:
        if self.entry_long is None and self.entry_short is None:
            raise ValueError("at least one of entry_long/entry_short is required")
        return self
