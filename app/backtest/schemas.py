"""API request/response models for /api/v1/backtest (ADR-003 B4).

BacktestParams itself lives in params.py — it is the engine contract;
these models are only the HTTP envelope around it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.backtest.params import BacktestParams


class RunRequest(BaseModel):
    params: BacktestParams
    notes: str | None = None


class MetricsModel(BaseModel):
    """JSON mirror of analysis.SummaryMetrics."""

    session_count: int
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float
    total_pnl_usd: float
    profit_factor: float | None
    expectancy_usd: float
    max_drawdown_usd: float
    sharpe_annualized: float | None
    best_day_usd: float
    worst_day_usd: float


class EquityPoint(BaseModel):
    date: str
    equity_usd: float


class TradeRecord(BaseModel):
    session_date: date
    exit_reason: str
    direction: str | None
    entry_ts: datetime | None
    entry_price: float | None
    exit_ts: datetime | None
    exit_price: float | None
    pnl_points: float
    pnl_usd: float
    mae_points: float
    mfe_points: float
    range_high: float | None
    range_low: float | None


class RunResponse(BaseModel):
    run_id: str
    runtime_ms: int
    metrics: MetricsModel
    equity_curve: list[EquityPoint]
    trades: list[TradeRecord]


class RunRecord(BaseModel):
    """One stored run as listed / fetched back."""

    id: str
    created_at: datetime
    instrument: str
    params: dict[str, Any]
    metrics: dict[str, Any]
    runtime_ms: int
    notes: str | None
    owner_email: str | None = None  # populated for admins (LEFT JOIN users)


class RunDetail(RunRecord):
    equity_curve: list[EquityPoint]
    trades: list[TradeRecord]


class SeasonalityBucket(BaseModel):
    bucket: int
    trade_count: int
    total_pnl_usd: float
    mean_pnl_usd: float
    win_rate: float


class SeasonalityResponse(BaseModel):
    bucket_by: Literal["month", "weekday"]
    buckets: list[SeasonalityBucket]


class MonteCarloResponse(BaseModel):
    n_sims: int
    horizon_days: int
    method: Literal["bootstrap", "permutation"]
    terminal_pnl_percentiles: dict[int, float]
    max_drawdown_percentiles: dict[int, float]
    prob_terminal_loss: float = Field(ge=0, le=1)
    prob_ruin: float | None = None
