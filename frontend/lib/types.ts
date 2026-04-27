/**
 * Mirrors the FastAPI Pydantic models declared in `app/api/`. Kept in sync by
 * hand because the codebase is small enough that an OpenAPI-generated client
 * would add a build step without meaningful safety wins.
 */

export type Instrument =
  | "NQ" | "ES" | "YM" | "RTY"   // equity indices
  | "GC" | "SI" | "HG"            // metals
  | "CL" | "NG";                  // energy

export const INSTRUMENTS: readonly Instrument[] = [
  "NQ", "ES", "YM", "RTY",
  "GC", "SI", "HG",
  "CL", "NG",
];

export type AssetClass = "equity_index" | "metal" | "energy";

export interface InstrumentMeta {
  symbol: Instrument;
  name: string;
  assetClass: AssetClass;
}

export const INSTRUMENT_META: Record<Instrument, InstrumentMeta> = {
  NQ:  { symbol: "NQ",  name: "Nasdaq-100",     assetClass: "equity_index" },
  ES:  { symbol: "ES",  name: "S&P 500",        assetClass: "equity_index" },
  YM:  { symbol: "YM",  name: "Dow Jones",      assetClass: "equity_index" },
  RTY: { symbol: "RTY", name: "Russell 2000",   assetClass: "equity_index" },
  GC:  { symbol: "GC",  name: "Gold",            assetClass: "metal"        },
  SI:  { symbol: "SI",  name: "Silver",          assetClass: "metal"        },
  HG:  { symbol: "HG",  name: "Copper",          assetClass: "metal"        },
  CL:  { symbol: "CL",  name: "Crude Oil (WTI)", assetClass: "energy"       },
  NG:  { symbol: "NG",  name: "Natural Gas",     assetClass: "energy"       },
};

// Display order: equity → metal → energy. Used by UI groupings.
export const INSTRUMENTS_BY_CLASS: Record<AssetClass, Instrument[]> = {
  equity_index: ["NQ", "ES", "YM", "RTY"],
  metal:        ["GC", "SI", "HG"],
  energy:       ["CL", "NG"],
};

export const ASSET_CLASS_LABEL: Record<AssetClass, string> = {
  equity_index: "Indices",
  metal:        "Metals",
  energy:       "Energy",
};

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
