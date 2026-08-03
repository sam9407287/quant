/**
 * Chart-type registry for the price chart.
 *
 * Every type here is built from the OHLCV bars the API already returns —
 * no extra endpoint, no tick data. A type is either rendered directly by a
 * lightweight-charts series (candles, bar, line, area, baseline, histogram)
 * or derived by a pure transform in this file and then handed to one of
 * those same primitives.
 *
 * What is deliberately absent, and why: volume candles need per-bar width
 * control, footprint / TPO / session volume profile need intrabar (tick)
 * data, and point & figure needs a non-time x-axis. lightweight-charts
 * exposes none of those — they are features of TradingView's proprietary
 * Advanced Charts library, which is not on npm.
 */

import type { KBar } from "./types";

export type ChartKind =
  | "bar"
  | "candles"
  | "hollow"
  | "line"
  | "line_markers"
  | "step"
  | "area"
  | "hlc_area"
  | "baseline"
  | "columns"
  | "high_low"
  | "heikin_ashi"
  | "renko"
  | "line_break"
  | "kagi"
  | "range";

export interface ChartKindMeta {
  kind: ChartKind;
  label: string;
  /** Groups match the separators in the TradingView type menu. */
  group: "bars" | "lines" | "areas" | "columns" | "derived";
}

export const CHART_KINDS: ChartKindMeta[] = [
  { kind: "bar", label: "Bars (OHLC)", group: "bars" },
  { kind: "candles", label: "Candles", group: "bars" },
  { kind: "hollow", label: "Hollow candles", group: "bars" },

  { kind: "line", label: "Line", group: "lines" },
  { kind: "line_markers", label: "Line with markers", group: "lines" },
  { kind: "step", label: "Step line", group: "lines" },

  { kind: "area", label: "Area", group: "areas" },
  { kind: "hlc_area", label: "HLC area", group: "areas" },
  { kind: "baseline", label: "Baseline", group: "areas" },

  { kind: "columns", label: "Columns", group: "columns" },
  { kind: "high_low", label: "High-Low", group: "columns" },

  { kind: "heikin_ashi", label: "Heikin Ashi", group: "derived" },
  { kind: "renko", label: "Renko", group: "derived" },
  { kind: "line_break", label: "Line break", group: "derived" },
  { kind: "kagi", label: "Kagi", group: "derived" },
  { kind: "range", label: "Range", group: "derived" },
];

export const GROUP_LABEL: Record<ChartKindMeta["group"], string> = {
  bars: "Bars",
  lines: "Lines",
  areas: "Areas",
  columns: "Columns",
  derived: "Derived",
};

const UP = "#26a69a";
const DOWN = "#ef5350";
const NEUTRAL = "#5b8def";

type Sec = number;

function secs(iso: string): Sec {
  return Math.floor(new Date(iso).getTime() / 1000);
}

/**
 * lightweight-charts rejects a series whose times are not strictly
 * ascending. Derived types (renko, kagi, …) can emit several points from a
 * single bar, so collisions are nudged forward one second: ordering and the
 * rough time label both stay right.
 */
function monotonic(times: Sec[]): Sec[] {
  const out: Sec[] = [];
  let prev = -Infinity;
  for (const t of times) {
    const v = t <= prev ? prev + 1 : t;
    out.push(v);
    prev = v;
  }
  return out;
}

/** Mean bar range — the auto step for renko / kagi / range bars. */
export function meanRange(bars: KBar[]): number {
  if (!bars.length) return 0;
  const total = bars.reduce((sum, b) => sum + (b.high - b.low), 0);
  return total / bars.length;
}

// ── Derived-series transforms (pure) ──────────────────────────────

export interface Ohlc {
  time: Sec;
  open: number;
  high: number;
  low: number;
  close: number;
}

