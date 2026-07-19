"""Strategy CRUD + evaluation endpoints (ADR-004).

Evaluation runs synchronously in the request (same stance as /ml/train
and /backtest/runs): the engine is one vectorised pass plus a Python
loop over at most 50k bars.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.analysis import equity_curve, summarize
from app.backtest.types import DayResult
from app.core.instruments import Symbol as Instrument
from app.db.session import get_db
from app.strategies.engine import Trade, evaluate
from app.strategies.loader import load_bars_df
from app.strategies.repository import (
    delete_strategy,
    get_strategy,
    insert_strategy,
    list_strategies,
    update_strategy,
)
from app.strategies.schemas import StrategyDefinition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


class StrategyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    definition: StrategyDefinition


class StrategyRecord(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    name: str
    description: str | None
    definition: dict[str, Any]


class TradeModel(BaseModel):
    direction: Literal["long", "short"]
    entry_ts: datetime
    entry_price: float
    exit_ts: datetime
    exit_price: float
    exit_reason: Literal["signal", "sl", "tp", "end"]
    sl_level: float | None
    tp_level: float | None
    pnl_points: float


class MetricsPoints(BaseModel):
    """Strategy metrics in POINTS (no contract sizing at this layer)."""

    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float
    total_pnl_points: float
    profit_factor: float | None
    expectancy_points: float
    max_drawdown_points: float
    best_trade_points: float
    worst_trade_points: float


class EvaluateRequest(BaseModel):
    instrument: Instrument
    start: datetime
    end: datetime
    adjustment: Literal["raw", "ratio", "absolute"] = "ratio"


class EquityPointModel(BaseModel):
    date: str
    equity_points: float


class EvaluateResponse(BaseModel):
    strategy_id: str
    timeframe: str
    bar_count: int
    trades: list[TradeModel]
    metrics: MetricsPoints
    equity_curve: list[EquityPointModel]


def _as_day_results(trades: list[Trade]) -> list[DayResult]:
    """Adapter for the shared analysis layer: one pseudo-session per
    trade, keyed by exit date, P&L carried in points."""
    reason_map = {"sl": "sl", "tp": "tp", "signal": "eod", "end": "eod"}
    return [
        DayResult(
            session_date=t.exit_ts.date() if isinstance(t.exit_ts, datetime) else date.today(),
            exit_reason=reason_map[t.exit_reason],  # type: ignore[arg-type]
            direction=t.direction,
            pnl_usd=t.pnl_points,  # points, relabelled in the response
        )
        for t in trades
    ]


def _metrics(trades: list[Trade]) -> MetricsPoints:
    s = summarize(_as_day_results(trades))
    return MetricsPoints(
        trade_count=s.trade_count,
        win_count=s.win_count,
        loss_count=s.loss_count,
        win_rate=s.win_rate,
        total_pnl_points=s.total_pnl_usd,
        profit_factor=s.profit_factor,
        expectancy_points=s.expectancy_usd,
        max_drawdown_points=s.max_drawdown_usd,
        best_trade_points=s.best_day_usd,
        worst_trade_points=s.worst_day_usd,
    )


@router.post("", response_model=StrategyRecord, summary="Create a strategy")
async def create(
    body: StrategyCreate, db: AsyncSession = Depends(get_db)
) -> StrategyRecord:
    strategy_id = await insert_strategy(
        db,
        name=body.name,
        description=body.description,
        definition=body.definition.model_dump(mode="json"),
    )
    row = await get_strategy(db, strategy_id)
    assert row is not None
    return StrategyRecord(**row)


@router.get("", response_model=list[StrategyRecord], summary="List strategies")
async def list_all(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[StrategyRecord]:
    return [StrategyRecord(**r) for r in await list_strategies(db, limit=limit)]


@router.get("/{strategy_id}", response_model=StrategyRecord, summary="Fetch one strategy")
async def get_one(strategy_id: str, db: AsyncSession = Depends(get_db)) -> StrategyRecord:
    row = await get_strategy(db, strategy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    return StrategyRecord(**row)


@router.put("/{strategy_id}", response_model=StrategyRecord, summary="Update a strategy")
async def update(
    strategy_id: str, body: StrategyCreate, db: AsyncSession = Depends(get_db)
) -> StrategyRecord:
    ok = await update_strategy(
        db,
        strategy_id,
        name=body.name,
        description=body.description,
        definition=body.definition.model_dump(mode="json"),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="strategy not found")
    row = await get_strategy(db, strategy_id)
    assert row is not None
    return StrategyRecord(**row)


@router.delete("/{strategy_id}", summary="Delete a strategy")
async def delete(strategy_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    if not await delete_strategy(db, strategy_id):
        raise HTTPException(status_code=404, detail="strategy not found")
    return {"status": "deleted"}


@router.post(
    "/{strategy_id}/evaluate",
    response_model=EvaluateResponse,
    summary="Evaluate a strategy over stored bars → trades + metrics",
)
async def evaluate_strategy(
    strategy_id: str,
    body: EvaluateRequest,
    db: AsyncSession = Depends(get_db),
) -> EvaluateResponse:
    row = await get_strategy(db, strategy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    defn = StrategyDefinition.model_validate(row["definition"])

    df = await load_bars_df(
        db, body.instrument, defn.timeframe, body.start, body.end, body.adjustment
    )
    if df.empty:
        raise HTTPException(status_code=400, detail="no bars for this instrument/range")

    trades = evaluate(df, defn)
    logger.info(
        "strategies.evaluate: id=%s instrument=%s tf=%s bars=%d trades=%d",
        strategy_id, body.instrument, defn.timeframe, len(df), len(trades),
    )
    return EvaluateResponse(
        strategy_id=strategy_id,
        timeframe=defn.timeframe,
        bar_count=len(df),
        trades=[TradeModel(**asdict(t), pnl_points=t.pnl_points) for t in trades],
        metrics=_metrics(trades),
        equity_curve=[
            EquityPointModel(date=d, equity_points=v)
            for d, v in equity_curve(_as_day_results(trades))
        ],
    )
