# Session handoff — 2026-11-05 — Pairs lab (ADR-010)

> For the next assistant session. Read this, then `docs/ADR-010-pairs-lab.md`
> (design + findings) and `docs/STATUS.md` §11 (operator runbook). Reply to
> Sam in Traditional Chinese; code, commits and docs stay in English.

## 1. State of the repository

- Branch `main`, in sync with `origin/main`, working tree clean.
- Last commit: `739c7fd feat(frontend): phone-friendly shell and installable web app`.
- Everything below is **pushed to GitHub but NOT deployed**. The auto-mode
  permission guard blocks `railway up` and Railway env-var writes, so Sam
  must run the deploy himself (§3).
- Quality gate at the last push: `ruff check .` clean; `mypy app/pairs
  app/api/pairs.py fetcher/pairs_job.py` clean (pre-existing mypy errors in
  `app/core/adjustment.py`, `app/api/kbars.py`, `fetcher/notifier.py`,
  `fetcher/scheduler.py` are untouched and not ours); `pytest -m "not
  integration"` 433 passed; `python scripts/smoke_pairs.py` OK;
  `cd frontend && pnpm typecheck && pnpm build` OK. `next lint` is skipped
  repo-wide because there is no ESLint config (pre-existing).

## 2. What was built this session (8 commits)

| Commit | Scope |
|---|---|
| `3c4be2a` | Phase 1 — `app/pairs/universe.py` (60 tickers, CME contract specs, micro variants, settlement times), `app/pairs/data.py` (yfinance 1d batch fetch, quality checks, upsert, wide price matrix, 1m snapshot series), `db/migrations/002_pairs.sql` + `app/pairs/schema.py` (`ensure_schema()`, idempotent), ADR-010 |
| `f95c150` | Phase 2 — `stats.py` (OLS/TLS/Johansen β, EG both ways, ADF, Hurst, OU half-life + bootstrap CI, z variants, BH), `screen.py` (explicit / watchlist / universe scan + qualification), `diagnostics.py` (rolling series, conditional forward returns), `schemas.py` |
| `817cce3` | Phase 3 — `signals.py` (shared state machine), `sizing.py`, `metrics.py` (Sharpe CI, deflated Sharpe), `backtest.py` (walk-forward, portfolio, costs, sensitivity, tradeability tax), `notify.py`, `scripts/smoke_pairs.py` |
| `ad0482e` | Phase 4 — `repository.py`, `service.py`, `app/api/pairs.py` (`/api/v1/pairs/*`), router + startup `ensure_schema()` in `app/main.py` |
| `e3814a9` | Phase 5 — `fetcher/pairs_job.py` (idempotent daily job), second APScheduler job, `PAIRS_*` settings |
| `5ac0621` | Phase 6 — `frontend/app/research/pairs/{page,analyze,backtest,guide}`, `components/pairs/*`, `lib/pairs.ts`, nav link |
| `0928516` | Phase 7 — CI smoke step, `.env.example`, ADR checklist + findings, STATUS §11 runbook, CLAUDE.md snapshot |
| `739c7fd` | Mobile — scrollable nav, horizontal-scroll tables, `app/manifest.ts`, viewport/Apple web-app metadata |

Tests added: `tests/test_pairs_{universe,data,stats,screen,signals,backtest,api,job}.py` (≈170 tests) plus `app/pairs/synthetic.py` generators.

## 3. TODO — Sam (blocked on permissions)

1. Create a Discord webhook on a dedicated channel (separate from the ops one).
2. Railway **fetcher** service: set `PAIRS_WEBHOOK_URL=<webhook>` and `PAIRS_DRY_RUN=true`.
3. Deploy all three services from the repo root:
   ```bash
   railway up --service quant --detach
   railway up --service fetcher --detach
   railway up --service frontend --detach
   ```
   No migration step: tables are created at API startup and by the job.
4. Post-deploy smoke (each step under a minute):
   ```bash
   curl -s https://quant-production-d645.up.railway.app/api/v1/pairs/universe | head -c 200
   curl -s https://quant-production-d645.up.railway.app/api/v1/pairs/data/coverage      # expect []
   curl -s -o /dev/null -w "%{http_code}\n" https://quant.samlabhq.com/research/pairs/guide
   ```
   then, signed in on `/research/pairs`: **Refresh data** → **Seed default
   pairs** → **Run scan** → **Dry-run daily job** (admin) → open **Analyze**
   on one pair → run one **Backtest**. Finally, with the webhook set, trigger
   the job once with `PAIRS_DRY_RUN=false` to see the digest arrive, then set
   it back to `true`.
