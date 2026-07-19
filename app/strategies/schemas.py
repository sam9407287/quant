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

# price/const are structural; ema/sma/rsi delegate to
# app.ml.features.build_feature (kind names align on purpose);
# highest_high/lowest_low are Donchian-style extremes of the PRIOR
# `window` bars (shifted one bar so a breakout compares against a
# channel that excludes the current bar).
OperandKind = Literal[
    "price", "const", "ema", "sma", "rsi", "highest_high", "lowest_low"
]

ConditionOp = Literal["cross_above", "cross_below", "gt", "lt"]


class Operand(BaseModel):
    kind: OperandKind
    window: int = Field(default=14, ge=1, le=500)
    value: float | None = None  # const only

    @model_validator(mode="after")
    def _validate(self) -> Operand:
        if self.kind == "const" and self.value is None:
            raise ValueError("const operand requires a value")
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
    sl: Bracket | None = None
    tp: Bracket | None = None

    @model_validator(mode="after")
    def _validate(self) -> StrategyDefinition:
        if self.entry_long is None and self.entry_short is None:
            raise ValueError("at least one of entry_long/entry_short is required")
        return self