export function heikinAshi(bars: KBar[]): Ohlc[] {
  const out: Ohlc[] = [];
  let prevOpen = 0;
  let prevClose = 0;
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const close = (b.open + b.high + b.low + b.close) / 4;
    const open = i === 0 ? (b.open + b.close) / 2 : (prevOpen + prevClose) / 2;
    out.push({
      time: secs(b.ts),
      open,
      close,
      high: Math.max(b.high, open, close),
      low: Math.min(b.low, open, close),
    });
    prevOpen = open;
    prevClose = close;
  }
  return out;
}

/**
 * Close-based Renko. A brick is emitted every time the close clears the
 * current level by one `size`; the classic two-brick reversal rule is not
 * applied, which is the common simplified form.
 */
export function renko(bars: KBar[], size: number): Ohlc[] {
  if (!bars.length || size <= 0) return [];
  const out: Ohlc[] = [];
  let base = Math.round(bars[0].close / size) * size;
  for (const b of bars) {
    const t = secs(b.ts);
    while (b.close >= base + size) {
      out.push({ time: t, open: base, close: base + size, high: base + size, low: base });
      base += size;
    }
    while (b.close <= base - size) {
      out.push({ time: t, open: base, close: base - size, high: base, low: base - size });
      base -= size;
    }
  }
  return withMonotonicTimes(out);
}

/** N-line break: a new line only when the close clears the last N lines. */
export function lineBreak(bars: KBar[], n = 3): Ohlc[] {
  if (!bars.length) return [];
  const out: Ohlc[] = [];
  for (const b of bars) {
    const t = secs(b.ts);
    if (!out.length) {
      out.push({ time: t, open: b.open, close: b.close, high: Math.max(b.open, b.close), low: Math.min(b.open, b.close) });
      continue;
    }
    const window = out.slice(-n);
    const hi = Math.max(...window.map((l) => Math.max(l.open, l.close)));
    const lo = Math.min(...window.map((l) => Math.min(l.open, l.close)));
    const prevClose = out[out.length - 1].close;
    if (b.close > hi) {
      out.push({ time: t, open: prevClose, close: b.close, high: b.close, low: prevClose });
    } else if (b.close < lo) {
      out.push({ time: t, open: prevClose, close: b.close, high: prevClose, low: b.close });
    }
  }
  return withMonotonicTimes(out);
}

export interface Point {
  time: Sec;
  value: number;
}

/**
 * Kagi path: the line extends while price runs and turns only after a
 * `reversal`-sized move against it. Rendered as a plain line — the
 * yang/yin thickness switch needs a custom renderer we do not have.
 */
export function kagi(bars: KBar[], reversal: number): Point[] {
  if (!bars.length || reversal <= 0) return [];
  const pts: Point[] = [{ time: secs(bars[0].ts), value: bars[0].close }];
  let dir: 1 | -1 | 0 = 0;
  let extreme = bars[0].close;
  for (const b of bars) {
    const t = secs(b.ts);
    const c = b.close;
    if (dir === 0) {
      if (Math.abs(c - extreme) >= reversal) {
        dir = c > extreme ? 1 : -1;
        extreme = c;
        pts.push({ time: t, value: c });
      }
      continue;
    }
    if ((dir === 1 && c > extreme) || (dir === -1 && c < extreme)) {
      extreme = c;
      pts.push({ time: t, value: c }); // extend the current leg
    } else if (Math.abs(c - extreme) >= reversal) {
      dir = dir === 1 ? -1 : 1;
      extreme = c;
      pts.push({ time: t, value: c }); // turn
    }
  }
  const times = monotonic(pts.map((p) => p.time));
  return pts.map((p, i) => ({ ...p, time: times[i] }));
}

/**
 * Range bars: a bar closes once price has travelled `size`. Built from
 * closes because the API serves bars, not ticks — the intrabar path is
 * unknown, so this is an approximation of a true range chart.
 */
export function rangeBars(bars: KBar[], size: number): Ohlc[] {
  if (!bars.length || size <= 0) return [];
  const out: Ohlc[] = [];
  let open = bars[0].close;
  let high = open;
  let low = open;
  for (const b of bars) {
    high = Math.max(high, b.close);
    low = Math.min(low, b.close);
    if (high - low >= size) {
      out.push({ time: secs(b.ts), open, high, low, close: b.close });
      open = b.close;
      high = b.close;
      low = b.close;
    }
  }
  return withMonotonicTimes(out);
}

