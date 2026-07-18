# ADR-003: Rule-Based Intraday Backtest Engine (Period 2 Kickoff)

- **Status:** Proposed — architecture settled, strategy-spec open questions pending (§6)
- **Date:** 2026-07-19
- **Deciders:** Sam
- **Supersedes / relates:** Extends the Period 2 sketch in `STATUS.md` §8; does not replace the ML-signal vectorised backtest planned there.

---

## 1. Context

Period 1 gives us a live TimescaleDB with 1m OHLCV for 9 instruments and
auto-derived higher timeframes. Period 2 is "strategy research: signals +
backtesting" (SPEC §Period 2).

Two distinct backtest families have emerged:

1. **ML-signal backtests** (STATUS.md §8): position vector from a trained
   model → vectorised P&L. Not covered by this ADR.
2. **Rule-based intraday session strategies** — the first concrete case is
   Sam's *Judas-swing killzone OCO* strategy on NQ/MNQ:
   - Before the New York killzone, compute a reference range high/low.
   - When the killzone opens, place two OCO bracket orders at
     (range high ± offset) and (range low ∓ offset).
   - On fill, cancel the opposite bracket; fixed SL/TP (e.g. 100 pt stop,
     2.0 RRR); force-flat at end of session regardless of position.
   - One decision cycle per trading day → one P&L record per day.
   - Analysis: equity curve, drawdown, **bootstrap Monte Carlo** over the
     daily P&L series, and **seasonality group-bys** (month-of-year,
     day-of-week).

These per-day event strategies do not fit a position-vector engine: order
type (stop vs limit), OCO semantics, and intrabar touch ordering matter.
They need a small per-day event loop over 1m bars.

A separate prototype repo (`QuantFlow`, dormant since 2025-12) validated
the appetite for a **ComfyUI-style visual node editor** that composes
backtest logic. That UI concept is worth preserving; this ADR therefore
constrains the engine to be **config-driven** (a strategy run is fully
described by one JSON document) so a node canvas can later compile to the
same config without touching the engine.

## 2. Decision

### 2.1 New module `app/backtest/`

```
app/backtest/
├── params.py       # Pydantic v2 BacktestParams — THE contract (JSON-serialisable)
├── engine.py       # per-day event loop over kbars_1m (pure functions, no I/O)
├── loader.py       # kbars_1m → per-session Polars/NumPy frames (DB access lives here)
├── strategies/
│   └── killzone_oco.py   # first strategy: Judas-swing killzone OCO fade
├── analysis.py     # equity curve, drawdown, seasonality group-bys, bootstrap Monte Carlo
└── schemas.py      # API request/response models
```

Engine rules:

- **Per-day event loop, not vectorbt.** External frameworks rebuild OCO /
  intrabar semantics poorly; the loop is ~200 lines and fully testable.
  (Same "no heavy framework" stance as STATUS.md §8 took for the
  vectorised path.)
- **Pure core:** `engine.run_day(bars, params) -> DayResult` takes arrays
  in, returns a result dataclass — no DB, no clock, no globals. All I/O
  in `loader.py` / the API layer.
- **Session logic in `America/New_York`** (killzone times, EOD flat, DST
  handled by `zoneinfo`), storage stays UTC.
- **Conservative intrabar rule:** if one 1m bar touches both SL and TP,
  count it as a **stop-loss**. Documented and test-pinned; can be revisited
  with tick data later.
- **Cost model:** per-side slippage (points) + per-round-turn commission
  (USD) are explicit params, never implicit.

### 2.2 Parameterisation (all knobs Sam asked for)

`BacktestParams` (all fields validated, JSON round-trippable):

| Group | Fields |
|---|---|
| Universe | `instrument` (NQ…), `contract_spec` (point value, e.g. MNQ $2/pt), `start`, `end` |
| Range window | `range_window` (session preset or explicit NY-time window) — the period whose high/low seeds the orders |
| Killzone | `killzone` (NY-time window in which entries may trigger), `eod_flat` (NY time) |
| Entry | `entry_offset_mode` = `pct` \| `points` \| `atr`, `entry_offset_value`, `direction_mode` = `fade` \| `breakout` |
| Exit | `sl_mode` = `points` \| `pct` \| `atr`, `sl_value`, `rrr` (TP = SL × rrr) **or** explicit `tp_value` |
| ATR | `atr_period`, `atr_timeframe` (for `atr`-mode offsets/stops) |
| Costs | `slippage_points_per_side`, `commission_usd_per_rt` |

Parameter sweeps = cartesian product over a params grid; each combo is one
run row (§2.3), so sweeps are reproducible and diffable.

### 2.3 Persistence

Two tables, mirroring the `experiments` pattern (diffable, reproducible):

- `backtest_runs` — one row per run: full params JSON, git SHA of engine,
  data coverage actually used, summary metrics (total P&L, Sharpe, max DD,
  win rate, profit factor, expectancy).
