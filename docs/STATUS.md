# Project Status & Session Handoff

> Snapshot: **2026-04-27** · Period 1 + Period 1.5 fully live. 9 instruments, ML workbench end-to-end, all four Railway services green.
>
> This document is optimised for two readers: (1) the operator (you, Sam),
> and (2) the next assistant session that picks up where this one left off.
> Keep it honest — when reality drifts, update this file before it bites.

---

## 1. At a glance (TL;DR)

- **Period 1 (data collection) is online.** Four Railway services deployed,
  daily fetcher scheduled, dashboard reachable on the public internet.
- **9 instruments tracked** across three asset classes — equity indices
  (NQ/ES/YM/RTY), metals (GC/SI/HG), energy (CL/NG). Single source of
  truth in `app/core/instruments.py`.
- **Data path verified end-to-end.** yfinance → kbars_1m → 6 Continuous
  Aggregates → API → Next.js charts.
- **Period 1.5 — ML workbench fully live (backend + frontend).**
  `/research` wizard runs sklearn / xgboost / lightgbm models with
  time-series safety rails; experiments persist to the `experiments`
  table; result page renders ECharts visualisations per task type. See
  `docs/ADR-002-ml-workbench.md`.
- **Pending code work:** none blocking. Optimisation backlog in §7.
- **Hot warning — gotchas you must remember:** Railway CLI service-name
  trailing whitespace; root `.gitignore` `lib/` rule swallowing
  `frontend/lib/`; Railway PostgreSQL plugin lacks the `timescaledb`
  extension (do not migrate back to it).

---

## 2. Live deployment

| Service | Build | Public URL | Internal URL | Status |
|---------|-------|-----------|---------------|--------|
| `timescaledb` | `db/Dockerfile` | — | `timescaledb.railway.internal:5432` | 🟢 |
| `api` (`quant`) | `Dockerfile` | `https://quant-production-d645.up.railway.app` | — | 🟢 |
| `fetcher` | `Dockerfile.fetcher` | — | — | 🟢 (scheduler idle, fires 00:00 UTC (Taiwan 08:00) weekdays) |
| `frontend` | `frontend/Dockerfile` | `https://frontend-production-d637.up.railway.app` | — | 🟢 |
| `Postgres` (legacy plugin) | template | — | `postgres.railway.internal:5432` | ⚠ orphan, scheduled for decommission |

Project: `quant` · Environment: `production` · Region: `Southeast Asia`
(asia-southeast1).

### Service IDs (use when CLI cannot resolve by name)

```
timescaledb : 82a308b5-105d-4984-a2d8-0b7816dc75de
quant (api) : 467d97f0-95cb-4abd-8753-84aa10ecb49f
fetcher     : 6a335858-5f88-4b60-bfe0-e7222260b971
frontend    : 2b6a7428-0ce5-4678-8bfb-64f4803582d4
Postgres    : 45aec38f-49bb-4796-a1bb-db2c19d88c82  (legacy)
```

---

## 3. Repo state (commits added this session)

```
69c3fc9 feat(instruments): expand to 9 symbols across 3 asset classes
0b22cb6 feat(frontend): ML workbench wizard, result viz, experiments list
76a57b7 feat(ml): no-code ML workbench backend (ADR-002)
7e8ef09 docs: ADR-002 — ML workbench architecture
b9816da docs: reflect ML workbench backend landing in CLAUDE.md and STATUS.md
b6afa6b chore: shift daily fetch to 00:00 UTC (Taiwan 08:00)
48e393b docs: add Operating Mode (autonomy) section to CLAUDE.md
9e4bd7f docs: add STATUS.md handoff doc, link from CLAUDE.md
a621f36 fix(infra): track frontend/lib/ — was silently ignored by Python rule
63717ae feat(infra): deploy frontend as a fourth Railway service
f58e4ef feat(frontend): seed Next.js charting dashboard for ingested data
06d0718 fix(fetcher): widen CA refresh window and isolate per-view failures
daddf3f fix(infra): set PGDATA to a subdir to bypass Railway volume lost+found
028771d docs: revise ADR-001 for self-hosted Railway TimescaleDB
2ec867a feat(infra): self-host TimescaleDB as a Railway Docker service
```

