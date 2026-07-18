"""DB persistence for backtest runs and trades (ADR-003 B2).

Pure-SQL access via SQLAlchemy `text()`, mirroring app/ml/repository.py:
params and metrics are JSONB (fluid shape, validated by Pydantic at the
API boundary); per-session outcomes are relational rows because the
analysis endpoints re-read them as a series.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.types import DayResult


async def insert_run(
    session: AsyncSession,
    *,
    instrument: str,
    params: dict[str, Any],
    metrics: dict[str, Any],
    results: list[DayResult],
    runtime_ms: int,
    notes: str | None = None,
) -> str:
    """Insert one run and all its session rows atomically; return run id."""
    run_stmt = text(
        """
        INSERT INTO backtest_runs (instrument, params, metrics, runtime_ms, notes)
        VALUES (:instrument, CAST(:params AS JSONB), CAST(:metrics AS JSONB),
                :runtime_ms, :notes)
        RETURNING id::text
        """
    )
    run_id = (
        await session.execute(
            run_stmt,
            {
                "instrument": instrument,
                "params": json.dumps(params),
                "metrics": json.dumps(metrics),
                "runtime_ms": runtime_ms,
                "notes": notes,
            },
        )
    ).scalar_one()

    trade_stmt = text(
        """
        INSERT INTO backtest_trades
            (run_id, session_date, exit_reason, direction, entry_ts,
             entry_price, exit_ts, exit_price, pnl_points, pnl_usd,
             mae_points, mfe_points, range_high, range_low)
        VALUES
            (CAST(:run_id AS UUID), :session_date, :exit_reason, :direction,
             :entry_ts, :entry_price, :exit_ts, :exit_price, :pnl_points,
             :pnl_usd, :mae_points, :mfe_points, :range_high, :range_low)
        """
    )
    for r in results:
        await session.execute(
            trade_stmt,
            {
                "run_id": run_id,
                "session_date": r.session_date,
                "exit_reason": r.exit_reason,
                "direction": r.direction,
                "entry_ts": r.entry_ts,
                "entry_price": r.entry_price,
                "exit_ts": r.exit_ts,
                "exit_price": r.exit_price,
                "pnl_points": r.pnl_points,
                "pnl_usd": r.pnl_usd,
                "mae_points": r.mae_points,
                "mfe_points": r.mfe_points,
                "range_high": r.range_high,
                "range_low": r.range_low,
            },
        )
    await session.commit()
    return str(run_id)


async def list_runs(session: AsyncSession, limit: int = 50) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT id::text AS id, created_at, instrument, params, metrics,
               runtime_ms, notes
        FROM backtest_runs
        ORDER BY created_at DESC
        LIMIT :limit
        """
    )
    rows = (await session.execute(stmt, {"limit": limit})).fetchall()
    return [dict(row._mapping) for row in rows]


async def get_run(session: AsyncSession, run_id: str) -> dict[str, Any] | None:
    stmt = text(
        """
        SELECT id::text AS id, created_at, instrument, params, metrics,
               runtime_ms, notes
        FROM backtest_runs
        WHERE id = CAST(:id AS UUID)
        """
    )
    row = (await session.execute(stmt, {"id": run_id})).fetchone()
    return dict(row._mapping) if row else None


async def get_trades(session: AsyncSession, run_id: str) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT session_date, exit_reason, direction, entry_ts, entry_price,
               exit_ts, exit_price, pnl_points, pnl_usd, mae_points,
               mfe_points, range_high, range_low
        FROM backtest_trades
        WHERE run_id = CAST(:id AS UUID)
        ORDER BY session_date ASC
        """
    )
    rows = (await session.execute(stmt, {"id": run_id})).fetchall()
    return [dict(row._mapping) for row in rows]


def results_from_trade_rows(rows: list[dict[str, Any]]) -> list[DayResult]:
    """Rehydrate stored trade rows into DayResult for the analysis layer."""
    return [
        DayResult(
            session_date=r["session_date"],
            exit_reason=r["exit_reason"],
            direction=r["direction"],
            entry_ts=r["entry_ts"],
            entry_price=r["entry_price"],
            exit_ts=r["exit_ts"],
            exit_price=r["exit_price"],
            pnl_points=r["pnl_points"],
            pnl_usd=r["pnl_usd"],
            mae_points=r["mae_points"],
            mfe_points=r["mfe_points"],
            range_high=r["range_high"],
            range_low=r["range_low"],
        )
        for r in rows
    ]
