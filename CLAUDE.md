# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Production-grade quantitative analytics platform for CME index futures (NQ, ES, YM, RTY).
Built as a portfolio project targeting senior/staff engineer standards at top-tier companies.

See `docs/SPEC.md` for functional requirements and `docs/SYSTEM_DESIGN.md` for architecture details.

## Development Phases

- **Period 1 (current):** Data collection — TimescaleDB + daily auto-fetch
- **Period 2:** Strategy research — signals + backtesting
- **Period 3:** Live trading — IBKR real-time + automated orders
- **Frontend (parallel):** React/Next.js charting dashboard

## Code Standards (Portfolio / Interview Quality)

### General
- All commits and code comments in **English**
- Commits follow **Conventional Commits**: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`
- No commented-out code, no TODOs left in merged code
- Every public function/class has a one-line docstring explaining *why*, not *what*

### Python
- Python **3.12**, strict type hints everywhere (`from __future__ import annotations`)
- Lint: `ruff check .` — must pass clean
- Type check: `mypy app/ fetcher/` — strict mode, must pass clean
- Tests: `pytest` with `pytest-asyncio`, minimum coverage on core logic
- Use `pydantic` for all data validation and settings
- Use `sqlalchemy[asyncio]` with async sessions — no sync DB calls in async context
- Prefer `pathlib.Path` over `os.path`

### API Design
- Versioned endpoints: `/api/v1/...`
- All responses typed with Pydantic response models
- HTTP status codes used correctly (200, 201, 400, 404, 422, 500)
- CORS configured explicitly, not wildcard in production
- OpenAPI tags and descriptions on all routes

### Security
- Secrets only via environment variables — never hardcoded
- Validate and sanitize all query parameters (use Pydantic + FastAPI Query)
- SQL via SQLAlchemy ORM only — no raw f-string queries
- `.env` is in `.gitignore` — always use `.env.example` as template

### Testing
- Unit tests for: adjustment logic, dedup/upsert pipeline, roll detection
- Integration tests for: API endpoints (use `httpx.AsyncClient`)
- No real network calls in tests — mock `yfinance` responses

## Architecture Decisions (settled — do not re-discuss)

| Decision | Choice | Reason |
|----------|--------|--------|
| Raw storage unit | 1m Unadjusted K-bars only | Single source of truth; all TFs derived |
| Higher timeframes | TimescaleDB Continuous Aggregates | Auto-consistent, no manual sync |
| Price adjustment | Applied at query time (not stored) | Raw data is always recoverable |
| Roll handling | `roll_calendar` table + Ratio Adjustment | Best for technical analysis |
| Historical source | FirstRate Data CSV (Unadjusted) | 18 years, one-time purchase |
| Daily updates | yfinance with 7-day overlap | Free, dedup prevents double-writes |
| Deployment | Railway Pro (API + Fetcher services) | Managed infra, PostgreSQL plugin |

## Key Data Facts

- Futures trading hours (CME Globex): Sun 18:00 – Fri 17:00 ET; daily break 17:00–18:00 ET
- Roll schedule: 3rd Friday of Mar / Jun / Sep / Dec (volume migrates ~2 weeks before expiry)
- Contract naming: `NQH25` = NQ March 2025; months H=Mar M=Jun U=Sep Z=Dec
- yfinance known issue: occasional 1–2 day gaps in futures data (GitHub #2635); mitigated by overlap fetch

## CI/CD

GitHub Actions at `.github/workflows/ci.yml` runs on every push/PR:
1. `ruff check` — linting
2. `mypy` — type checking
3. `pytest` — unit + integration tests (with ephemeral TimescaleDB service)
4. Docker build check for both images

All checks must pass before merging to `main`.

## Future Frontend (React/Next.js)

The FastAPI backend is designed to support a charting dashboard:
- CORS configured via `CORS_ORIGINS` env var
- `/api/v1/kbars` returns paginated JSON ready for TradingView Lightweight Charts
- WebSocket endpoint planned for Period 3 real-time feed (`/ws/v1/stream/{instrument}`)
- Keep response shapes stable — treat the API contract as public once frontend exists

## Commands

```bash
# Start local dev environment
docker-compose up -d db
uvicorn app.main:app --reload

# Lint + type check
ruff check . && mypy app/ fetcher/

# Tests
pytest -v

# One-time data bootstrap (after purchasing FirstRate Data)
python scripts/bootstrap_csv.py --data-dir data/firstrate/

# Check data gaps
python scripts/verify_coverage.py

# Trigger daily fetch manually
python fetcher/main.py --once
```
