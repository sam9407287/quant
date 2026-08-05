/**
 * Technical indicators, computed in the browser from the OHLCV bars the
 * chart already has. No extra endpoint and no server round-trip: the same
 * array that draws the candles feeds every overlay and oscillator.
 *
 * Everything here is a pure function over `KBar[]`. Values that cannot be
 * computed yet (the warm-up window at the start of a series) are `null`
 * rather than 0, so a chart never draws a fake line to zero.
 *
 * Two families:
 *   overlay    — drawn on the price pane, same units as price
 *   oscillator — drawn in a second pane below, own units
 */

import type { KBar } from "./types";

export type Series = (number | null)[];

// ── primitives ────────────────────────────────────────────────────

export function sma(values: Series, period: number): Series {
  const out: Series = new Array(values.length).fill(null);
  let sum = 0;
  let count = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v === null) {
      // A gap resets the window — averaging across it would be a lie.
      sum = 0;
      count = 0;
      continue;
    }
    sum += v;
    count++;
    if (count > period) {
      const drop = values[i - period];
      if (drop !== null) sum -= drop;
      count = period;
    }
    if (count === period) out[i] = sum / period;
  }
  return out;
}

export function ema(values: Series, period: number): Series {
  const out: Series = new Array(values.length).fill(null);
  const k = 2 / (period + 1);
  let prev: number | null = null;
  let seed = 0;
  let seen = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v === null) continue;
    if (prev === null) {
      // Seed with the SMA of the first `period` values, as most platforms do.
      seed += v;
      seen++;
      if (seen === period) {
        prev = seed / period;
        out[i] = prev;
      }
      continue;
    }
    prev = v * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

export function wma(values: Series, period: number): Series {
  const out: Series = new Array(values.length).fill(null);
  const denom = (period * (period + 1)) / 2;
  for (let i = period - 1; i < values.length; i++) {
    let acc = 0;
    let ok = true;
    for (let j = 0; j < period; j++) {
      const v = values[i - period + 1 + j];
      if (v === null) {
        ok = false;
        break;
      }
      acc += v * (j + 1);
    }
    if (ok) out[i] = acc / denom;
  }
  return out;
}

/** Wilder's smoothing — the average used by RSI, ATR and ADX. */
function wilder(values: Series, period: number): Series {
  const out: Series = new Array(values.length).fill(null);
  let prev: number | null = null;
  let seed = 0;
  let seen = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v === null) continue;
    if (prev === null) {
      seed += v;
      seen++;
      if (seen === period) {
        prev = seed / period;
        out[i] = prev;
      }
      continue;
    }
    prev = (prev * (period - 1) + v) / period;
    out[i] = prev;
  }
  return out;
}

function stdev(values: Series, period: number, means: Series): Series {
  const out: Series = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    const mean = means[i];
    if (mean === null) continue;
    let acc = 0;
    let ok = true;
    for (let j = i - period + 1; j <= i; j++) {
      const v = values[j];
      if (v === null) {
        ok = false;
        break;
      }
      acc += (v - mean) ** 2;
    }
    // Population stdev, matching Bollinger's original definition.
    if (ok) out[i] = Math.sqrt(acc / period);
  }
  return out;
}

const closes = (bars: KBar[]): Series => bars.map((b) => b.close);
const typical = (bars: KBar[]): Series => bars.map((b) => (b.high + b.low + b.close) / 3);

export function trueRange(bars: KBar[]): Series {
  return bars.map((b, i) => {
    if (i === 0) return b.high - b.low;
    const prevClose = bars[i - 1].close;
    return Math.max(b.high - b.low, Math.abs(b.high - prevClose), Math.abs(b.low - prevClose));
  });
}

export function atr(bars: KBar[], period: number): Series {
  return wilder(trueRange(bars), period);
}

// ── overlays ──────────────────────────────────────────────────────

export function bollinger(bars: KBar[], period: number, mult: number) {
  const src = closes(bars);
  const mid = sma(src, period);
  const sd = stdev(src, period, mid);
  return {
    upper: mid.map((m, i) => (m === null || sd[i] === null ? null : m + mult * sd[i]!)),
    middle: mid,
    lower: mid.map((m, i) => (m === null || sd[i] === null ? null : m - mult * sd[i]!)),
  };
}

export function keltner(bars: KBar[], period: number, mult: number, atrPeriod: number) {
  const mid = ema(closes(bars), period);
  const range = atr(bars, atrPeriod);
  return {
    upper: mid.map((m, i) => (m === null || range[i] === null ? null : m + mult * range[i]!)),
    middle: mid,
    lower: mid.map((m, i) => (m === null || range[i] === null ? null : m - mult * range[i]!)),
  };
}

export function donchian(bars: KBar[], period: number) {
  const upper: Series = new Array(bars.length).fill(null);
  const lower: Series = new Array(bars.length).fill(null);
  const middle: Series = new Array(bars.length).fill(null);
  for (let i = period - 1; i < bars.length; i++) {
    let hi = -Infinity;
    let lo = Infinity;
    for (let j = i - period + 1; j <= i; j++) {
      hi = Math.max(hi, bars[j].high);
      lo = Math.min(lo, bars[j].low);
    }
    upper[i] = hi;
    lower[i] = lo;
    middle[i] = (hi + lo) / 2;
  }
  return { upper, middle, lower };
}

/**
 * Session VWAP: the cumulative volume-weighted average price, reset at the
 * start of each UTC day. Anchoring matters — a VWAP that never resets drifts
 * into meaninglessness over a long window.
 */
