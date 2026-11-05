-- Statistical arbitrage lab (ADR-010).
--
-- Applied automatically by `app.pairs.schema.ensure_schema()` from the API
-- lifespan and the daily pairs job; also appended to db/schema.sql for
-- fresh volumes. Every statement is idempotent so re-running is a no-op.
--
-- Manual application, if ever needed:
--   railway ssh --service timescaledb "psql -U quant -d quant_futures" < db/migrations/002_pairs.sql

-- Daily bars for the pairs universe. Futures rows hold the settlement /
-- close yfinance reports for the front-month series; ETFs and stocks
-- also carry the dividend-adjusted close. Keyed by the vendor ticker
-- because the universe is wider than the 1m instrument registry.
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

-- Named Y/X pairs the daily job scans. `overrides` holds per-pair scan
-- parameters (formation window, thresholds) merged over the defaults.
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

-- One row per scan execution (manual from the UI or the daily job) and
-- one result row per pair, so the dashboard can show how a pair's
-- statistics evolved rather than only the latest snapshot.
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

-- Live position state per watchlist pair. `entry_params` freezes β, α,
-- mean and std at entry so exits are judged against what was known then.
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

-- Event log. The unique key is the idempotency guarantee: a same-day
-- re-run of the job cannot insert a second entry for the same event, and
-- `notified_at` records whether the push already went out.
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

-- Walk-forward backtest runs. The result document (equity curve, trades,
-- per-pair attribution, sensitivity grid) is bounded in size and only
-- ever read whole, so JSONB beats a trades table here.
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

-- One row per daily job execution for the ops panel.
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
