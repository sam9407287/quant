"use client";

import dynamic from "next/dynamic";

import type { AnalysisResponse, EquityPoint, ForwardBucket, PairAttribution, SensitivityCell } from "@/lib/pairs";

// echarts touches `window` on import — same lazy stance as the other chart modules.
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
const GREEN = "#26a69a";
const RED = "#ef5350";
const BLUE = "#5b8def";
const AMBER = "#e0a458";

function sparse(dates: string[]): { interval: number } {
  return { interval: Math.max(1, Math.floor(dates.length / 10)) };
}

/** Spread (top) and z-score with ±entry/±stop bands (bottom), roll dates marked. */
export function SpreadZChart({ data, entryZ = 2, stopZ = 3.5 }: { data: AnalysisResponse; entryZ?: number; stopZ?: number }) {
  const rollMarks = data.roll_dates.map((d) => ({ xAxis: d, lineStyle: { color: AMBER, type: "dashed", width: 1 } }));
  const option = {
    ...baseTheme,
    tooltip: { trigger: "axis", valueFormatter: (v: number | null) => (v === null ? "—" : v.toFixed(3)) },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: 48, right: 24, top: 28, height: "34%", containLabel: false },
      { left: 48, right: 24, top: "52%", height: "38%", containLabel: false },
    ],
    xAxis: [
      { type: "category", data: data.dates, gridIndex: 0, axisLabel: { show: false }, axisLine: AXIS.axisLine },
      { type: "category", data: data.dates, gridIndex: 1, axisLabel: { color: "#a1a7b3", ...sparse(data.dates) }, axisLine: AXIS.axisLine },
    ],
    yAxis: [
      { type: "value", gridIndex: 0, name: "spread", scale: true, ...AXIS },
      { type: "value", gridIndex: 1, name: "z", ...AXIS },
    ],
    series: [
      {
        name: "spread",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: data.spread,
        showSymbol: false,
        lineStyle: { color: BLUE, width: 1.2 },
        markLine: rollMarks.length ? { symbol: "none", silent: true, data: rollMarks, label: { show: false } } : undefined,
      },
      {
        name: "z",
        type: "line",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: data.zscore,
        showSymbol: false,
        lineStyle: { color: "#e6e8eb", width: 1.2 },
        markLine: {
          symbol: "none",
          silent: true,
          label: { show: true, position: "end", color: "#71717a", fontSize: 10 },
          data: [
            { yAxis: entryZ, lineStyle: { color: RED, type: "dashed" } },
            { yAxis: -entryZ, lineStyle: { color: GREEN, type: "dashed" } },
            { yAxis: stopZ, lineStyle: { color: RED, type: "dotted" } },
            { yAxis: -stopZ, lineStyle: { color: GREEN, type: "dotted" } },
            { yAxis: 0, lineStyle: { color: "#3a4150" } },
          ],
        },
        markArea: {
          silent: true,
          itemStyle: { color: "rgba(239, 83, 80, 0.05)" },
          data: [[{ yAxis: entryZ }, { yAxis: stopZ }]],
        },
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 460 }} notMerge />;
}

