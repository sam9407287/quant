/**
 * Mirrors the FastAPI Pydantic models declared in `app/api/`. Kept in sync by
 * hand because the codebase is small enough that an OpenAPI-generated client
 * would add a build step without meaningful safety wins.
 */

export type Instrument =
  | "NQ" | "ES" | "YM" | "RTY"          // US equity indices
  | "NKD"                                // international indices
  | "ZT" | "ZF" | "ZN" | "ZB"           // rates
  | "6E" | "6J" | "6B" | "6A"           // FX
  | "GC" | "SI" | "HG" | "PL" | "PA"    // metals
  | "CL" | "NG" | "HO" | "RB" | "BZ"    // energy
  | "ZC" | "ZS" | "ZW" | "ZL" | "ZM"    // grains
  | "KC" | "SB" | "CC"                   // softs
  | "HE" | "LE"                          // livestock
  | "BTC" | "ETH";                       // crypto

export const INSTRUMENTS: readonly Instrument[] = [
  "NQ", "ES", "YM", "RTY", "NKD",
  "ZT", "ZF", "ZN", "ZB",
  "6E", "6J", "6B", "6A",
  "GC", "SI", "HG", "PL", "PA",
  "CL", "NG", "HO", "RB", "BZ",
  "ZC", "ZS", "ZW", "ZL", "ZM",
  "KC", "SB", "CC",
  "HE", "LE",
  "BTC", "ETH",
];

export type AssetClass =
  | "equity_index" | "intl_index" | "rates" | "fx" | "metal"
  | "energy" | "grain" | "soft" | "livestock" | "crypto";

export interface InstrumentMeta {
  symbol: Instrument;
  name: string;
  assetClass: AssetClass;
}

export const INSTRUMENT_META: Record<Instrument, InstrumentMeta> = {
  NQ:  { symbol: "NQ",  name: "Nasdaq-100",       assetClass: "equity_index" },
  ES:  { symbol: "ES",  name: "S&P 500",          assetClass: "equity_index" },
  YM:  { symbol: "YM",  name: "Dow Jones",        assetClass: "equity_index" },
  RTY: { symbol: "RTY", name: "Russell 2000",     assetClass: "equity_index" },
  NKD: { symbol: "NKD", name: "Nikkei 225 (USD)", assetClass: "intl_index"   },
  ZT:  { symbol: "ZT",  name: "2-Year T-Note",    assetClass: "rates"        },
  ZF:  { symbol: "ZF",  name: "5-Year T-Note",    assetClass: "rates"        },
  ZN:  { symbol: "ZN",  name: "10-Year T-Note",   assetClass: "rates"        },
  ZB:  { symbol: "ZB",  name: "30-Year T-Bond",   assetClass: "rates"        },
  "6E": { symbol: "6E", name: "Euro FX",           assetClass: "fx"           },
  "6J": { symbol: "6J", name: "Japanese Yen",      assetClass: "fx"           },
  "6B": { symbol: "6B", name: "British Pound",     assetClass: "fx"           },
  "6A": { symbol: "6A", name: "Australian Dollar", assetClass: "fx"           },
  GC:  { symbol: "GC",  name: "Gold",              assetClass: "metal"        },
  SI:  { symbol: "SI",  name: "Silver",            assetClass: "metal"        },
  HG:  { symbol: "HG",  name: "Copper",            assetClass: "metal"        },
  PL:  { symbol: "PL",  name: "Platinum",          assetClass: "metal"        },
  PA:  { symbol: "PA",  name: "Palladium",         assetClass: "metal"        },
  CL:  { symbol: "CL",  name: "Crude Oil (WTI)",   assetClass: "energy"       },
  NG:  { symbol: "NG",  name: "Natural Gas",       assetClass: "energy"       },
  HO:  { symbol: "HO",  name: "Heating Oil",       assetClass: "energy"       },
  RB:  { symbol: "RB",  name: "RBOB Gasoline",     assetClass: "energy"       },
  BZ:  { symbol: "BZ",  name: "Brent Crude",       assetClass: "energy"       },
  ZC:  { symbol: "ZC",  name: "Corn",              assetClass: "grain"        },
  ZS:  { symbol: "ZS",  name: "Soybeans",          assetClass: "grain"        },
  ZW:  { symbol: "ZW",  name: "Wheat",             assetClass: "grain"        },
  ZL:  { symbol: "ZL",  name: "Soybean Oil",       assetClass: "grain"        },
  ZM:  { symbol: "ZM",  name: "Soybean Meal",      assetClass: "grain"        },
  KC:  { symbol: "KC",  name: "Coffee",            assetClass: "soft"         },
  SB:  { symbol: "SB",  name: "Sugar No. 11",      assetClass: "soft"         },
  CC:  { symbol: "CC",  name: "Cocoa",             assetClass: "soft"         },
  HE:  { symbol: "HE",  name: "Lean Hogs",         assetClass: "livestock"    },
  LE:  { symbol: "LE",  name: "Live Cattle",       assetClass: "livestock"    },
  BTC: { symbol: "BTC", name: "Bitcoin",           assetClass: "crypto"       },
  ETH: { symbol: "ETH", name: "Ether",             assetClass: "crypto"       },
};

export const ASSET_CLASSES: readonly AssetClass[] = [
  "equity_index", "intl_index", "rates", "fx", "metal",
  "energy", "grain", "soft", "livestock", "crypto",
];

// Derived grouping in ASSET_CLASSES display order.
export const INSTRUMENTS_BY_CLASS: Record<AssetClass, Instrument[]> =
  ASSET_CLASSES.reduce(
    (acc, cls) => {
      acc[cls] = INSTRUMENTS.filter((i) => INSTRUMENT_META[i].assetClass === cls);
      return acc;
    },
    {} as Record<AssetClass, Instrument[]>,
  );

export const ASSET_CLASS_LABEL: Record<AssetClass, string> = {
  equity_index: "US Indices",
  intl_index:   "Intl Indices",
  rates:        "Rates",
  fx:           "FX",
  metal:        "Metals",
  energy:       "Energy",
  grain:        "Grains",
  soft:         "Softs",
  livestock:    "Livestock",
  crypto:       "Crypto",
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