Branch: `main`, in sync with `origin/main`. Working tree clean unless this
file or `CLAUDE.md` was just edited and not committed.

---

## 4. Completed in this session

### Backend / infra

1. **Self-hosted TimescaleDB on Railway** as a Docker service with persistent
   volume — replaces the Railway PostgreSQL plugin which lacks the
   `timescaledb` extension. Schema and seed bake into the image; Railway's
   built-in DB browser does not work for this service (see §5.G).
2. **CA refresh hardening** in `fetcher/pipeline.py`:
   - Default window widened from 8 → 14 days (always covers a full
     Mon–Sun bucket of `kbars_1w`).
   - Per-view `try/except` so one misaligned view cannot halt the loop.
3. **Scheduler decoupled** from `fetch_overlap_days` for CA refresh — uses
   the pipeline's safe default instead.
4. **Daily fetch shifted to 00:00 UTC (Taiwan 08:00 weekdays)** so failures
   surface during business hours rather than overnight.

### ML workbench (Period 1.5)

5. **Backend** under `app/ml/` (ADR-002):
   - `schemas.py` — typed Pydantic config + response models.
   - `features.py` — feature engineers (lag returns, rolling stats, RSI,
     EMA/SMA, volume ratio, HL spread) and target builders (log/simple
     return, direction with deadband, realised vol). Targets are the
     **only** place a forward shift is allowed.
   - `models.py` — `MODEL_REGISTRY` of 21 sklearn / xgboost / lightgbm
     models keyed by task. `build_model()` applies registry defaults
     and silently drops unknown hyperparameters.
   - `pipeline.py` — orchestrator: load bars → align target/features →
     drop warm-up → chronological split → fit StandardScaler on train
     only → fit model → metrics → response packaging. Hard caps at
     100 k samples and 5 k response points.
   - `repository.py` — JSONB-backed persistence; new `experiments` table
     in `db/schema.sql`, gated by the `pgcrypto` extension.
6. **Endpoints** under `/api/v1/ml/`:
   - `POST /train` — runs end-to-end training, persists, returns metrics.
   - `GET /experiments` and `GET /experiments/{id}`.
   - 20 unit tests covering the load-bearing safety properties (no
     leakage, fit-on-train-only, registry binding) — 109 total.
7. **Frontend wizard at `/research`** (and `/research/experiments`):
   - 4-section single-page wizard with task-aware defaults that prevent
     impossible (task, target) combos from leaving the browser.
   - Permanent "Time-series ML mode" banner spelling out the safety rails.
   - Result panel renders ECharts visualisations per task: regression
     gets predicted-vs-actual time series + scatter; classification gets
     a sample-match table; clustering gets a 2D PCA scatter coloured by
     cluster label. Feature importance bar appears whenever the model
     exposes one.
   - `/research/experiments` lists past runs with the most relevant
     metric per task type.

### Frontend (general)

8. **Next.js 14 dashboard** under `frontend/` with five pages:
   - `/` — instrument cards grouped by asset class (Indices / Metals /
     Energy) with bar count + `latest_ts`
   - `/coverage` — full `(instrument × timeframe)` matrix
   - `/chart` — interactive candlestick chart (lightweight-charts v4)
     with grouped instrument selector
   - `/research` — ML wizard (above)
   - `/research/experiments` — experiments list (above)
9. **Multi-stage Dockerfile** (`frontend/Dockerfile`) using
   `output: "standalone"` for a thin runtime image; non-root `nextjs` user.
10. **Public deployment** with explicit CORS (no wildcard) — `quant`'s
    `CORS_ORIGINS` is now `http://localhost:3000,https://frontend-production-d637.up.railway.app`.

### Multi-instrument expansion

11. **`app/core/instruments.py`** — single-source-of-truth registry
    mapping internal `Symbol` to (display name, asset class, exchange,
    yfinance ticker). `Instrument` Literal types in `app/api/kbars.py`
    and `app/ml/schemas.py` re-export from this registry; mypy will
    flag any place that still expects the old shorter set.
12. **5 new instruments** seeded into `data_coverage` and `FETCH_INSTRUMENTS`
    on Railway. First one-shot fetch landed 32 406 new 1m bars across
    GC/SI/HG/CL/NG.

### Documentation

