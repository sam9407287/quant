-- =============================================================
-- Quant Futures — TimescaleDB schema
--
-- Design principle:
--   * `kbars_1m` is the only table written to. It is a hypertable
--     partitioned by time so writes stay fast as years of data
--     accumulate.
--   * All higher timeframes (5m / 15m / 1h / 4h / 1d / 1w) are
--     Continuous Aggregates. They refresh incrementally and are
--     always consistent with the source data — no manual rollup.
--   * Old chunks (> 30 days) are compressed columnar to save space.
--
-- This file is idempotent: every DDL uses IF NOT EXISTS or the
-- equivalent TimescaleDB helper, so it can be re-applied safely.
-- =============================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- pgcrypto provides gen_random_uuid(), used by the experiments table
-- introduced in ADR-002 (ML workbench). It is shipped with PostgreSQL
-- contrib and present in the timescale/timescaledb image.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =============================================================
-- 1m raw OHLCV bars — hypertable, single source of truth
-- =============================================================
CREATE TABLE IF NOT EXISTS kbars_1m (
    instrument  TEXT           NOT NULL,
    ts          TIMESTAMPTZ    NOT NULL,
    open        NUMERIC(12, 4) NOT NULL,
    high        NUMERIC(12, 4) NOT NULL,
    low         NUMERIC(12, 4) NOT NULL,
    close       NUMERIC(12, 4) NOT NULL,
    volume      BIGINT         NOT NULL,
    source      TEXT           NOT NULL DEFAULT 'yfinance',
    PRIMARY KEY (instrument, ts)
);

-- One chunk per 7 days of 1m bars. Roughly ~40k rows/instrument/chunk —
-- well below TimescaleDB's recommended chunk size sweet spot (~25% of RAM).
SELECT create_hypertable(
    'kbars_1m',
    'ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_kbars_1m_lookup
    ON kbars_1m (instrument, ts DESC);

-- Compression: bars older than 30 days are converted to columnar storage.
-- Typical compression ratio for OHLCV is 90%+.
ALTER TABLE kbars_1m SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'instrument',
    timescaledb.compress_orderby = 'ts DESC'
);

SELECT add_compression_policy('kbars_1m', INTERVAL '30 days', if_not_exists => TRUE);

-- =============================================================
-- Continuous Aggregates — auto-derived higher timeframes
--
-- Each view is queryable like a regular table. TimescaleDB tracks
-- which buckets are stale (because their underlying 1m bars changed)
-- and refreshes only those, incrementally.
--
-- Refresh strategy:
--   * Policy below schedules an hourly refresh of the last 2 days.
--   * After each daily fetch, the fetcher additionally calls
--     `refresh_continuous_aggregate` to force-refresh through "now".
-- =============================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS kbars_5m
WITH (timescaledb.continuous) AS
SELECT
    instrument,
    time_bucket(INTERVAL '5 minutes', ts) AS ts,
    first(open, ts)              AS open,
    max(high)                    AS high,
    min(low)                     AS low,
    last(close, ts)              AS close,
    sum(volume)                  AS volume
FROM kbars_1m
GROUP BY instrument, time_bucket(INTERVAL '5 minutes', ts)
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS kbars_15m
WITH (timescaledb.continuous) AS
SELECT
    instrument,
    time_bucket(INTERVAL '15 minutes', ts) AS ts,
    first(open, ts)              AS open,
    max(high)                    AS high,
    min(low)                     AS low,
    last(close, ts)              AS close,
    sum(volume)                  AS volume
FROM kbars_1m
GROUP BY instrument, time_bucket(INTERVAL '15 minutes', ts)
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS kbars_1h
WITH (timescaledb.continuous) AS
SELECT
    instrument,
    time_bucket(INTERVAL '1 hour', ts) AS ts,
    first(open, ts)              AS open,
    max(high)                    AS high,
    min(low)                     AS low,
    last(close, ts)              AS close,
    sum(volume)                  AS volume
