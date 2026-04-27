# Project Status & Session Handoff

> Snapshot: **2026-04-27** · Period 1 live. Period 1.5 (ML workbench) — backend landed, frontend pending.
>
> This document is optimised for two readers: (1) the operator (you, Sam),
> and (2) the next assistant session that picks up where this one left off.
> Keep it honest — when reality drifts, update this file before it bites.

---

## 1. At a glance (TL;DR)

- **Period 1 (data collection) is online.** Four Railway services deployed,
  daily fetcher scheduled, dashboard reachable on the public internet.
- **Data path verified end-to-end.** yfinance → kbars_1m → 6 Continuous
  Aggregates → API → Next.js charts.
- **Period 1.5 — ML workbench backend is live.** `/api/v1/ml/train`
  accepts a wizard config, fits an sklearn / xgboost / lightgbm model
  with time-series safety rails, and persists each run to the new
  `experiments` table. See `docs/ADR-002-ml-workbench.md`.
- **Pending code work:** the workbench front-end (`/research` wizard,
  result visualisations, experiments list).
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

### Frontend

4. **Next.js 14 dashboard** under `frontend/` with three pages:
   - `/` — per-instrument cards with bar count + `latest_ts`
   - `/coverage` — full `(instrument × timeframe)` matrix
   - `/chart` — interactive candlestick chart (lightweight-charts v4),
     instrument & timeframe selectors, ratio adjustment server-side
5. **Multi-stage Dockerfile** (`frontend/Dockerfile`) using
   `output: "standalone"` for a thin runtime image; non-root `nextjs` user.
6. **Public deployment** with explicit CORS (no wildcard) — `quant`'s
   `CORS_ORIGINS` is now `http://localhost:3000,https://frontend-production-d637.up.railway.app`.

### Documentation

7. ADR-001 rewritten for "self-hosted Railway" path (was "Timescale Cloud").
8. README + CLAUDE.md updated for 4-service topology and frontend status.

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

| # | Item | When | How |
|---|------|------|-----|
| **#19** | Decommission the legacy `Postgres` plugin and `postgres-volume` | After the next 00:00 UTC (Taiwan 08:00) fetch confirms the pipeline is solid | Dashboard → `Postgres` service → Settings → Danger → Delete; then Volume → Delete |
| **#48** | Build the workbench front-end (`/research` wizard, result charts, experiments list) — backend is live and ready to receive POSTs at `/api/v1/ml/train` | Next session | See ADR-002 and `app/ml/schemas.py` for the request shape |
| 📋 | Re-watch the next scheduled fetch | After 00:00 UTC (Taiwan 08:00) weekday | `railway logs --service fetcher --since 1h`, then check `latest_ts` on dashboard |

Everything else is in `# 7. Optimisation ideas` (not blocking).

---

## 7. Optimisation ideas (Period 1.5)

In rough priority order. Pick what ties in with portfolio narrative; don't
do all of them.

### Backend

- **Health endpoint exposing real db connectivity.** `/health` currently
  returns 200 unconditionally; richer probe (`SELECT 1` + last-fetch
  freshness) would justify discussing observability in interviews.
- **Structured JSON logs + request IDs.** Today logs are plain text
  per-line. Switching to `structlog` with correlation IDs makes the
  Railway log search useful and fits Stripe/Google review standards.
- **`/api/v1/coverage/gaps` is O(N²).** Generates a per-minute series
  for the whole window and left-joins. For long ranges it's slow;
  switch to a CTE that walks `kbars_1m` ordered and detects deltas.
- **API rate limiting.** `slowapi` middleware with a sensible per-IP
  cap; no auth model yet.
- **Backups for self-hosted timescaledb.** Currently zero. Cron a
  `pg_dump` to S3 (or Railway's own backup service if/when it lands
  for self-hosted DBs). Without this, ADR-001's "no managed backups"
  trade-off is real risk.
- **Compression policy review.** Schema declares one but the data is
  still small enough that nothing has compressed yet. Verify it
  triggers as expected once volumes grow.

### Fetcher

- **Multi-source ingestion path.** Today only `YFinanceSource` exists.
  Period 2 needs IBKR for live; abstracting now is cheap and shows
  good design choices in code review.
- **Catch-up backfill on missed days.** If the scheduler misses a run
  (Railway redeploy at the wrong moment), there's no retry-from-gap
  logic. Add a one-shot script that detects and fills gaps.

### Frontend

- **Time-range selector on `/chart`.** Today the lookback is hard-coded
  per timeframe. A date-range picker would make the dashboard genuinely
  useful for inspecting historical regimes.
- **Volume-weighted average price overlay** (or any indicator). Cheap
  to add and signals that this codebase is going somewhere.
- **Loading skeletons + error boundaries.** Currently a 500 from the
  API renders an ugly inline error message. Polish helps the portfolio
  story.
- **Coverage page filters.** Filter by instrument, sort columns. With
  28 rows it's manageable; with more instruments it isn't.
- **Add the frontend URL to its own README.**

### Tooling

- **CI build for the frontend.** `.github/workflows/ci.yml` doesn't
  exercise the Next.js build today. Add a `frontend` job that runs
  `pnpm typecheck` and `pnpm build` so renames don't break Railway
  silently.
- **mypy: clean up the 5 pre-existing `Missing type parameters`
  warnings** in `fetcher/notifier.py` and `fetcher/scheduler.py` so
  strict mode is actually green.
- **`pnpm approve-builds`** for `unrs-resolver` to silence the install
  warning.

### Observability

- **Hook a real notifier endpoint.** `fetcher/notifier.py` posts to
  `WEBHOOK_URL` if set; today nothing is configured. A free Discord/
  Slack webhook means the daily run posts a summary.
- **Per-deployment alerting.** Railway's built-in deploy notifications
  are off — turn them on for `api` and `fetcher` failures.

### Security / cleanup

- **Rotate `API_SECRET_KEY`** away from `changeme` (visible in
  Suggested Variables earlier). It's not used anywhere yet but it
  exists.
- **Tighten CORS to https only** if a localhost variant is no longer
  needed for active dev.
- **Decommission the old `Postgres` plugin** (Task #19, see above).

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
