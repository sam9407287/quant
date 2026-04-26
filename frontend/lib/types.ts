/**
 * Mirrors the FastAPI Pydantic models declared in `app/api/`. Kept in sync by
 * hand because the codebase is small enough that an OpenAPI-generated client
 * would add a build step without meaningful safety wins.
 */

export type Instrument = "NQ" | "ES" | "YM" | "RTY";
export const INSTRUMENTS: readonly Instrument[] = ["NQ", "ES", "YM", "RTY"];

export type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1d" | "1w";
export const TIMEFRAMES: readonly Timeframe[] = [
  "1m",
  "5m",
  "15m",
  "1h",
  "4h",
  "1d",
  "1w",
];

export type Adjustment = "raw" | "ratio" | "absolute";
export const ADJUSTMENTS: readonly Adjustment[] = ["raw", "ratio", "absolute"];

export interface KBar {
  ts: string; // ISO 8601 UTC
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface KBarsResponse {
  instrument: string;
  timeframe: string;
  adjustment: string;
  count: number;
  data: KBar[];
}

export interface CoverageRecord {
  instrument: string;
  timeframe: string;
  earliest_ts: string | null;
  latest_ts: string | null;
  bar_count: number;
  gap_count: number;
  last_fetch_ts: string | null;
  last_fetch_ok: boolean;
}
