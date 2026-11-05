// Typed client for /api/v1/pairs — hand-maintained mirror of
// app/pairs/schemas.py + app/api/pairs.py (same convention as lib/backtest.ts).

import { apiError, authHeaders } from "@/lib/http";

const DEFAULT_API_URL = "https://quant-production-d645.up.railway.app";

function url(path: string, params?: Record<string, string | number | undefined>): string {
  const base = process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL;
  const u = new URL(`/api/v1/pairs${path}`, base);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "") u.searchParams.set(k, String(v));
    }
  }
  return u.toString();
}

async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const target = url(path, params);
  const res = await fetch(target, { headers: { Accept: "application/json", ...authHeaders() }, cache: "no-store" });
  if (!res.ok) throw await apiError(target, res);
  return (await res.json()) as T;
}

async function send<T>(method: "POST" | "DELETE", path: string, body?: unknown, params?: Record<string, string | number | undefined>): Promise<T> {
  const target = url(path, params);
  const res = await fetch(target, {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json", ...authHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw await apiError(target, res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ContractSpec {
  code: string;
  multiplier: number;
  tick_size: number;
  micro: boolean;
}

export interface UniverseItem {
  ticker: string;
  name: string;
  group: string;
  kind: "futures" | "etf" | "stock";
  exchange: string;
  settlement_et: string;
  registry_symbol: string | null;
  contracts: ContractSpec[];
}

export interface WatchlistItem {
  id: string;
  name: string;
  y_ticker: string;
  x_ticker: string;
  enabled: boolean;
  overrides: Record<string, unknown>;
  rationale: string | null;
  created_at: string;
}

export interface CoverageItem {
  ticker: string;
  name: string | null;
  kind: string | null;
  first_date: string;
  last_date: string;
  bar_count: number;
  last_fetch: string | null;
}

export interface RefreshResponse {
  tickers: number;
  rows_written: number;
  issues: { ticker: string; date: string | null; kind: string; detail: string }[];
  latest_date: string | null;
  runtime_ms: number;
}

export interface QualificationRules {
  eg_pvalue_max: number;
  half_life_min: number;
  half_life_max: number;
  stability_lookback: number;
  stability_min_ratio: number;
  beta_cv_max: number;
  require_positive_beta: boolean;
  require_johansen: boolean;
}

export type ScanMode = "watchlist" | "universe" | "explicit";
export type PriceSource = "settlement" | "snapshot_1m";

export interface ScanConfig {
  mode: ScanMode;
  pairs?: [string, string][];
  tickers?: string[];
  as_of?: string | null;
  formation_window: number;
  hedge_method: "ols" | "tls";
  z_window_min: number;
  z_window_max: number;
  z_window_multiple: number;
  rules?: Partial<QualificationRules>;
  price_source: PriceSource;
  snapshot_time_et?: string;
  stability_step: number;
  max_pairs?: number;
}

export interface PairStats {
  pair_name: string;
  y_ticker: string;
  x_ticker: string;
  as_of: string;
  n_obs: number;
  alpha: number;
  beta: number;
  beta_tls: number | null;
  beta_johansen: number | null;
  eg_pvalue: number;
  eg_pvalue_reverse: number;
  eg_qvalue: number | null;
  adf_pvalue: number | null;
  johansen_trace: number;
  johansen_crit_95: number;
  johansen_pass: boolean;
  hurst: number | null;
  half_life: number | null;
  half_life_ci_low: number | null;
  half_life_ci_high: number | null;
  z_window: number;
  z: number | null;
  spread_last: number | null;
  spread_mean: number | null;
  spread_std: number | null;
  stability_ratio: number | null;
  beta_cv: number | null;
  corr_returns_60d: number | null;
  qualified: boolean;
  reasons: string[];
  roll_gap_days: number;
  quality_flags: string[];
}

export interface ScanSummary {
  id: string;
  created_at: string;
  as_of: string;
  trigger: "manual" | "daily";
  universe_size: number;
  pair_count: number;
  qualified_count: number;
  runtime_ms: number;
  config: ScanConfig;
}

export interface ScanResponse extends ScanSummary {
  results: PairStats[];
}

export interface ForwardBucket {
  bucket: string;
  z_low: number;
  z_high: number;
  horizon: number;
  count: number;
  mean: number;
  median: number;
  p25: number;
  p75: number;
  hit_rate: number;
}

export interface AnalysisResponse {
  pair_name: string;
  y_ticker: string;
  x_ticker: string;
  stats: PairStats;
  dates: string[];
  log_y: number[];
  log_x: number[];
  spread: (number | null)[];
  zscore: (number | null)[];
  rolling_beta: (number | null)[];
  rolling_pvalue: (number | null)[];
  forward: ForwardBucket[];
  roll_dates: string[];
  settlement_note: string | null;
}

export type ExitRule = "threshold" | "cross_zero";
export type FillMode = "next_open" | "next_close";
export type SizingMode = "fractional" | "integer";
export type WeightScheme = "equal" | "inverse_vol";

export interface SignalRules {
  entry_z: number;
  exit_z: number;
  exit_rule: ExitRule;
  stop_z: number;
  time_stop_half_lives: number;
  breakdown_pvalue: number;
  breakdown_days: number;
  cooldown_days: number;
  freeze_params: boolean;
  require_qualified: boolean;
}

export interface CostModel {
  commission_per_contract: number;
  slippage_ticks: number;
  roll_cost_per_contract: number;
}

export interface PortfolioConfig {
  capital: number;
  gross_leverage: number;
  weight_scheme: WeightScheme;
  max_concurrent: number;
  sizing: SizingMode;
  prefer_micro: boolean;
}

export interface BacktestConfig {
  pairs: [string, string][];
  start: string | null;
  end: string | null;
  formation_window: number;
  hedge_method: "ols" | "tls";
  z_window_min: number;
  z_window_max: number;
  z_window_multiple: number;
  fill: FillMode;
  rules: SignalRules;
  qualification: QualificationRules;
  costs: CostModel;
  portfolio: PortfolioConfig;
  sensitivity: boolean;
  sensitivity_entry_z: number[];
  sensitivity_formation: number[];
  price_source: PriceSource;
}

export interface BacktestMetrics {
  total_return: number;
  annual_return: number;
  annual_vol: number;
  sharpe: number | null;
  sortino: number | null;
  calmar: number | null;
  max_drawdown: number;
  max_drawdown_days: number;
  cvar_95: number;
  trade_count: number;
  win_rate: number | null;
  profit_factor: number | null;
  avg_hold_days: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  exit_mix: Record<string, number>;
  time_in_market: number;
  sharpe_ci_low: number | null;
  sharpe_ci_high: number | null;
  deflated_sharpe_p: number | null;
  trials: number;
  benchmark_return: number | null;
  benchmark_max_drawdown: number | null;
  tradeability_tax: number | null;
}

export interface Trade {
  pair_name: string;
  side: "long_spread" | "short_spread" | "flat";
  entry_date: string;
  exit_date: string | null;
  entry_z: number;
  exit_z: number | null;
  exit_reason: string | null;
  beta: number;
  half_life: number | null;
  days_held: number;
  y_qty: number;
  x_qty: number;
  y_contract: string;
  x_contract: string;
  gross_pnl: number;
  costs: number;
  net_pnl: number;
  notional: number;
  rounding_error_pct: number | null;
}

export interface PairAttribution {
  pair_name: string;
  net_pnl: number;
  trade_count: number;
  win_rate: number | null;
  sharpe: number | null;
  max_drawdown: number;
  qualified_days: number;
  total_days: number;
}

export interface SensitivityCell {
  entry_z: number;
  formation_window: number;
  exit_rule: ExitRule;
  sharpe: number | null;
  total_return: number;
  trade_count: number;
  max_drawdown: number;
}

export interface EquityPoint {
  date: string;
  equity: number;
  drawdown: number;
  positions: number;
}

export interface BacktestResultDoc {
  equity: EquityPoint[];
  trades: Trade[];
  attribution: PairAttribution[];
  correlation: { pairs: string[]; matrix: number[][] };
  sensitivity: SensitivityCell[];
}

export interface BacktestRunRecord {
  id: string;
  created_at: string;
  config: BacktestConfig;
  metrics: BacktestMetrics;
  runtime_ms: number;
  notes: string | null;
}

export interface BacktestRunDetail extends BacktestRunRecord {
  result: BacktestResultDoc;
}

export interface PairState {
  pair_name: string;
  y_ticker: string;
  x_ticker: string;
  side: "flat" | "long_spread" | "short_spread";
  entered_on: string | null;
  entry_params: Record<string, number | null> | null;
  days_held: number;
  breakdown_days: number;
  cooldown_until: string | null;
  last_z: number | null;
  as_of: string | null;
  updated_at: string;
}

export interface Signal {
  id: string;
  signal_date: string;
  pair_name: string;
  event: string;
  side: string;
  payload: Record<string, unknown>;
  notified_at: string | null;
  created_at: string;
}

export interface JobRun {
  id: string;
  run_date: string;
  started_at: string;
  finished_at: string | null;
  status: "running" | "ok" | "no_data" | "error";
  dry_run: boolean;
  summary: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// Defaults (mirror the Pydantic defaults so the forms start where the API does)
// ---------------------------------------------------------------------------

export const DEFAULT_RULES: SignalRules = {
  entry_z: 2.0,
  exit_z: 0.5,
  exit_rule: "threshold",
  stop_z: 3.5,
  time_stop_half_lives: 3,
  breakdown_pvalue: 0.1,
  breakdown_days: 5,
  cooldown_days: 5,
  freeze_params: true,
  require_qualified: true,
};

export const DEFAULT_QUALIFICATION: QualificationRules = {
  eg_pvalue_max: 0.05,
  half_life_min: 3,
  half_life_max: 40,
  stability_lookback: 60,
  stability_min_ratio: 0.8,
  beta_cv_max: 0.5,
  require_positive_beta: true,
  require_johansen: false,
};

export const DEFAULT_COSTS: CostModel = {
  commission_per_contract: 1.25,
  slippage_ticks: 1,
  roll_cost_per_contract: 2.5,
};

export const DEFAULT_PORTFOLIO: PortfolioConfig = {
  capital: 1_000_000,
  gross_leverage: 1,
  weight_scheme: "equal",
  max_concurrent: 10,
  sizing: "fractional",
  prefer_micro: true,
};

export function defaultBacktestConfig(pairs: [string, string][]): BacktestConfig {
  return {
    pairs,
    start: null,
    end: null,
    formation_window: 504,
    hedge_method: "ols",
    z_window_min: 20,
    z_window_max: 120,
    z_window_multiple: 4,
    fill: "next_open",
    rules: { ...DEFAULT_RULES },
    qualification: { ...DEFAULT_QUALIFICATION },
    costs: { ...DEFAULT_COSTS },
    portfolio: { ...DEFAULT_PORTFOLIO },
    sensitivity: false,
    sensitivity_entry_z: [1.5, 2.0, 2.5],
    sensitivity_formation: [252, 504],
    price_source: "settlement",
  };
}

export function defaultScanConfig(mode: ScanMode = "watchlist"): ScanConfig {
  return {
    mode,
    formation_window: 504,
    hedge_method: "ols",
    z_window_min: 20,
    z_window_max: 120,
    z_window_multiple: 4,
    price_source: "settlement",
    stability_step: 1,
  };
}

// ---------------------------------------------------------------------------
// Calls
// ---------------------------------------------------------------------------

export const fetchUniverse = () => get<UniverseItem[]>("/universe");
export const fetchWatchlist = () => get<WatchlistItem[]>("/watchlist");
export const addWatchlistPair = (body: { name: string; y_ticker: string; x_ticker: string; rationale?: string }) =>
  send<WatchlistItem>("POST", "/watchlist", body);
export const removeWatchlistPair = (id: string) => send<void>("DELETE", `/watchlist/${id}`);
export const toggleWatchlistPair = (id: string, enabled: boolean) =>
  send<{ id: string; enabled: boolean }>("POST", `/watchlist/${id}/enabled`, undefined, { enabled: String(enabled) });
export const seedDefaultWatchlist = () => send<{ inserted: number }>("POST", "/watchlist/defaults");

export const fetchCoverage = () => get<CoverageItem[]>("/data/coverage");
export const refreshData = (body: { tickers?: string[]; years?: number; full?: boolean }) =>
  send<RefreshResponse>("POST", "/data/refresh", body);

export const runScan = (config: ScanConfig, notes?: string) => send<ScanResponse>("POST", "/scans", { config, notes });
export const fetchScans = (limit = 30) => get<ScanSummary[]>("/scans", { limit });
export const fetchLatestScan = (trigger?: "manual" | "daily") => get<ScanResponse | null>("/scans/latest", { trigger });
export const fetchScan = (id: string) => get<ScanResponse>(`/scans/${id}`);

export interface AnalysisQuery {
  y: string;
  x: string;
  formation_window?: number;
  as_of?: string;
  lookback_days?: number;
  z_window_min?: number;
  z_window_max?: number;
  z_window_multiple?: number;
  hedge_method?: "ols" | "tls";
  price_source?: PriceSource;
  snapshot_time_et?: string;
}
export const fetchAnalysis = (q: AnalysisQuery) =>
  get<AnalysisResponse>("/analysis", q as unknown as Record<string, string | number | undefined>);

export const runPairsBacktest = (config: BacktestConfig, notes?: string) =>
  send<BacktestRunDetail>("POST", "/backtests", { config, notes });
export const fetchPairsBacktests = (limit = 50) => get<BacktestRunRecord[]>("/backtests", { limit });
export const fetchPairsBacktest = (id: string) => get<BacktestRunDetail>(`/backtests/${id}`);

export const fetchState = () => get<PairState[]>("/state");
export const fetchSignals = (limit = 100) => get<Signal[]>("/signals", { limit });
export const fetchJobs = (limit = 30) => get<JobRun[]>("/jobs", { limit });
export const runDailyJob = (dryRun: boolean) =>
  send<Record<string, unknown>>("POST", "/jobs/daily", undefined, { dry_run: String(dryRun) });

// ---------------------------------------------------------------------------
// Formatting helpers shared by the pages
// ---------------------------------------------------------------------------

export function fmt(v: number | null | undefined, digits = 2, suffix = ""): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}${suffix}`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function usd(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v < 0 ? "-" : "";
  return `${sign}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export function shortTicker(t: string): string {
  return t.replace(/=F$/, "");
}

/** Colour class for a z value: strong when |z| ≥ 2, muted inside ±1. */
export function zTone(z: number | null): string {
  if (z === null) return "text-zinc-500";
  const a = Math.abs(z);
  if (a >= 3) return z > 0 ? "text-accent-red font-semibold" : "text-accent-green font-semibold";
  if (a >= 2) return z > 0 ? "text-accent-red" : "text-accent-green";
  if (a >= 1) return "text-accent-amber";
  return "text-zinc-400";
}
