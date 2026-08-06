// Typed client for /api/v1/strategies — hand-maintained mirror of
// app/strategies/schemas.py + app/api/strategies.py.

import { apiError, authHeaders } from "@/lib/http";
import type { Timeframe } from "@/lib/types";

export type OperandKind =
  | "price"
  | "const"
  | "ema"
  | "sma"
  | "rsi"
  | "highest_high"
  | "lowest_low"
  | "macd"
  | "macd_signal"
  | "atr"
  | "roc"
  | "bollinger_upper"
  | "bollinger_lower"
  | "session_high"
  | "session_low";

export type ConditionOp = "cross_above" | "cross_below" | "gt" | "lt";

export interface Operand {
  kind: OperandKind;
  window?: number;
  window2?: number; // macd slow period
  value?: number | null; // const value or bollinger std multiple
  /** session_high/session_low only — "HH:MM:SS" bounds of the window. */
  time_start?: string;
  time_end?: string;
}

export interface Condition {
  op: ConditionOp;
  left: Operand;
  right: Operand;
}

export interface Bracket {
  mode: "pct" | "points";
  value: number;
}

/** The trading session an intraday strategy lives inside; `close` is also
 *  the forced-flat time. Times are "HH:MM:SS". */
export interface SessionSpec {
  tz: string;
  open: string;
  close: string;
}

/** Two resting orders bracketing a level pair, first touch wins — the
 *  order-driven entry an ICT killzone needs. */
export interface StopEntry {
  upper_level: Operand | null;
  lower_level: Operand | null;
  mode: "breakout" | "fade";
  offset_mode: "points" | "pct" | "atr";
  offset_value: number;
  atr_period: number;
  active_from: string | null;
  oco: boolean;
}

export interface StrategyDefinition {
  timeframe: Timeframe;
  default_lookback_days: number;
  entry_long: Condition | null;
  entry_short: Condition | null;
  exit_long: Condition | null;
  exit_short: Condition | null;
  filters: Condition[];
  sl: Bracket | null;
  tp: Bracket | null;
  session?: SessionSpec | null;
  stop_entry?: StopEntry | null;
  max_trades_per_session?: number | null;
}

export interface StrategyRecord {
  id: string;
  created_at: string;
  updated_at: string;
  name: string;
  description: string | null;
  definition: StrategyDefinition;
  /** Google account that owns the row. Null only for pre-auth legacy rows. */
  owner_email: string | null;
}

// ── Sharing ───────────────────────────────────────────────────────

export type AccessStatus = "pending" | "granted" | "denied" | "revoked";

export interface AccessRow {
  id: string;
  status: AccessStatus;
  message: string | null;
  requested_at: string;
  decided_at: string | null;
  seen_at: string | null;
  counterparty_email: string;
  counterparty_name: string | null;
  counterparty_picture: string | null;
}

export interface AccessOverview {
  /** People asking to read my strategies. */
  incoming: AccessRow[];
  /** People I have asked to read. */
  outgoing: AccessRow[];
  pending_count: number;
}

export interface StrategyTrade {
  direction: "long" | "short";
  entry_ts: string;
  entry_price: number;
  exit_ts: string;
  exit_price: number;
  exit_reason: "signal" | "sl" | "tp" | "end";
  sl_level: number | null;
  tp_level: number | null;
  pnl_points: number;
}

export interface StrategyMetrics {
  trade_count: number;
  win_count: number;
  loss_count: number;
  win_rate: number;
  total_pnl_points: number;
  profit_factor: number | null;
  expectancy_points: number;
  max_drawdown_points: number;
  best_trade_points: number;
  worst_trade_points: number;
}

export interface EvaluateResponse {
  strategy_id: string;
  timeframe: Timeframe;
  bar_count: number;
  trades: StrategyTrade[];
  metrics: StrategyMetrics;
  equity_curve: { date: string; equity_points: number }[];
}

