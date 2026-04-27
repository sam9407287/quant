"use client";

import dynamic from "next/dynamic";

import type { PredictionPoint, ProjectionPoint } from "@/lib/ml";

// echarts-for-react reaches for `window` on import. Lazy-load with SSR
// disabled so the page can still server-render its shell.
const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

const baseTheme = {
  backgroundColor: "transparent",
  textStyle: { color: "#a1a7b3", fontFamily: "ui-monospace, monospace" },
  grid: { containLabel: true, left: 36, right: 24, top: 32, bottom: 36 },
};

// ---------------------------------------------------------------------
// Regression — predicted vs actual time series
// ---------------------------------------------------------------------

export function RegressionTimeSeries({ data }: { data: PredictionPoint[] }) {
  const option = {
    ...baseTheme,
    tooltip: { trigger: "axis" },
    legend: { data: ["actual", "predicted"], textStyle: { color: "#a1a7b3" } },
    xAxis: {
      type: "category",
      data: data.map((d) => d.ts.replace("T", " ").slice(0, 16)),
      axisLine: { lineStyle: { color: "#3a4150" } },
      axisLabel: { color: "#a1a7b3", interval: Math.floor(data.length / 10) },
    },
    yAxis: {
      type: "value",
      axisLine: { lineStyle: { color: "#3a4150" } },
      splitLine: { lineStyle: { color: "#1c2029" } },
    },
    series: [
      {
        name: "actual",
        type: "line",
        data: data.map((d) => d.actual),
        showSymbol: false,
        lineStyle: { color: "#a1a7b3", width: 1 },
      },
      {
        name: "predicted",
        type: "line",
        data: data.map((d) => d.predicted),
        showSymbol: false,
        lineStyle: { color: "#5b8def", width: 1.5 },
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 320 }} />;
}

// ---------------------------------------------------------------------
// Predicted vs actual scatter — diagonal = perfect prediction
// ---------------------------------------------------------------------

export function PredictedVsActualScatter({ data }: { data: PredictionPoint[] }) {
  const points = data.map((d) => [d.actual, d.predicted]);
  const min = Math.min(...points.flat());
  const max = Math.max(...points.flat());
  const option = {
    ...baseTheme,
    tooltip: {
      trigger: "item",
      formatter: (p: { data: [number, number] }) =>
        `actual ${p.data[0].toFixed(5)}<br/>pred ${p.data[1].toFixed(5)}`,
    },
    xAxis: {
      type: "value",
      name: "actual",
      nameTextStyle: { color: "#a1a7b3" },
      axisLine: { lineStyle: { color: "#3a4150" } },
      splitLine: { lineStyle: { color: "#1c2029" } },
    },
    yAxis: {
      type: "value",
      name: "predicted",
      nameTextStyle: { color: "#a1a7b3" },
      axisLine: { lineStyle: { color: "#3a4150" } },
      splitLine: { lineStyle: { color: "#1c2029" } },
    },
    series: [
      {
        type: "scatter",
        data: points,
        itemStyle: { color: "#5b8def" },
        symbolSize: 4,
      },
      {
        type: "line",
        data: [
          [min, min],
          [max, max],
        ],
        showSymbol: false,
        lineStyle: { color: "#3a4150", type: "dashed" },
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 320 }} />;
}

// ---------------------------------------------------------------------
// Feature importance bar
// ---------------------------------------------------------------------

export function FeatureImportanceBar({
  importance,
}: {
  importance: Record<string, number>;
}) {
  const entries = Object.entries(importance).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const option = {
    ...baseTheme,
    grid: { ...baseTheme.grid, left: 140 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: {
      type: "value",
      axisLine: { lineStyle: { color: "#3a4150" } },
      splitLine: { lineStyle: { color: "#1c2029" } },
    },
    yAxis: {
      type: "category",
      data: entries.map(([k]) => k),
      axisLine: { lineStyle: { color: "#3a4150" } },
      axisLabel: { color: "#a1a7b3" },
    },
    series: [
      {
        type: "bar",
        data: entries.map(([, v]) => v),
        itemStyle: { color: "#26a69a" },
      },
    ],
  };
  return (
    <ReactECharts option={option} style={{ height: Math.max(200, entries.length * 28) }} />
  );
}

// ---------------------------------------------------------------------
// Clustering — 2D projection scatter coloured by cluster label
// ---------------------------------------------------------------------

const CLUSTER_COLORS = [
  "#5b8def", "#26a69a", "#ef5350", "#f0ad4e",
  "#9b59b6", "#16a085", "#e67e22", "#34495e",
];

export function ClusterScatter({ points }: { points: ProjectionPoint[] }) {
  const labels = Array.from(new Set(points.map((p) => p.label))).sort((a, b) => a - b);
  const series = labels.map((label, i) => ({
    name: label === -1 ? "noise" : `cluster ${label}`,
    type: "scatter",
    data: points
      .filter((p) => p.label === label)
      .map((p) => [p.x, p.y, p.target, p.ts]),
    itemStyle: {
      color:
        label === -1
          ? "#3a4150"
          : CLUSTER_COLORS[i % CLUSTER_COLORS.length],
    },
    symbolSize: 5,
  }));

  const option = {
    ...baseTheme,
    legend: {
      data: series.map((s) => s.name),
      textStyle: { color: "#a1a7b3" },
      top: 0,
    },
    tooltip: {
      trigger: "item",
      formatter: (p: { data: [number, number, number, string] }) =>
        `(${p.data[0].toFixed(2)}, ${p.data[1].toFixed(2)})<br/>` +
        `target ${p.data[2].toFixed(5)}<br/>${p.data[3].slice(0, 16)}`,
    },
    xAxis: {
      type: "value",
      name: "PC1",
      nameTextStyle: { color: "#a1a7b3" },
      axisLine: { lineStyle: { color: "#3a4150" } },
      splitLine: { lineStyle: { color: "#1c2029" } },
    },
    yAxis: {
      type: "value",
      name: "PC2",
      nameTextStyle: { color: "#a1a7b3" },
      axisLine: { lineStyle: { color: "#3a4150" } },
      splitLine: { lineStyle: { color: "#1c2029" } },
    },
    series,
  };
  return <ReactECharts option={option} style={{ height: 480 }} />;
}
