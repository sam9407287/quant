"""Pydantic contract describing one backtest run (ADR-003 §2.2).

This schema is the single interface between the engine and every
frontend — the near-term params form and the future node canvas both
compile to this JSON. Keep it literal-typed and fully validated so a
run is reproducible from its stored params alone.
"""

from __future__ import annotations

from datetime import date, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.instruments import Symbol

DirectionMode = Literal["fade", "breakout"]
OffsetMode = Literal["points", "pct", "atr"]
StopMode = Literal["points", "pct", "atr"]


class SessionClock(BaseModel):
    """Wall-clock schedule of one trading session, in a user-chosen tz.

    Windows may wrap midnight (e.g. an Asia range viewed from New York
    is 20:00 → 02:00); membership tests in the engine handle the wrap,
    so no ordering constraint is imposed between start and end here.
    """

    tz: str = "America/New_York"
    range_start: time
    range_end: time
    orders_place: time
    eod_flat: time

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
        """Resolved ZoneInfo — validated at construction, safe to build."""
        return ZoneInfo(self.tz)


class BacktestParams(BaseModel):
    """Every knob of one killzone-OCO run — see docs/STRATEGIES.md."""

    instrument: Symbol = "NQ"
    # NQ prices, MNQ economics by default; both sizing knobs stay
    # adjustable per the 2026-07-19 decision (future position sizing).
    point_value_usd: float = Field(default=2.0, gt=0)
    contracts: int = Field(default=1, ge=1)
    # Optional: each edge left unset means "as far as the stored 1m bars
    # go". The API resolves them to concrete dates before the run is
    # persisted, so a saved run still records exactly what it covered —
    # "everything" is a request, not a reproducible span.
    start: date | None = None
    end: date | None = None

    clock: SessionClock

    direction_mode: DirectionMode = "fade"
    # Signed: positive pushes the entry level beyond the range extreme,
    # negative pulls it inside the range.
    entry_offset_mode: OffsetMode = "points"
    entry_offset_value: float = 0.0

    sl_mode: StopMode = "points"
    sl_value: float = Field(default=100.0, gt=0)
    # Take-profit: explicit tp_points wins when set; otherwise SL × rrr.
    rrr: float | None = Field(default=2.0, gt=0)
    tp_points: float | None = Field(default=None, gt=0)

    atr_period: int = Field(default=14, ge=1)

    # Costs exist in the schema but are intentionally 0 for now
    # (2026-07-19 decision) — enabling them later is a params change.
    slippage_points_per_side: float = Field(default=0.0, ge=0)
    commission_usd_per_rt: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def _validate(self) -> BacktestParams:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("end date must be >= start date")
        if self.tp_points is None and self.rrr is None:
            raise ValueError("either rrr or tp_points must be set")
        return self

    @property
    def span(self) -> tuple[date, date]:
        """The date range this run covers, once resolved.

        `start`/`end` are optional in the request so a caller can ask for
        "every stored bar" without knowing how far back the data goes; the
        API fills them in from the bars before anything runs. Everything
        downstream reads the span through here, so a path that forgot to
        resolve fails loudly instead of running over a silently wrong range.
        """
        if self.start is None or self.end is None:
            raise ValueError("backtest span was never resolved against stored bars")
        return self.start, self.end

    @property
    def uses_atr(self) -> bool:
        """Engine must be fed a per-session ATR when any mode is 'atr'."""
        return self.entry_offset_mode == "atr" or self.sl_mode == "atr"