FROM kbars_1m
GROUP BY instrument, time_bucket(INTERVAL '1 hour', ts)
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS kbars_4h
WITH (timescaledb.continuous) AS
SELECT
    instrument,
    time_bucket(INTERVAL '4 hours', ts) AS ts,
    first(open, ts)              AS open,
    max(high)                    AS high,
    min(low)                     AS low,
    last(close, ts)              AS close,
    sum(volume)                  AS volume
FROM kbars_1m
GROUP BY instrument, time_bucket(INTERVAL '4 hours', ts)
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS kbars_1d
WITH (timescaledb.continuous) AS
SELECT
    instrument,
    time_bucket(INTERVAL '1 day', ts) AS ts,
    first(open, ts)              AS open,
    max(high)                    AS high,
    min(low)                     AS low,
    last(close, ts)              AS close,
    sum(volume)                  AS volume
FROM kbars_1m
GROUP BY instrument, time_bucket(INTERVAL '1 day', ts)
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS kbars_1w
WITH (timescaledb.continuous) AS
SELECT
    instrument,
    time_bucket(INTERVAL '1 week', ts) AS ts,
    first(open, ts)              AS open,
    max(high)                    AS high,
    min(low)                     AS low,
    last(close, ts)              AS close,
    sum(volume)                  AS volume
FROM kbars_1m
GROUP BY instrument, time_bucket(INTERVAL '1 week', ts)
WITH NO DATA;

