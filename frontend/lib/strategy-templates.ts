// Starting points for a new strategy.
//
// A template is a StrategyDefinition — the real contract — not a
// canvas-shaped or form-shaped structure. Both editors read from here, so
// "EMA crossover" cannot come to mean two different things depending on
// which page you opened.
//
// Brackets are in percent wherever the idea is instrument-agnostic, so one
// template means the same thing on NQ as on GC. The session template is the
// exception: a killzone is quoted in points because that is how the setup
// is actually specified.
//
// These are illustrative, not recommendations — every one of them is a
// textbook shape with textbook parameters, and none has been fitted to
// anything.

import type { Condition, Operand, StrategyDefinition } from "@/lib/strategies";
import type { Timeframe } from "@/lib/types";

export interface StrategyTemplate {
  key: string;
  /** Menu label. */
  label: string;
  /** Default name when saved. */
  name: string;
  /** One line: the idea it encodes, not the mechanics. */
  blurb: string;
  definition: StrategyDefinition;
}

const price: Operand = { kind: "price" };
const num = (value: number): Operand => ({ kind: "const", value });
const ind = (kind: Operand["kind"], window: number, extra: Partial<Operand> = {}): Operand => ({
  kind,
  window,
  ...extra,
});
const when = (left: Operand, op: Condition["op"], right: Operand): Condition => ({ op, left, right });

function base(timeframe: Timeframe): StrategyDefinition {
  return {
    timeframe,
    default_lookback_days: 180,
    entry_long: null,
    entry_short: null,
    exit_long: null,
    exit_short: null,
    filters: [],
    sl: null,
    tp: null,
    session: null,
    stop_entry: null,
    max_trades_per_session: null,
  };
}

export const STRATEGY_TEMPLATES: StrategyTemplate[] = [
  {
    key: "ema_cross",
    label: "EMA crossover (trend)",
    name: "EMA 20/60 crossover",
    blurb: "Ride a trend while the fast average stays above the slow one.",
    definition: {
      ...base("1h"),
      entry_long: when(ind("ema", 20), "cross_above", ind("ema", 60)),
      exit_long: when(ind("ema", 20), "cross_below", ind("ema", 60)),
      sl: { mode: "pct", value: 1 },
      tp: { mode: "pct", value: 2 },
    },
  },
  {
    key: "mean_reversion",
    label: "Mean reversion (Bollinger)",
    name: "Bollinger mean reversion",
    blurb:
      "Buy the stretch below the lower band, leave once price is back at the mean.",
    definition: {
      ...base("1h"),
      entry_long: when(price, "cross_below", ind("bollinger_lower", 20, { value: 2 })),
      exit_long: when(price, "cross_above", ind("sma", 20)),
      // Without this it buys every leg of a decline that simply keeps going.
      filters: [when(ind("rsi", 14), "lt", num(40))],
      sl: { mode: "pct", value: 1 },
      tp: { mode: "pct", value: 2 },
    },
  },
  {
    key: "donchian_breakout",
    label: "Donchian breakout (turtle)",
    name: "Donchian 20/10 breakout",
    blurb: "Trade the break of a 20-bar channel; leave on the 10-bar reverse.",
    definition: {
      ...base("4h"),
      entry_long: when(price, "cross_above", ind("highest_high", 20)),
      entry_short: when(price, "cross_below", ind("lowest_low", 20)),
      exit_long: when(price, "cross_below", ind("lowest_low", 10)),
      exit_short: when(price, "cross_above", ind("highest_high", 10)),
      sl: { mode: "pct", value: 2 },
      tp: { mode: "pct", value: 4 },
    },
  },
  {
    key: "macd_trend",
    label: "MACD momentum + trend gate",
    name: "MACD momentum (above 200 SMA)",
    blurb: "Take momentum crosses, but only on the right side of the 200 SMA.",
    definition: {
      ...base("1h"),
      entry_long: when(
        ind("macd", 12, { window2: 26 }),
        "cross_above",
        ind("macd_signal", 12, { window2: 26 }),
      ),
      exit_long: when(
        ind("macd", 12, { window2: 26 }),
        "cross_below",
        ind("macd_signal", 12, { window2: 26 }),
      ),
      filters: [when(price, "gt", ind("sma", 200))],
      sl: { mode: "pct", value: 1.5 },
      tp: { mode: "pct", value: 3 },
    },
  },
  {
    key: "rsi_pullback",
    label: "RSI pullback in an uptrend",
    name: "RSI 30/70 pullback",
    blurb: "Buy an oversold dip inside an uptrend, sell it back into strength.",
    definition: {
      ...base("1d"),
      entry_long: when(ind("rsi", 14), "cross_above", num(30)),
      exit_long: when(ind("rsi", 14), "cross_below", num(70)),
      filters: [when(price, "gt", ind("sma", 200))],
      sl: { mode: "pct", value: 3 },
      tp: { mode: "pct", value: 6 },
    },
  },
  {
    key: "ict_killzone",
    label: "ICT killzone (session OCO)",
    name: "NY killzone breakout",
    blurb:
      "Measure the first 30 minutes, rest a buy above and a sell below, flat by the close.",
    definition: {
      ...base("5m"),
      session: { tz: "America/New_York", open: "09:30:00", close: "16:00:00" },
      stop_entry: {
        upper_level: { kind: "session_high", time_start: "09:30:00", time_end: "10:00:00" },
        lower_level: { kind: "session_low", time_start: "09:30:00", time_end: "10:00:00" },
        mode: "breakout",
        offset_mode: "points",
        offset_value: 0,
        atr_period: 14,
        active_from: "10:00:00",
        oco: true,
      },
      max_trades_per_session: 1,
      sl: { mode: "points", value: 10 },
      tp: { mode: "points", value: 20 },
    },
  },
];

export const findTemplate = (key: string) => STRATEGY_TEMPLATES.find((t) => t.key === key);
