"""Daily pairs job: refresh daily bars → scan the watchlist → step state → alert.

Runs inside the fetcher's APScheduler process (ADR-010 §2.6) and from the
admin endpoint. Idempotent by construction:

* the state row carries `as_of`; a pair already advanced to today's date
  is not stepped again, so `days_held` cannot double-count on a re-run;
* `pairs_signals` has a unique (date, pair, event) key, so a re-run cannot
  insert a second event, and only rows with `notified_at IS NULL` are
  pushed, so nothing is pushed twice;
* the digest is itself recorded as a signal row (`_digest_`), which gives
  it the same guarantee.

Everything that can fail is wrapped: the job always returns a summary
dict and records it in `pairs_job_runs`.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import AsyncSessionLocal
from app.pairs import notify
from app.pairs import repository as repo
from app.pairs.data import latest_trading_date
from app.pairs.schema import ensure_schema
from app.pairs.schemas import PairStatsModel, RefreshRequest, ScanConfig
from app.pairs.service import refresh_daily_bars, run_scan
from app.pairs.signals import EntryParams, Observation, PairState, Transition, step
from app.pairs.sizing import size_position

logger = logging.getLogger(__name__)

DIGEST_PAIR = "_digest_"


async def run_pairs_job(
    *, dry_run: bool | None = None, trigger: str = "scheduled", today: date | None = None
) -> dict[str, Any]:
    """Entry point for the scheduler and the admin endpoint; never raises."""
    settings = get_settings()
    dry = settings.pairs_dry_run if dry_run is None else dry_run
    run_date = today or datetime.now(UTC).date()
    async with AsyncSessionLocal() as session:
        await ensure_schema(session)
        job_id = await repo.start_job_run(session, run_date=run_date, dry_run=dry)
        try:
            summary = await execute(session, settings=settings, today=run_date, dry_run=dry, trigger=trigger)
        except Exception as exc:
            logger.exception("pairs job failed")
            summary = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            if not dry and settings.pairs_webhook_url:
                notify.post(settings.pairs_webhook_url, notify.error_embed(signal_date=run_date, message=summary["error"]))
        await repo.finish_job_run(session, job_id, status=str(summary["status"]), summary=summary)
        return summary


async def execute(
    session: AsyncSession, *, settings: Settings, today: date, dry_run: bool, trigger: str
) -> dict[str, Any]:
    """The job body, separated so tests can drive it with a mocked session."""
    watch = await repo.list_watchlist(session, enabled_only=True)
    if not watch:
        await repo.seed_default_watchlist(session)
        watch = await repo.list_watchlist(session, enabled_only=True)
    pairs = [(r["y_ticker"], r["x_ticker"]) for r in watch]
    overrides = {(r["y_ticker"], r["x_ticker"]): dict(r.get("overrides") or {}) for r in watch}
    tickers = sorted({t for p in pairs for t in p})

    refreshed = await refresh_daily_bars(session, RefreshRequest(tickers=tickers, years=settings.pairs_history_years))
    latest = await latest_trading_date(session, tickers)
    expected = expected_trading_date(today)
    if latest is None or latest < expected:
        summary = {
            "status": "no_data", "expected": expected, "latest": latest, "rows_written": refreshed.rows_written,
            "issues": len(refreshed.issues),
        }
        if settings.pairs_notify_no_data and not dry_run and settings.pairs_webhook_url:
            notify.post(
                settings.pairs_webhook_url,
                notify.error_embed(signal_date=today, message=f"No new daily bar for {expected} (latest {latest})."),
            )
        return summary

    config = ScanConfig(mode="explicit", pairs=pairs, as_of=latest)
    scan, wide = await run_scan(session, config, trigger="daily", overrides=overrides)
    stats_by_pair = {(r.y_ticker, r.x_ticker): r for r in scan.results}
    last_prices = wide.ffill(limit=1).iloc[-1] if not wide.empty else None

    states = {r["pair_name"]: r for r in await repo.load_states(session)}
    events: list[dict[str, Any]] = []
    skipped = 0
    for row in watch:
        key = (row["y_ticker"], row["x_ticker"])
        stats = stats_by_pair.get(key)
        if stats is None:
            continue
        prev = states.get(stats.pair_name)
        if prev is not None and prev.get("as_of") == latest:
            skipped += 1  # already advanced today → idempotent re-run
            continue
        state = state_from_row(prev, latest)
        transition = step(state, observation_from_stats(stats), rules_for(row, config))
        entered_on = _entered_on(prev, transition, latest)
        cooldown_until = _cooldown_until(transition.state, latest)
        await repo.upsert_state(
            session, pair_name=stats.pair_name, y=stats.y_ticker, x=stats.x_ticker, state=transition.state,
            as_of=latest, entered_on=entered_on, cooldown_until=cooldown_until, last_z=stats.z,
        )
        if transition.event != "none":
            payload = signal_payload(stats, transition, prev, last_prices, settings)
            side = transition.state.side if transition.event == "entry" else str(prev["side"] if prev else "flat")
            signal_id = await repo.insert_signal(
                session, signal_date=latest, pair_name=stats.pair_name, event=transition.event, side=side, payload=payload
            )
            events.append({"pair": stats.pair_name, "event": transition.event, "side": side, "new": signal_id is not None})
    await session.commit()

    if settings.pairs_daily_digest:
        digest_id = await repo.insert_signal(
            session, signal_date=latest, pair_name=DIGEST_PAIR, event="digest", side="flat",
            payload={"pairs": [r.pair_name for r in scan.results], "qualified": scan.qualified_count},
        )
        await session.commit()
        if digest_id is None:
            logger.info("digest for %s already recorded", latest)

    pushed = await push_pending(session, latest, scan.results, settings, dry_run=dry_run)
    return {
        "status": "ok", "as_of": latest, "trigger": trigger, "dry_run": dry_run, "pairs_scanned": scan.pair_count,
        "qualified": scan.qualified_count, "events": events, "state_skipped_as_current": skipped,
        "pushed": pushed, "rows_written": refreshed.rows_written, "data_issues": len(refreshed.issues),
        "scan_id": scan.id,
    }


# ---------------------------------------------------------------------------
# Helpers (pure where possible)
# ---------------------------------------------------------------------------

def expected_trading_date(today: date) -> date:
    """The most recent weekday on or before `today` (US holidays yield no_data)."""
    d = today
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def rules_for(row: dict[str, Any], config: ScanConfig) -> Any:
    """Signal rules for a watchlist row: defaults overlaid with its overrides."""
    from app.pairs.schemas import SignalRules

    ov = dict(row.get("overrides") or {})
    fields = {k: v for k, v in ov.items() if k in SignalRules.model_fields}
    return SignalRules(**fields)


def state_from_row(row: dict[str, Any] | None, as_of: date) -> PairState:
    if row is None:
        return PairState()
    params = None
    raw = row.get("entry_params")
    if raw:
        params = EntryParams(
            alpha=float(raw["alpha"]), beta=float(raw["beta"]), mean=float(raw["mean"]), std=float(raw["std"]),
            half_life=None if raw.get("half_life") is None else float(raw["half_life"]), z_window=int(raw.get("z_window", 0)),
        )
    cooldown_until = row.get("cooldown_until")
    remaining = 0
    if cooldown_until is not None and cooldown_until > as_of:
        remaining = int(np.busday_count(as_of, cooldown_until))
    return PairState(
        side=row.get("side", "flat"), entry_params=params,
        entry_z=None if raw is None else raw.get("entry_z"), days_held=int(row.get("days_held", 0)),
        breakdown_days=int(row.get("breakdown_days", 0)), cooldown_remaining=max(remaining, 0),
    )


def observation_from_stats(stats: PairStatsModel) -> Observation:
    """What the scan already computed, in the shape the state machine reads.

    `log_y` / `log_x` are reconstructed from the spread identity so a
    frozen-parameter z can be evaluated without reloading prices:
    spread = log_y − α − β·log_x with log_x fixed at 0 gives log_y = spread + α.
    The state machine only ever uses them through `frozen_z`, which is
    invariant to that choice once β is frozen at the same value — and when
    β has drifted the difference is exactly the model error a frozen trade
    carries, so it is reported, not hidden.
    """
    params = EntryParams(
        alpha=stats.alpha, beta=stats.beta, mean=stats.spread_mean or 0.0, std=stats.spread_std or 0.0,
        half_life=stats.half_life, z_window=stats.z_window,
    )
    spread = stats.spread_last or 0.0
    return Observation(
        log_y=spread + stats.alpha, log_x=0.0, z_live=stats.z, pvalue=stats.eg_pvalue, qualified=stats.qualified,
        live_params=params,
    )


def _entered_on(prev: dict[str, Any] | None, transition: Transition, today: date) -> date | None:
    if transition.event == "entry":
        return today
    if transition.state.in_position and prev is not None:
        return prev.get("entered_on")
    return None


def _cooldown_until(state: PairState, today: date) -> date | None:
    if state.cooldown_remaining <= 0:
        return None
    return today + timedelta(days=math.ceil(state.cooldown_remaining * 7 / 5))


def signal_payload(
    stats: PairStatsModel, transition: Transition, prev: dict[str, Any] | None, last_prices: Any, settings: Settings
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stats": stats.model_dump(mode="json"), "z_used": transition.z_used,
        "days_held": int(prev.get("days_held", 0)) + 1 if prev else 0,
    }
    if transition.event == "entry" and last_prices is not None and stats.beta > 0:
        try:
            py = float(last_prices[stats.y_ticker])
            px = float(last_prices[stats.x_ticker])
            size = size_position(
                stats.y_ticker, stats.x_ticker, price_y=py, price_x=px, beta=stats.beta,
                gross_notional=settings.pairs_capital, mode="integer", prefer_micro=True, spread_std=stats.spread_std,
            )
            payload["sizing"] = {
                "y_qty": size.y.qty, "y_contract": size.y.contract, "x_qty": size.x.qty, "x_contract": size.x.contract,
                "rounding_error_pct": size.rounding_error_pct, "adverse_2sigma_usd": size.adverse_2sigma_usd,
                "feasible": size.feasible, "gross_notional": size.gross_notional,
            }
        except (KeyError, ValueError, TypeError) as exc:
            payload["sizing_error"] = str(exc)
    return payload


async def push_pending(
    session: AsyncSession, signal_date: date, results: list[PairStatsModel], settings: Settings, *, dry_run: bool
) -> int:
    """Post every un-notified signal for the date; mark each on success."""
    pending = await repo.unnotified_signals(session, signal_date)
    if dry_run or not settings.pairs_webhook_url:
        logger.info("pairs job: %d signal(s) pending, not pushed (dry_run=%s, webhook=%s)",
                    len(pending), dry_run, bool(settings.pairs_webhook_url))
        return 0
    by_pair = {r.pair_name: r for r in results}
    base = settings.frontend_base_url
    pushed = 0
    for row in pending:
        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        if row["pair_name"] == DIGEST_PAIR:
            embed = notify.digest_embed(signal_date=signal_date, rows=results, base_url=base)
        else:
            stats = by_pair.get(row["pair_name"])
            if stats is None:
                stats = PairStatsModel(**payload["stats"])
            if row["event"] == "entry":
                embed = notify.entry_embed(signal_date=signal_date, stats=stats, side=row["side"], sizing=payload.get("sizing"), base_url=base)
            else:
                embed = notify.exit_embed(
                    signal_date=signal_date, stats=stats, event=row["event"], side_before=row["side"],
                    days_held=int(payload.get("days_held", 0)), base_url=base,
                )
        if notify.post(settings.pairs_webhook_url, embed):
            await repo.mark_notified(session, row["id"])
            pushed += 1
    await session.commit()
    return pushed
