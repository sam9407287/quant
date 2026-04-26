# System Design

## 1. Architecture

### Period 1 — Data Collection

```
┌────────────────────────────────────────────────────────┐
│                     Railway Platform                    │
│                                                         │
│  ┌──────────────────┐     ┌─────────────────────────┐  │
│  │   API Service    │     │    Fetcher Service      │  │
│  │   (FastAPI)      │     │  (APScheduler Worker)   │  │
│  │                  │     │                         │  │
│  │  REST /api/v1/*  │     │  Weekdays 18:00 UTC     │  │
│  │  Auto OpenAPI    │     │  yfinance → TimescaleDB │  │
│  └────────┬─────────┘     └────────────┬────────────┘  │
│           │                            │                │
│           └──────────────┬─────────────┘                │
│                          │                              │
│             ┌────────────▼─────────────┐                │
│             │       TimescaleDB        │                │
│             │  kbars_1m  (hypertable)  │                │
│             │  roll_calendar           │                │
│             │  data_coverage           │                │
│             │  ── Continuous Aggregates──               │
│             │  kbars_5m / 15m / 1h     │                │
│             │  kbars_4h / 1d / 1w      │                │
│             └──────────────────────────┘                │
└────────────────────────────────────────────────────────┘
```

### Period 3 — Live Trading (additive to Period 1 infra)

```
Added services:
  ┌──────────────────────────────────┐
  │     Real-time Engine Service     │
  │   (ib_insync + asyncio)          │
  │                                  │
  │  1m bar → Redis Pub/Sub          │
  │  Signal engine subscribes        │
  │  Signals → Order executor        │
  │  Orders → IBKR TWS API           │
  └──────────────┬───────────────────┘
                 │ TCP socket
  ┌──────────────▼───────────────────┐
  │  IB Gateway (Docker, VPS)        │
  └──────────────────────────────────┘
                 │
        [IBKR Broker Servers]
```

---

## 2. Database Design

### Core Principle

Only `kbars_1m` is written to directly. All other timeframes are computed automatically via TimescaleDB Continuous Aggregates and are always consistent with the source data.

### Schema

```sql
-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ─────────────────────────────────────────
-- Primary table: raw 1m bars
-- ─────────────────────────────────────────
CREATE TABLE kbars_1m (
    instrument  TEXT           NOT NULL,  -- 'NQ', 'ES', 'YM', 'RTY'
    ts          TIMESTAMPTZ    NOT NULL,  -- UTC
    open        NUMERIC(12, 4) NOT NULL,
    high        NUMERIC(12, 4) NOT NULL,
    low         NUMERIC(12, 4) NOT NULL,
    close       NUMERIC(12, 4) NOT NULL,
    volume      BIGINT         NOT NULL,
    source      TEXT           NOT NULL   -- 'firstrate' | 'yfinance' | 'ibkr'
);

SELECT create_hypertable('kbars_1m', 'ts', chunk_time_interval => INTERVAL '1 week');

-- Deduplication guard — silently ignore duplicate inserts
CREATE UNIQUE INDEX uix_kbars_1m ON kbars_1m (instrument, ts);

-- Query performance index
CREATE INDEX idx_kbars_1m_lookup ON kbars_1m (instrument, ts DESC);

-- ─────────────────────────────────────────
-- Derived timeframes (auto-managed by TimescaleDB)
-- ─────────────────────────────────────────
CREATE MATERIALIZED VIEW kbars_5m
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
GROUP BY 1, 2;

-- Repeat for 15m, 1h, 4h, 1d, 1w with respective bucket widths

-- Refresh policy: keep last 2 days up to date, check hourly
SELECT add_continuous_aggregate_policy('kbars_5m',
    start_offset    => INTERVAL '2 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');

-- ─────────────────────────────────────────
-- Contract roll calendar
-- ─────────────────────────────────────────
CREATE TABLE roll_calendar (
    id            SERIAL PRIMARY KEY,
    instrument    TEXT           NOT NULL,
    old_contract  TEXT           NOT NULL,  -- e.g. 'NQH25'
    new_contract  TEXT           NOT NULL,  -- e.g. 'NQM25'
    roll_date     DATE           NOT NULL,
    roll_ts       TIMESTAMPTZ,              -- midnight ET on roll date
    price_diff    NUMERIC(12, 4),           -- new_open - old_close (absolute adjust)
    price_ratio   NUMERIC(10, 8),           -- new_open / old_close (ratio adjust)
    created_at    TIMESTAMPTZ    DEFAULT NOW()
);

CREATE UNIQUE INDEX uix_roll_calendar ON roll_calendar (instrument, roll_date);

-- ─────────────────────────────────────────
-- Data coverage tracking
-- ─────────────────────────────────────────
CREATE TABLE data_coverage (
    instrument      TEXT        NOT NULL,
    timeframe       TEXT        NOT NULL,  -- '1m', '5m', '1h', etc.
    earliest_ts     TIMESTAMPTZ,
    latest_ts       TIMESTAMPTZ,
    bar_count       BIGINT      DEFAULT 0,
    gap_count       INT         DEFAULT 0,
    last_fetch_ts   TIMESTAMPTZ,
    last_fetch_ok   BOOLEAN     DEFAULT TRUE,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (instrument, timeframe)
);
```

