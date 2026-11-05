"""SQL persistence for the pairs lab (watchlist, scans, state, signals, runs).

Same stance as the other repositories: `text()` with bound parameters,
JSONB for documents whose shape is validated by Pydantic at the boundary,
relational rows where the UI filters or sorts. Every function takes the
session it should use so the API, the daily job and tests control
transactions.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.pairs.schemas import PairStatsModel, WatchlistCreate
from app.pairs.signals import PairState
from app.pairs.universe import DEFAULT_PAIRS


def _rows(result: Any) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in result.fetchall()]


def _row(result: Any) -> dict[str, Any] | None:
    r = result.first()
    return None if r is None else dict(r._mapping)


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

async def list_watchlist(session: AsyncSession, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT id::text AS id, name, y_ticker, x_ticker, enabled, overrides, rationale, created_at
        FROM pairs_watchlist
        WHERE (:enabled_only = FALSE OR enabled)
        ORDER BY created_at, name
        """
    )
    return _rows(await session.execute(stmt, {"enabled_only": enabled_only}))


async def add_watchlist(session: AsyncSession, item: WatchlistCreate) -> dict[str, Any]:
    stmt = text(
        """
        INSERT INTO pairs_watchlist (name, y_ticker, x_ticker, rationale, overrides)
        VALUES (:name, :y, :x, :rationale, CAST(:overrides AS JSONB))
        ON CONFLICT (y_ticker, x_ticker) DO UPDATE
            SET name = EXCLUDED.name, rationale = EXCLUDED.rationale,
                overrides = EXCLUDED.overrides, enabled = TRUE
        RETURNING id::text AS id, name, y_ticker, x_ticker, enabled, overrides, rationale, created_at
        """
    )
    row = _row(
        await session.execute(
            stmt,
            {
                "name": item.name, "y": item.y_ticker, "x": item.x_ticker,
                "rationale": item.rationale, "overrides": json.dumps(item.overrides),
            },
        )
    )
    await session.commit()
    assert row is not None
    return row


async def set_watchlist_enabled(session: AsyncSession, item_id: str, enabled: bool) -> bool:
    stmt = text("UPDATE pairs_watchlist SET enabled = :enabled WHERE id = CAST(:id AS UUID) RETURNING id")
    row = (await session.execute(stmt, {"id": item_id, "enabled": enabled})).first()
    await session.commit()
    return row is not None


async def delete_watchlist(session: AsyncSession, item_id: str) -> bool:
    stmt = text("DELETE FROM pairs_watchlist WHERE id = CAST(:id AS UUID) RETURNING id")
    row = (await session.execute(stmt, {"id": item_id})).first()
    await session.commit()
    return row is not None


async def seed_default_watchlist(session: AsyncSession) -> int:
    """Insert the brief's ten pairs; existing rows are left untouched."""
    stmt = text(
        """
        INSERT INTO pairs_watchlist (name, y_ticker, x_ticker, rationale, overrides)
        VALUES (:name, :y, :x, :rationale, CAST(:overrides AS JSONB))
        ON CONFLICT (y_ticker, x_ticker) DO NOTHING
        """
    )
    inserted = 0
    for p in DEFAULT_PAIRS:
        res = await session.execute(
            stmt, {"name": p.name, "y": p.y, "x": p.x, "rationale": p.rationale, "overrides": json.dumps(p.overrides)}
        )
        inserted += int(getattr(res, "rowcount", 0) or 0)
    await session.commit()
    return inserted


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------

async def insert_scan(
    session: AsyncSession,
    *,
    as_of: date,
    trigger: str,
    config: dict[str, Any],
    results: list[PairStatsModel],
    universe_size: int,
    runtime_ms: int,
) -> str:
    head = text(
        """
        INSERT INTO pairs_scans (as_of, trigger, config, universe_size, pair_count, qualified_count, runtime_ms)
        VALUES (:as_of, :trigger, CAST(:config AS JSONB), :universe_size, :pair_count, :qualified_count, :runtime_ms)
        RETURNING id::text
        """
    )
    scan_id = (
        await session.execute(
            head,
            {
                "as_of": as_of, "trigger": trigger, "config": json.dumps(config), "universe_size": universe_size,
                "pair_count": len(results), "qualified_count": sum(1 for r in results if r.qualified),
                "runtime_ms": runtime_ms,
            },
        )
    ).scalar_one()
    if results:
        rows = text(
            """
            INSERT INTO pairs_scan_results (scan_id, pair_name, y_ticker, x_ticker, qualified, z, stats)
            VALUES (CAST(:scan_id AS UUID), :pair_name, :y, :x, :qualified, :z, CAST(:stats AS JSONB))
            ON CONFLICT (scan_id, y_ticker, x_ticker) DO NOTHING
            """
        )
        await session.execute(
            rows,
            [
                {
                    "scan_id": scan_id, "pair_name": r.pair_name, "y": r.y_ticker, "x": r.x_ticker,
                    "qualified": r.qualified, "z": r.z, "stats": r.model_dump_json(),
                }
                for r in results
            ],
        )
    await session.commit()
    return str(scan_id)