5. Keep `PAIRS_DRY_RUN=true` for two weeks; compare the signal feed with a
   backtest over the same pairs; then flip to `false`.
6. Optional: `railway ssh --service quant "cat /sys/fs/cgroup/memory.max"` —
   the older #22 item (container memory before full 1m crypto runs) is still open.

## 4. TODO — next assistant session (code)

Ordered by value. None is blocking activation.

1. **Production verification** once Sam has deployed: read `railway logs
   --service quant|fetcher --since 2h | grep pairs`, confirm tables exist,
   confirm the first `pairs_job_runs` row. Reads are allowed under auto mode.
2. **Real-data calibration.** On live data (2024–2026) none of the brief's ten
   pairs qualified; NQ/ES and EWA/EWC fail only the 60-day stability gate.
   Run a universe scan and a few backtests on production data, record what the
   forward-return tables show, and decide with Sam whether the stability
   threshold (0.8) or lookback (60) should move. Do not loosen gates silently.
3. **Continuous futures series.** Front-month `=F` tickers carry roll gaps.
   Options: Databento continuous daily, Norgate, or the FirstRate purchase
   already pending (B6) which also sells continuous daily. Design hook:
   `app/pairs/data.py` + `universe.registry_symbol`; equity index pairs already
   read `roll_calendar`.
4. **Basket engine** (3–4 legs from the Johansen eigenvector: Treasury curve,
   NQ/ES/YM). New module next to `backtest.py`; the state machine generalises
   if `Observation` carries a vector of legs.
5. **Pair detail from the live job**: the Analyze page could overlay the
   job's actual entries/exits (`pairs_signals`) on the z chart.
6. **Point-in-time price snapshots** (vendor revisions): store a hash of the
   inputs per signal so a later recompute can be reconciled (brief §12.5).
7. **Scan history view**: `pairs_scans` keeps every run; the dashboard shows
   only the latest. A per-pair sparkline of p-value / z across scans is cheap.
8. **Optional native shell**: if Sam wants a real app, Capacitor around the
   existing site + native push is the low-effort path. Not started on purpose.
9. **Housekeeping**: `pytest-asyncio` deprecation warning
   (`asyncio_default_fixture_loop_scope` unset) — add it to `pyproject.toml`;
   pre-existing mypy errors listed in §1 if Sam wants `mypy app/ fetcher/`
   fully green.

## 5. Decisions and findings to keep in mind

- **Placement:** sub-system of this repo (`app/pairs/`), reusing fetcher,
  DB, Discord notifier, auth, CI and the UI shell. The killzone engine is
  deliberately not reused (1m session loop vs daily walk-forward).
- **No prop-firm constraints** by Sam's instruction: capital allocation,
  portfolio and baskets are first-class; account rules are out of scope.
- **z window:** the brief's `2·HL` understates spread variance and fires the
  3.5σ stop constantly (synthetic Sharpe ≈ 0 vs 1.4–1.7 with 60 days).
  Defaults are `clip(4·HL, 20, 120)`; multiple is configurable everywhere.
- **Hedge geometry:** with a log regression, X-leg notional = β × Y-leg
  notional (the brief had it reversed). `sizing.py` and the guide are correct.
- **Universe lives in `app/pairs/universe.py`**, not `app/core/instruments.py`
  (ETFs/stocks must not enter the 1m fetcher registry).
- **Idempotency contract of the daily job:** state `as_of`, unique
  `(signal_date, pair_name, event)`, `notified_at`. The digest is itself a
  signal row (`_digest_`).
- **Reads are open, writes need a signed-in user, the manual job trigger
  needs admin** — same model as the rest of the API.
- **Environment gotchas** (unchanged): auto mode blocks Railway deploys and
  env writes; no local Postgres (integration tests run only in CI); Railway
  service-name trailing whitespace; `NEXT_PUBLIC_*` must be declared as ARG in
  `frontend/Dockerfile`.

## 6. Where things are

| Need | Path |
|---|---|
| Design, methodology, findings, open items | `docs/ADR-010-pairs-lab.md` |
| Runbook (activation, operation, smoke) | `docs/STATUS.md` §11 |
| In-app explanation of every page and metric | `/research/pairs/guide` (`frontend/app/research/pairs/guide/page.tsx`) |
| API surface | `app/api/pairs.py` |
| Daily job | `fetcher/pairs_job.py` |
| Offline smoke | `scripts/smoke_pairs.py` |
| Env variables | `.env.example` (`PAIRS_*`) |
| Memory note for assistants | `~/.claude/projects/-Users-sam-Desktop-quant-futures/memory/project_pairs_scanner.md` |
