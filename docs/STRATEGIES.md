# Trading Strategies

Catalog of rule-based strategies implemented (or planned) on top of the
Period 2 backtest engine (`docs/ADR-003-backtest-engine.md`). Each entry
states the trading narrative, the exact mechanical spec, and how it maps
onto `BacktestParams`. One strategy = one reproducible parameter set; a
tweak of the numbers is a new run, not a new strategy.

---

## ICT — Judas Swing (猶大擺盪)

**Status:** Spec frozen 2026-07-19 (decisions below) · Engine: `app/backtest/`

### Narrative

From the ICT (Inner Circle Trader) playbook: early in a session the
market often makes a deceptive push beyond a reference range's high or
low (the "Judas swing") before reversing. The strategy fades that push —
it parks limit orders at (or beyond) the reference range's extremes and
bets on mean reversion, with a fixed bracket and a hard end-of-session
flat.

### Mechanical spec (as decided)

| # | Rule | Decision |
|---|------|----------|
| 1 | **Reference range** | High/low of a **user-configurable time window** (`range_start`–`range_end`, in a **user-configurable timezone**) |
| 2 | **Order placement** | At a **configurable wall-clock time** (`orders_place`), place both OCO brackets based on the reference range computed in rule 1 |
| 3 | **Direction** | Default **fade** (sell at/above range high, buy at/below range low — mean reversion). **Breakout mode** (buy the upper level, sell the lower) is a supported toggle |
| 4 | **One trade per day** | Max one entry per session. The moment one side fills, the other side's entry + bracket orders are cancelled. No re-entry after exit |
| 5 | **Entry offset** | Levels may sit beyond or inside the raw high/low: offset in **points**, **% of the level price**, or **ATR multiples** — signed (positive = beyond the range) |
| 6 | **Bracket** | Stop-loss in points / % of entry / ATR multiple; take-profit = SL × RRR, or an explicit point override |
| 7 | **End of session** | At a **configurable flat time** (`eod_flat`), force-close any open position at market and cancel unfilled orders — no overnight exposure |
| 8 | **Contract math** | Backtest on NQ price history, P&L booked at **MNQ $2/point, 1 contract** by default — both `point_value_usd` and `contracts` are parameters (kept flexible by design) |
| 9 | **Costs** | Commission and slippage **not modeled for now** (params exist, default 0) |
| 10 | **Intrabar tie rule** | If a single 1m bar touches both SL and TP, count it as a **stop-loss** (pessimistic; engine-wide rule, see ADR-003 §2.1) |

### Parameter mapping

| Spec item | `BacktestParams` field |
|---|---|
| Reference range window + tz | `clock.range_start`, `clock.range_end`, `clock.tz` |
| Order placement time | `clock.orders_place` |
| Forced flat time | `clock.eod_flat` |
| Fade vs breakout | `direction_mode` |
| Entry offset | `entry_offset_mode`, `entry_offset_value` |
| Stop / target | `sl_mode`, `sl_value`, `rrr`, `tp_points` |
| Contract sizing | `point_value_usd`, `contracts` |
| Costs (off for now) | `slippage_points_per_side`, `commission_usd_per_rt` |

### Research questions this strategy is meant to answer

- Long-horizon daily P&L curve (needs FirstRate 18y load — ADR-003 B6).
- Bootstrap Monte Carlo on the daily P&L series: drawdown distribution,
  P(ruin), terminal-equity percentile bands.
- Seasonality: which **months** and **weekdays** does the edge
  concentrate in?
- Sensitivity sweeps: entry offset (±%, points, ATR), SL size, RRR,
  range window choice, placement time.
