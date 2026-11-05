"""Orchestration shared by the REST API and the daily job.

The API routes and `fetcher/pairs_job.py` must not drift apart in how they
load prices, refresh data or run a scan, so those steps live here once.
Everything is async and takes the session explicitly; CPU-bound work is
pushed to a worker thread.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.pairs import repository as repo
from app.pairs.data import (
    daily_coverage,
    fetch_daily_history,
    latest_trading_date,
    load_wide_prices,
    log_price_matrix,
    quality_check,
    snapshot_prices_from_1m,
    upsert_daily_bars,
)
from app.pairs.schemas import (
    PairStatsModel,
    RefreshRequest,
    RefreshResponse,
    ScanConfig,
    ScanResponse,
)
from app.pairs.screen import candidate_pairs, scan_pairs
from app.pairs.universe import ALL_TICKERS, get_instrument

logger = logging.getLogger(__name__)

# Calendar days to fetch per trading day wanted (weekends + holidays).
CAL_PER_TRADING = 1.5
INCREMENTAL_DAYS = 14


def check_ticker(ticker: str) -> None:
    """Raise ValueError for a ticker outside the universe (API maps to 400)."""
    get_instrument(ticker)


# ---------------------------------------------------------------------------
# Data refresh
# ---------------------------------------------------------------------------

async def refresh_daily_bars(db: AsyncSession, req: RefreshRequest) -> RefreshResponse:
    """Download and store daily bars; full history for new tickers, overlap otherwise."""
    started = time.perf_counter()
    tickers = req.tickers or list(ALL_TICKERS)
    for t in tickers:
        check_ticker(t)
    today = datetime.now(UTC).date()
    known = {r["ticker"] for r in await daily_coverage(db)}
    deep_start = today - timedelta(days=365 * req.years)
    fresh = [t for t in tickers if req.full or t not in known]
    incremental = [t for t in tickers if t not in fresh]

    frames = []
    if fresh:
        frames.append(await asyncio.to_thread(fetch_daily_history, fresh, deep_start, today))
    if incremental:
        frames.append(
            await asyncio.to_thread(fetch_daily_history, incremental, today - timedelta(days=INCREMENTAL_DAYS), today)
        )
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    clean, issues = quality_check(raw, today=today) if not raw.empty else (raw, [])
    written = await upsert_daily_bars(db, clean)
    latest = await latest_trading_date(db, tickers)
    return RefreshResponse(
        tickers=len(tickers), rows_written=written,
        issues=[{"ticker": i.ticker, "date": i.trading_date, "kind": i.kind, "detail": i.detail} for i in issues[:200]],
        latest_date=latest, runtime_ms=int((time.perf_counter() - started) * 1000),
    )


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

async def load_prices(
    db: AsyncSession,
    tickers: list[str],
    *,
    trading_days: int,
    as_of: date | None,
    start: date | None = None,
    price_source: str = "settlement",
    snapshot_time_et: str = "15:00",
    field: str = "close",
) -> pd.DataFrame:
    """Date × ticker matrix covering roughly `trading_days` before `as_of`."""
    end = as_of
    begin = start or ((as_of or datetime.now(UTC).date()) - timedelta(days=int(trading_days * CAL_PER_TRADING) + 30))
    if price_source == "snapshot_1m":
        return await snapshot_prices_from_1m(db, tickers, at_et=snapshot_time_et, start=begin, end=end)
    return await load_wide_prices(db, tickers, start=begin, end=end, field=field)


def roll_gap_counts(wide: pd.DataFrame, window: int) -> dict[str, int]:
    """Days with a > 25 % log move inside the last `window` rows, per ticker."""
    out: dict[str, int] = {}
    if wide.empty:
        return out
    tail = np.log(wide.where(wide > 0)).iloc[-window:]
    jumps = tail.diff().abs() > 0.25
    for col in tail.columns:
        out[str(col)] = int(jumps[col].sum())
    return out


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

async def run_scan(
    db: AsyncSession,
    config: ScanConfig,
    *,
    trigger: str,
    overrides: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> tuple[ScanResponse, pd.DataFrame]:
    """Load prices, evaluate every candidate pair, persist, return (response, prices).

    `overrides` maps a (y, x) pair to per-pair config overrides from the
    watchlist; pairs sharing an override set are scanned together so the
    BH correction still sees the whole family.
    """
    started = time.perf_counter()
    watch = None
    if config.mode == "watchlist":
        watch = [(r["y_ticker"], r["x_ticker"]) for r in await repo.list_watchlist(db, enabled_only=True)]
    pairs = candidate_pairs(config, watchlist=watch)
    if not pairs:
        raise ValueError("no pairs to scan: the watchlist is empty")
    tickers = sorted({t for p in pairs for t in p})
    overrides = overrides or {}
    longest = max([config.formation_window] + [int(o.get("formation_window", 0)) for o in overrides.values()])
    days = longest + config.rules.stability_lookback + 10
    wide = await load_prices(
        db, tickers, trading_days=days, as_of=config.as_of,
        price_source=config.price_source, snapshot_time_et=config.snapshot_time_et,
    )
    if wide.empty:
        raise ValueError("no daily bars stored for these tickers — refresh the data first")
    logp = log_price_matrix(wide, max_ffill=1)
    gaps = roll_gap_counts(wide, longest)

    groups: dict[str, tuple[ScanConfig, list[tuple[str, str]]]] = {}
    for pair in pairs:
        ov = overrides.get(pair, {})
        key = repr(sorted(ov.items()))
        if key not in groups:
            groups[key] = (config.model_copy(update=ov) if ov else config, [])
        groups[key][1].append(pair)

    results: list[PairStatsModel] = []
    for cfg, group_pairs in groups.values():
        results.extend(await asyncio.to_thread(scan_pairs, logp, group_pairs, cfg, roll_gaps=gaps))
    results.sort(key=lambda r: (not r.qualified, -abs(r.z) if r.z is not None else 0.0))

    as_of = results[0].as_of if results else (config.as_of or wide.index[-1].date())
    runtime_ms = int((time.perf_counter() - started) * 1000)
    scan_id = await repo.insert_scan(
        db, as_of=as_of, trigger=trigger, config=config.model_dump(mode="json"), results=results,
        universe_size=len(tickers), runtime_ms=runtime_ms,
    )
    response = ScanResponse(
        id=scan_id, created_at=datetime.now(UTC), as_of=as_of, trigger=trigger, universe_size=len(tickers),
        pair_count=len(results), qualified_count=sum(1 for r in results if r.qualified), runtime_ms=runtime_ms,
        config=config.model_dump(mode="json"), results=results,
    )
    return response, wide
