# ADR-008: Signal Testing (test the idea before the backtest)

- **Status:** Accepted — implemented 2026-08-03
- **Date:** 2026-08-03
- **Deciders:** Sam
- **Relates:** ADR-003 (backtest engine), ADR-004 (strategy builder)
- **Source:** CMT quantitative-methods curriculum (M. Verdouw; R. Martin)

## 1. Context

The platform could evaluate a strategy (entries + exits + SL/TP) and
backtest the killzone strategy, but had no way to test an *idea* in
isolation. The CMT curriculum makes this the central lesson: a backtest
bundles the idea together with exits, stops, position size and starting
capital, so its result cannot tell you whether the idea itself has an
edge. Three failure modes it names:

- **Too many degrees of freedom** — entry, exit, stop, size, capital,
  dates each move the result; success may be trade management, not idea.
- **Path dependency** — the specific sequence of trades taken drives the
  equity curve as much as the rule does.
- **First-trade bias** — with compounding, one lucky/unlucky first trade
  can make or break the whole run.

The prescribed first step is a **signal test**: find every bar the
entry fires, treat each as day 0, and measure the forward return across
all signals. No exits, no stops, no sizing.

## 2. Decision

Add a signal-test capability that reuses the existing rule engine.

- `app/strategies/signal_test.py`: pure function over a bars DataFrame +
  `StrategyDefinition`. Reuses `engine._condition_series` to find every
  `entry_long` / `entry_short` signal, builds a `[n_signals, horizon+1]`
  matrix of directional forward returns (short signals negated so a
  "win" always means price moved the signalled way), and aggregates:
  **probability of gain** (win rate at the horizon), mean / median /
  std of terminal returns, the **average forward path**, and a terminal
  **return distribution**. Tail signals without a full forward window
  are dropped (no lookahead).
- `POST /api/v1/strategies/{id}/signal-test` (owner-scoped like the rest
  of the strategy API), body adds `horizon` (bars, 1–250).
- Frontend page `/research/signal-test`: strategy picker + instrument /
  range / horizon; renders the forward-return path (green line, zero
  reference), the metric tiles, and the terminal-return histogram —
  the curriculum's signal-test report.

### Reading the report (encoded in the UI copy)

- A near-straight, rising path = a persistent edge; a flat start that
  rises later suggests delaying entry a few bars.
- Mean ≈ median = outliers aren't distorting the average.
- Win rate targets ~55–60%+ per the curriculum; dispersion (std) small
  relative to the mean gives more confidence in repeatability.

## 3. Consequences

- The research flow now mirrors the curriculum's order: **Signal Test →
  Strategy → Backtest**, with cross-links between the three pages.
- Directional treatment (long fwd return, short negated) keeps a single
  win-rate meaningful for two-sided strategies. Benchmark-relative
  comparison (the curriculum's yellow index line) is a deliberate
  follow-up, not in v1.
- The node canvas became genuinely extensible in the same change (add /
  duplicate / delete modules from a toolbar) — see §4.

## 4. Node canvas: addable modules

The QuantFlow-concept canvas (ADR-003 B7) shipped with a fixed five-node
graph and no way to add or duplicate blocks. It now holds controlled
node/edge state with a palette toolbar (add any module type, duplicate
or delete the selection, reset layout). Because every node edits the
same shared params context, duplicates are simply extra editing handles
— safe by construction, no schema change.

## 5. Roadmap surfaced by the curriculum (not yet built)

Ordered by value; each maps cleanly onto existing building blocks:

1. **Filter vs trigger vs value rules.** The strategy schema treats all
   conditions as triggers. Add explicit **filter** conditions (must be
   true, not a discrete cross) and a **value/rank** rule for choosing
   among same-bar signals.
2. **Benchmark overlay** on the signal test (index forward path + the
   relative outperformance line).
3. **Richer performance metrics** on backtests: Sharpe, Sortino,
   **Calmar** (annualised return / max drawdown), CAGR, annualised
   volatility, expectancy — the go/no-go set from the curriculum.
4. **Walk-forward / out-of-sample** evaluation (rolling re-optimisation)
   — the honest test the curriculum insists on over a single backtest.
5. **Survivorship-bias note** in the UI once equity universes with
   delistings are loaded (futures/crypto are unaffected).
