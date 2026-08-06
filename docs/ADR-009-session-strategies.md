# ADR-009: Session-Aware Strategies + Order-Driven (OCO) Entries

- **Status:** Accepted, 2026-08-07
- **Relates:** ADR-003 (backtest engine), ADR-004 (strategy builder)

## Context

Two canvases existed and they compiled to different engines.

The **strategy canvas** produced a `StrategyDefinition` — indicator
conditions with `cross_above`/`gt`-style operators, evaluated on a bar's
close, entering at the next open. The **backtest canvas** produced
`BacktestParams` for the hard-coded `killzone_oco` session engine (ICT
Judas Swing): a reference range measured over an intraday window, two
resting orders bracketing it, first touch wins, flat at the close.

Users reasonably wanted one canvas with the killzone as a module they
add. That is not a UI change. The rule DSL could not express:

1. **A session** — no notion of trading hours, forced flat, or "today".
2. **The extremes of an intraday window** — `highest_high` is a rolling
   N-bar channel, not "the high of 09:30–10:00 in this session".
3. **Resting orders** — the engine was signal-driven (condition true →
   enter next open), not order-driven (price touches a level → filled).

(1) and (2) are additive. (3) is a change of execution model, and it is
the one that mattered: without it a "killzone module" on the strategy
canvas would have had to secretly compile to the other engine, which
means it could never combine with a Filter module. Shipping that would
have been a canvas that looks unified and is not.

## Decision

Extend the rule engine so the killzone becomes an ordinary strategy,
rather than special-casing it.

**`SessionSpec`** — timezone plus open/close. `close` doubles as the
forced-flat time. Sessions may wrap midnight.

**`session_high` / `session_low` operands** — the extreme of an intraday
window within the current session. **NaN until that window closes**, so
a range that is still forming cannot be read. This is the no-lookahead
guarantee, enforced by construction rather than by discipline.

**`StopEntry`** — two resting orders derived from level operands plus an
offset, with `mode: breakout | fade`, an `active_from` time, and an
`oco` flag. These fill **intrabar**.

Plus `max_trades_per_session`.

All of it is optional. A strategy with no `session` behaves exactly as
before — the existing tests pass unchanged.

### Session-relative seconds

`app/strategies/session.py` converts every bar to `(local_seconds -
session_open) % 86400`. A session then runs monotonically from 0 to its
length even when it crosses midnight, so window membership and "has this
window finished" are plain comparisons. No wrap cases in the engine.

### Conservatism (inherited from ADR-003 §2.1)

The order path reuses the killzone engine's rules, because those are
what stop a backtest flattering itself:

- A bar touching both SL and TP books as **SL**.
- A breakout (stop) order on a bar that already opens beyond its level
  fills at that **open**, not back at the level. A fade (limit) order
  fills at the level — a gapped limit fills at the same price or better.
- One bar touching **both** entry levels resolves by proximity to that
  bar's open; an exact tie is unresolvable, so the session stands down.
- The entry bar's own range counts for the bracket; skipping it would
  silently drop same-bar stops.
- A session whose range window has no bars produces no level at all,
  rather than borrowing a neighbouring day's.

### Level timing

Session extremes are known at a bar's open (the window closed before it
began), so they are used unshifted. Every other operand is close-derived
and is shifted one bar before being used as a level or as an order gate
— otherwise bar *i*'s close would authorise a fill inside bar *i*.

## Consequences

- One canvas. Session / Killzone / Bracket are modules beside Trigger /
  Filter / Exit, and they compose: a killzone entry gated by an RSI
  filter is one strategy, one position, one engine.
- `/research/backtest/canvas` redirects to the strategy canvas;
  `components/backtest/canvas.tsx` is deleted.
- **The dedicated killzone runner at `/research/backtest` stays.** The
  rule engine scores in points and models neither slippage nor
  commission; that page reports USD P&L after costs and keeps the
  seasonality and Monte Carlo analysis. The two are not redundant, and
  the canvas page says so.
- The definition is stored as JSONB, and `time` round-trips through
  `model_dump(mode="json")` — no migration was needed.

## Not done

Per-side slippage and USD P&L in the rule engine. That is what would
make the killzone runner redundant, and it is a separate decision about
whether `StrategyDefinition` should carry contract economics at all.
