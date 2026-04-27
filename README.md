# Quant Futures — CME Index Futures Analytics Platform

[![CI](https://github.com/sam9407287/quant/actions/workflows/ci.yml/badge.svg)](https://github.com/sam9407287/quant/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com/)
[![TimescaleDB](https://img.shields.io/badge/TimescaleDB-PostgreSQL-orange.svg)](https://www.timescale.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A production-grade quantitative analysis platform for CME index futures (NQ, ES, YM, RTY), built with a phased architecture that scales from historical data collection through signal research to live automated trading.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                         Railway Platform                          │
│                                                                   │
│  ┌────────────────┐                                               │
│  │  Frontend      │   public HTTPS                                │
│  │  (Next.js 14)  │ ─────────────────┐                            │
│  │  /, /coverage, │                  │                            │
│  │  /chart        │                  ▼                            │
│  └────────────────┘        ┌───────────────┐  ┌───────────────┐   │
│                            │  API Service  │  │   Fetcher     │   │
│                            │  (FastAPI)    │  │  (APScheduler)│   │
│                            │  REST + WS    │  │  Daily 00:00Z │   │
│                            │  OpenAPI docs │  │  yfinance →   │   │
│                            └───────┬───────┘  └───────┬───────┘   │
│                                    │                  │           │
│                                    └────────┬─────────┘           │
│                                             │ railway.internal    │
│                              ┌──────────────▼──────────────┐      │
│                              │  TimescaleDB Service        │      │
│                              │  (timescale/timescaledb)    │      │
│                              │  ─ kbars_1m (hypertable)    │      │
│                              │  ─ Continuous Aggregates    │      │
│                              │    → 5m/15m/1h/4h/1d/1w     │      │
│                              │  ─ Persistent volume        │      │
│                              └─────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────┘
```

**Core principle:** Only 1-minute bars are stored as raw data. All higher timeframes are derived automatically via TimescaleDB Continuous Aggregates — ensuring perpetual consistency across all timeframes.

---

## Instruments

| Symbol | Full Name | Exchange | yfinance Ticker |
|--------|-----------|----------|-----------------|
| NQ | E-mini Nasdaq-100 | CME | `NQ=F` |
| ES | E-mini S&P 500 | CME | `ES=F` |
| YM | E-mini Dow Jones | CBOT | `YM=F` |
| RTY | E-mini Russell 2000 | CME | `RTY=F` |

---

## Multi-Timeframe Analysis Design

```
Weekly / Daily  →  Market regime (trend / range / risk-off)
4H / 1H         →  Primary trend direction + key structure levels
15m / 5m        →  Signal trigger (entry pattern confirmation)
1m              →  Precise entry / exit execution
```

---

## Development Phases

| Phase | Status | Description |
|-------|--------|-------------|
| **Period 1** | 🚧 In Progress | Data collection: historical ingestion + daily auto-update |
| **Period 2** | 📋 Planned | Strategy research: signal development + backtesting |
| **Period 3** | 📋 Planned | Live trading: IBKR real-time feed + automated order execution |
| **Frontend** | 🌱 Seeded | Next.js dashboard for browsing ingested data ([`frontend/`](frontend/)) |

---

## Tech Stack

| Layer | Technology | Reason |
|-------|-----------|--------|
| API | FastAPI (Python 3.12) | Async-native, auto OpenAPI docs, type-safe |
| Database | PostgreSQL + TimescaleDB | Time-series hypertables, Continuous Aggregates for OHLCV rollup |
| Scheduler | APScheduler | Lightweight in-process cron, no external dependency |
| Historical Data | FirstRate Data (CSV, one-time) | 18 years of clean 1m futures data |
| Daily Updates | yfinance | Free, reliable, CME-sourced prices |
| Backtesting | VectorBT (Period 2) | Vectorized engine, millions of bars in seconds |
| Indicators | pandas-ta | 90+ indicators, pure Python |
| Broker API | ib_insync / IBKR TWS (Period 3) | Official async Python wrapper for IBKR |
| Deployment | Railway Pro | API + Fetcher + self-hosted TimescaleDB Docker services |
| CI/CD | GitHub Actions | Lint → test → Docker build on every PR |

---

## Project Structure

```
quant-futures/
├── app/                        # FastAPI service
│   ├── api/
│   │   ├── kbars.py            # GET /api/v1/kbars
│   │   ├── coverage.py         # GET /api/v1/coverage
│   │   └── roll_calendar.py    # GET /api/v1/roll-calendar
│   ├── core/
│   │   ├── config.py           # Pydantic settings
│   │   └── adjustment.py       # Ratio / Absolute price adjustment
│   ├── db/
│   │   └── session.py          # Async SQLAlchemy session
│   └── main.py
│
├── fetcher/                    # Data ingestion worker
│   ├── sources/
│   │   ├── base.py             # DataSource ABC
│   │   └── yfinance_source.py
│   ├── pipeline.py             # Dedup + upsert logic
│   ├── roll_detector.py        # Contract roll detection
│   ├── scheduler.py            # APScheduler jobs
│   └── main.py
│
├── db/
│   ├── schema.sql              # Full DDL incl. TimescaleDB setup
│   └── seed_roll_calendar.sql  # Roll dates 2008–2030
│
├── scripts/
│   ├── bootstrap_csv.py        # One-time: import FirstRate Data CSV
│   └── verify_coverage.py      # Gap detection + coverage report
│
├── tests/
│   ├── test_pipeline.py
│   ├── test_adjustment.py
│   └── test_api.py
│
├── docs/
│   ├── SPEC.md                 # Functional requirements & API spec
│   └── SYSTEM_DESIGN.md        # Architecture & DB schema design
│
├── .github/workflows/ci.yml    # GitHub Actions CI pipeline
├── docker-compose.yml          # Local development environment
├── Dockerfile                  # API service image
├── Dockerfile.fetcher          # Fetcher worker image
├── pyproject.toml              # Ruff + mypy + pytest config
├── .env.example                # Environment variable template
└── CLAUDE.md                   # AI assistant context
```

---

## Getting Started

### Prerequisites

- Docker & Docker Compose
- Python 3.12+
- Git

### Local Development

```bash
# 1. Clone the repository
git clone https://github.com/sam9407287/quant.git
cd quant

# 2. Set up environment variables
cp .env.example .env
# Edit .env with your values

# 3. Start local infrastructure (TimescaleDB)
docker-compose up -d db

# 4. Apply database schema
docker-compose exec db psql -U dev -d quant_futures -f /docker-entrypoint-initdb.d/schema.sql

# 5. Install Python dependencies
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# 6. Run the API
uvicorn app.main:app --reload

# 7. Run the fetcher (manual trigger)
python fetcher/main.py --once
```

API docs available at: `http://localhost:8000/docs`

### Seed Historical Data

```bash
# After purchasing FirstRate Data CSVs, place them in data/firstrate/
python scripts/bootstrap_csv.py --data-dir data/firstrate/

# Verify data coverage
python scripts/verify_coverage.py
```

---

## API Reference

### `GET /api/v1/kbars`

Query OHLCV bars for any supported timeframe.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `instrument` | `NQ\|ES\|YM\|RTY` | required | Futures symbol |
| `timeframe` | `1m\|5m\|15m\|1h\|4h\|1d\|1w` | `1h` | Bar timeframe |
| `start` | ISO 8601 datetime | required | Range start (UTC) |
| `end` | ISO 8601 datetime | required | Range end (UTC) |
| `adjustment` | `raw\|ratio\|absolute` | `ratio` | Price adjustment method |

```bash
curl "http://localhost:8000/api/v1/kbars?instrument=NQ&timeframe=1h&start=2024-01-01T00:00:00Z&end=2024-01-31T23:59:59Z&adjustment=ratio"
```

### `GET /api/v1/coverage`

Check data availability and detect gaps.

```bash
curl "http://localhost:8000/api/v1/coverage?instrument=all"
```

---

## Deployment

This project is deployed on [Railway](https://railway.app) as four services
in a single project, all configured via `railway.toml`:

| Service | Build | Description |
|---------|-------|-------------|
| `timescaledb` | `db/Dockerfile` | PostgreSQL 16 + TimescaleDB extension. Schema and seed are baked into the image and applied on first boot. A persistent volume must be attached to `/var/lib/postgresql/data` via the Railway dashboard. |
| `api` | `Dockerfile` | FastAPI REST server. |
| `fetcher` | `Dockerfile.fetcher` | Daily data ingestion worker. |
| `frontend` | `frontend/Dockerfile` | Next.js 14 dashboard. Multi-stage build with `output: "standalone"`; runs as non-root, exposes port 3000. |

The API and fetcher reach the database over Railway's private network at
`timescaledb.railway.internal:5432`, so the database is not exposed
publicly. The frontend talks to the API over the public URL because requests
originate in the user's browser; both server-side (App Router) and
client-side fetches share the same `NEXT_PUBLIC_API_URL`.

Connection strings, instrument lists, and webhook URLs are all provided via
Railway environment variables (see `.env.example` for the full list). When
the frontend's public URL is generated, it must also be added to the API
service's `CORS_ORIGINS` env var.

See [ADR-001](docs/SYSTEM_DESIGN.md#adr-001-self-hosted-timescaledb-on-railway-not-railways-pg-plugin-not-timescale-cloud)
for why this self-hosted topology was chosen over Railway's PostgreSQL
plugin (no `timescaledb` extension) and over a managed Timescale Cloud
instance (cost and cross-region latency).

---

## Security Considerations

- All secrets managed via environment variables (never committed)
- CORS origins explicitly configured via `CORS_ORIGINS` env var
- API rate limiting applied at the proxy layer
- Database credentials rotated via Railway's secret management
- No raw market data files committed to the repository

---

## Roadmap

- [x] System design & documentation
- [ ] **Period 1:** TimescaleDB schema + bootstrap script
- [ ] **Period 1:** Daily auto-fetch with gap detection
- [ ] **Period 1:** REST API for kbars & coverage
- [ ] **Period 1:** Railway deployment
- [ ] **Period 2:** Technical indicators API
- [ ] **Period 2:** Signal engine (multi-timeframe top-down)
- [ ] **Period 2:** Backtesting engine (VectorBT integration)
- [ ] **Period 3:** IBKR real-time data feed
- [ ] **Period 3:** Automated order execution
- [ ] **Frontend:** React/Next.js charting dashboard (TradingView Lightweight Charts)

---

## License

MIT © 2025 sam9407287
