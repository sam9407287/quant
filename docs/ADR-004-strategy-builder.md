# ADR-004: Rule-Based Strategy Builder + Chart Trade Overlay

- **Status:** Accepted — implemented 2026-07-20
- **Date:** 2026-07-20
- **Deciders:** Sam
- **Relates:** ADR-003 (backtest engine), STATUS.md §8 (signal definition surface)

## 1. Context

The platform had one hardcoded strategy (killzone OCO, ADR-003) and no
way to author, save, or visualise arbitrary rule-based strategies.
Product ask: build a strategy in a form, save it as a template in a
strategy database, then apply it on the chart page — the backend
computes every entry/exit and the chart shows long/short entries and
exits, with TradingView-style position boxes when a bracket exists
(green box on the profit side entry→TP, red box on the risk side
entry→SL; a one-sided bracket draws only its side).

This is the rule-based half of the "signal definition surface" already
sketched in STATUS.md §8 (the ML-signal half stays future work).

## 2. Decision

### Strategy = one JSONB document (`strategies` table)

`StrategyDefinition` (app/strategies/schemas.py, Pydantic v2):

- **Operand algebra:** `price` | `const` | `ema(w)` | `sma(w)` |
  `rsi(w)` | `highest_high(w)` | `lowest_low(w)` (Donchian extremes of
  the PRIOR w bars, shift(1) so a bar can't break a channel that
  includes itself).
- **Conditions:** `cross_above` / `cross_below` / `gt` / `lt` between
  two operands.
- **Slots:** `entry_long`, `entry_short`, `exit_long`, `exit_short`
  (each optional; ≥1 entry required) + optional `sl` / `tp` bracket
  (pct or points — either side alone is valid).
- **Per-strategy `timeframe`** (1m…1w — served by the existing
  continuous aggregates) and `default_lookback_days`.

Indicator math is NOT reimplemented: operands delegate to
`app/ml/features.build_feature` (kind names align with `FeatureKind`).

### Evaluation engine (app/strategies/engine.py, pure)

- Conditions evaluated on bar **close**, orders filled at the **next
  bar's open** — no lookahead by construction.
- One position at a time; an opposite entry signal closes and
  reverses; exits also via the direction's exit condition, the
  bracket, or end-of-data.
- Bracket conservatism identical to the killzone engine: same-bar
  SL-over-TP tie rule; stops gapped through at a later bar's open fill
  at that open; the entry bar is exempt (position opened mid-bar).
- Bars come from `app/strategies/loader.py`, which reuses the kbars
  fetch + roll-adjustment helpers so evaluation sees exactly the
  series the chart displays (default `ratio` adjustment).

### API (app/api/strategies.py)

CRUD under `/api/v1/strategies` + `POST /{id}/evaluate`
(`{instrument, start, end, adjustment}`) → trades (with `sl_level` /
`tp_level` for the boxes), metrics **in points** (reusing
`app/backtest/analysis` via a DayResult adapter), equity curve.

### Frontend

- `/research/strategies` — form builder (condition rows: operand /
  op / operand; four signal slots; bracket toggles) + saved list with
  edit/delete. `lib/strategies.ts` mirrors the backend types.
- `/chart` — strategy dropdown; selecting one pins the chart to the
  strategy's timeframe and evaluates over the visible range. Entries/
  exits render via `series.setMarkers` (v4.2); position boxes via a
  custom `ISeriesPrimitive` (`components/chart/trade-overlay.ts`) that
  recomputes pixel rects in `updateAllViews` and clamps half-visible
  boxes to the pane edges. Switching timeframe away clears the overlay
  instead of showing misaligned trades. A metrics strip (trades, win
  rate, PF, total pts, maxDD, expectancy) sits above the chart.

## 3. Consequences

- Three strategy surfaces now exist: killzone-OCO backtest (ADR-003),
  saved rule strategies (this ADR), and the ML workbench. The rule
  engine's trades are in points — contract sizing/costs stay out of
  this layer (consistent with the 2026-07-19 no-costs decision).
- The v1 operand set is deliberately lean; adding MACD/Bollinger/ATR
  channels is one operand kind + one `build_feature` branch each.
- Reversal semantics are fixed (opposite entry = close and flip) and
  documented in the builder UI.

## 4. Verification (2026-07-20)

- 16 engine unit tests + 2 API integration tests (local TimescaleDB).
- End-to-end on real data: 84,588 NQ 1m bars seeded locally, CAs
  refreshed; EMA 20/60 cross (SL-only) and RSI fade (SL+TP) strategies
  created via API and rendered in a headless-Chromium screenshot —
  markers, one-sided red boxes, and dual green/red boxes all correct,
  zero console errors.
