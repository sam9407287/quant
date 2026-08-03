/**
 * Interval model for the chart.
 *
 * The API stores exactly seven timeframes (see `app/api/kbars.py`). Anything
 * else the user picks is folded client-side from the largest stored timeframe
 * that divides it evenly — 30m from 15m, 6h from 1h, 3d from 1d — so a custom
 * interval costs no backend work and no extra request.
 *
 * Sub-minute intervals (ticks, seconds) are NOT offered: the database has no
 * data below 1m, so there is nothing to fold from.
 */

import type { KBar, Timeframe } from "./types";

export const NATIVE_MINUTES: Record<Timeframe, number> = {
  "1m": 1,
  "5m": 5,
  "15m": 15,
  "1h": 60,
  "4h": 240,
  "1d": 1440,
  "1w": 10080,
};

// Lookback per stored timeframe, sized for a useful bar count on first load
// without overshooting the 50 000-bar API cap.
const NATIVE_LOOKBACK_DAYS: Record<Timeframe, number> = {
  "1m": 2,
  "5m": 7,
  "15m": 14,
  "1h": 60,
  "4h": 180,
  "1d": 365 * 2,
  "1w": 365 * 5,
};

export interface Interval {
  /** Stable id, also what the user types: "30m", "6h", "3d", "1M". */
  id: string;
  label: string;
  /** Minutes per bar. Months use 0 — they are grouped by calendar instead. */
  minutes: number;
  /** Stored timeframe to request and fold from. */
  base: Timeframe;
  /** True when the API serves this interval directly (no folding). */
  native: boolean;
  /** Calendar-month buckets rather than fixed-length ones. */
  monthly?: boolean;
}

const NATIVES = Object.keys(NATIVE_MINUTES) as Timeframe[];

/** Largest stored timeframe that divides `minutes` evenly. */
export function baseFor(minutes: number): Timeframe {
  const usable = NATIVES.filter(
    (tf) => NATIVE_MINUTES[tf] <= minutes && minutes % NATIVE_MINUTES[tf] === 0,
  ).sort((a, b) => NATIVE_MINUTES[b] - NATIVE_MINUTES[a]);
  return usable[0] ?? "1m";
}

function labelFor(minutes: number): string {
  if (minutes % 10080 === 0) {
    const n = minutes / 10080;
    return n === 1 ? "1 week" : `${n} weeks`;
  }
  if (minutes % 1440 === 0) {
    const n = minutes / 1440;
    return n === 1 ? "1 day" : `${n} days`;
  }
  if (minutes % 60 === 0) {
    const n = minutes / 60;
    return n === 1 ? "1 hour" : `${n} hours`;
  }
  return minutes === 1 ? "1 minute" : `${minutes} minutes`;
}

function idFor(minutes: number): string {
  if (minutes % 10080 === 0) return `${minutes / 10080}w`;
  if (minutes % 1440 === 0) return `${minutes / 1440}d`;
  if (minutes % 60 === 0) return `${minutes / 60}h`;
  return `${minutes}m`;
}

export function makeInterval(minutes: number): Interval {
  const base = baseFor(minutes);
  return {
    id: idFor(minutes),
    label: labelFor(minutes),
    minutes,
    base,
    native: NATIVE_MINUTES[base] === minutes,
  };
}

export const MONTHLY: Interval = {
  id: "1M",
  label: "1 month",
  minutes: 0,
  base: "1d",
  native: false,
  monthly: true,
};

/**
 * Parse a user-typed interval. Accepts "45", "45m", "8h", "3d", "2w" and the
 * month shorthand "1M" (capital M — lowercase m is minutes).
 */
export function parseInterval(raw: string): Interval | null {
  const text = raw.trim();
  if (!text) return null;
  if (/^1\s*M$/.test(text)) return MONTHLY;
  const m = /^(\d+)\s*([mhdwM]?)$/.exec(text);
  if (!m) return null;
  const n = Number(m[1]);
  if (!Number.isFinite(n) || n <= 0) return null;
  const unit = m[2] || "m";
  if (unit === "M") return n === 1 ? MONTHLY : null;
  const minutes = n * { m: 1, h: 60, d: 1440, w: 10080 }[unit as "m" | "h" | "d" | "w"];
  // Above ~3 months a fold from daily bars stops being meaningful, and below
  // a minute there is simply no stored data.
  if (minutes < 1 || minutes > 10080 * 13) return null;
  return makeInterval(minutes);
}

export const PRESET_GROUPS: { title: string; intervals: Interval[] }[] = [
  { title: "Minutes", intervals: [1, 2, 3, 5, 10, 15, 30, 45].map(makeInterval) },
  { title: "Hours", intervals: [60, 120, 180, 240, 360, 480, 720].map(makeInterval) },
  {
    title: "Days",
    intervals: [makeInterval(1440), makeInterval(2880), makeInterval(4320), makeInterval(10080), MONTHLY],
  },
];

/** Days of history to request so a fold still yields a full-looking chart. */
export function lookbackDays(interval: Interval): number {
  if (interval.monthly) return 365 * 12;
  const baseDays = NATIVE_LOOKBACK_DAYS[interval.base];
  const multiple = interval.minutes / NATIVE_MINUTES[interval.base];
  return Math.min(baseDays * multiple, 365 * 20);
}

// ── Folding ───────────────────────────────────────────────────────

function foldGroup(group: KBar[]): KBar {
  return {
    ts: group[0].ts,
    open: group[0].open,
    high: Math.max(...group.map((b) => b.high)),
    low: Math.min(...group.map((b) => b.low)),
    close: group[group.length - 1].close,
    volume: group.reduce((sum, b) => sum + b.volume, 0),
  };
}

/**
 * Fold stored bars up to the requested interval. Native intervals pass
 * through untouched. Bars are assumed ascending by time, which the API
 * guarantees.
 */
export function resample(bars: KBar[], interval: Interval): KBar[] {
  if (interval.native || bars.length === 0) return bars;

  const keyOf = interval.monthly
    ? (ts: string) => ts.slice(0, 7) // YYYY-MM
    : (ts: string) => {
        const size = interval.minutes * 60_000;
        return String(Math.floor(new Date(ts).getTime() / size) * size);
      };

  const out: KBar[] = [];
  let group: KBar[] = [];
  let key: string | null = null;
  for (const bar of bars) {
    const k = keyOf(bar.ts);
    if (key === null || k === key) {
      group.push(bar);
      key = k;
      continue;
    }
    out.push(foldGroup(group));
    group = [bar];
    key = k;
  }
  if (group.length) out.push(foldGroup(group));
  return out;
}