---

## 3. Contract Roll Handling

### Roll Schedule (CME Standard)

```
NQ, ES, RTY, YM roll quarterly: 3rd Friday of Mar / Jun / Sep / Dec
Volume migrates to the new contract approximately 2 weeks before expiry.
FirstRate Data rolls at midnight ET when volume crosses over.

2025 roll dates:
  2025-03-13  (Mar → Jun contract)
  2025-06-12  (Jun → Sep contract)
  2025-09-11  (Sep → Dec contract)
  2025-12-11  (Dec → Mar 2026 contract)
```

### Contract Code Conventions

```
Format: [Symbol][Month][2-digit year]
Month codes:  H = Mar   M = Jun   U = Sep   Z = Dec

Examples:
  NQH25  = NQ March 2025
  ESM25  = ES June 2025
  YMU25  = YM September 2025
  RTYZ25 = RTY December 2025
```

### Price Adjustment at Query Time

```
Raw storage: unadjusted prices (real traded values, price gaps visible at rolls)

Ratio Adjustment (default, recommended for technical analysis):
  For each roll event after query start date:
    ratio = new_contract_open / old_contract_close
  Apply cumulative product of all ratios to all bars before each respective roll.
  Result: percentage moves are preserved; absolute levels shift.

Absolute Adjustment:
  For each roll: diff = new_contract_open - old_contract_close
  Apply cumulative sum to all bars before each respective roll.
  Result: dollar moves are preserved; can produce negative prices for old data.
```

---

## 4. Data Ingestion Design

### Daily Fetch Flow (Fetcher Service)

```
Trigger: weekdays at 18:00 UTC (APScheduler cron)

For each instrument in [NQ, ES, YM, RTY]:
  1. Fetch last 7 days of 1m bars from yfinance (7-day overlap)
  2. Upsert into kbars_1m (ON CONFLICT DO NOTHING — dedup is free)
  3. Detect roll: compare volume between old and new front-month contract
     → If roll detected: insert into roll_calendar, compute price_diff / price_ratio
  4. Refresh data_coverage row for this instrument
  5. Emit structured log: {instrument, fetched, inserted, skipped, roll_detected}
```

### One-Time Bootstrap Flow

```
scripts/bootstrap_csv.py:

1. Decompress FirstRate Data ZIP (Unadjusted version)
2. Parse CSV: DateTime (EST), Open, High, Low, Close, Volume
3. Convert timestamps to UTC
4. Batch upsert into kbars_1m in chunks of 10,000 rows
5. Run verify_coverage.py on completion

Time zone note: FirstRate uses EST — convert with pytz or zoneinfo before insert.
```

### Gap Detection Logic

```python
# Valid trading windows (ET):
#   Weekdays: 18:00 previous day → 17:00 current day
#   Exclude:  17:00–18:00 daily settlement break
#   Exclude:  Saturday, Sunday
#   Exclude:  US federal holidays (use pandas_market_calendars)

# A "gap" is defined as 2+ consecutive missing 1m bars within a valid window.
# Output: list of (gap_start, gap_end, missing_bar_count) tuples
```

---

## 5. Project Structure

