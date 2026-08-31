"""Strategy CRUD + evaluation endpoints (ADR-004).

Evaluation runs synchronously in the request (same stance as /ml/train
and /backtest/runs): the engine is one vectorised pass plus a Python
loop over at most 50k bars.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.kbars import _TIMEFRAME_SOURCE, bars_span
from app.auth.dependency import CurrentUser, get_current_user
from app.backtest.analysis import equity_curve, summarize
from app.backtest.types import DayResult
from app.core.instruments import Symbol as Instrument
from app.db.session import get_db
from app.strategies.access import granted_owner_ids
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
from app.strategies.signal_test import signal_test

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


async def _readable_owners(db: AsyncSession, user: CurrentUser) -> list[str] | None:
    """Owner ids this caller may read: their own plus anyone who granted them
    access. None for admins, who see everything."""
    if user.is_admin:
        return None
    return [user.id, *await granted_owner_ids(db, user.id)]


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
    owner_email: str | None = None  # populated for admins (LEFT JOIN users)


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
    """A run over stored bars.

    `start`/`end` are optional and each default to the corresponding edge of
    what the database holds at the strategy's timeframe. Omitting both means
    "score every bar there is", and keeps meaning that as more history is
    ingested — the caller never has to know how far back the data goes.
    """

    instrument: Instrument
    start: datetime | None = None
    end: datetime | None = None
    adjustment: Literal["raw", "ratio", "absolute"] = "ratio"


class EquityPointModel(BaseModel):
    date: str
    equity_points: float


class EvaluateResponse(BaseModel):
    strategy_id: str
    timeframe: str
    # Resolved span — echoed back so a caller that omitted the range can
    # state what was actually covered instead of guessing.
    start: datetime
    end: datetime
    bar_count: int
    trades: list[TradeModel]
    metrics: MetricsPoints
    equity_curve: list[EquityPointModel]


class SignalTestRequest(EvaluateRequest):
    horizon: int = Field(default=21, ge=1, le=250)


class SignalTestResponse(BaseModel):
    """Forward-return profile of a strategy's entry signals — see
    app/strategies/signal_test.py for the methodology (CMT curriculum)."""

    strategy_id: str
    timeframe: str
    start: datetime
    end: datetime
    bar_count: int
    signal_count: int
    horizon: int
    win_rate: float
    mean_return_pct: float
    median_return_pct: float
    std_return_pct: float
    best_return_pct: float
    worst_return_pct: float
    avg_path_pct: list[float]
    distribution: list[dict[str, float]]  # {center, count}


async def _resolve_span(
    db: AsyncSession,
    timeframe: str,
    instrument: str,
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime]:
    """Fill in whichever edge the caller left open from the stored bars.

    The upper edge is nudged past the newest bar because `_fetch_bars` uses a
    half-open interval — without it the last bar of the series would be the
    one bar a full-history run silently dropped.
    """
    if start is not None and end is not None:
        return start, end
    span = await bars_span(db, _TIMEFRAME_SOURCE[timeframe], instrument)
    if span is None:
        raise HTTPException(
            status_code=400,
            detail=f"no {timeframe} bars stored for {instrument}",
        )
    lo, hi = span
    return (start or lo), (end or hi + timedelta(seconds=1))


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
    body: StrategyCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> StrategyRecord:
    strategy_id = await insert_strategy(
        db,
        name=body.name,
        description=body.description,
        definition=body.definition.model_dump(mode="json"),
        owner_id=user.id,
    )
    row = await get_strategy(db, strategy_id)
    assert row is not None
    return StrategyRecord(**row)


@router.get("", response_model=list[StrategyRecord], summary="List strategies")
async def list_all(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[StrategyRecord]:
    rows = await list_strategies(db, limit=limit, owner_ids=await _readable_owners(db, user))
    return [StrategyRecord(**r) for r in rows]


@router.get("/{strategy_id}", response_model=StrategyRecord, summary="Fetch one strategy")
async def get_one(
    strategy_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> StrategyRecord:
    row = await get_strategy(db, strategy_id, owner_ids=await _readable_owners(db, user))
    if row is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    return StrategyRecord(**row)


@router.put("/{strategy_id}", response_model=StrategyRecord, summary="Update a strategy")
async def update(
    strategy_id: str,
    body: StrategyCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> StrategyRecord:
    ok = await update_strategy(
        db,
        strategy_id,
        name=body.name,
        description=body.description,
        definition=body.definition.model_dump(mode="json"),
        owner_id=user.owner_filter,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="strategy not found")
    row = await get_strategy(db, strategy_id)
    assert row is not None
    return StrategyRecord(**row)


@router.delete("/{strategy_id}", summary="Delete a strategy")
async def delete(
    strategy_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    if not await delete_strategy(db, strategy_id, owner_id=user.owner_filter):
        raise HTTPException(status_code=404, detail="strategy not found")
    return {"status": "deleted"}


@router.post(
    "/{strategy_id}/copy",
    response_model=StrategyRecord,
    summary="Copy a readable strategy into your own account",
)
async def copy(
    strategy_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> StrategyRecord:
    """The write half of read-plus-copy: the source row is never touched."""
    row = await get_strategy(db, strategy_id, owner_ids=await _readable_owners(db, user))
    if row is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    source_owner = row.get("owner_email") or "unknown"
    new_id = await insert_strategy(
        db,
        name=f"{row['name']} (copy)",
        description=(row.get("description") or "") + f"\n\nCopied from {source_owner}.",
        definition=row["definition"],
        owner_id=user.id,
    )
    created = await get_strategy(db, new_id)
    assert created is not None
    return StrategyRecord(**created)


@router.post(
    "/{strategy_id}/evaluate",
    response_model=EvaluateResponse,
    summary="Evaluate a strategy over stored bars → trades + metrics",
)
async def evaluate_strategy(
    strategy_id: str,
    body: EvaluateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> EvaluateResponse:
    row = await get_strategy(db, strategy_id, owner_ids=await _readable_owners(db, user))
    if row is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    defn = StrategyDefinition.model_validate(row["definition"])

    start, end = await _resolve_span(
        db, defn.timeframe, body.instrument, body.start, body.end
    )
    try:
        df = await load_bars_df(
            db, body.instrument, defn.timeframe, start, end, body.adjustment
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
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
        start=start,
        end=end,
        bar_count=len(df),
        trades=[TradeModel(**asdict(t), pnl_points=t.pnl_points) for t in trades],
        metrics=_metrics(trades),
        equity_curve=[
            EquityPointModel(date=d, equity_points=v)
            for d, v in equity_curve(_as_day_results(trades))
        ],
    )


@router.post(
    "/{strategy_id}/signal-test",
    response_model=SignalTestResponse,
    summary="Signal-test a strategy's entries in isolation (forward-return profile)",
)
async def signal_test_strategy(
    strategy_id: str,
    body: SignalTestRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> SignalTestResponse:
    row = await get_strategy(db, strategy_id, owner_ids=await _readable_owners(db, user))
    if row is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    defn = StrategyDefinition.model_validate(row["definition"])

    start, end = await _resolve_span(
        db, defn.timeframe, body.instrument, body.start, body.end
    )
    try:
        df = await load_bars_df(
            db, body.instrument, defn.timeframe, start, end, body.adjustment
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if df.empty:
        raise HTTPException(status_code=400, detail="no bars for this instrument/range")

    res = signal_test(df, defn, horizon=body.horizon)
    logger.info(
        "strategies.signal_test: id=%s instrument=%s tf=%s bars=%d signals=%d",
        strategy_id, body.instrument, defn.timeframe, len(df), res.signal_count,
    )
    return SignalTestResponse(
        strategy_id=strategy_id,
        timeframe=defn.timeframe,
        start=start,
        end=end,
        bar_count=len(df),
        signal_count=res.signal_count,
        horizon=res.horizon,
        win_rate=res.win_rate,
        mean_return_pct=res.mean_return_pct,
        median_return_pct=res.median_return_pct,
        std_return_pct=res.std_return_pct,
        best_return_pct=res.best_return_pct,
        worst_return_pct=res.worst_return_pct,
        avg_path_pct=res.avg_path_pct,
        distribution=[{"center": c, "count": float(n)} for c, n in res.distribution],
    )
