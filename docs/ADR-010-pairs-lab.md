# ADR-010: Statistical Arbitrage Lab (Pairs / Cointegration Research)

- **Status:** Accepted — design settled 2026-11-05; implementation tracked in §9
- **Date:** 2026-11-05
- **Deciders:** Sam
- **Relates:** ADR-003 (killzone engine — deliberately *not* reused), ADR-007
  (daily yfinance fetch path), `fetcher/notifier.py` (Discord webhook)

---

## 1. Context

Sam wrote a stand-alone requirements document for a cointegration-based
pairs-trading scanner (daily bars, rolling Engle-Granger, hedge ratio,
half-life, z-score signals, walk-forward backtest, cloud schedule with push
alerts). The document assumed a fresh project. An integration review
against this repository concluded:

| Capability | Existing | Verdict |
|---|---|---|
| Daily-bar history (3–5y, settlement aligned) | No — DB holds 1m bars only, futures history starts 2026-04, `kbars_1d` is a UTC-midnight bucket | **build** |
| Continuous-contract roll handling | `roll_calendar` for NQ/ES/YM/RTY + ratio/absolute adjustment | reuse for the equity pairs, mark gaps elsewhere |
| Multi-leg positions, hedge-ratio sizing, walk-forward, cost model | None | **build** |
| Cloud schedule, DB, Discord webhook, auth, CI, frontend shell | All live | **reuse** |

Two framing decisions were taken with Sam before design:

1. **No prop-firm constraints.** The system is a research arena: capital
   allocation, portfolio construction and baskets are first-class; account
   rule checks are out of scope.
2. **Not a Markdown report — a product surface.** Results live in the
   existing Next.js dashboard with an in-app guide explaining what every
   number means and how to use the pages.

## 2. Decision

**Build the lab as a sub-system of this repository** (`app/pairs/`,
`/api/v1/pairs/*`, `frontend/app/research/pairs/*`), reusing the data
infrastructure, scheduler process, Discord notifier, auth, CI and UI shell.
**Do not** route it through the killzone engine: the two engines differ in
granularity (1m session loop vs. daily vectorised walk-forward) and share no
useful abstraction. Everything that already exists keeps working unchanged.

### 2.1 Module layout

```
app/pairs/
├── universe.py     # tickers, asset groups, CME contract specs (standard + micro), settlement times
├── schemas.py      # Pydantic contracts: ScanConfig, BacktestConfig, responses
├── data.py         # daily bars: yfinance fetch, quality checks, upsert, aligned log-price matrix
├── schema.py       # ensure_schema(): idempotent DDL (db/migrations/002_pairs.sql)
├── stats.py        # OLS/TLS hedge ratio, Engle-Granger, Johansen, ADF, OU half-life, Hurst, z-score, BH
├── screen.py       # scan a universe → PairStats per pair + qualification
├── diagnostics.py  # rolling β / p-value series, conditional forward-return buckets
├── signals.py      # pure state machine (shared by backtest and the daily job)
├── sizing.py       # dollar-neutral notional, integer contracts (micro-first), rounding error, 2σ risk
├── backtest.py     # walk-forward engine, portfolio aggregation, costs, metrics, sensitivity, deflated Sharpe
├── repository.py   # SQL persistence (scans, state, signals, backtest runs, job runs)
└── notify.py       # Discord embeds for signal events and digests
fetcher/pairs_job.py  # daily entry point (23:00 UTC weekdays), idempotent
app/api/pairs.py      # REST surface
frontend/app/research/pairs/{page,analyze,backtest,guide}
```

### 2.2 Data model (`db/migrations/002_pairs.sql`)

| Table | Purpose |
|---|---|
| `pairs_daily_bars` | One row per (ticker, trading_date): OHLC, `adj_close`, volume, source. Futures use the daily settlement/close yfinance reports; ETFs and stocks use adjusted close. |
| `pairs_watchlist` | Named Y/X pairs with per-pair overrides. Seeded with the ten pairs from the brief. |
| `pairs_scans` / `pairs_scan_results` | Every scan (manual or daily) with its config and one stats row per pair, so the dashboard shows history, not only the latest. |
| `pairs_state` | Current side per pair plus the frozen entry parameters, day count, breakdown counter, cooldown. |
| `pairs_signals` | Event log; `UNIQUE (signal_date, pair_name, event)` + `notified_at` is what makes a same-day re-run idempotent. |
| `pairs_backtest_runs` | Config, metrics and the full result document (JSONB) per run, owned by a user like `backtest_runs`. |
| `pairs_job_runs` | One row per daily job execution for the ops view. |