```
quant-futures/
├── app/                         # FastAPI service
│   ├── api/
│   │   ├── kbars.py             # GET /api/v1/kbars
│   │   ├── coverage.py          # GET /api/v1/coverage[/gaps]
│   │   └── roll_calendar.py     # GET /api/v1/roll-calendar
│   ├── core/
│   │   ├── config.py            # Pydantic BaseSettings
│   │   └── adjustment.py        # Ratio / absolute price adjustment logic
│   ├── db/
│   │   └── session.py           # Async SQLAlchemy engine + session factory
│   └── main.py                  # FastAPI app, middleware, lifespan
│
├── fetcher/                     # Worker service
│   ├── sources/
│   │   ├── base.py              # DataSource ABC
│   │   └── yfinance_source.py   # yfinance implementation
│   ├── pipeline.py              # Clean, validate, upsert
│   ├── roll_detector.py         # Contract roll detection
│   ├── scheduler.py             # APScheduler job definitions
│   └── main.py                  # Worker entry point
│
├── db/
│   ├── schema.sql               # Full DDL including TimescaleDB setup
│   └── seed_roll_calendar.sql   # Pre-filled roll dates 2008–2030
│
├── scripts/
│   ├── bootstrap_csv.py         # One-time: import FirstRate Data CSVs
│   └── verify_coverage.py       # Gap detection + coverage report
│
├── tests/
│   ├── conftest.py              # Async DB fixtures
│   ├── test_pipeline.py         # Dedup, upsert logic
│   ├── test_adjustment.py       # Roll adjustment calculations
│   └── test_api.py              # API endpoint integration tests
│
├── docs/
│   ├── SPEC.md                  # Functional requirements & API spec
│   └── SYSTEM_DESIGN.md         # This file
│
├── .github/
│   └── workflows/ci.yml         # GitHub Actions: lint → typecheck → test → docker
│
├── .env.example                 # All env vars documented, no real values
├── docker-compose.yml           # Local dev: TimescaleDB + API + Fetcher
├── Dockerfile                   # API service image
├── Dockerfile.fetcher           # Fetcher worker image
├── pyproject.toml               # ruff + mypy + pytest config
└── CLAUDE.md                    # AI assistant context
```

---

## 6. Environment Variables

```bash
# Database (Railway injects automatically in production)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/quant_futures

# Fetcher
FETCH_INSTRUMENTS=NQ,ES,YM,RTY
FETCH_OVERLAP_DAYS=7
FETCH_CRON=0 18 * * 1-5          # weekdays 18:00 UTC

# API
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:3000  # comma-separated in production

# Security
API_SECRET_KEY=<openssl rand -hex 32>

# Period 3 (not needed yet)
# IBKR_HOST=
# IBKR_PORT=4003
# IBKR_CLIENT_ID=1
```

---

## 7. Deployment

### Railway Services

| Service | Dockerfile | Role |
|---------|-----------|------|
| `api` | `Dockerfile` | FastAPI REST server |
| `fetcher` | `Dockerfile.fetcher` | Daily data ingestion worker |

Railway's PostgreSQL plugin is used with the TimescaleDB extension enabled post-provision.

### Docker Images

```dockerfile
# Shared base pattern (both services)
FROM python:3.12-slim
RUN addgroup --system app && adduser --system --group app   # non-root user
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER app
```

### Local Development

```yaml
# docker-compose.yml (key services)
services:
  db:
    image: timescale/timescaledb:latest-pg16
    ports: ["5432:5432"]
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/schema.sql:/docker-entrypoint-initdb.d/01_schema.sql
      - ./db/seed_roll_calendar.sql:/docker-entrypoint-initdb.d/02_seed.sql

  api:
    build: { dockerfile: Dockerfile }
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [db]

  fetcher:
    build: { dockerfile: Dockerfile.fetcher }
    env_file: .env
    depends_on: [db]
```

---

## 8. Tech Stack Rationale

| Technology | Reason |
|-----------|--------|
| TimescaleDB | Native time-series hypertables; Continuous Aggregates eliminate manual OHLCV rollup |
| FastAPI | Async-native; auto OpenAPI docs; excellent Pydantic integration |
| APScheduler | Zero extra infrastructure (no Redis/Celery needed for a single-worker cron) |
| yfinance | Free; CME-sourced; adequate for T+0 daily ingestion |
| VectorBT (Period 2) | Vectorized backtester; millions of bars in seconds |
| pandas-ta | 90+ indicators; pure Python; no compilation |
| ib_insync (Period 3) | Async wrapper for IBKR TWS API; production-proven |
| Railway Pro | Managed compute + PostgreSQL; zero-ops for a solo project |
| GitHub Actions | First-class CI for open-source; free for public repos |

---

## 9. Period 1 Development Milestones

