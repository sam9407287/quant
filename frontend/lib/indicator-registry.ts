/**
 * The indicator catalogue: what the picker lists and what the chart draws.
 *
 * Each entry turns bars + params into a set of named lines. Overlays land on
 * the price pane; oscillators get their own pane below, because their units
 * have nothing to do with price.
 *
 * Line colours come from the same documented dark-surface categorical steps
 * the charts already use — they were validated as a set for lightness,
 * chroma, colour-blind separation and contrast.
 */

import {
  atr,
  bollinger,
  cci,
  donchian,
  ema,
  kdj,
  keltner,
  macd,
  mfi,
  obv,
  rsi,
  sma,
  stochastic,
  vwap,
  williamsR,
  wma,
  type Series,
} from "./indicators";
import type { KBar } from "./types";

const C = {
  blue: "#3987e5",
  orange: "#d95926",
  aqua: "#199e70",
  yellow: "#c98500",
  magenta: "#d55181",
  violet: "#9085e9",
  red: "#e66767",
  grey: "#7d8da3",
} as const;

export interface IndicatorParam {
  key: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
}

export interface IndicatorLine {
  key: string;
  label: string;
  color: string;
  values: Series;
  /** Histograms colour themselves by sign; lines take `color`. */
  kind?: "line" | "histogram";
  lineWidth?: number;
}

export type Pane = "price" | "oscillator";

export interface IndicatorMeta {
  id: string;
  name: string;
  group: string;
  pane: Pane;
  params: IndicatorParam[];
  /** Horizontal reference levels, oscillator pane only. */
  guides?: number[];
  build: (bars: KBar[], p: Record<string, number>) => IndicatorLine[];
}

const p = (key: string, label: string, value: number, min = 1, max = 500, step = 1): IndicatorParam => ({
  key,
  label,
  value,
  min,
  max,
  step,
});