/** Rolling hedge ratio and Engle-Granger p-value through time. */
export function RollingBetaPChart({ data, pMax = 0.05 }: { data: AnalysisResponse; pMax?: number }) {
  const option = {
    ...baseTheme,
    tooltip: { trigger: "axis", valueFormatter: (v: number | null) => (v === null ? "—" : v.toFixed(3)) },
    legend: { data: ["β (OLS)", "EG p-value"], textStyle: { color: "#a1a7b3" } },
    xAxis: { type: "category", data: data.dates, axisLine: AXIS.axisLine, axisLabel: { color: "#a1a7b3", ...sparse(data.dates) } },
    yAxis: [
      { type: "value", name: "β", scale: true, ...AXIS },
      { type: "value", name: "p", min: 0, max: 1, ...AXIS, splitLine: { show: false } },
    ],
    series: [
      { name: "β (OLS)", type: "line", data: data.rolling_beta, showSymbol: false, lineStyle: { color: BLUE, width: 1.2 } },
      {
        name: "EG p-value",
        type: "line",
        yAxisIndex: 1,
        data: data.rolling_pvalue,
        showSymbol: false,
        step: "end",
        lineStyle: { color: AMBER, width: 1 },
        areaStyle: { color: "rgba(224, 164, 88, 0.08)" },
        markLine: { symbol: "none", silent: true, data: [{ yAxis: pMax, lineStyle: { color: RED, type: "dashed" } }], label: { show: false } },
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 280 }} notMerge />;
}

/** Mean forward spread change and hit rate per z bucket for one horizon. */
export function ForwardBucketChart({ buckets, horizon }: { buckets: ForwardBucket[]; horizon: number }) {
  const rows = buckets.filter((b) => b.horizon === horizon);
  const option = {
    ...baseTheme,
    tooltip: {
      trigger: "axis",
      formatter: (items: Array<{ dataIndex: number }>) => {
        const b = rows[items[0].dataIndex];
        return (
          `${b.bucket}<br/>n = ${b.count}<br/>mean Δspread: ${b.mean.toFixed(4)}<br/>` +
          `median: ${b.median.toFixed(4)}<br/>IQR: ${b.p25.toFixed(4)} … ${b.p75.toFixed(4)}<br/>` +
          `hit rate (toward mean): ${(b.hit_rate * 100).toFixed(0)}%`
        );
      },
    },
    legend: { data: ["mean Δspread", "hit rate"], textStyle: { color: "#a1a7b3" } },
    xAxis: { type: "category", data: rows.map((b) => b.bucket), axisLine: AXIS.axisLine, axisLabel: { color: "#a1a7b3", rotate: 30 } },
    yAxis: [
      { type: "value", name: "Δspread", ...AXIS },
      { type: "value", name: "hit", min: 0, max: 1, ...AXIS, splitLine: { show: false } },
    ],
    series: [
      {
        name: "mean Δspread",
        type: "bar",
        data: rows.map((b) => ({ value: b.mean, itemStyle: { color: b.mean >= 0 ? GREEN : RED } })),
        barMaxWidth: 28,
      },
      {
        name: "hit rate",
        type: "line",
        yAxisIndex: 1,
        data: rows.map((b) => b.hit_rate),
        lineStyle: { color: AMBER },
        itemStyle: { color: AMBER },
        markLine: { symbol: "none", silent: true, data: [{ yAxis: 0.5, lineStyle: { color: "#3a4150", type: "dashed" } }], label: { show: false } },
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 300 }} notMerge />;
}

export function EquityDrawdownChart({ curve }: { curve: EquityPoint[] }) {
  const option = {
    ...baseTheme,
    tooltip: { trigger: "axis" },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: 60, right: 24, top: 24, height: "52%", containLabel: false },
      { left: 60, right: 24, top: "70%", height: "22%", containLabel: false },
    ],
    xAxis: [
      { type: "category", data: curve.map((p) => p.date), gridIndex: 0, axisLabel: { show: false }, axisLine: AXIS.axisLine },
      { type: "category", data: curve.map((p) => p.date), gridIndex: 1, axisLabel: { color: "#a1a7b3", ...sparse(curve.map((p) => p.date)) }, axisLine: AXIS.axisLine },
    ],
    yAxis: [
      { type: "value", gridIndex: 0, scale: true, ...AXIS, axisLabel: { formatter: (v: number) => `${(v / 1000).toFixed(0)}k` } },
      { type: "value", gridIndex: 1, max: 0, ...AXIS, axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` } },
    ],
    series: [
      {
        name: "equity",
        type: "line",
        data: curve.map((p) => p.equity),
        showSymbol: false,
        lineStyle: { color: GREEN, width: 1.5 },
        areaStyle: { color: "rgba(38, 166, 154, 0.08)" },
      },
      {
        name: "positions",
        type: "bar",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: [],
      },
      {
        name: "drawdown",
        type: "line",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: curve.map((p) => p.drawdown),
        showSymbol: false,
        lineStyle: { color: RED, width: 1 },
        areaStyle: { color: "rgba(239, 83, 80, 0.15)" },
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 380 }} notMerge />;
}

export function AttributionBars({ rows }: { rows: PairAttribution[] }) {
  const option = {
    ...baseTheme,
    tooltip: {
      trigger: "axis",
      formatter: (items: Array<{ dataIndex: number }>) => {
        const r = rows[items[0].dataIndex];
        return `${r.pair_name}<br/>net: $${r.net_pnl.toFixed(0)}<br/>trades: ${r.trade_count}<br/>Sharpe: ${r.sharpe?.toFixed(2) ?? "—"}<br/>max DD: ${(r.max_drawdown * 100).toFixed(1)}%`;
      },
    },
    xAxis: { type: "category", data: rows.map((r) => r.pair_name), axisLine: AXIS.axisLine, axisLabel: { color: "#a1a7b3" } },
    yAxis: { type: "value", ...AXIS, axisLabel: { formatter: (v: number) => `${(v / 1000).toFixed(0)}k` } },
    series: [
      {
        type: "bar",
        data: rows.map((r) => ({ value: r.net_pnl, itemStyle: { color: r.net_pnl >= 0 ? GREEN : RED } })),
        barMaxWidth: 40,
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 240 }} notMerge />;
}

export function CorrelationHeatmap({ pairs, matrix }: { pairs: string[]; matrix: number[][] }) {
  const data: [number, number, number][] = [];
  matrix.forEach((row, i) => row.forEach((v, j) => data.push([j, i, v])));
  const option = {
    ...baseTheme,
    grid: { containLabel: true, left: 24, right: 60, top: 16, bottom: 24 },
    tooltip: { formatter: (p: { value: [number, number, number] }) => `${pairs[p.value[1]]} × ${pairs[p.value[0]]}: ${p.value[2].toFixed(2)}` },
    xAxis: { type: "category", data: pairs, axisLabel: { color: "#a1a7b3", rotate: 30 }, axisLine: AXIS.axisLine },
    yAxis: { type: "category", data: pairs, axisLabel: { color: "#a1a7b3" }, axisLine: AXIS.axisLine },
    visualMap: { min: -1, max: 1, calculable: false, orient: "vertical", right: 0, top: "center", inRange: { color: [GREEN, "#13161d", RED] }, textStyle: { color: "#a1a7b3" } },
    series: [{ type: "heatmap", data, label: { show: true, color: "#e6e8eb", fontSize: 10, formatter: (p: { value: [number, number, number] }) => p.value[2].toFixed(2) } }],
  };
  return <ReactECharts option={option} style={{ height: 80 + pairs.length * 36 }} notMerge />;
}

/** Sharpe over the entry-z × formation grid, one panel per exit rule. */
export function SensitivityHeatmap({ cells, metric = "sharpe" }: { cells: SensitivityCell[]; metric?: "sharpe" | "total_return" | "max_drawdown" }) {
  const zs = Array.from(new Set(cells.map((c) => c.entry_z))).sort((a, b) => a - b);
  const windows = Array.from(new Set(cells.map((c) => c.formation_window))).sort((a, b) => a - b);
  const rules: Array<"threshold" | "cross_zero"> = ["threshold", "cross_zero"];
  const values = cells.map((c) => (metric === "sharpe" ? c.sharpe ?? 0 : c[metric]));
  const lo = Math.min(...values, 0);
  const hi = Math.max(...values, 0);
  const grids = rules.map((_, i) => ({ left: `${6 + i * 50}%`, width: "36%", top: 36, bottom: 48, containLabel: false }));
  const option = {
    ...baseTheme,
    title: rules.map((r, i) => ({ text: `exit: ${r.replace("_", " ")}`, left: `${6 + i * 50}%`, top: 4, textStyle: { color: "#a1a7b3", fontSize: 11 } })),
    tooltip: {
      formatter: (p: { seriesIndex: number; value: [number, number, number] }) => {
        const c = cells.find((x) => x.exit_rule === rules[p.seriesIndex] && x.entry_z === zs[p.value[0]] && x.formation_window === windows[p.value[1]]);
        if (!c) return "";
        return `entry z ${c.entry_z} · window ${c.formation_window}<br/>Sharpe ${c.sharpe?.toFixed(2) ?? "—"} · return ${(c.total_return * 100).toFixed(1)}%<br/>max DD ${(c.max_drawdown * 100).toFixed(1)}% · ${c.trade_count} trades`;
      },
    },
    grid: grids,
    xAxis: rules.map((_, i) => ({ type: "category", gridIndex: i, data: zs.map(String), name: "entry z", nameLocation: "middle", nameGap: 26, axisLabel: { color: "#a1a7b3" }, axisLine: AXIS.axisLine })),
    yAxis: rules.map((_, i) => ({ type: "category", gridIndex: i, data: windows.map(String), name: i === 0 ? "formation" : "", axisLabel: { color: "#a1a7b3" }, axisLine: AXIS.axisLine })),
    visualMap: { min: lo, max: hi, calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: [RED, "#13161d", GREEN] }, textStyle: { color: "#a1a7b3" } },
    series: rules.map((rule, i) => ({
      type: "heatmap",
      xAxisIndex: i,
      yAxisIndex: i,
      data: cells
        .filter((c) => c.exit_rule === rule)
        .map((c) => [zs.indexOf(c.entry_z), windows.indexOf(c.formation_window), metric === "sharpe" ? c.sharpe ?? 0 : c[metric]]),
      label: { show: true, color: "#e6e8eb", fontSize: 10, formatter: (p: { value: [number, number, number] }) => p.value[2].toFixed(2) },
    })),
  };
  return <ReactECharts option={option} style={{ height: 120 + windows.length * 40 }} notMerge />;
}