function withMonotonicTimes(rows: Ohlc[]): Ohlc[] {
  const times = monotonic(rows.map((r) => r.time));
  return rows.map((r, i) => ({ ...r, time: times[i] }));
}

// ── Series build plan ─────────────────────────────────────────────

export type SeriesKind =
  | "Candlestick"
  | "Bar"
  | "Line"
  | "Area"
  | "Baseline"
  | "Histogram";

export interface SeriesBuild {
  seriesKind: SeriesKind;
  options: Record<string, unknown>;
  data: unknown[];
}

export interface ChartBuild {
  /** series[0] is the primary one; trade markers and boxes attach to it. */
  series: SeriesBuild[];
  /** Derived types rewrite the x-axis, so bar volume no longer lines up. */
  showVolume: boolean;
  /** Shown under the toolbar when the rendering is an approximation. */
  note?: string;
}

const candleColors = {
  upColor: UP,
  downColor: DOWN,
  borderUpColor: UP,
  borderDownColor: DOWN,
  wickUpColor: UP,
  wickDownColor: DOWN,
};

function ohlcFromBars(bars: KBar[]): Ohlc[] {
  return bars.map((b) => ({
    time: secs(b.ts),
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
  }));
}

function closeLine(bars: KBar[]): Point[] {
  return bars.map((b) => ({ time: secs(b.ts), value: b.close }));
}

