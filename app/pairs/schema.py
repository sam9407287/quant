"""Idempotent DDL for the pairs lab tables (mirror of db/migrations/002_pairs.sql).

The DDL is embedded rather than read from `db/` because neither Docker
image ships that directory. A unit test asserts the two copies agree, so
editing one without the other fails CI instead of drifting silently.
Every statement is `IF NOT EXISTS`, which is what lets the API lifespan and
the daily job call `ensure_schema()` on every start without a migration
runbook.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS pairs_daily_bars (
    ticker        TEXT             NOT NULL,
    trading_date  DATE             NOT NULL,
    open          DOUBLE PRECISION,
    high          DOUBLE PRECISION,
    low           DOUBLE PRECISION,
    close         DOUBLE PRECISION NOT NULL,
    adj_close     DOUBLE PRECISION NOT NULL,
    volume        BIGINT,
    source        TEXT             NOT NULL DEFAULT 'yfinance',
    fetched_at    TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, trading_date)
);

CREATE INDEX IF NOT EXISTS pairs_daily_bars_date_idx
    ON pairs_daily_bars (trading_date);

CREATE TABLE IF NOT EXISTS pairs_watchlist (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL UNIQUE,
    y_ticker    TEXT        NOT NULL,
    x_ticker    TEXT        NOT NULL,
    enabled     BOOLEAN     NOT NULL DEFAULT TRUE,
    overrides   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    rationale   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pairs_watchlist_legs UNIQUE (y_ticker, x_ticker),
    CONSTRAINT pairs_watchlist_not_self CHECK (y_ticker <> x_ticker)
);

CREATE TABLE IF NOT EXISTS pairs_scans (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    as_of            DATE        NOT NULL,
    trigger          TEXT        NOT NULL DEFAULT 'manual',
    config           JSONB       NOT NULL,
    universe_size    INT         NOT NULL DEFAULT 0,
    pair_count       INT         NOT NULL DEFAULT 0,
    qualified_count  INT         NOT NULL DEFAULT 0,
    runtime_ms       INT         NOT NULL DEFAULT 0,
    CONSTRAINT pairs_scans_trigger CHECK (trigger IN ('manual', 'daily'))
);

CREATE INDEX IF NOT EXISTS pairs_scans_created_at_idx
    ON pairs_scans (created_at DESC);

CREATE TABLE IF NOT EXISTS pairs_scan_results (
    scan_id    UUID    NOT NULL REFERENCES pairs_scans(id) ON DELETE CASCADE,
    pair_name  TEXT    NOT NULL,
    y_ticker   TEXT    NOT NULL,
    x_ticker   TEXT    NOT NULL,
    qualified  BOOLEAN NOT NULL DEFAULT FALSE,
    z          DOUBLE PRECISION,
    stats      JSONB   NOT NULL,
    PRIMARY KEY (scan_id, y_ticker, x_ticker)
);

CREATE TABLE IF NOT EXISTS pairs_state (
    pair_name       TEXT        PRIMARY KEY,
    y_ticker        TEXT        NOT NULL,
    x_ticker        TEXT        NOT NULL,
    side            TEXT        NOT NULL DEFAULT 'flat',
    entered_on      DATE,
    entry_params    JSONB,
    days_held       INT         NOT NULL DEFAULT 0,
    breakdown_days  INT         NOT NULL DEFAULT 0,
    cooldown_until  DATE,
    last_z          DOUBLE PRECISION,
    as_of           DATE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pairs_state_side CHECK (side IN ('flat', 'long_spread', 'short_spread'))
);

CREATE TABLE IF NOT EXISTS pairs_signals (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_date  DATE        NOT NULL,
    pair_name    TEXT        NOT NULL,
    event        TEXT        NOT NULL,
    side         TEXT        NOT NULL,
    payload      JSONB       NOT NULL,
    notified_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pairs_signals_unique UNIQUE (signal_date, pair_name, event)
);

CREATE INDEX IF NOT EXISTS pairs_signals_date_idx
    ON pairs_signals (signal_date DESC);

CREATE TABLE IF NOT EXISTS pairs_backtest_runs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    owner_id    UUID        REFERENCES users(id) ON DELETE SET NULL,
    config      JSONB       NOT NULL,
    metrics     JSONB       NOT NULL,
    result      JSONB       NOT NULL,
    runtime_ms  INT         NOT NULL,
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS pairs_backtest_runs_created_at_idx
    ON pairs_backtest_runs (created_at DESC);

CREATE TABLE IF NOT EXISTS pairs_job_runs (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_date     DATE        NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ,
    status       TEXT        NOT NULL DEFAULT 'running',
    dry_run      BOOLEAN     NOT NULL DEFAULT FALSE,
    summary      JSONB,
    CONSTRAINT pairs_job_runs_status CHECK (status IN ('running', 'ok', 'no_data', 'error'))
);

CREATE INDEX IF NOT EXISTS pairs_job_runs_started_idx
    ON pairs_job_runs (started_at DESC);
"""


def statements(sql: str = DDL) -> list[str]:
    """Split a DDL script into executable statements, dropping comments."""
    lines = [ln for ln in sql.splitlines() if not ln.lstrip().startswith("--")]
    out: list[str] = []
    for chunk in "\n".join(lines).split(";"):
        body = chunk.strip()
        if body:
            out.append(body)
    return out


async def ensure_schema(session: AsyncSession) -> int:
    """Create any missing pairs tables; returns the statement count run."""
    stmts = statements()
    for stmt in stmts:
        await session.execute(text(stmt))
    await session.commit()
    logger.info("pairs schema ensured (%d statements)", len(stmts))
    return len(stmts)
