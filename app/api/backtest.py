"""Backtest endpoints — run the killzone-OCO engine and inspect runs.

See `docs/ADR-003-backtest-engine.md`. Runs execute synchronously in
the request (same stance as /api/v1/ml/train): the engine is pure CPU
and a multi-year 1m run completes in seconds; MAX_BARS in the loader
bounds the worst case.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.kbars import bars_span
from app.auth.dependency import CurrentUser, get_current_user
from app.backtest.analysis import equity_curve, monte_carlo, seasonality, summarize
from app.backtest.engine import run_backtest
from app.backtest.loader import load_sessions
from app.backtest.params import BacktestParams
from app.backtest.repository import (
    get_run,
    get_trades,
    insert_run,
    list_runs,
    results_from_trade_rows,
)
from app.backtest.schemas import (
    EquityPoint,
    MetricsModel,
    MonteCarloResponse,
    RunDetail,
    RunRecord,
    RunRequest,
    RunResponse,
    SeasonalityBucket,
    SeasonalityResponse,
    TradeRecord,
)
from app.backtest.types import DayResult
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])


def _equity_points(results: list[DayResult]) -> list[EquityPoint]:
    return [EquityPoint(date=d, equity_usd=v) for d, v in equity_curve(results)]


async def _with_resolved_dates(
    db: AsyncSession, params: BacktestParams
) -> BacktestParams:
    """Replace any unset start/end with the edges of the stored 1m bars.

    Resolved *before* the run is persisted: a saved run must record the span
    it actually covered, or re-running it after more history lands would
    silently be a different experiment.
    """
    if params.start is not None and params.end is not None:
        return params
    span = await bars_span(db, "kbars_1m", params.instrument)
    if span is None:
        raise ValueError(f"no 1m bars stored for {params.instrument}")
    lo, hi = span
    # The loader takes calendar dates in the params' timezone and already
    # pads both ends, so the local date of each edge is the right bound.
    zone = params.clock.zone
    return params.model_copy(
        update={
            "start": params.start or lo.astimezone(zone).date(),
            "end": params.end or hi.astimezone(zone).date(),
        }
    )


@router.post(
    "/runs",
    response_model=RunResponse,
    summary="Run a backtest and persist the result",
)
async def create_run(
    req: RunRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> RunResponse:
    started = time.perf_counter()
    try:
        params = await _with_resolved_dates(db, req.params)
        sessions, atr_by_date = await load_sessions(db, params)
        if not sessions:
            raise ValueError("no 1m bars found for this instrument/date range")
        results = run_backtest(sessions, params, atr_by_date=atr_by_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    runtime_ms = int((time.perf_counter() - started) * 1000)
    metrics = asdict(summarize(results))
    run_id = await insert_run(
        db,
        instrument=params.instrument,
        params=params.model_dump(mode="json"),
        metrics=metrics,
        results=results,
        runtime_ms=runtime_ms,
        notes=req.notes,
        owner_id=user.id,
    )
    logger.info(
        "backtest.run: id=%s instrument=%s sessions=%d runtime=%dms",
        run_id, params.instrument, len(results), runtime_ms,
    )
    span_start, span_end = params.span
    return RunResponse(
        run_id=run_id,
        runtime_ms=runtime_ms,
        start=span_start,
        end=span_end,
        metrics=MetricsModel(**metrics),
        equity_curve=_equity_points(results),
        trades=[TradeRecord(**asdict(r)) for r in results],
    )


@router.get(
    "/runs",
    response_model=list[RunRecord],
    summary="List recent backtest runs",
)
async def list_recent(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[RunRecord]:
    rows = await list_runs(db, limit=limit, owner_id=user.owner_filter)
    return [RunRecord(**r) for r in rows]


@router.get(
    "/runs/{run_id}",
    response_model=RunDetail,
    summary="Fetch one run with its trades and equity curve",
)
async def get_one(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> RunDetail:
    row = await get_run(db, run_id, owner_id=user.owner_filter)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    trade_rows = await get_trades(db, run_id)
    results = results_from_trade_rows(trade_rows)
    return RunDetail(
        **row,
        equity_curve=_equity_points(results),
        trades=[TradeRecord(**t) for t in trade_rows],
    )


@router.get(
    "/runs/{run_id}/seasonality",
    response_model=SeasonalityResponse,
    summary="Month / weekday P&L buckets for one run",
)
async def get_seasonality(
    run_id: str,
    bucket: str = Query(default="month", pattern="^(month|weekday)$"),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> SeasonalityResponse:
    if await get_run(db, run_id, owner_id=user.owner_filter) is None:
        raise HTTPException(status_code=404, detail="run not found")
    trade_rows = await get_trades(db, run_id)
    if not trade_rows:
        raise HTTPException(status_code=404, detail="run not found or has no sessions")
    stats = seasonality(results_from_trade_rows(trade_rows), bucket)
    return SeasonalityResponse(
        bucket_by=bucket,  # type: ignore[arg-type]  # pattern-validated above
        buckets=[SeasonalityBucket(**asdict(b)) for b in stats],
    )


@router.get(
    "/runs/{run_id}/montecarlo",
    response_model=MonteCarloResponse,
    summary="Bootstrap / permutation Monte Carlo over the run's daily P&L",
)
async def get_montecarlo(
    run_id: str,
    n_sims: int = Query(default=10_000, ge=100, le=100_000),
    method: str = Query(default="bootstrap", pattern="^(bootstrap|permutation)$"),
    seed: int = Query(default=42),
    horizon_days: int | None = Query(default=None, ge=1, le=10_000),
    initial_capital: float | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> MonteCarloResponse:
    if await get_run(db, run_id, owner_id=user.owner_filter) is None:
        raise HTTPException(status_code=404, detail="run not found")
    trade_rows = await get_trades(db, run_id)
    if not trade_rows:
        raise HTTPException(status_code=404, detail="run not found or has no sessions")
    results = results_from_trade_rows(trade_rows)
    daily = [r.pnl_usd for r in results if r.exit_reason in {"tp", "sl", "eod", "no_fill"}]
    try:
        report = monte_carlo(
            daily,
            n_sims=n_sims,
            method=method,
            seed=seed,
            horizon_days=horizon_days,
            initial_capital=initial_capital,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return MonteCarloResponse(**asdict(report))
