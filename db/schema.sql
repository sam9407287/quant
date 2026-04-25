-- =============================================================
-- Quant Futures — TimescaleDB Schema
-- =============================================================

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- =============================================================
-- 1m raw OHLCV bars — the single source of truth
-- =============================================================
CREATE TABLE IF NOT EXISTS kbars_1m (
    instrument  TEXT           NOT NULL,
    ts          TIMESTAMPTZ    NOT NULL,
    open        NUMERIC(12, 4) NOT NULL,
    high        NUMERIC(12, 4) NOT NULL,
    low         NUMERIC(12, 4) NOT NULL,
    close       NUMERIC(12, 4) NOT NULL,
    volume      BIGINT         NOT NULL,
    source      TEXT           NOT NULL DEFAULT 'yfinance'
);

SELECT create_hypertable(
    'kbars_1m', 'ts',
    chunk_time_interval => INTERVAL '1 week',
    if_not_exists => TRUE
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_kbars_1m
    ON kbars_1m (instrument, ts);

CREATE INDEX IF NOT EXISTS idx_kbars_1m_lookup
    ON kbars_1m (instrument, ts DESC);

-- =============================================================
-- Derived timeframes via Continuous Aggregates
-- =============================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS kbars_5m
WITH (timescaledb.continuous) AS
SELECT
    instrument,
    time_bucket('5 minutes', ts) AS ts,
    first(open, ts)              AS open,
    max(high)                    AS high,
    min(low)                     AS low,
    last(close, ts)              AS close,
    sum(volume)                  AS volume
FROM kbars_1m
GROUP BY instrument, time_bucket('5 minutes', ts)
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS kbars_15m
WITH (timescaledb.continuous) AS
SELECT
    instrument,
    time_bucket('15 minutes', ts) AS ts,
    first(open, ts)               AS open,
    max(high)                     AS high,
    min(low)                      AS low,
    last(close, ts)               AS close,
    sum(volume)                   AS volume
FROM kbars_1m
GROUP BY instrument, time_bucket('15 minutes', ts)
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS kbars_1h
WITH (timescaledb.continuous) AS
SELECT
    instrument,
    time_bucket('1 hour', ts) AS ts,
    first(open, ts)           AS open,
    max(high)                 AS high,
    min(low)                  AS low,
    last(close, ts)           AS close,
    sum(volume)               AS volume
FROM kbars_1m
GROUP BY instrument, time_bucket('1 hour', ts)
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS kbars_4h
WITH (timescaledb.continuous) AS
SELECT
    instrument,
    time_bucket('4 hours', ts) AS ts,
    first(open, ts)            AS open,
    max(high)                  AS high,
    min(low)                   AS low,
    last(close, ts)            AS close,
    sum(volume)                AS volume
FROM kbars_1m
GROUP BY instrument, time_bucket('4 hours', ts)
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS kbars_1d
WITH (timescaledb.continuous) AS
SELECT
    instrument,
    time_bucket('1 day', ts) AS ts,
    first(open, ts)          AS open,
    max(high)                AS high,
    min(low)                 AS low,
    last(close, ts)          AS close,
    sum(volume)              AS volume
FROM kbars_1m
GROUP BY instrument, time_bucket('1 day', ts)
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS kbars_1w
WITH (timescaledb.continuous) AS
SELECT
    instrument,
    time_bucket('1 week', ts) AS ts,
    first(open, ts)           AS open,
    max(high)                 AS high,
    min(low)                  AS low,
    last(close, ts)           AS close,
    sum(volume)               AS volume
FROM kbars_1m
GROUP BY instrument, time_bucket('1 week', ts)
WITH NO DATA;

-- Refresh policies — keep last 2 days current, refresh hourly
SELECT add_continuous_aggregate_policy('kbars_5m',
    start_offset    => INTERVAL '2 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists   => TRUE);

SELECT add_continuous_aggregate_policy('kbars_15m',
    start_offset    => INTERVAL '2 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists   => TRUE);

SELECT add_continuous_aggregate_policy('kbars_1h',
    start_offset    => INTERVAL '3 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists   => TRUE);

SELECT add_continuous_aggregate_policy('kbars_4h',
    start_offset    => INTERVAL '7 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists   => TRUE);

SELECT add_continuous_aggregate_policy('kbars_1d',
    start_offset    => INTERVAL '14 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists   => TRUE);

SELECT add_continuous_aggregate_policy('kbars_1w',
    start_offset    => INTERVAL '30 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists   => TRUE);

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
    created_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_roll_calendar
    ON roll_calendar (instrument, roll_date);

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

-- Seed initial coverage rows so upserts always have a target
INSERT INTO data_coverage (instrument, timeframe)
SELECT i.instrument, t.timeframe
FROM
    (VALUES ('NQ'), ('ES'), ('YM'), ('RTY')) AS i(instrument),
    (VALUES ('1m'), ('5m'), ('15m'), ('1h'), ('4h'), ('1d'), ('1w')) AS t(timeframe)
ON CONFLICT DO NOTHING;
