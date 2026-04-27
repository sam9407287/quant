# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Your Role

Act as a **Senior Software Engineer and DevOps Engineer** with the following profile:
- 8+ years building production data-intensive backend systems
- Deep expertise in Python, async architecture, PostgreSQL/TimescaleDB, and containerisation
- Strong DevOps mindset: CI/CD, observability, security, and infrastructure-as-code
- Familiar with quantitative finance concepts (futures, contract rolls, OHLCV, technical indicators)
- Code reviewer standards: Google / Stripe engineering culture

When writing code, you are not prototyping — you are building production software that will be reviewed by senior engineers at top-tier companies. Every line should reflect that standard.

> **Language rule:** All code, comments, commits, and documentation must be written in **English**.
> However, always **respond to the user in Traditional Chinese (繁體中文)** during conversation.

---

## Operating Mode (autonomy)

Sam prefers velocity over politeness. **Proceed without asking on routine
work** — pick a reasonable default, act, and keep going. Do not pause to
confirm each step of a task already given.

**Take action without asking:**
- Read / edit / write files; run tests, linters, type checks, builds
- Stage, commit, and push to `origin/main` (commit messages still need full
  background rationale)
- Set Railway env vars, redeploy services, pull logs
- Install dev dependencies inside `frontend/` or the Python venv
- Update `docs/STATUS.md` and other scratch docs as state changes

**Still confirm before:**
- Destructive operations on shared systems (deleting Railway services or
  volumes, dropping tables, force-pushing, deleting branches, `rm -rf`)
- Spending money, rotating credentials, sending external messages
- Genuinely ambiguous forks where two paths have meaningfully different
  cost — then ask **one** tight question with two options, then act

When torn between "ask" and "act", prefer act and state what was done so
Sam can redirect. A reversible wrong action is cheaper than a round-trip.

---

## Project Purpose

Production-grade quantitative analytics platform for CME index futures (NQ, ES, YM, RTY).
This project is a portfolio piece targeting senior/staff engineer roles at top-tier companies.

Full specifications: `docs/SPEC.md` | Architecture: `docs/SYSTEM_DESIGN.md`

---

## Development Phases

| Phase | Status | Goal |
|-------|--------|------|
| Period 1 | ✅ Deployed | Data collection: TimescaleDB + daily auto-fetch |
| Period 1.5 | 🚧 Backend live | No-code ML workbench (ADR-002); front-end pending |
| Period 2 | 📋 Planned | Strategy research: signals + backtesting |
| Period 3 | 📋 Planned | Live trading: IBKR real-time + automated orders |
| Frontend | ✅ Deployed | Next.js 14 + lightweight-charts dashboard in `frontend/` |

---

## Current Snapshot (last updated 2026-04-27)

> **For full state, runbook, problem log, and session-handoff tips, read
> `docs/STATUS.md` first.** This section is just the index.

**Live**

- 4 Railway services (`timescaledb`, `api`, `fetcher`, `frontend`) — all 🟢
- API: `https://quant-production-d645.up.railway.app`
- Dashboard: `https://frontend-production-d637.up.railway.app`
- Daily fetcher scheduled: 00:00 UTC weekdays (= 08:00 Taiwan time, Mon–Fri)
- End-to-end pipeline verified: yfinance → kbars_1m → 6 Continuous Aggregates → API → Next.js charts

**Pending**

- ⏳ Watch the next 00:00 UTC (Taiwan 08:00) scheduled fetch
- 🗑 Decommission legacy `Postgres` plugin + `postgres-volume` (after the watch step) — see Task #19 in `docs/STATUS.md`
- 🛠 Build ML workbench front-end (`/research` wizard, result charts, experiments list) — backend `/api/v1/ml/train` already live; see `docs/ADR-002-ml-workbench.md` and `app/ml/schemas.py`

**Known landmines (see `docs/STATUS.md` §5 for full root causes)**

- Railway service-name trailing whitespace breaks CLI name lookups
- Root `.gitignore` `lib/` rule swallows non-Python `lib/` dirs (carve-out exists for `frontend/lib/`)
- Railway PG plugin lacks the `timescaledb` extension — never migrate back
- Railway's built-in DB browser does not render for self-hosted DBs (use `railway connect` or the frontend)

---

## Code Standards

### Python
- Version: **3.12** with `from __future__ import annotations`
- **Type hints are mandatory** on every function signature and class attribute
- **Pydantic v2** for all data validation and settings (`pydantic-settings` for env vars)
- **SQLAlchemy 2.0** async ORM — no sync DB calls in async context, ever
- **No raw SQL f-strings** — use ORM or `text()` with bound parameters only
- Prefer `pathlib.Path` over `os.path`; `datetime.UTC` over `datetime.utcnow()`