async def list_scans(session: AsyncSession, *, limit: int = 50) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT id::text AS id, created_at, as_of, trigger, config, universe_size, pair_count, qualified_count, runtime_ms
        FROM pairs_scans ORDER BY created_at DESC LIMIT :limit
        """
    )
    return _rows(await session.execute(stmt, {"limit": limit}))


async def get_scan(session: AsyncSession, scan_id: str) -> dict[str, Any] | None:
    head = _row(
        await session.execute(
            text(
                """
                SELECT id::text AS id, created_at, as_of, trigger, config, universe_size, pair_count, qualified_count, runtime_ms
                FROM pairs_scans WHERE id = CAST(:id AS UUID)
                """
            ),
            {"id": scan_id},
        )
    )
    if head is None:
        return None
    rows = _rows(
        await session.execute(
            text("SELECT stats FROM pairs_scan_results WHERE scan_id = CAST(:id AS UUID) ORDER BY qualified DESC, abs(coalesce(z, 0)) DESC"),
            {"id": scan_id},
        )
    )
    head["results"] = [r["stats"] if isinstance(r["stats"], dict) else json.loads(r["stats"]) for r in rows]
    return head


async def latest_scan_id(session: AsyncSession, *, trigger: str | None = None) -> str | None:
    stmt = text(
        """
        SELECT id::text FROM pairs_scans
        WHERE (:trigger IS NULL OR trigger = :trigger)
        ORDER BY created_at DESC LIMIT 1
        """
    )
    row = (await session.execute(stmt, {"trigger": trigger})).first()
    return None if row is None else str(row[0])


# ---------------------------------------------------------------------------
# Live state + signals
# ---------------------------------------------------------------------------

async def load_states(session: AsyncSession) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT pair_name, y_ticker, x_ticker, side, entered_on, entry_params, days_held, breakdown_days,
               cooldown_until, last_z, as_of, updated_at
        FROM pairs_state ORDER BY pair_name
        """
    )
    return _rows(await session.execute(stmt))


async def upsert_state(
    session: AsyncSession,
    *,
    pair_name: str,
    y: str,
    x: str,
    state: PairState,
    as_of: date,
    entered_on: date | None,
    cooldown_until: date | None,
    last_z: float | None,
) -> None:
    params = None
    if state.entry_params is not None:
        params = json.dumps(
            {
                "alpha": state.entry_params.alpha, "beta": state.entry_params.beta, "mean": state.entry_params.mean,
                "std": state.entry_params.std, "half_life": state.entry_params.half_life,
                "z_window": state.entry_params.z_window, "entry_z": state.entry_z,
            }
        )
    stmt = text(
        """
        INSERT INTO pairs_state
            (pair_name, y_ticker, x_ticker, side, entered_on, entry_params, days_held, breakdown_days,
             cooldown_until, last_z, as_of, updated_at)
        VALUES
            (:pair_name, :y, :x, :side, :entered_on, CAST(:entry_params AS JSONB), :days_held, :breakdown_days,
             :cooldown_until, :last_z, :as_of, NOW())
        ON CONFLICT (pair_name) DO UPDATE SET
            y_ticker = EXCLUDED.y_ticker, x_ticker = EXCLUDED.x_ticker, side = EXCLUDED.side,
            entered_on = EXCLUDED.entered_on, entry_params = EXCLUDED.entry_params,
            days_held = EXCLUDED.days_held, breakdown_days = EXCLUDED.breakdown_days,
            cooldown_until = EXCLUDED.cooldown_until, last_z = EXCLUDED.last_z,
            as_of = EXCLUDED.as_of, updated_at = NOW()
        """
    )
    await session.execute(
        stmt,
        {
            "pair_name": pair_name, "y": y, "x": x, "side": state.side, "entered_on": entered_on,
            "entry_params": params, "days_held": state.days_held, "breakdown_days": state.breakdown_days,
            "cooldown_until": cooldown_until, "last_z": last_z, "as_of": as_of,
        },
    )