export function buildChart(kind: ChartKind, bars: KBar[]): ChartBuild {
  const step = meanRange(bars);

  switch (kind) {
    case "candles":
      return {
        series: [{ seriesKind: "Candlestick", options: candleColors, data: ohlcFromBars(bars) }],
        showVolume: true,
      };

    case "hollow":
      // Up bars are drawn as an outline; down bars stay filled. That is
      // exactly what "hollow candles" means.
      return {
        series: [
          {
            seriesKind: "Candlestick",
            options: { ...candleColors, upColor: "rgba(0,0,0,0)" },
            data: ohlcFromBars(bars),
          },
        ],
        showVolume: true,
      };

    case "bar":
      return {
        series: [
          {
            seriesKind: "Bar",
            options: { upColor: UP, downColor: DOWN, thinBars: false },
            data: ohlcFromBars(bars),
          },
        ],
        showVolume: true,
      };

    case "line":
      return {
        series: [
          { seriesKind: "Line", options: { color: NEUTRAL, lineWidth: 2 }, data: closeLine(bars) },
        ],
        showVolume: true,
      };

    case "line_markers":
      return {
        series: [
          {
            seriesKind: "Line",
            options: { color: NEUTRAL, lineWidth: 2, pointMarkersVisible: true, pointMarkersRadius: 3 },
            data: closeLine(bars),
          },
        ],
        showVolume: true,
      };

    case "step":
      return {
        series: [
          {
            seriesKind: "Line",
            // 1 === LineType.WithSteps; imported as a literal to keep this
            // module free of a lightweight-charts import.
            options: { color: NEUTRAL, lineWidth: 2, lineType: 1 },
            data: closeLine(bars),
          },
        ],
        showVolume: true,
      };

    case "area":
      return {
        series: [
          {
            seriesKind: "Area",
            options: {
              lineColor: NEUTRAL,
              topColor: "rgba(91,141,239,0.35)",
              bottomColor: "rgba(91,141,239,0.02)",
              lineWidth: 2,
            },
            data: closeLine(bars),
          },
        ],
        showVolume: true,
      };

    case "hlc_area":
      // Three lines rather than a filled band: lightweight-charts has no
      // band/fill-between series.
      return {
        series: [
          {
            seriesKind: "Line",
            options: { color: NEUTRAL, lineWidth: 2 },
            data: closeLine(bars),
          },
          {
            seriesKind: "Line",
            options: { color: UP, lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false },
            data: bars.map((b) => ({ time: secs(b.ts), value: b.high })),
          },
          {
            seriesKind: "Line",
            options: { color: DOWN, lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false },
            data: bars.map((b) => ({ time: secs(b.ts), value: b.low })),
          },
        ],
        showVolume: true,
        note: "HLC area is drawn as high/low/close lines — the charting library has no filled band series.",
      };

    case "baseline": {
      const closes = bars.map((b) => b.close);
      const mid = closes.length ? closes.reduce((a, c) => a + c, 0) / closes.length : 0;
      return {
        series: [
          {
            seriesKind: "Baseline",
            options: {
              baseValue: { type: "price", price: mid },
              topLineColor: UP,
              topFillColor1: "rgba(38,166,154,0.28)",
              topFillColor2: "rgba(38,166,154,0.02)",
              bottomLineColor: DOWN,
              bottomFillColor1: "rgba(239,83,80,0.02)",
              bottomFillColor2: "rgba(239,83,80,0.28)",
              lineWidth: 2,
            },
            data: closeLine(bars),
          },
        ],
        showVolume: true,
      };
    }

    case "columns": {
      // Histogram bars grow from `base`, which defaults to 0 — for prices
      // that squashes every column against the top of the pane. Anchor the
      // base just under the lowest low so the columns show real variation.
      const lows = bars.map((b) => b.low);
      const highs = bars.map((b) => b.high);
      const lo = lows.length ? Math.min(...lows) : 0;
      const hi = highs.length ? Math.max(...highs) : 0;
      const base = lo - (hi - lo) * 0.08;
      return {
        series: [
          {
            seriesKind: "Histogram",
            options: { priceFormat: { type: "price" }, base },
            data: bars.map((b) => ({
              time: secs(b.ts),
              value: b.close,
              color: b.close >= b.open ? `${UP}cc` : `${DOWN}cc`,
            })),
          },
        ],
        showVolume: true,
      };
    }

    case "high_low":
      // A body spanning low→high with no wick.
      return {
        series: [
          {
            seriesKind: "Candlestick",
            options: { ...candleColors, wickUpColor: "rgba(0,0,0,0)", wickDownColor: "rgba(0,0,0,0)" },
            data: bars.map((b) => ({
              time: secs(b.ts),
              open: b.close >= b.open ? b.low : b.high,
              close: b.close >= b.open ? b.high : b.low,
              high: b.high,
              low: b.low,
            })),
          },
        ],
        showVolume: true,
      };

    case "heikin_ashi":
      return {
        series: [{ seriesKind: "Candlestick", options: candleColors, data: heikinAshi(bars) }],
        showVolume: true,
      };

    case "renko":
      return {
        series: [
          {
            seriesKind: "Candlestick",
            options: { ...candleColors, wickUpColor: "rgba(0,0,0,0)", wickDownColor: "rgba(0,0,0,0)" },
            data: renko(bars, step),
          },
        ],
        showVolume: false,
        note: `Renko bricks of ${step.toFixed(2)} (mean bar range), close-based. Bricks are not evenly spaced in time.`,
      };

    case "line_break":
      return {
        series: [
          { seriesKind: "Candlestick", options: candleColors, data: lineBreak(bars, 3) },
        ],
        showVolume: false,
        note: "3-line break. Lines are not evenly spaced in time.",
      };

    case "kagi":
      return {
        series: [
          {
            seriesKind: "Line",
            options: { color: NEUTRAL, lineWidth: 2 },
            data: kagi(bars, step * 2),
          },
        ],
        showVolume: false,
        note: `Kagi with a ${(step * 2).toFixed(2)} reversal. Drawn at one thickness — the yang/yin switch needs a custom renderer.`,
      };

    case "range":
      return {
        series: [
          { seriesKind: "Candlestick", options: candleColors, data: rangeBars(bars, step) },
        ],
        showVolume: false,
        note: `Range bars of ${step.toFixed(2)}, built from closes — the API serves bars, not ticks, so the intrabar path is approximated.`,
      };
  }
}