Schema is applied two ways: baked into `db/schema.sql` for fresh volumes,
and `ensure_schema()` (all `IF NOT EXISTS`) run by the API lifespan and the
daily job so the production database needs no manual migration step.

### 2.3 Methodology

- **Prices:** `log(price)`; futures settlement/close, ETFs adjusted close.
- **Alignment:** inner join on trading date; forward fill at most one day.
- **Formation window:** 504 trading days default (252 as sensitivity).
  Every statistic for date *t* is computed from data **strictly before t**.
- **Hedge ratio:** OLS `log Y = α + β log X` (default) and TLS (orthogonal,
  symmetric in Y/X) reported side by side; Johansen eigenvector as a third
  reference.
- **Cointegration evidence:** Engle-Granger in both directions, ADF on the
  spread, Johansen trace (det_order=0, k_ar_diff=1), Hurst exponent of the
  spread. Disagreements are reported, never hidden.
- **Half-life:** OU regression `Δs_t = λ s_{t-1} + c`; `HL = −ln2/λ`;
  `λ ≥ 0` disqualifies. A block-bootstrap confidence interval accompanies
  the point estimate.
- **Qualification (all required, configurable):** EG p < 0.05, 3 ≤ HL ≤ 40,
  stability ≥ 80 % of the last 60 days with p < 0.05, β > 0 and β
  coefficient of variation below threshold.
- **Multiple testing:** Benjamini–Hochberg q-values across the whole scan.
- **Universe screening:** every pair in the universe (≈ 60 tickers → ~1.8k
  ordered pairs) can be scanned, not only the watchlist. Stability (the
  expensive rolling test) runs only for pairs that pass the point-in-time
  filters.
- **Conditional forward returns:** for each z bucket, the distribution of
  the spread change over the next 5/10/20 days — the diagnostic that shows
  whether mean reversion is real before any trading rule is layered on.

### 2.4 Signal rules (one state machine, used by backtest and live)

| Rule | Default |
|---|---|
| z window | `clip(round(2·HL), 10, 60)` |
| Entry | z ≥ +2 short spread; z ≤ −2 long spread |
| Exit | \|z\| ≤ 0.5 **or** z crosses zero (configurable, both backtested) |
| Stop | \|z\| ≥ 3.5 |
| Time stop | held > 3·HL days |
| Breakdown | EG p > 0.10 for 5 consecutive days while in a position → exit + pause entries |
| Cooldown | N days after a stop |
| Parameter freeze | β, mean, std fixed at entry (default) or refreshed daily (comparison mode) |

### 2.5 Backtest and portfolio

- **Walk-forward:** parameters re-estimated every trading day from the
  trailing formation window (no in-period information); qualification
  gating can be switched off for ablation.
- **Fills:** signal at *t* close → fill at *t+1* open (default) or close.
- **Costs:** commission per contract per side, slippage in ticks per leg,
  roll cost per leg on roll dates (equity index pairs read `roll_calendar`;
  other futures use a monthly/bi-monthly proxy from the universe table).
- **Sizing:** two modes — `fractional` (ideal dollar-neutral, the research
  truth) and `integer` (micro-first rounding; rounding error and the
  tradeability tax are reported).
- **Portfolio:** capital split by equal weight or inverse spread volatility
  across concurrently qualified pairs; portfolio equity, drawdown and a
  correlation matrix of pair P&L streams.
- **Metrics:** total/annualised return, Sharpe, Sortino, Calmar, max DD and
  duration, CVaR(95 %), win rate, profit factor, average hold, exit-reason
  mix, per-pair attribution, benchmark (hold Y), bootstrap Sharpe CI,
  deflated Sharpe given the number of parameter trials.
- **Sensitivity:** entry z × formation window × exit rule grid rendered as
  a heatmap.
- **Look-ahead guard:** a test randomises every bar after *T* and asserts
  the signal history up to *T* is byte-identical.

### 2.6 Daily job