export const INDICATORS: IndicatorMeta[] = [
  // ── Moving averages ─────────────────────────────────────────────
  {
    id: "sma",
    name: "Simple moving average",
    group: "Moving averages",
    pane: "price",
    params: [p("period", "Length", 20)],
    build: (bars, q) => [
      { key: "sma", label: `SMA ${q.period}`, color: C.blue, values: sma(bars.map((b) => b.close), q.period) },
    ],
  },
  {
    id: "ema",
    name: "Exponential moving average",
    group: "Moving averages",
    pane: "price",
    params: [p("period", "Length", 20)],
    build: (bars, q) => [
      { key: "ema", label: `EMA ${q.period}`, color: C.orange, values: ema(bars.map((b) => b.close), q.period) },
    ],
  },
  {
    id: "wma",
    name: "Weighted moving average",
    group: "Moving averages",
    pane: "price",
    params: [p("period", "Length", 20)],
    build: (bars, q) => [
      { key: "wma", label: `WMA ${q.period}`, color: C.violet, values: wma(bars.map((b) => b.close), q.period) },
    ],
  },
  {
    id: "vwap",
    name: "VWAP (session)",
    group: "Moving averages",
    pane: "price",
    params: [],
    build: (bars) => [{ key: "vwap", label: "VWAP", color: C.yellow, values: vwap(bars), lineWidth: 2 }],
  },

  // ── Bands & channels ────────────────────────────────────────────
  {
    id: "bollinger",
    name: "Bollinger Bands",
    group: "Bands & channels",
    pane: "price",
    params: [p("period", "Length", 20), p("mult", "Std dev", 2, 0.1, 10, 0.1)],
    build: (bars, q) => {
      const b = bollinger(bars, q.period, q.mult);
      return [
        { key: "upper", label: `BB upper`, color: C.blue, values: b.upper },
        { key: "middle", label: `BB ${q.period}`, color: C.grey, values: b.middle },
        { key: "lower", label: `BB lower`, color: C.blue, values: b.lower },
      ];
    },
  },
  {
    id: "keltner",
    name: "Keltner Channels",
    group: "Bands & channels",
    pane: "price",
    params: [p("period", "Length", 20), p("mult", "ATR mult", 2, 0.1, 10, 0.1), p("atrPeriod", "ATR length", 10)],
    build: (bars, q) => {
      const k = keltner(bars, q.period, q.mult, q.atrPeriod);
      return [
        { key: "upper", label: "KC upper", color: C.aqua, values: k.upper },
        { key: "middle", label: `KC ${q.period}`, color: C.grey, values: k.middle },
        { key: "lower", label: "KC lower", color: C.aqua, values: k.lower },
      ];
    },
  },
  {
    id: "donchian",
    name: "Donchian Channels",
    group: "Bands & channels",
    pane: "price",
    params: [p("period", "Length", 20)],
    build: (bars, q) => {
      const d = donchian(bars, q.period);
      return [
        { key: "upper", label: "DC upper", color: C.magenta, values: d.upper },
        { key: "middle", label: `DC ${q.period}`, color: C.grey, values: d.middle },
        { key: "lower", label: "DC lower", color: C.magenta, values: d.lower },
      ];
    },
  },

  // ── Momentum ────────────────────────────────────────────────────
  {
    id: "rsi",
    name: "RSI",
    group: "Momentum",
    pane: "oscillator",
    guides: [30, 50, 70],
    params: [p("period", "Length", 14)],
    build: (bars, q) => [
      { key: "rsi", label: `RSI ${q.period}`, color: C.violet, values: rsi(bars, q.period), lineWidth: 2 },
    ],
  },
  {
    id: "macd",
    name: "MACD",
    group: "Momentum",
    pane: "oscillator",
    guides: [0],
    params: [p("fast", "Fast", 12), p("slow", "Slow", 26), p("signal", "Signal", 9)],
    build: (bars, q) => {
      const m = macd(bars, q.fast, q.slow, q.signal);
      return [
        { key: "hist", label: "Histogram", color: C.grey, values: m.histogram, kind: "histogram" },
        { key: "macd", label: `MACD ${q.fast}/${q.slow}`, color: C.blue, values: m.line, lineWidth: 2 },
        { key: "signal", label: `Signal ${q.signal}`, color: C.orange, values: m.signal },
      ];
    },
  },
  {
    id: "stochastic",
    name: "Stochastic",
    group: "Momentum",
    pane: "oscillator",
    guides: [20, 50, 80],
    params: [p("k", "%K length", 14), p("kSmooth", "%K smoothing", 3), p("d", "%D length", 3)],
    build: (bars, q) => {
      const s = stochastic(bars, q.k, q.kSmooth, q.d);
      return [
        { key: "k", label: "%K", color: C.blue, values: s.k, lineWidth: 2 },
        { key: "d", label: "%D", color: C.orange, values: s.d },
      ];
    },
  },
  {
    id: "kdj",
    name: "KDJ",
    group: "Momentum",
    pane: "oscillator",
    guides: [20, 50, 80],
    params: [p("period", "Length", 9), p("kSmooth", "K smoothing", 3), p("dSmooth", "D smoothing", 3)],
    build: (bars, q) => {
      const k = kdj(bars, q.period, q.kSmooth, q.dSmooth);
      return [
        { key: "k", label: "K", color: C.blue, values: k.k, lineWidth: 2 },
        { key: "d", label: "D", color: C.orange, values: k.d },
        { key: "j", label: "J", color: C.magenta, values: k.j },
      ];
    },
  },
  {
    id: "cci",
    name: "CCI",
    group: "Momentum",
    pane: "oscillator",
    guides: [-100, 0, 100],
    params: [p("period", "Length", 20)],
    build: (bars, q) => [
      { key: "cci", label: `CCI ${q.period}`, color: C.aqua, values: cci(bars, q.period), lineWidth: 2 },
    ],
  },
  {
    id: "williams",
    name: "Williams %R",
    group: "Momentum",
    pane: "oscillator",
    guides: [-80, -50, -20],
    params: [p("period", "Length", 14)],
    build: (bars, q) => [
      { key: "wr", label: `%R ${q.period}`, color: C.red, values: williamsR(bars, q.period), lineWidth: 2 },
    ],
  },

  // ── Volume & volatility ─────────────────────────────────────────
  {
    id: "obv",
    name: "On-balance volume",
    group: "Volume & volatility",
    pane: "oscillator",
    params: [],
    build: (bars) => [{ key: "obv", label: "OBV", color: C.aqua, values: obv(bars), lineWidth: 2 }],
  },
  {
    id: "mfi",
    name: "Money flow index",
    group: "Volume & volatility",
    pane: "oscillator",
    guides: [20, 50, 80],
    params: [p("period", "Length", 14)],
    build: (bars, q) => [
      { key: "mfi", label: `MFI ${q.period}`, color: C.yellow, values: mfi(bars, q.period), lineWidth: 2 },
    ],
  },
  {
    id: "atr",
    name: "Average true range",
    group: "Volume & volatility",
    pane: "oscillator",
    params: [p("period", "Length", 14)],
    build: (bars, q) => [
      { key: "atr", label: `ATR ${q.period}`, color: C.orange, values: atr(bars, q.period), lineWidth: 2 },
    ],
  },
];

export const INDICATOR_GROUPS = [
  "Moving averages",
  "Bands & channels",
  "Momentum",
  "Volume & volatility",
] as const;

export function findIndicator(id: string): IndicatorMeta | undefined {
  return INDICATORS.find((i) => i.id === id);
}

/** One indicator placed on the chart. `uid` allows two SMAs at once. */
export interface ActiveIndicator {
  uid: string;
  id: string;
  params: Record<string, number>;
  /** Hidden indicators stay in the list but draw nothing. */
  hidden?: boolean;
}

export function defaultParams(meta: IndicatorMeta): Record<string, number> {
  return Object.fromEntries(meta.params.map((x) => [x.key, x.value]));
}

export function describe(active: ActiveIndicator): string {
  const meta = findIndicator(active.id);
  if (!meta) return active.id;
  const args = meta.params.map((x) => active.params[x.key]).join(", ");
  return args ? `${meta.name} (${args})` : meta.name;
}
