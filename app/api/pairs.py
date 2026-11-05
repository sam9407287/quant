"""Statistical arbitrage lab endpoints (ADR-010 §2.8).

Reads are open like the kbars/coverage routes — nothing here is per-user
except backtest runs, which follow the `backtest_runs` ownership model.
Writes require a signed-in user; the manual job trigger requires admin.
CPU-bound work (scans, backtests, rolling diagnostics) runs in a worker
thread so the event loop keeps serving while a multi-pair run finishes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependency import CurrentUser, get_current_user
from app.db.session import get_db
from app.pairs import repository as repo
from app.pairs import service
from app.pairs.backtest import run_with_sensitivity
from app.pairs.data import daily_coverage, equity_roll_dates
from app.pairs.diagnostics import forward_buckets, rolling_series, to_list
from app.pairs.schemas import (
    AnalysisResponse,
    BacktestRequest,
    BacktestRunDetail,
    BacktestRunRecord,
    CoverageItem,
    JobRunModel,
    PairStateModel,
    PairStatsModel,
    RefreshRequest,
    RefreshResponse,
    ScanConfig,
    ScanRequest,
    ScanResponse,
    ScanSummary,
    SignalModel,
    UniverseItem,
    WatchlistCreate,
    WatchlistItem,
)
from app.pairs.screen import evaluate_pair, pair_name
from app.pairs.universe import UNIVERSE, get_instrument

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pairs", tags=["pairs"])


# ---------------------------------------------------------------------------
# Universe / watchlist
# ---------------------------------------------------------------------------

@router.get("/universe", response_model=list[UniverseItem], summary="Tradeable universe with contract specs")
async def universe() -> list[UniverseItem]:
    return [
        UniverseItem(
            ticker=i.ticker, name=i.name, group=i.group, kind=i.kind, exchange=i.exchange,
            settlement_et=i.settlement_et, registry_symbol=i.registry_symbol,
            contracts=[
                {"code": c.code, "multiplier": c.multiplier, "tick_size": c.tick_size, "micro": c.micro}
                for c in i.tradeable
            ],
        )
        for i in UNIVERSE.values()
    ]


def _check_ticker(t: str) -> None:
    try:
        get_instrument(t)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/watchlist", response_model=list[WatchlistItem], summary="Pairs the daily job scans")
async def watchlist(db: AsyncSession = Depends(get_db)) -> list[WatchlistItem]:
    return [WatchlistItem(**r) for r in await repo.list_watchlist(db)]


@router.post("/watchlist", response_model=WatchlistItem, status_code=201, summary="Add a pair to the watchlist")
async def add_pair(
    item: WatchlistCreate, db: AsyncSession = Depends(get_db), _: CurrentUser = Depends(get_current_user)
) -> WatchlistItem:
    _check_ticker(item.y_ticker)
    _check_ticker(item.x_ticker)
    return WatchlistItem(**await repo.add_watchlist(db, item))


@router.post("/watchlist/defaults", summary="Seed the ten pairs from the brief")
async def seed_defaults(db: AsyncSession = Depends(get_db), _: CurrentUser = Depends(get_current_user)) -> dict[str, int]:
    return {"inserted": await repo.seed_default_watchlist(db)}


@router.delete("/watchlist/{item_id}", status_code=204, response_class=Response, summary="Remove a pair from the watchlist")
async def remove_pair(item_id: str, db: AsyncSession = Depends(get_db), _: CurrentUser = Depends(get_current_user)) -> Response:
    if not await repo.delete_watchlist(db, item_id):
        raise HTTPException(status_code=404, detail="watchlist item not found")
    return Response(status_code=204)


@router.post("/watchlist/{item_id}/enabled", response_model=dict, summary="Enable or disable a watchlist pair")
async def toggle_pair(
    item_id: str, enabled: bool = Query(...), db: AsyncSession = Depends(get_db), _: CurrentUser = Depends(get_current_user)
) -> dict[str, Any]:
    if not await repo.set_watchlist_enabled(db, item_id, enabled):
        raise HTTPException(status_code=404, detail="watchlist item not found")
    return {"id": item_id, "enabled": enabled}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@router.get("/data/coverage", response_model=list[CoverageItem], summary="Daily-bar coverage per ticker")
async def coverage(db: AsyncSession = Depends(get_db)) -> list[CoverageItem]:
    out = []
    for r in await daily_coverage(db):
        inst = UNIVERSE.get(r["ticker"])
        out.append(
            CoverageItem(
                ticker=r["ticker"], name=inst.name if inst else None, kind=inst.kind if inst else None,
                first_date=r["first_date"], last_date=r["last_date"], bar_count=int(r["bar_count"]),
                last_fetch=r.get("last_fetch"),
            )
        )
    return out


@router.post("/data/refresh", response_model=RefreshResponse, summary="Fetch daily bars from the vendor")
async def refresh(
    req: RefreshRequest, db: AsyncSession = Depends(get_db), _: CurrentUser = Depends(get_current_user)
) -> RefreshResponse:
    try:
        return await service.refresh_daily_bars(db, req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------

@router.post("/scans", response_model=ScanResponse, summary="Run a cointegration scan and persist it")
async def create_scan(
    req: ScanRequest, db: AsyncSession = Depends(get_db), _: CurrentUser = Depends(get_current_user)
) -> ScanResponse:
    try:
        response, _ = await service.run_scan(db, req.config, trigger="manual")
        return response
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/scans", response_model=list[ScanSummary], summary="Recent scans")
async def scans(limit: int = Query(default=30, ge=1, le=200), db: AsyncSession = Depends(get_db)) -> list[ScanSummary]:
    return [ScanSummary(**r) for r in await repo.list_scans(db, limit=limit)]


@router.get("/scans/latest", response_model=ScanResponse | None, summary="Most recent scan with results")
async def latest_scan(
    trigger: str | None = Query(default=None, pattern="^(manual|daily)$"), db: AsyncSession = Depends(get_db)
) -> ScanResponse | None:
    scan_id = await repo.latest_scan_id(db, trigger=trigger)
    if scan_id is None:
        return None
    row = await repo.get_scan(db, scan_id)
    return None if row is None else ScanResponse(**row)


@router.get("/scans/{scan_id}", response_model=ScanResponse, summary="One scan with its per-pair results")
async def scan_detail(scan_id: str, db: AsyncSession = Depends(get_db)) -> ScanResponse:
    row = await repo.get_scan(db, scan_id)
    if row is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return ScanResponse(**row)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@router.get("/analysis", response_model=AnalysisResponse, summary="Spread, z, rolling β/p and forward returns for one pair")
async def analysis(
    y: str = Query(...),
    x: str = Query(...),
    formation_window: int = Query(default=504, ge=60, le=2520),
    as_of: date | None = Query(default=None),
    lookback_days: int = Query(default=1260, ge=120, le=5040),
    z_window_min: int = Query(default=20, ge=5),
    z_window_max: int = Query(default=120, ge=10),
    z_window_multiple: float = Query(default=4.0, gt=0, le=20),
    hedge_method: str = Query(default="ols", pattern="^(ols|tls)$"),
    price_source: str = Query(default="settlement", pattern="^(settlement|snapshot_1m)$"),
    snapshot_time_et: str = Query(default="15:00", pattern=r"^\d{2}:\d{2}$"),
    db: AsyncSession = Depends(get_db),
) -> AnalysisResponse:
    _check_ticker(y)
    _check_ticker(x)
    if y == x:
        raise HTTPException(status_code=400, detail="pair legs must differ")
    wide = await service.load_prices(
        db, [y, x], trading_days=formation_window + lookback_days, as_of=as_of,
        price_source=price_source, snapshot_time_et=snapshot_time_et,
    )
    pair = wide[[c for c in (y, x) if c in wide.columns]].ffill(limit=1).dropna() if not wide.empty else wide
    if pair.empty or len(pair) <= formation_window + 5:
        raise HTTPException(status_code=400, detail="not enough aligned daily bars for this formation window")
    logp = np.log(pair)
    cfg = ScanConfig(
        mode="explicit", pairs=[(y, x)], as_of=as_of, formation_window=formation_window,
        hedge_method=hedge_method, z_window_min=z_window_min, z_window_max=z_window_max,  # type: ignore[arg-type]
        z_window_multiple=z_window_multiple, stability_step=5,
    )
    stats = await asyncio.to_thread(evaluate_pair, logp, y, x, cfg)
    if stats is None:
        raise HTTPException(status_code=400, detail="pair could not be evaluated")
    series = await asyncio.to_thread(
        rolling_series, logp[y].to_numpy(dtype=float), logp[x].to_numpy(dtype=float), pd.DatetimeIndex(logp.index),
        formation_window=formation_window, z_window_min=z_window_min, z_window_max=z_window_max,
        z_window_multiple=z_window_multiple, hedge_method=hedge_method,
    )
    buckets = forward_buckets(series.spread, series.zscore)
    rolls = sorted(set(await equity_roll_dates(db, y)) | set(await equity_roll_dates(db, x)))
    iy, ix = get_instrument(y), get_instrument(x)
    note = None
    if iy.settlement_et != ix.settlement_et:
        note = (
            f"{iy.ticker} settles at {iy.settlement_et} ET and {ix.ticker} at {ix.settlement_et} ET; "
            "the settlement spread mixes two moments. Use price_source=snapshot_1m for a same-instant series."
        )
    return AnalysisResponse(
        pair_name=pair_name(y, x), y_ticker=y, x_ticker=x, stats=stats,
        dates=[d.date() for d in logp.index], log_y=[float(v) for v in logp[y]], log_x=[float(v) for v in logp[x]],
        spread=to_list(series.spread), zscore=to_list(series.zscore), rolling_beta=to_list(series.beta),
        rolling_pvalue=to_list(series.pvalue), forward=buckets,
        roll_dates=[d for d in rolls if logp.index[0].date() <= d <= logp.index[-1].date()], settlement_note=note,
    )


# ---------------------------------------------------------------------------
# Backtests
# ---------------------------------------------------------------------------

@router.post("/backtests", response_model=BacktestRunDetail, summary="Run a walk-forward backtest and persist it")
async def create_backtest(
    req: BacktestRequest, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)
) -> BacktestRunDetail:
    cfg = req.config
    tickers = sorted({t for p in cfg.pairs for t in p})
    for t in tickers:
        _check_ticker(t)
    started = time.perf_counter()
    warmup = max(cfg.formation_window, *cfg.sensitivity_formation) if cfg.sensitivity else cfg.formation_window
    start = None if cfg.start is None else cfg.start - timedelta(days=int(warmup * service.CAL_PER_TRADING) + 30)
    close = await service.load_prices(db, tickers, trading_days=warmup + 2520, as_of=cfg.end, start=start, price_source=cfg.price_source)
    if close.empty:
        raise HTTPException(status_code=400, detail="no daily bars stored for these tickers — refresh the data first")
    close = close.ffill(limit=1)
    opens = None
    if cfg.fill == "next_open":
        opens = await service.load_prices(db, tickers, trading_days=warmup + 2520, as_of=cfg.end, start=start, field="open")
        opens = opens.reindex(index=close.index, columns=close.columns)
    roll_dates: dict[str, set[date]] = {}
    for t in tickers:
        dates = await equity_roll_dates(db, t)
        if dates:
            roll_dates[t] = set(dates)
    try:
        result = await asyncio.to_thread(run_with_sensitivity, close, cfg, prices_open=opens, roll_dates=roll_dates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime_ms = int((time.perf_counter() - started) * 1000)
    doc = result.model_dump(mode="json")
    metrics = doc.pop("metrics")
    run_id = await repo.insert_backtest_run(
        db, config=cfg.model_dump(mode="json"), metrics=metrics, result=doc, runtime_ms=runtime_ms,
        owner_id=user.id, notes=req.notes,
    )
    logger.info("pairs.backtest: id=%s pairs=%d trades=%d runtime=%dms", run_id, len(cfg.pairs), result.metrics.trade_count, runtime_ms)
    return BacktestRunDetail(
        id=run_id, created_at=datetime.now(UTC), config=cfg.model_dump(mode="json"), metrics=metrics,
        runtime_ms=runtime_ms, notes=req.notes, result=doc,
    )


@router.get("/backtests", response_model=list[BacktestRunRecord], summary="Recent pairs backtest runs")
async def backtests(
    limit: int = Query(default=50, ge=1, le=200), db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[BacktestRunRecord]:
    return [BacktestRunRecord(**r) for r in await repo.list_backtest_runs(db, limit=limit, owner_id=user.owner_filter)]


@router.get("/backtests/{run_id}", response_model=BacktestRunDetail, summary="One pairs backtest run")
async def backtest_detail(
    run_id: str, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)
) -> BacktestRunDetail:
    row = await repo.get_backtest_run(db, run_id, owner_id=user.owner_filter)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    return BacktestRunDetail(**row)


# ---------------------------------------------------------------------------
# Live state / signals / jobs
# ---------------------------------------------------------------------------

@router.get("/state", response_model=list[PairStateModel], summary="Current position state per watchlist pair")
async def state(db: AsyncSession = Depends(get_db)) -> list[PairStateModel]:
    return [PairStateModel(**r) for r in await repo.load_states(db)]


@router.get("/signals", response_model=list[SignalModel], summary="Recent signal events")
async def signals(limit: int = Query(default=100, ge=1, le=500), db: AsyncSession = Depends(get_db)) -> list[SignalModel]:
    return [SignalModel(**r) for r in await repo.list_signals(db, limit=limit)]


@router.get("/jobs", response_model=list[JobRunModel], summary="Daily job executions")
async def jobs(limit: int = Query(default=30, ge=1, le=200), db: AsyncSession = Depends(get_db)) -> list[JobRunModel]:
    return [JobRunModel(**r) for r in await repo.list_job_runs(db, limit=limit)]


@router.post("/jobs/daily", summary="Run the daily pairs job now (admin)")
async def run_daily_now(
    dry_run: bool = Query(default=True), user: CurrentUser = Depends(get_current_user)
) -> dict[str, Any]:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    from fetcher.pairs_job import (
        run_pairs_job,  # local import: the fetcher package is optional for the API
    )

    summary: dict[str, Any] = await run_pairs_job(dry_run=dry_run, trigger="manual")
    return summary


def stats_for_pair(results: list[PairStatsModel], y: str, x: str) -> PairStatsModel | None:
    return next((r for r in results if r.y_ticker == y and r.x_ticker == x), None)
