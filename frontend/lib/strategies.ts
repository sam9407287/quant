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
  | "lowest_low";

export type ConditionOp = "cross_above" | "cross_below" | "gt" | "lt";

export interface Operand {
  kind: OperandKind;
  window?: number;
  value?: number | null;
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

export interface StrategyDefinition {
  timeframe: Timeframe;
  default_lookback_days: number;
  entry_long: Condition | null;
  entry_short: Condition | null;
  exit_long: Condition | null;
  exit_short: Condition | null;
  sl: Bracket | null;
  tp: Bracket | null;
}

export interface StrategyRecord {
  id: string;
  created_at: string;
  updated_at: string;
  name: string;
  description: string | null;
  definition: StrategyDefinition;
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

export function evaluateStrategy(
  id: string,
  body: { instrument: string; start: string; end: string; adjustment?: string },
): Promise<EvaluateResponse> {
  return request(`/api/v1/strategies/${id}/evaluate`, {
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
  };
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