`fetcher/pairs_job.py`, scheduled by the existing APScheduler process at
`0 23 * * 1-5` UTC (configurable via `PAIRS_CRON`). Steps: ensure schema →
incremental daily-bar fetch → verify a new bar exists → scan watchlist →
step state machine per pair → persist signals → Discord. Any failure is
isolated from the 1m fetch job. Same-day re-runs produce no duplicate
signals or pushes. `PAIRS_DRY_RUN=true` logs but does not post.

### 2.7 Notifications

Discord webhook (`PAIRS_WEBHOOK_URL`, separate channel from the ops
summary). Pushed: state changes (entry/exit/stop/time stop/breakdown),
a compact daily z digest (optional), and error summaries. Each message
links to the pair's analysis page.

### 2.8 API (`/api/v1/pairs`)

| Method | Path | Auth |
|---|---|---|
| GET | `/universe` | — |
| GET/POST/DELETE | `/watchlist`, `/watchlist/{id}`; POST `/watchlist/defaults` | write: user |
| GET | `/data/coverage` | — |
| POST | `/data/refresh` | user |
| POST | `/scans`; GET `/scans`, `/scans/latest`, `/scans/{id}` | write: user |
| GET | `/analysis?y=&x=&formation_window=&as_of=` | — |
| POST | `/backtests`; GET `/backtests`, `/backtests/{id}` | user |
| GET | `/signals`, `/state`, `/jobs` | — |
| POST | `/jobs/daily?dry_run=` | admin |

### 2.9 Frontend

`/research/pairs` dashboard (coverage, latest scan table with
qualification badges and z heat strip, live state and signal feed, run
scan / refresh data actions), `/research/pairs/analyze` (spread with z
bands, rolling β and p-value, forward-return buckets, evidence table),
`/research/pairs/backtest` (config form, equity + drawdown, metrics,
per-pair attribution, sensitivity heatmap, trade list, runs history) and
`/research/pairs/guide` (concepts, page walk-through, metric glossary,
research workflow M1–M4, caveats).

## 3. Consequences

- Fetcher and API images gain `statsmodels` (scipy already present).
- A new daily job shares the fetcher process; it runs an hour before the
  1m fetch and is wrapped so a failure cannot affect ingestion.
- `app/core/instruments.py` is untouched: ETFs and stocks do not belong in
  the 1m registry. The pairs universe is its own module.
- yfinance `=F` tickers are unadjusted front-month series. Equity index
  pairs get roll dates from `roll_calendar`; other pairs flag large gaps.
  A paid continuous-contract source remains an open purchase decision.

## 4. Testing strategy

Every phase ships with unit tests; the lab also has an offline smoke run.

| Layer | Tests |
|---|---|
| universe / data | spec integrity, batch-download normalisation, quality checks, alignment with limited ffill |
| stats | synthetic cointegrated series pass with β/HL inside tolerance; independent random walks reject at ≈ α; TLS symmetry; BH monotonicity |
| signals / sizing | every transition of the state machine; integer rounding and error reporting |
| backtest | look-ahead randomisation, frozen vs refreshed params, fill modes, cost monotonicity, portfolio equity identity |
| API | FastAPI TestClient with overridden `get_db` / `get_current_user` |
| job / notify | idempotent re-run, dry run, no-new-bar day, payload shape |
| smoke | `scripts/smoke_pairs.py` (synthetic data, no DB, exit 0) in CI; `pnpm typecheck && pnpm build` for the frontend |

## 5. Project checklist

| Phase | Deliverable | Status |
|---|---|---|
| 0 | This ADR | ✅ |
| 1 | Universe + contract specs, migration, daily-bar data layer, tests | ⏳ |
| 2 | Statistics, screening, diagnostics, tests | ⏳ |
| 3 | Signals, sizing, walk-forward backtest, portfolio, sensitivity, smoke script | ⏳ |
| 4 | Repository + REST API, tests | ⏳ |
| 5 | Daily job, scheduler wiring, Discord notify, tests | ⏳ |
| 6 | Frontend: dashboard, analysis, backtest, guide, nav | ⏳ |
| 7 | Docs (STATUS, CLAUDE.md), CI smoke step, deploy notes | ⏳ |

## 6. Operator notes

Environment variables (fetcher): `PAIRS_WEBHOOK_URL`, `PAIRS_CRON`
(default `0 23 * * 1-5`), `PAIRS_DRY_RUN` (default `false`),
`PAIRS_HISTORY_YEARS` (default `10`). No schema step is required: the API
and the job create the tables on first use.
