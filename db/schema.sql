-- =============================================================
-- Quant Futures — PostgreSQL Schema (no TimescaleDB required)
-- TimescaleDB can be added later when data volume demands it.
-- =============================================================

-- =============================================================
-- 1m raw OHLCV bars — single source of truth
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

-- Fast lookups by instrument + time range
CREATE INDEX IF NOT EXISTS idx_kbars_1m_lookup
    ON kbars_1m (instrument, ts DESC);

-- =============================================================
-- Higher timeframes — pre-aggregated for fast API reads
-- Refreshed by the fetcher after each daily ingest.
-- =============================================================
CREATE TABLE IF NOT EXISTS kbars_5m  (LIKE kbars_1m INCLUDING ALL);
CREATE TABLE IF NOT EXISTS kbars_15m (LIKE kbars_1m INCLUDING ALL);
CREATE TABLE IF NOT EXISTS kbars_1h  (LIKE kbars_1m INCLUDING ALL);
CREATE TABLE IF NOT EXISTS kbars_4h  (LIKE kbars_1m INCLUDING ALL);
CREATE TABLE IF NOT EXISTS kbars_1d  (LIKE kbars_1m INCLUDING ALL);
CREATE TABLE IF NOT EXISTS kbars_1w  (LIKE kbars_1m INCLUDING ALL);

CREATE INDEX IF NOT EXISTS idx_kbars_5m_lookup  ON kbars_5m  (instrument, ts DESC);
CREATE INDEX IF NOT EXISTS idx_kbars_15m_lookup ON kbars_15m (instrument, ts DESC);
CREATE INDEX IF NOT EXISTS idx_kbars_1h_lookup  ON kbars_1h  (instrument, ts DESC);
CREATE INDEX IF NOT EXISTS idx_kbars_4h_lookup  ON kbars_4h  (instrument, ts DESC);
CREATE INDEX IF NOT EXISTS idx_kbars_1d_lookup  ON kbars_1d  (instrument, ts DESC);
CREATE INDEX IF NOT EXISTS idx_kbars_1w_lookup  ON kbars_1w  (instrument, ts DESC);

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

-- Seed initial coverage rows
INSERT INTO data_coverage (instrument, timeframe)
SELECT i.instrument, t.timeframe
FROM
    (VALUES ('NQ'), ('ES'), ('YM'), ('RTY')) AS i(instrument),
    (VALUES ('1m'), ('5m'), ('15m'), ('1h'), ('4h'), ('1d'), ('1w')) AS t(timeframe)
ON CONFLICT DO NOTHING;