export interface SignalTestResponse {
  strategy_id: string;
  timeframe: Timeframe;
  bar_count: number;
  signal_count: number;
  horizon: number;
  win_rate: number;
  mean_return_pct: number;
  median_return_pct: number;
  std_return_pct: number;
  best_return_pct: number;
  worst_return_pct: number;
  avg_path_pct: number[];
  distribution: { center: number; count: number }[];
}

const DEFAULT_API_URL = "https://quant-production-d645.up.railway.app";

function apiUrl(path: string): string {
  const base = process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL;
  return new URL(path, base).toString();
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) throw await apiError(`${init?.method ?? "GET"} ${path}`, res);
  return (await res.json()) as T;
}

export function listStrategies(): Promise<StrategyRecord[]> {
  return request("/api/v1/strategies");
}

export function createStrategy(body: {
  name: string;
  description: string | null;
  definition: StrategyDefinition;
}): Promise<StrategyRecord> {
  return request("/api/v1/strategies", { method: "POST", body: JSON.stringify(body) });
}

export function updateStrategy(
  id: string,
  body: { name: string; description: string | null; definition: StrategyDefinition },
): Promise<StrategyRecord> {
  return request(`/api/v1/strategies/${id}`, { method: "PUT", body: JSON.stringify(body) });
}

export function deleteStrategy(id: string): Promise<{ status: string }> {
  return request(`/api/v1/strategies/${id}`, { method: "DELETE" });
}

/** Duplicate a readable strategy into the caller's own account. */
export function copyStrategy(id: string): Promise<StrategyRecord> {
  return request(`/api/v1/strategies/${id}/copy`, { method: "POST" });
}

export function fetchAccess(): Promise<AccessOverview> {
  return request("/api/v1/strategy-access");
}

export function requestAccess(email: string, message: string | null): Promise<AccessRow> {
  return request("/api/v1/strategy-access/requests", {
    method: "POST",
    body: JSON.stringify({ email, message }),
  });
}

export function decideAccess(
  id: string,
  status: "granted" | "denied" | "revoked",
): Promise<{ status: string }> {
  return request(`/api/v1/strategy-access/requests/${id}/decide`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
}

/** Clears the pending badge without deciding anything. */
export function markAccessSeen(): Promise<{ pending_count: number }> {
  return request("/api/v1/strategy-access/seen", { method: "POST" });
}

export function evaluateStrategy(
  id: string,
  body: { instrument: string; start: string; end: string; adjustment?: string },
): Promise<EvaluateResponse> {
  return request(`/api/v1/strategies/${id}/evaluate`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function signalTestStrategy(
  id: string,
  body: {
    instrument: string;
    start: string;
    end: string;
    horizon: number;
    adjustment?: string;
  },
): Promise<SignalTestResponse> {
  return request(`/api/v1/strategies/${id}/signal-test`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// Shared display helpers (builder + chart overlay)

export function operandLabel(o: Operand): string {
  if (o.kind === "price") return "Price";
  if (o.kind === "const") return String(o.value ?? "?");
  const names: Record<string, string> = {
    ema: "EMA",
    sma: "SMA",
    rsi: "RSI",
    highest_high: "HH",
    lowest_low: "LL",
    macd: "MACD",
    macd_signal: "MACD-sig",
    atr: "ATR",
    roc: "ROC",
    bollinger_upper: "BB-upper",
    bollinger_lower: "BB-lower",
  };
  if (o.kind === "macd" || o.kind === "macd_signal") {
    return `${names[o.kind]}(${o.window ?? 12},${o.window2 ?? 26})`;
  }
  return `${names[o.kind] ?? o.kind}(${o.window ?? "?"})`;
}

const OP_LABEL: Record<ConditionOp, string> = {
  cross_above: "crosses above",
  cross_below: "crosses below",
  gt: ">",
  lt: "<",
};

export function conditionLabel(c: Condition | null): string {
  if (!c) return "—";
  return `${operandLabel(c.left)} ${OP_LABEL[c.op]} ${operandLabel(c.right)}`;
}
