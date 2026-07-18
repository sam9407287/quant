"use client";

import dynamic from "next/dynamic";

import type {
  EquityPoint,
  MonteCarloResponse,
  SeasonalityResponse,
} from "@/lib/backtest";

// Same lazy-load stance as components/research/charts.tsx — echarts
// touches `window` on import.
const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

const baseTheme = {
  backgroundColor: "transparent",
  textStyle: { color: "#a1a7b3", fontFamily: "ui-monospace, monospace" },
  grid: { containLabel: true, left: 36, right: 24, top: 32, bottom: 36 },
};

const AXIS = {
  axisLine: { lineStyle: { color: "#3a4150" } },
  splitLine: { lineStyle: { color: "#1c2029" } },
};

export function EquityChart({ curve }: { curve: EquityPoint[] }) {
  const equity = curve.map((p) => p.equity_usd);
  // Running peak → per-day drawdown, so the pain is visible next to
  // the headline curve.
  let peak = 0;
  const drawdown = equity.map((v) => {
    peak = Math.max(peak, v);
    return -(peak - v);
  });
  const option = {
    ...baseTheme,
    tooltip: { trigger: "axis" },
    legend: { data: ["equity", "drawdown"], textStyle: { color: "#a1a7b3" } },
    xAxis: {
      type: "category",
      data: curve.map((p) => p.date),
      axisLine: AXIS.axisLine,
      axisLabel: { color: "#a1a7b3", interval: Math.floor(curve.length / 10) },
    },
    yAxis: { type: "value", ...AXIS },
    series: [
      {
        name: "equity",
        type: "line",
        data: equity,
        showSymbol: false,
        lineStyle: { color: "#26a69a", width: 1.5 },
        areaStyle: { color: "rgba(38, 166, 154, 0.08)" },
      },
      {
        name: "drawdown",
        type: "line",
        data: drawdown,
        showSymbol: false,
        lineStyle: { color: "#ef5350", width: 1 },
        areaStyle: { color: "rgba(239, 83, 80, 0.12)" },
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 320 }} />;
}

const MONTH_LABELS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function SeasonalityBars({ data }: { data: SeasonalityResponse }) {
  const labels =
    data.bucket_by === "month"
      ? data.buckets.map((b) => MONTH_LABELS[b.bucket - 1])
      : data.buckets.map((b) => WEEKDAY_LABELS[b.bucket]);
  const option = {
    ...baseTheme,
    tooltip: {
      trigger: "axis",
      formatter: (items: Array<{ dataIndex: number; value: number }>) => {
        const b = data.buckets[items[0].dataIndex];
        return (
          `${labels[items[0].dataIndex]}<br/>` +
          `total: $${b.total_pnl_usd.toFixed(0)}<br/>` +
          `mean: $${b.mean_pnl_usd.toFixed(1)}<br/>` +
          `trades: ${b.trade_count} · win ${(b.win_rate * 100).toFixed(0)}%`
        );
      },
    },
    xAxis: {
      type: "category",
      data: labels,
      axisLine: AXIS.axisLine,
      axisLabel: { color: "#a1a7b3" },
    },
    yAxis: { type: "value", ...AXIS },
    series: [
      {
        type: "bar",
        data: data.buckets.map((b) => ({
          value: b.total_pnl_usd,
          itemStyle: { color: b.total_pnl_usd >= 0 ? "#26a69a" : "#ef5350" },
        })),
        barMaxWidth: 36,
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 260 }} />;
}

const PCTS = ["5", "25", "50", "75", "95"];

export function MonteCarloBars({ data }: { data: MonteCarloResponse }) {
  const option = {
    ...baseTheme,
    tooltip: { trigger: "axis" },
    legend: {
      data: ["terminal P&L", "max drawdown"],
      textStyle: { color: "#a1a7b3" },
    },
    xAxis: {
      type: "category",
      data: PCTS.map((p) => `p${p}`),
      axisLine: AXIS.axisLine,
      axisLabel: { color: "#a1a7b3" },
    },
    yAxis: { type: "value", ...AXIS },
    series: [
      {
        name: "terminal P&L",
        type: "bar",
        data: PCTS.map((p) => data.terminal_pnl_percentiles[p]),
        itemStyle: { color: "#5b8def" },
        barMaxWidth: 28,
      },
      {
        name: "max drawdown",
        type: "bar",
        data: PCTS.map((p) => -data.max_drawdown_percentiles[p]),
        itemStyle: { color: "#ef5350" },
        barMaxWidth: 28,
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 260 }} />;
}