```
Week 1: Infrastructure
  □ docker-compose with TimescaleDB running locally
  □ db/schema.sql applied and verified
  □ db/seed_roll_calendar.sql populated (2008–2030)

Week 2: Data Bootstrap
  □ scripts/bootstrap_csv.py complete
  □ FirstRate Data imported, bar counts verified
  □ scripts/verify_coverage.py passing (< 0.1% gaps)

Week 3: Daily Automation
  □ fetcher/ service complete with roll detection
  □ Manual trigger test passes end-to-end
  □ APScheduler cron confirmed running in Docker

Week 4: API + Deployment
  □ app/ FastAPI with /kbars, /coverage, /roll-calendar
  □ All CI checks passing on GitHub Actions
  □ Deployed to Railway; daily fetch confirmed in production logs

Definition of Done for Period 1:
  □ All four instruments have data from 2008-01-02 to present
  □ Two consecutive weeks of automated daily fetches with zero failures
  □ Coverage API shows gap_count = 0 for all instruments
```

---

## 10. Architecture Decision Records (ADR)

### ADR-001: TimescaleDB on Timescale Cloud, not on Railway PostgreSQL plugin

**Status:** Accepted (supersedes the brief excursion through plain PostgreSQL)

**Context.** This system stores OHLCV bars: append-mostly, time-ordered, queried
exclusively by time range. Two characteristics dominate:

1. The 1m hypertable will accumulate ~50M rows per instrument over 18 years
   (200M+ across all four). On vanilla PostgreSQL, B-tree index maintenance
   and full-table aggregation become a real cost.
2. Six higher timeframes (5m / 15m / 1h / 4h / 1d / 1w) must always stay
   consistent with the 1m source. Hand-rolling this either means daily full
   recomputation (slow) or hand-written incremental sync (fragile).

Both problems are exactly what TimescaleDB hypertables and Continuous
Aggregates solve. Hypertables auto-partition by time so writes stay flat in
cost; CAs maintain the higher-timeframe rollups incrementally and query like
ordinary views.

**The detour.** An earlier iteration migrated to plain PostgreSQL because
Railway's managed PostgreSQL plugin does not include the `timescaledb`
extension (commit `8ae8873`). The pipeline grew a hand-written
`aggregate_higher_timeframes()` function — a 50-line `INSERT ... SELECT
GROUP BY date_trunc()` block per timeframe, run on every fetch. This worked
but had three problems:

* It rebuilds aggregates from scratch each run; cost grows linearly with
  history size, not with new data.
* Sub-hour buckets (5m / 15m / 4h) needed `EXTRACT(EPOCH ...)` arithmetic
  because PostgreSQL `date_trunc` only takes named units.
* The implementation is essentially an inferior reimplementation of CAs.

**Decision.** Move PostgreSQL to **Timescale Cloud** (managed) and connect
both Railway services to it via `DATABASE_URL`. Use:

* `kbars_1m` as a hypertable, 7-day chunks
* Six Continuous Aggregates with hourly refresh policies
* Compression policy on chunks older than 30 days (segmentby instrument)

The fetcher loses `aggregate_higher_timeframes()`. A new, much smaller
`refresh_continuous_aggregates()` calls `refresh_continuous_aggregate(view,
start, end)` once per CA after each daily fetch — this is just a
"force-fresh-now" call; the policy keeps things current between fetches.

**Why managed (Timescale Cloud) and not self-hosted on Railway.**
Self-hosting TSDB as a Docker service on Railway is feasible but adds
operational surface area (volume backups, version upgrades, security
patches) for no compounding benefit. Splitting compute (Railway) and DB
(Timescale Cloud) also matches the canonical AWS RDS + ECS / GCP Cloud
SQL + Cloud Run pattern, which is the reference architecture that
production-grade systems converge on.

**Consequences.**

* Schema is more declarative: 6 `CREATE MATERIALIZED VIEW ... WITH
  (timescaledb.continuous)` statements replace the entire manual aggregation
  module.
* `app/api/kbars.py` is unchanged — CAs are queried as ordinary views.
* CI test job switched from `postgres:16` to `timescale/timescaledb:latest-pg16`.
* `docker-compose` for local dev was already on the timescale image, so no
  workflow change for developers.
* Costs: free tier of Timescale Cloud is sufficient through Period 1; an
  upgrade is a Period 2 concern when historical bootstrap lands.

**Trade-offs accepted.**

* Two cloud accounts to manage instead of one.
* Cross-region latency between Railway (asia-southeast1) and Timescale
  Cloud must be sized when picking the TSDB region — keep them in the same
  region or geographically close.
* `CALL refresh_continuous_aggregate(...)` cannot run inside a transaction,
  so the fetcher opens a dedicated AUTOCOMMIT connection. This is a known
  TSDB constraint, documented inline.

**Reversibility.** The schema and pipeline could be reverted to the manual
aggregation model in a single revert commit if Timescale Cloud became
unavailable; the API layer (`/api/v1/kbars`) makes no assumption that
higher-timeframe sources are CAs versus tables.

