/**
 * Thin wrapper around the FastAPI backend.
 *
 * All requests funnel through `apiUrl()` so the production URL stays the
 * default (matching the local-dev override pattern documented in
 * `.env.local.example`). Network errors surface as plain `Error` instances
 * with the response status baked into the message; callers that need richer
 * error handling can switch to throwing a custom subclass later.
 */

import type {
  Adjustment,
  CoverageRecord,
  Instrument,
  KBarsResponse,
  Timeframe,
} from "./types";

const DEFAULT_API_URL = "https://quant-production-d645.up.railway.app";

function apiUrl(path: string, params?: Record<string, string | number>): string {
  const base = process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL;
  const url = new URL(path, base);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      url.searchParams.set(k, String(v));
    }
  }
  return url.toString();
}

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`GET ${url} → ${res.status} ${res.statusText}\n${body}`);
  }
  return (await res.json()) as T;
}

export interface KBarsQuery {
  instrument: Instrument;
  timeframe: Timeframe;
  start: Date;
  end: Date;
  adjustment?: Adjustment;
  limit?: number;
}

/**
 * Fetch OHLCV bars at the requested timeframe.
 *
 * Date inputs are sent as ISO 8601 with the trailing `Z` because FastAPI
 * parses `datetime` query params via `datetime.fromisoformat`, which only
 * accepts a fully-qualified timezone marker.
 */
export function fetchKBars(query: KBarsQuery, init?: RequestInit) {
  return getJson<KBarsResponse>(
    apiUrl("/api/v1/kbars", {
      instrument: query.instrument,
      timeframe: query.timeframe,
      start: query.start.toISOString(),
      end: query.end.toISOString(),
      adjustment: query.adjustment ?? "ratio",
      limit: query.limit ?? 5000,
    }),
    init,
  );
}

/**
 * Fetch coverage rows. Pass an instrument to scope results, otherwise the
 * backend returns one row per (instrument, timeframe) for all four symbols.
 */
export function fetchCoverage(instrument: Instrument | "all" = "all", init?: RequestInit) {
  return getJson<CoverageRecord[]>(
    apiUrl("/api/v1/coverage", { instrument }),
    init,
  );
}
