// Typed client for /api/v1/backtest — hand-maintained mirror of
// app/backtest/{params,schemas}.py, same convention as lib/ml.ts.

import { apiError, authHeaders } from "@/lib/http";

export interface SessionClock {
  tz: string;
  range_start: string; // "HH:MM"
  range_end: string;
  orders_place: string;
  eod_flat: string;
}

export type DirectionMode = "fade" | "breakout";
export type OffsetMode = "points" | "pct" | "atr";

export interface BacktestParams {
  instrument: string;
  point_value_usd: number;
  contracts: number;
  start: string; // "YYYY-MM-DD"
  end: string;
  clock: SessionClock;
  direction_mode: DirectionMode;
  entry_offset_mode: OffsetMode;
  entry_offset_value: number;
  sl_mode: OffsetMode;
  sl_value: number;
  rrr: number | null;
  tp_points: number | null;
  atr_period: number;
  slippage_points_per_side: number;
  commission_usd_per_rt: number;
}

export interface Metrics {
  session_count: number;
  trade_count: number;
  win_count: number;
  loss_count: number;
  win_rate: number;
  total_pnl_usd: number;
  profit_factor: number | null;
  expectancy_usd: number;
  max_drawdown_usd: number;
  sharpe_annualized: number | null;
  best_day_usd: number;
  worst_day_usd: number;
}

export interface EquityPoint {
  date: string;
  equity_usd: number;
}

export interface TradeRecord {
  session_date: string;
  exit_reason: string;
  direction: string | null;
  entry_ts: string | null;
  entry_price: number | null;
  exit_ts: string | null;
  exit_price: number | null;
  pnl_points: number;
  pnl_usd: number;
  mae_points: number;
  mfe_points: number;
  range_high: number | null;
  range_low: number | null;
}

export interface RunResponse {
  run_id: string;
  runtime_ms: number;
  metrics: Metrics;
  equity_curve: EquityPoint[];
  trades: TradeRecord[];
}

export interface SeasonalityBucket {
  bucket: number;
  trade_count: number;
  total_pnl_usd: number;
  mean_pnl_usd: number;
  win_rate: number;
}

export interface SeasonalityResponse {
  bucket_by: "month" | "weekday";
  buckets: SeasonalityBucket[];
}

export interface MonteCarloResponse {
  n_sims: number;
  horizon_days: number;
  method: "bootstrap" | "permutation";
  terminal_pnl_percentiles: Record<string, number>;
  max_drawdown_percentiles: Record<string, number>;
  prob_terminal_loss: number;
  prob_ruin: number | null;
}

const DEFAULT_API_URL = "https://quant-production-d645.up.railway.app";

function apiUrl(path: string): string {
  const base = process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL;
  return new URL(path, base).toString();
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(apiUrl(path), {
    headers: { Accept: "application/json", ...authHeaders() },
  });
  if (!res.ok) throw await apiError(`GET ${path}`, res);
  return (await res.json()) as T;
}

export async function runBacktest(
  params: BacktestParams,
  notes?: string,
): Promise<RunResponse> {
  const res = await fetch(apiUrl("/api/v1/backtest/runs"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({ params, notes: notes || null }),
  });
  if (!res.ok) throw await apiError("POST /backtest/runs", res);
  return (await res.json()) as RunResponse;
}

export function fetchSeasonality(
  runId: string,
  bucket: "month" | "weekday",
): Promise<SeasonalityResponse> {
  return getJson(`/api/v1/backtest/runs/${runId}/seasonality?bucket=${bucket}`);
}

export function fetchMonteCarlo(
  runId: string,
  opts: { nSims?: number; method?: "bootstrap" | "permutation"; initialCapital?: number } = {},
): Promise<MonteCarloResponse> {
  const q = new URLSearchParams();
  if (opts.nSims) q.set("n_sims", String(opts.nSims));
  if (opts.method) q.set("method", opts.method);
  if (opts.initialCapital) q.set("initial_capital", String(opts.initialCapital));
  const qs = q.toString();
  return getJson(`/api/v1/backtest/runs/${runId}/montecarlo${qs ? `?${qs}` : ""}`);
}