- `backtest_trades` — one row per session/day: date, direction, entry/exit
  ts+px, exit reason (`tp` / `sl` / `eod` / `no_fill`), P&L (USD + points),
  MAE/MFE. This is the raw series Monte Carlo and seasonality read from.

### 2.4 Analysis layer (`analysis.py`, pure functions)

- Equity curve + max drawdown + rolling stats from `backtest_trades`.
- **Seasonality:** group-by month / weekday / (optionally week-of-month)
  over daily P&L → mean, sum, count, win rate per bucket.
- **Monte Carlo:** bootstrap resampling (with replacement) and permutation
  (shuffle order) of the daily P&L series, N=10,000 → distributions of
  terminal equity and max drawdown, P(ruin) for a given capital,
  percentile bands. Seeded RNG for reproducibility.

### 2.5 API

- `POST /api/v1/backtest/runs` — body = `BacktestParams` (+ optional
  `params_grid` for sweeps); sync first, same stance as `/ml/train`.
- `GET /api/v1/backtest/runs` / `runs/{id}` — list + detail (metrics,
  equity curve, trades).
- `GET /api/v1/backtest/runs/{id}/montecarlo?n=10000&capital=...`
- `GET /api/v1/backtest/runs/{id}/seasonality?bucket=month|weekday`

### 2.6 Frontend & the QuantFlow concept

Phased, engine-first:

1. **B4 (near-term):** `/research/backtest` — a params **form** (the
   Pydantic schema drives it), run button, equity/drawdown charts, monthly
   & weekday bar charts, Monte Carlo band chart, trades table.
2. **B5 (later):** **node canvas** à la QuantFlow — React Flow page where
   nodes (range window → entry rule → risk block → session block →
   analysis) compile to the same `BacktestParams` JSON. The engine never
   knows the UI exists. QuantFlow the repo stays dormant; only its concept
   migrates. Its known pain points (laggy canvas, input-focus bugs — see
   QuantFlow's HOTFIX_*.md pile) argue for keeping the graph small and
   typed, not for importing that codebase.

## 3. Consequences

- Two backtest engines will coexist in Period 2 (vectorised ML-signal +
  per-day event loop). They share `analysis.py` and the run/trade
  persistence pattern; they do not share execution cores. This is
  deliberate — forcing one core would complicate both.
- The conservative intrabar rule biases results **against** the strategy
  (pessimistic). Acceptable: false confidence is the expensive failure.
- 1m resolution bounds fill realism; tick-level validation is explicitly
  out of scope until a strategy survives 1m + pessimistic assumptions.

## 4. Data prerequisite (blocking for long-horizon runs)

Production DB currently holds **~3 months** of 1m bars (yfinance daily
fetch, earliest 2026-04-19). The FirstRate 18-year 1m CSV purchase
(ADR-settled historical source, `scripts/bootstrap_csv.py` ready) has
**not happened yet**. Plan: build + verify the engine on the 3 live
months; buy/load FirstRate NQ before drawing any long-horizon or
seasonality conclusions (month-of-year buckets are meaningless on 3
months of data).

## 5. Task breakdown

| # | Task | Size | Depends on |
|---|---|---|---|
| B1 | `params.py` + `engine.py` + `killzone_oco.py` + unit tests (synthetic bar fixtures pin OCO, tie-rule, EOD, no-fill) | M | — |
| B2 | `loader.py` (kbars_1m → NY sessions) + `backtest_runs`/`backtest_trades` tables + migration | M | B1 |
| B3 | `analysis.py` (equity, seasonality, Monte Carlo) + tests | M | B1 |
| B4 | API endpoints + OpenAPI docs | S | B2 |
| B5 | Frontend params form + result charts | M | B4 |
| B6 | FirstRate NQ purchase + `bootstrap_csv.py` load + coverage verify | S (external $) | — |
| B7 | Node-canvas UI (QuantFlow concept) compiling to `BacktestParams` | L | B5 |

## 6. Open questions (need Sam before B1 freezes the strategy spec)

1. **Range window** — which period's high/low seeds the orders? Asia
   session, London session, NY pre-market (e.g. 00:00–09:30 NY), or a
   fixed lookback window?
2. **Killzone window** — exact NY-time entry window (e.g. 09:30–11:00)?
   And the EOD flat time (e.g. 15:55 NY)?
3. **Direction semantics** — "fade" = sell stop-limit at range high, buy
   at range low (mean reversion)? Or stop orders in the breakout
   direction? (The Judas-swing narrative implies fade — confirm.)
4. **Both-sides-filled day** — after one side fills and later exits, may
   the *other* side still trigger the same day, or is it one trade per
   day max?
5. **Contract math** — backtest on NQ price data but book P&L at MNQ
   $2/point, 1 contract, correct?
6. **Cost defaults** — proposed: slippage 1 pt/side on stop entries and
   stops, 0 on limits; commission $1.24/rt (MNQ retail typical). OK?