-- Refresh policies: refresh the last 2 days every hour. The end_offset
-- equals the bucket width so we never materialise an incomplete bucket.
SELECT add_continuous_aggregate_policy('kbars_5m',
    start_offset => INTERVAL '2 days',
    end_offset   => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('kbars_15m',
    start_offset => INTERVAL '2 days',
    end_offset   => INTERVAL '15 minutes',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('kbars_1h',
    start_offset => INTERVAL '2 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('kbars_4h',
    start_offset => INTERVAL '7 days',
    end_offset   => INTERVAL '4 hours',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('kbars_1d',
    start_offset => INTERVAL '14 days',
    end_offset   => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('kbars_1w',
    start_offset => INTERVAL '60 days',
    end_offset   => INTERVAL '1 week',
    schedule_interval => INTERVAL '1 day',
    if_not_exists => TRUE);

-- =============================================================
-- Contract roll calendar
-- =============================================================
CREATE TABLE IF NOT EXISTS roll_calendar (
    id            SERIAL PRIMARY KEY,
    instrument    TEXT           NOT NULL,
    old_contract  TEXT           NOT NULL,
    new_contract  TEXT           NOT NULL,
    roll_date     DATE           NOT NULL,
    roll_ts       TIMESTAMPTZ,
    price_diff    NUMERIC(12, 4),
    price_ratio   NUMERIC(10, 8),
    created_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    UNIQUE (instrument, roll_date)
);

-- =============================================================
-- Data coverage tracking
-- =============================================================
CREATE TABLE IF NOT EXISTS data_coverage (
    instrument      TEXT        NOT NULL,
    timeframe       TEXT        NOT NULL,
    earliest_ts     TIMESTAMPTZ,
    latest_ts       TIMESTAMPTZ,
    bar_count       BIGINT      NOT NULL DEFAULT 0,
    gap_count       INT         NOT NULL DEFAULT 0,
    last_fetch_ts   TIMESTAMPTZ,
    last_fetch_ok   BOOLEAN     NOT NULL DEFAULT TRUE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (instrument, timeframe)
);

INSERT INTO data_coverage (instrument, timeframe)
SELECT i.instrument, t.timeframe
FROM
    (VALUES
        ('NQ'), ('ES'), ('YM'), ('RTY'),   -- equity indices
        ('GC'), ('SI'), ('HG'),             -- metals (COMEX)
        ('CL'), ('NG')                      -- energy (NYMEX)
    ) AS i(instrument),
    (VALUES ('1m'), ('5m'), ('15m'), ('1h'), ('4h'), ('1d'), ('1w')) AS t(timeframe)
ON CONFLICT DO NOTHING;

-- =============================================================
-- ML experiment tracking (ADR-002)
-- =============================================================
-- Every wizard run on /api/v1/ml/train inserts one row here. The full
-- request config and the resulting metrics live as JSONB so the schema
-- doesn't need to evolve with every new feature or model the workbench
-- learns to handle. Plain table (no hypertable) — query patterns are
-- "list latest N" and "fetch by id", not time-bucketed scans.
CREATE TABLE IF NOT EXISTS experiments (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    config      JSONB       NOT NULL,
    metrics     JSONB       NOT NULL,
    artefacts   JSONB,
    runtime_ms  INT         NOT NULL,
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS experiments_created_at_idx
    ON experiments (created_at DESC);

-- =============================================================
-- Backtest runs & trades (ADR-003)
-- =============================================================
-- One backtest_runs row per engine invocation on /api/v1/backtest.
-- The full BacktestParams JSON and the summary metrics live as JSONB
-- (same reasoning as experiments); per-session outcomes are relational
-- rows in backtest_trades because the analysis endpoints re-read them
-- as a series (Monte Carlo, seasonality). Plain tables, not
-- hypertables — access is "by run id", never time-bucketed.
CREATE TABLE IF NOT EXISTS backtest_runs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    instrument  TEXT        NOT NULL,
    params      JSONB       NOT NULL,
    metrics     JSONB       NOT NULL,
    runtime_ms  INT         NOT NULL,
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS backtest_runs_created_at_idx
    ON backtest_runs (created_at DESC);

CREATE TABLE IF NOT EXISTS backtest_trades (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    session_date DATE NOT NULL,
    exit_reason  TEXT NOT NULL,
    direction    TEXT,
    entry_ts     TIMESTAMPTZ,
    entry_price  DOUBLE PRECISION,
    exit_ts      TIMESTAMPTZ,
    exit_price   DOUBLE PRECISION,
    pnl_points   DOUBLE PRECISION NOT NULL DEFAULT 0,
    pnl_usd      DOUBLE PRECISION NOT NULL DEFAULT 0,
    mae_points   DOUBLE PRECISION NOT NULL DEFAULT 0,
    mfe_points   DOUBLE PRECISION NOT NULL DEFAULT 0,
    range_high   DOUBLE PRECISION,
    range_low    DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS backtest_trades_run_idx
    ON backtest_trades (run_id, session_date);

-- =============================================================
-- Strategy definitions (ADR-004)
-- =============================================================
-- One row per saved strategy template. The full rule set (entry/exit
-- conditions, optional SL/TP bracket, timeframe, default lookback)
-- lives in `definition` as JSONB, validated by the Pydantic
-- StrategyDefinition schema at the API boundary.
CREATE TABLE IF NOT EXISTS strategies (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    name        TEXT        NOT NULL,
    description TEXT,
    definition  JSONB       NOT NULL
);

CREATE INDEX IF NOT EXISTS strategies_created_at_idx
    ON strategies (created_at DESC);

-- =============================================================
-- Users & ownership (ADR-005)
-- =============================================================
-- One row per Google account that has signed in. `google_sub` is
-- Google's stable subject id (emails can change); role is derived from
-- the ADMIN_EMAILS allowlist at sign-in time and re-synced every login.
CREATE TABLE IF NOT EXISTS users (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    google_sub  TEXT        NOT NULL UNIQUE,
    email       TEXT        NOT NULL,
    name        TEXT,
    picture     TEXT,
    role        TEXT        NOT NULL DEFAULT 'user'
);

-- Per-user ownership. NULL owner_id = legacy rows created before auth
-- existed; visible to admins only once filtering is on.
ALTER TABLE strategies    ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id);
ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id);

CREATE INDEX IF NOT EXISTS strategies_owner_idx    ON strategies (owner_id);
CREATE INDEX IF NOT EXISTS backtest_runs_owner_idx ON backtest_runs (owner_id);