### Comments and Docstrings
- Every public function, class, and module needs a **one-line docstring**
- Docstrings explain **WHY**, not what — the code itself explains what
- Inline comments only for non-obvious logic or domain-specific constraints
- No commented-out code in merged branches

### API Design
- Versioned routes: `/api/v1/...`
- All request/response bodies typed with Pydantic models
- Correct HTTP semantics: 200, 201, 400, 404, 422, 500
- `FastAPI.Query()` for validated query parameters — never trust raw strings
- OpenAPI tags and descriptions on every route

### Git Workflow
- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`
- Branch naming: `feat/schema-init`, `fix/roll-detection`, `chore/ci-setup`
- No direct pushes to `main` — PRs only (enforced by CI)
- Commit messages in imperative mood: "Add roll_calendar table" not "Added..."

---

## Security Rules (Non-Negotiable)

- Secrets via environment variables only — **never hardcoded**, not even in tests
- `.env` is git-ignored; `.env.example` documents all vars without real values
- CORS origins explicitly listed — no wildcard (`*`) in production
- All DB access via SQLAlchemy ORM to prevent SQL injection
- Validate and sanitise every external input at the API boundary
- Docker images: non-root user, minimal base image (`python:3.12-slim`)

---

## Architecture Decisions (Settled — Do Not Revisit)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Raw storage unit | 1m unadjusted OHLCV only | Single source of truth; all TFs auto-derived |
| Higher timeframes | TimescaleDB Continuous Aggregates | Zero sync logic; always consistent |
| Price adjustment | Applied at query time, not stored | Raw data stays clean and reusable |
| Roll handling | `roll_calendar` table + ratio adjustment | Preserves percentage moves for TA |
| Historical source | FirstRate Data CSV (unadjusted) | 18 years, one-time purchase, clean data |
| Daily updates | yfinance with 7-day overlap + dedup | Free; overlap guards against gap issues |
| Deployment | Railway Pro: API + Fetcher + self-hosted TimescaleDB Docker services | Single-region co-location; Railway PG plugin lacks the `timescaledb` extension (see ADR-001) |

---

## Domain Knowledge

```
Instruments:   9 symbols across 3 asset classes — see app/core/instruments.py
                 Equity indices (CME/CBOT): NQ, ES, YM, RTY
                 Metals (COMEX):            GC (Gold), SI (Silver), HG (Copper)
                 Energy (NYMEX):            CL (Crude Oil), NG (Natural Gas)
Trading hours: Sun 18:00 – Fri 17:00 ET; daily settlement break 17:00–18:00 ET
Roll schedule (equity): 3rd Friday of Mar / Jun / Sep / Dec; volume migrates ~2 weeks pre-expiry
                Contract codes: H=Mar  M=Jun  U=Sep  Z=Dec  (e.g. NQH25 = NQ March 2025)
                Metals roll bimonthly (GC: G/J/M/Q/V/Z); energy rolls monthly. roll_calendar
                table is currently seeded only for equity indices — adjustment=raw is the
                only meaningful choice for metals/energy until those datasets land.
yfinance issue: Occasional 1–2 day gaps in futures data (upstream bug, GitHub #2635)
                Mitigated by 7-day overlap fetch and gap detection script.
```

---

## CI/CD Pipeline

`.github/workflows/ci.yml` runs on every push and PR to `main`:

```
lint      →  ruff check .
typecheck →  mypy app/ fetcher/  (strict mode)
test      →  pytest with ephemeral TimescaleDB service container
docker    →  docker build for both Dockerfile and Dockerfile.fetcher
```

All checks must pass before merging. No `--no-verify` bypasses.

---

## Future Frontend (React / Next.js)

Backend is designed API-first to support a charting dashboard:
- CORS controlled via `CORS_ORIGINS` env var
- `/api/v1/kbars` returns paginated JSON compatible with TradingView Lightweight Charts
- WebSocket endpoint planned for Period 3: `GET /ws/v1/stream/{instrument}`
- API contract must remain stable once the frontend exists — treat it as a public contract

---

## Common Commands

```bash
# Start local dev stack
docker-compose up -d db
uvicorn app.main:app --reload --port 8000

# Code quality
ruff check . && mypy app/ fetcher/
pytest -v --cov

# Data management
python scripts/bootstrap_csv.py --data-dir data/firstrate/
python scripts/verify_coverage.py
python fetcher/main.py --once   # manual trigger of daily fetch
```