13. ADR-001 rewritten for "self-hosted Railway" path (was "Timescale Cloud").
14. ADR-002 added — ML workbench architecture decisions.
15. README + CLAUDE.md updated for 4-service topology, ML workbench, and
    9-instrument universe.
16. CLAUDE.md gained an **Operating Mode (autonomy)** section so the
    assistant proceeds without round-tripping on routine work.

---

## 5. Problems hit and how they were resolved

These are the institutional details that won't be obvious from reading
the code or commits.

### A. Railway PostgreSQL plugin has no `timescaledb` extension

**Symptom:** `pg_extension` query returns empty; `CREATE EXTENSION` fails.
**Resolution:** Migrated to a self-hosted `timescale/timescaledb:latest-pg16`
Docker service. See ADR-001 in `docs/SYSTEM_DESIGN.md`.

### B. `lost+found` breaks Postgres init on Railway volumes

**Symptom:** Postgres entrypoint refuses to initialise an "non-empty"
data dir; the only file present is `lost+found` (always present on
Railway's ext4 volumes).
**Resolution:** `ENV PGDATA=/var/lib/postgresql/data/pgdata` in
`db/Dockerfile` — actual data goes one level below the mount root.

### C. Trailing whitespace in Railway service names

**Symptom:** `railway logs --service fetcher` returns
`Service 'fetcher' not found`, even though the dashboard shows it
online. CLI does an exact-string match against the stored name.
**Resolution:** In dashboard, Settings → Service Name, **delete the
field and retype** (don't trust the existing value). Pre-fix the CLI
worked only via service ID.

### D. `kbars_1w` "refresh window too small"

**Symptom:** Daily fetcher's CA refresh fails with
`InvalidParameterValueError: refresh window too small`. 8-day window
between two arbitrary timestamps doesn't reliably enclose one full
Monday–Sunday weekly bucket.
**Resolution:** Default window is now 14 days; per-view `try/except`
prevents one failure from halting the loop. See `fetcher/pipeline.py`
and `tests/test_aggregation.py`.

### E. SQLAlchemy `::TIMESTAMPTZ` cast clashes with bind-param `:`

**Symptom:** Using PostgreSQL's shorthand `:bind::TIMESTAMPTZ` confuses
SQLAlchemy's bind-param parser.
**Resolution:** Use the long form `CAST(:bind AS TIMESTAMPTZ)`. This
is what the production code uses today.

### F. Procedure CALLs cannot run inside a transaction

**Symptom:** `CALL refresh_continuous_aggregate(...)` fails inside the
default async session.
**Resolution:** Open a dedicated AUTOCOMMIT connection from the engine:
`await conn.execution_options(isolation_level="AUTOCOMMIT")`.

### G. Railway's Database UI does not render for self-hosted DBs

**Symptom:** No "Database" tab on the `timescaledb` service — only on
the official Postgres template.
**Resolution:** Either `railway connect timescaledb` for a psql shell,
or use the Next.js frontend at the public URL. (This is exactly the
gap the frontend was built to fill.)

### H. `Suggested Variables` trap

**Symptom:** When adding a new service from the repo, Railway scans
the source tree and suggests adding env vars from the API/fetcher
(`DATABASE_URL`, `FETCH_INSTRUMENTS`, `CORS_ORIGINS`, `API_SECRET_KEY`,
…). Clicking any of these on the wrong service injects unwanted state.
**Resolution:** Always **ignore the entire Suggested Variables list**
on a fresh service. Only add the variables you have explicitly
identified as needed.

### I. Trailing whitespace in env-var values

**Symptom:** `database "quant_futures " does not exist`.
**Resolution:** Markdown copy/paste sometimes appends a newline that
ends up as trailing whitespace in Railway dashboard env values. Always
delete the field and retype, or strip carefully.

### J. Root `.gitignore` `lib/` rule silently ignored `frontend/lib/`

**Symptom:** Local Next.js build succeeded, Railway build failed with
`Module not found: Can't resolve '@/lib/api'`.
**Resolution:** Added `!frontend/lib/` and `!frontend/lib/**` exception
right after the Python `lib/` rule. The Python rule still applies to
virtualenvs.

### K. Railway CLI cannot modify Custom Start Command or service settings

**Symptom:** No CLI command for "clear Custom Start Command" or
"rename service" — these live only in the dashboard.
**Resolution:** Operator must use the dashboard for those. The CLI
covers env vars, logs, redeploy, and service listing.

### L. `NEXT_PUBLIC_*` is build-time, not runtime

**Symptom:** Changing `NEXT_PUBLIC_API_URL` in the dashboard does not
take effect until a redeploy.
**Resolution:** `lib/api.ts` falls back to the production URL when the
env var is unset, so the variable is technically optional. If you do
set it, trigger a redeploy.

---

## 6. Pending todos

Nothing is blocking new feature work. Two operational items, then
optimisation backlog.

| # | Item | When | How |
|---|------|------|-----|
| **#19** | Decommission the legacy `Postgres` plugin and `postgres-volume` | After the next 00:00 UTC (Taiwan 08:00) fetch confirms the pipeline is still solid with all 9 instruments | Dashboard → `Postgres` service → Settings → Danger → Delete; then Volume → Delete |
| 📋 | Watch the next scheduled fetch | 2026-04-28 (Tue) ≥ 00:30 UTC = Taiwan 08:30 | `railway logs --service fetcher --since 1h`. Confirm 9 instruments fetched and `data_coverage.latest_ts` advanced |
| **#20** | Period 2 backtest engine (B1–B7) | ✅ B1–B5 + B7 shipped 2026-07-19 | Engine + analysis + /api/v1/backtest + /research/backtest (form) + /research/backtest/canvas (node UI). Only **B6 remains: FirstRate NQ 1m purchase + bootstrap_csv.py load** — until then runs cover ~3 months of yfinance data and seasonality/Monte Carlo conclusions are not decision-grade |

Everything else is in §7 (optimisation) or §8 (Period 2 design direction).

---

## 7. Optimisation backlog

In rough priority order. Pick what ties into the portfolio narrative;
don't do all of them.

### High value (do first if time permits)

- **CI build for the frontend.** `.github/workflows/ci.yml` does not
  exercise `pnpm typecheck` or `pnpm build`. A frontend regression
  could land on `main` and only fail on Railway. Adding the job is
  ~15 minutes and prevents real outages.
- **Backups for self-hosted timescaledb.** Currently zero. Cron a
  `pg_dump` to object storage (or Railway's own backup service if it
  ships for self-hosted DBs). Without this, ADR-001's "no managed
  backups" trade-off is the highest production risk in the system.
- **Health endpoint with real DB probe.** `/health` returns 200
  unconditionally; richer `SELECT 1` + last-fetch-freshness check
  becomes the load-bearing signal for "is the pipeline healthy" and
  is interview-worthy on its own.
- **Hook a real notifier endpoint.** `fetcher/notifier.py` posts to
  `WEBHOOK_URL` when set; today nothing is configured. A free Discord
  or Slack webhook would mean each fetch posts a summary, closing the
  observability loop.

### Backend

- **Structured JSON logs + request IDs.** Today logs are plain text
  per-line. Switching to `structlog` with correlation IDs makes the
  Railway log search useful and fits Stripe/Google review standards.
- **`/api/v1/coverage/gaps` is O(N²).** Generates a per-minute series
  for the whole window and left-joins. Switch to a CTE that walks
  `kbars_1m` ordered and detects deltas.
- **API rate limiting.** `slowapi` middleware with a sensible per-IP
  cap; no auth model yet.
- **Compression policy review.** Schema declares one but data is still
  small enough that nothing has compressed yet. Verify it triggers as
  expected once volumes grow.

### Fetcher

- **Multi-source ingestion path.** Today only `YFinanceSource` exists.
  Period 2 needs IBKR for live; abstracting now is cheap.
- **Catch-up backfill on missed days.** If the scheduler misses a run
  (Railway redeploy at the wrong moment), no retry-from-gap logic
  exists. Add a one-shot script that detects and fills gaps.
- **Roll calendar for metals and energy.** Index futures roll quarterly
  (H/M/U/Z); GC/SI/HG roll bimonthly; CL/NG roll monthly. The seed
  table only has indices today. Adding the metal/energy schedules
  unlocks `adjustment="ratio"` for those symbols (currently only
  `raw` is meaningful for them).

### Frontend

- **Time-range selector on `/chart`.** The lookback is hard-coded per
  timeframe. A date picker would make historical regime inspection
  meaningful.
- **Indicator overlays** (SMA / EMA / VWAP / Bollinger). Cheap to add,
  signals the codebase is going somewhere.
- **Coverage page filters.** Filter by instrument, sort columns.
  Manageable with 63 rows; not with the next expansion.
- **Loading skeletons + error boundaries.** A 500 from the API renders
  an ugly inline message today. Polish helps the portfolio story.
- **Per-experiment detail page.** `/research/experiments/[id]` with
  the full config, metrics, and "fork & rerun" affordance.
- **Add the frontend URL to its own README.**

### Tooling

- **mypy: clean up the 5 pre-existing `Missing type parameters`
  warnings** in `fetcher/notifier.py`, `fetcher/scheduler.py`,
  `app/api/kbars.py`, `app/core/adjustment.py` so strict mode is
  actually green end-to-end.
- **`pnpm approve-builds`** for `unrs-resolver` to silence the install
  warning.
- **Pre-commit hooks** running ruff + mypy + pytest on changed files.
  Faster local feedback than waiting for CI.

### Security / cleanup

- **Rotate `API_SECRET_KEY`** away from `changeme`. Not used anywhere
  yet but the plaintext default is a footgun.
- **Tighten CORS to HTTPS only** once localhost dev tapers off.
- **Decommission the old `Postgres` plugin** (Task #19).

---

## 8. Period 2 design direction (signal research & backtesting)

> **Update 2026-07-19:** Period 2 now has a second track — a rule-based
> intraday backtest engine (killzone OCO / Judas-swing strategy, Monte
> Carlo, seasonality analysis), architecture in
> `docs/ADR-003-backtest-engine.md`. The ML-signal track sketched below
> stays valid; the two share the analysis layer and persistence pattern.

Period 1 + 1.5 supply the data and the model fitter. Period 2 turns
trained models into testable signals, then evaluates them properly.

### What "Period 2 done" looks like

1. **Signal definition surface.** A signal is a deterministic function
   from a model's prediction series + a threshold/parameter set →
   `{−1, 0, +1}` position vector. Signals live as DB rows so they're
   diffable and reproducible, exactly like experiments are now.
2. **Backtest engine.** Vectorised P&L over the position vector
   against the kbars: returns, Sharpe, Sortino, max drawdown, hit
   rate, average win/loss, transaction-cost model, slippage.
3. **Walk-forward evaluation.** Train on `[t-N, t]`, signal on
   `[t, t+M]`, slide the window. The single-fold metrics in the
   workbench today are diagnostic, not decision-grade.
4. **Comparison page on the frontend.** `/research/signals` lists
   signals (not raw experiments), with metric columns and a "compare
   two" affordance.

### Architecture sketch

- **New table `signals`** alongside `experiments`. Each row references
  one or more `experiment_id`s and stores the signal's parameter dict.
- **New module `app/backtest/`** — pure NumPy, single pass over the
  joined `(positions, returns)` arrays. No external libraries:
  vectorbt is great but heavy and rebuilds half of what we need
  anyway.
- **Endpoint `/api/v1/backtest`** taking `(signal_id, start, end,
  cost_bps)` and returning the full equity curve plus the metric
  table. Same sync vs async stance as `/ml/train` until proven slow.
- **Frontend `/research/signals`** — defines and persists signals;
  `/research/backtest/[id]` — renders the equity curve, drawdown,
  rolling Sharpe, trade table.

### Sequencing recommendation

1. **(small)** Land the per-experiment detail page (§7 frontend
   bullet) first — it makes the workbench self-sufficient as a
   research tool before signals exist.
2. **(medium)** Walk-forward CV inside the existing `/ml/train`
   endpoint. The schema already has `walk_forward_folds` — wire it
   up. Output: per-fold metrics distribution. This is high-leverage:
   one feature dramatically improves the rigour of every model run.
3. **(medium)** Roll calendar for metals/energy. Without this, the
   ML workbench is technically running on partially adjusted prices
   for those symbols (no rolls applied, but their data does have
   real roll discontinuities yfinance hasn't smoothed). Add the
   schedules before doing comparative cross-asset research.
4. **(large)** Backtest engine + signals + UI. This is Period 2
   proper.

### Things explicitly **not** doing yet

- **GPU / deep learning.** Confirmed out of scope per ADR-002 §D2.
  Linear/tree baselines first; revisit only if those plateau.
- **Live trading / IBKR integration.** Period 3 territory. Keep all
  Period 2 work paper-trading-only.
- **Multi-user auth.** This stays a single-operator tool through
  Period 2.

---

## 8. Operator runbook

### Read live data without the dashboard

```bash
# psql into the self-hosted TimescaleDB
railway connect timescaledb

# coverage table from inside any service container
railway ssh --service quant 'python -c "..."'   # complex; base64-encode
                                                   # the script first
```

### Pull logs

```bash
railway logs --service fetcher --lines 100
railway logs --service quant --since 1h
railway logs --service frontend --build         # build phase logs
```

If `--service <name>` fails with "not found", the service likely has
trailing whitespace in its name (see §5.C) or your CLI is
< 4.30 (upgrade with `brew upgrade railway`). Service IDs in §2 always
work.

### Set / inspect env vars

```bash
railway variables --service quant --kv          # dump
railway variables --service quant --set "FOO=bar"
```

Setting a variable triggers an automatic redeploy.

### Force a fetcher run now

```bash
# Override the start command in dashboard:
#   Settings → Deploy → Custom Start Command:
#       python -m fetcher.main --once
# Apply, wait for deploy, then CLEAR the override and apply again
# so the next deploy returns to scheduler mode.
```

### Manual CA refresh (if a fetcher run partially fails)

Use a base64-encoded script inside an SSH session:

```python
import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    eng = create_async_engine(os.environ["DATABASE_URL"])
    async with eng.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for view in ("kbars_5m","kbars_15m","kbars_1h","kbars_4h","kbars_1d","kbars_1w"):
            await conn.execute(text(f"CALL refresh_continuous_aggregate('{view}', NULL, NULL)"))
            print(f"OK {view}")

asyncio.run(main())
```

Refresh `data_coverage` afterwards by calling
`fetcher.pipeline.update_all_coverage()` in the same way.

---

## 9. Bringing the next session up to speed

If you (Sam) start a new conversation and want it productive immediately:

1. **Open the project**:
   `cd /Users/sam/Desktop/quant-futures` so `CLAUDE.md` auto-loads.
2. **Tell the assistant to read this file first**:
   *"Read `docs/STATUS.md` before doing anything else."*
3. **Hand it the immediate next task**:
   - "Watch tomorrow's 00:00 UTC (Taiwan 08:00) fetch — pull the fetcher logs, confirm
     all 4 instruments fetched, then update §2 / §6 of `docs/STATUS.md`."
   - Or: "Decommission the legacy Postgres plugin per Task #19 in
     `docs/STATUS.md`."

### What the next session should expect to find

- Backend at `/Users/sam/Desktop/quant-futures` — Python 3.12, pytest,
  ruff, mypy. 89 unit tests pass; integration suite uses Docker.
- Frontend at `frontend/` — Next.js 14, pnpm, TypeScript strict.
- Live deployment described above; no new infra is needed for
  Period 1.
- All commits up through `a621f36` are already live.

### What the next session should NOT do without confirmation

- Do **not** delete the legacy `Postgres` plugin until the operator
  confirms tomorrow's auto-fetch was successful (Task #19).
- Do **not** modify `CORS_ORIGINS` to a wildcard — the explicit list
  is intentional per CLAUDE.md security rules.
- Do **not** assume `railway service list` names are clean; check for
  trailing whitespace before any name-based CLI call.
- Do **not** add files under `lib/` at the repo root expecting them to
  be tracked — the Python ignore rule still applies; the frontend
  exception is the only carve-out.

---

## 10. Quick-reference paths

```
docs/SPEC.md             — functional requirements & API spec
docs/SYSTEM_DESIGN.md    — architecture decisions & DB schema
docs/STATUS.md           — this file
CLAUDE.md                — house rules for the assistant
README.md                — public-facing project overview
.env.example             — full list of backend env vars
frontend/.env.local.example — frontend env vars
railway.toml             — 4-service topology
```