export function vwap(bars: KBar[]): Series {
  const out: Series = new Array(bars.length).fill(null);
  let day = "";
  let pv = 0;
  let vol = 0;
  const tp = typical(bars);
  for (let i = 0; i < bars.length; i++) {
    const d = bars[i].ts.slice(0, 10);
    if (d !== day) {
      day = d;
      pv = 0;
      vol = 0;
    }
    pv += (tp[i] as number) * bars[i].volume;
    vol += bars[i].volume;
    out[i] = vol > 0 ? pv / vol : null;
  }
  return out;
}

// ── oscillators ───────────────────────────────────────────────────

export function rsi(bars: KBar[], period: number): Series {
  const src = closes(bars);
  const gains: Series = new Array(bars.length).fill(null);
  const losses: Series = new Array(bars.length).fill(null);
  for (let i = 1; i < src.length; i++) {
    const diff = (src[i] as number) - (src[i - 1] as number);
    gains[i] = Math.max(0, diff);
    losses[i] = Math.max(0, -diff);
  }
  const avgGain = wilder(gains.slice(1), period);
  const avgLoss = wilder(losses.slice(1), period);
  const out: Series = new Array(bars.length).fill(null);
  for (let i = 0; i < avgGain.length; i++) {
    const g = avgGain[i];
    const l = avgLoss[i];
    if (g === null || l === null) continue;
    // All-gain windows are RSI 100 by definition, not a divide-by-zero.
    out[i + 1] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
  }
  return out;
}

export function macd(bars: KBar[], fast: number, slow: number, signalPeriod: number) {
  const src = closes(bars);
  const fastLine = ema(src, fast);
  const slowLine = ema(src, slow);
  const line: Series = fastLine.map((f, i) =>
    f === null || slowLine[i] === null ? null : f - slowLine[i]!,
  );
  const signal = ema(line, signalPeriod);
  const histogram: Series = line.map((v, i) =>
    v === null || signal[i] === null ? null : v - signal[i]!,
  );
  return { line, signal, histogram };
}

/** Raw stochastic value: where the close sits in the period's range. */
function rsv(bars: KBar[], period: number): Series {
  const out: Series = new Array(bars.length).fill(null);
  for (let i = period - 1; i < bars.length; i++) {
    let hi = -Infinity;
    let lo = Infinity;
    for (let j = i - period + 1; j <= i; j++) {
      hi = Math.max(hi, bars[j].high);
      lo = Math.min(lo, bars[j].low);
    }
    // A flat range means "no information"; 50 is the neutral convention.
    out[i] = hi === lo ? 50 : ((bars[i].close - lo) / (hi - lo)) * 100;
  }
  return out;
}

export function stochastic(bars: KBar[], kPeriod: number, kSmooth: number, dPeriod: number) {
  const k = sma(rsv(bars, kPeriod), kSmooth);
  return { k, d: sma(k, dPeriod) };
}

/**
 * KDJ — the Chinese-market variant of the stochastic. K and D are 1/3
 * running averages of the raw stochastic, and J = 3K − 2D exaggerates
 * turns, so it routinely leaves the 0–100 band.
 */
export function kdj(bars: KBar[], period: number, kSmooth: number, dSmooth: number) {
  const raw = rsv(bars, period);
  const k: Series = new Array(bars.length).fill(null);
  const d: Series = new Array(bars.length).fill(null);
  let prevK = 50;
  let prevD = 50;
  for (let i = 0; i < bars.length; i++) {
    const r = raw[i];
    if (r === null) continue;
    prevK = (prevK * (kSmooth - 1) + r) / kSmooth;
    prevD = (prevD * (dSmooth - 1) + prevK) / dSmooth;
    k[i] = prevK;
    d[i] = prevD;
  }
  const j: Series = k.map((kv, i) => (kv === null || d[i] === null ? null : 3 * kv - 2 * d[i]!));
  return { k, d, j };
}

export function obv(bars: KBar[]): Series {
  const out: Series = new Array(bars.length).fill(null);
  let acc = 0;
  for (let i = 0; i < bars.length; i++) {
    if (i > 0) {
      const diff = bars[i].close - bars[i - 1].close;
      acc += diff > 0 ? bars[i].volume : diff < 0 ? -bars[i].volume : 0;
    }
    out[i] = acc;
  }
  return out;
}

export function cci(bars: KBar[], period: number): Series {
  const tp = typical(bars);
  const mean = sma(tp, period);
  const out: Series = new Array(bars.length).fill(null);
  for (let i = period - 1; i < bars.length; i++) {
    const m = mean[i];
    if (m === null) continue;
    let dev = 0;
    for (let j = i - period + 1; j <= i; j++) dev += Math.abs((tp[j] as number) - m);
    const meanDev = dev / period;
    out[i] = meanDev === 0 ? 0 : ((tp[i] as number) - m) / (0.015 * meanDev);
  }
  return out;
}

export function williamsR(bars: KBar[], period: number): Series {
  // %R is the stochastic mirrored into −100..0.
  return rsv(bars, period).map((v) => (v === null ? null : v - 100));
}

export function mfi(bars: KBar[], period: number): Series {
  const tp = typical(bars);
  const out: Series = new Array(bars.length).fill(null);
  for (let i = period; i < bars.length; i++) {
    let pos = 0;
    let neg = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const flow = (tp[j] as number) * bars[j].volume;
      const diff = (tp[j] as number) - (tp[j - 1] as number);
      if (diff > 0) pos += flow;
      else if (diff < 0) neg += flow;
    }
    out[i] = neg === 0 ? 100 : 100 - 100 / (1 + pos / neg);
  }
  return out;
}