async def insert_signal(
    session: AsyncSession,
    *,
    signal_date: date,
    pair_name: str,
    event: str,
    side: str,
    payload: dict[str, Any],
) -> str | None:
    """Insert one event; None when the same (date, pair, event) already exists.

    That None is the idempotency contract the daily job relies on: a
    re-run cannot create a second row, so it cannot push a second alert.
    """
    stmt = text(
        """
        INSERT INTO pairs_signals (signal_date, pair_name, event, side, payload)
        VALUES (:signal_date, :pair_name, :event, :side, CAST(:payload AS JSONB))
        ON CONFLICT (signal_date, pair_name, event) DO NOTHING
        RETURNING id::text
        """
    )
    row = (
        await session.execute(
            stmt,
            {
                "signal_date": signal_date, "pair_name": pair_name, "event": event, "side": side,
                "payload": json.dumps(payload, default=str),
            },
        )
    ).first()
    return None if row is None else str(row[0])


async def mark_notified(session: AsyncSession, signal_id: str) -> None:
    await session.execute(
        text("UPDATE pairs_signals SET notified_at = NOW() WHERE id = CAST(:id AS UUID)"), {"id": signal_id}
    )


async def unnotified_signals(session: AsyncSession, signal_date: date) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT id::text AS id, signal_date, pair_name, event, side, payload, notified_at, created_at
        FROM pairs_signals WHERE signal_date = :d AND notified_at IS NULL ORDER BY created_at
        """
    )
    return _rows(await session.execute(stmt, {"d": signal_date}))


async def list_signals(session: AsyncSession, *, limit: int = 100) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT id::text AS id, signal_date, pair_name, event, side, payload, notified_at, created_at
        FROM pairs_signals ORDER BY signal_date DESC, created_at DESC LIMIT :limit
        """
    )
    return _rows(await session.execute(stmt, {"limit": limit}))


# ---------------------------------------------------------------------------
# Backtest runs
# ---------------------------------------------------------------------------

async def insert_backtest_run(
    session: AsyncSession,
    *,
    config: dict[str, Any],
    metrics: dict[str, Any],
    result: dict[str, Any],
    runtime_ms: int,
    owner_id: str | None,
    notes: str | None,
) -> str:
    stmt = text(
        """
        INSERT INTO pairs_backtest_runs (owner_id, config, metrics, result, runtime_ms, notes)
        VALUES (CAST(:owner AS UUID), CAST(:config AS JSONB), CAST(:metrics AS JSONB), CAST(:result AS JSONB), :runtime_ms, :notes)
        RETURNING id::text
        """
    )
    run_id = (
        await session.execute(
            stmt,
            {
                "owner": owner_id, "config": json.dumps(config, default=str), "metrics": json.dumps(metrics, default=str),
                "result": json.dumps(result, default=str), "runtime_ms": runtime_ms, "notes": notes,
            },
        )
    ).scalar_one()
    await session.commit()
    return str(run_id)


async def list_backtest_runs(session: AsyncSession, *, limit: int = 50, owner_id: str | None = None) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT id::text AS id, created_at, config, metrics, runtime_ms, notes
        FROM pairs_backtest_runs
        WHERE (:owner IS NULL OR owner_id = CAST(:owner AS UUID))
        ORDER BY created_at DESC LIMIT :limit
        """
    )
    return _rows(await session.execute(stmt, {"limit": limit, "owner": owner_id}))


async def get_backtest_run(session: AsyncSession, run_id: str, *, owner_id: str | None = None) -> dict[str, Any] | None:
    stmt = text(
        """
        SELECT id::text AS id, created_at, config, metrics, result, runtime_ms, notes
        FROM pairs_backtest_runs
        WHERE id = CAST(:id AS UUID) AND (:owner IS NULL OR owner_id = CAST(:owner AS UUID))
        """
    )
    return _row(await session.execute(stmt, {"id": run_id, "owner": owner_id}))


# ---------------------------------------------------------------------------
# Job runs
# ---------------------------------------------------------------------------

async def start_job_run(session: AsyncSession, *, run_date: date, dry_run: bool) -> str:
    stmt = text(
        "INSERT INTO pairs_job_runs (run_date, dry_run) VALUES (:run_date, :dry_run) RETURNING id::text"
    )
    job_id = (await session.execute(stmt, {"run_date": run_date, "dry_run": dry_run})).scalar_one()
    await session.commit()
    return str(job_id)


async def finish_job_run(session: AsyncSession, job_id: str, *, status: str, summary: dict[str, Any]) -> None:
    stmt = text(
        """
        UPDATE pairs_job_runs SET finished_at = NOW(), status = :status, summary = CAST(:summary AS JSONB)
        WHERE id = CAST(:id AS UUID)
        """
    )
    await session.execute(stmt, {"id": job_id, "status": status, "summary": json.dumps(summary, default=str)})
    await session.commit()


async def list_job_runs(session: AsyncSession, *, limit: int = 30) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT id::text AS id, run_date, started_at, finished_at, status, dry_run, summary
        FROM pairs_job_runs ORDER BY started_at DESC LIMIT :limit
        """
    )
    return _rows(await session.execute(stmt, {"limit": limit}))
