"use client";

// Signal Test — measure an idea in isolation before backtesting it.
// Central lesson of the CMT quant curriculum: a backtest entangles the
// idea with exits/stops/sizing, so signal-test first. This page finds
// every entry signal, treats each as day 0, and shows the average
// forward-return path, win rate, dispersion and return distribution.

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import type { SignalTestResponse, StrategyRecord } from "@/lib/strategies";
import { listStrategies, signalTestStrategy } from "@/lib/strategies";
import { INSTRUMENTS, type Instrument } from "@/lib/types";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

const SECTION = "rounded-lg border border-border bg-bg-panel p-5 space-y-4";
const LABEL = "block text-xs font-mono uppercase tracking-wider text-zinc-500 mb-1";
const INPUT =
  "w-full rounded-md border border-border bg-bg-hover px-3 py-2 text-sm font-mono " +
  "text-zinc-100 focus:border-accent-blue focus:outline-none";

const baseTheme = {
  backgroundColor: "transparent",
  textStyle: { color: "#a1a7b3", fontFamily: "ui-monospace, monospace" },
  grid: { containLabel: true, left: 44, right: 24, top: 24, bottom: 36 },
};
const AXIS = {
  axisLine: { lineStyle: { color: "#3a4150" } },
  splitLine: { lineStyle: { color: "#1c2029" } },
};

function defaultDates(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end.getTime() - 365 * 86400_000);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  const color = tone === "pos" ? "text-accent-green" : tone === "neg" ? "text-accent-red" : "text-zinc-100";
  return (
    <div className="rounded-md border border-border bg-bg-hover p-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={`mt-1 font-mono text-lg ${color}`}>{value}</div>
    </div>
  );
}

function ForwardPathChart({ path }: { path: number[] }) {
  const option = {
    ...baseTheme,
    tooltip: {
      trigger: "axis",
      valueFormatter: (v: number) => `${v.toFixed(3)}%`,
    },
    xAxis: {
      type: "category",
      name: "days after signal",
      nameLocation: "middle",
      nameGap: 26,
      nameTextStyle: { color: "#6b7280" },
      data: path.map((_, i) => i),
      axisLine: AXIS.axisLine,
      axisLabel: { color: "#a1a7b3" },
    },
    yAxis: {
      type: "value",
      name: "avg return %",
      nameTextStyle: { color: "#6b7280" },
      ...AXIS,
    },
    series: [
      {
        type: "line",
        data: path,
        showSymbol: false,
        lineStyle: { color: "#26a69a", width: 2 },
        areaStyle: { color: "rgba(38, 166, 154, 0.10)" },
        markLine: {
          silent: true,
          symbol: "none",
          data: [{ yAxis: 0 }],
          lineStyle: { color: "#3a4150", type: "dashed" },
          label: { show: false },
        },
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 300 }} />;
}

function DistributionChart({ dist }: { dist: { center: number; count: number }[] }) {
  const option = {
    ...baseTheme,
    tooltip: { trigger: "axis" },
    xAxis: {
      type: "category",
      name: "terminal return %",
      nameLocation: "middle",
      nameGap: 26,
      nameTextStyle: { color: "#6b7280" },
      data: dist.map((d) => d.center.toFixed(1)),
      axisLine: AXIS.axisLine,
      axisLabel: { color: "#a1a7b3" },
    },
    yAxis: { type: "value", name: "signals", nameTextStyle: { color: "#6b7280" }, ...AXIS },
    series: [
      {
        type: "bar",
        data: dist.map((d) => ({
          value: d.count,
          itemStyle: { color: d.center >= 0 ? "#26a69a" : "#ef5350" },
        })),
        barCategoryGap: "10%",
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 260 }} />;
}

export function SignalTestPanel() {
  const dates = defaultDates();
  const [strategies, setStrategies] = useState<StrategyRecord[]>([]);
  const [strategyId, setStrategyId] = useState("");
  const [instrument, setInstrument] = useState<Instrument>("NQ");
  // Default to the whole record — see the backtest form for why. The date
  // inputs stay for deliberately narrowing a test.
  const [allData, setAllData] = useState(true);
  const [start, setStart] = useState(dates.start);
  const [end, setEnd] = useState(dates.end);
  const [horizon, setHorizon] = useState(21);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SignalTestResponse | null>(null);

  useEffect(() => {
    listStrategies()
      .then((s) => {
        setStrategies(s);
        if (s.length && !strategyId) setStrategyId(s[0].id);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function run() {
    if (!strategyId) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await signalTestStrategy(strategyId, {
          instrument,
          ...(allData
            ? {}
            : {
                start: new Date(start).toISOString(),
                end: new Date(end).toISOString(),
              }),
          horizon,
          adjustment: "ratio",
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const winTone = result && result.win_rate >= 0.55 ? "pos" : undefined;

  return (
    <div className="space-y-6">
      <section className={SECTION}>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <div className="lg:col-span-2">
            <label className={LABEL}>Strategy</label>
            <select className={INPUT} value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
              {strategies.length === 0 && <option value="">No strategies yet</option>}
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.definition.timeframe})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={LABEL}>Instrument</label>
            <select className={INPUT} value={instrument} onChange={(e) => setInstrument(e.target.value as Instrument)}>
              {INSTRUMENTS.map((i) => (
                <option key={i}>{i}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={LABEL}>Start</label>
            <input type="date" className={`${INPUT} disabled:opacity-40`} value={start} disabled={allData} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div>
            <label className={LABEL}>End</label>
            <input type="date" className={`${INPUT} disabled:opacity-40`} value={end} disabled={allData} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <div>
            <label className={LABEL}>Horizon (bars)</label>
            <input type="number" min={1} max={250} className={INPUT} value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} />
          </div>
        </div>
        <label className="flex w-fit cursor-pointer items-center gap-2 text-xs text-zinc-400">
          <input
            type="checkbox"
            checked={allData}
            onChange={(e) => setAllData(e.target.checked)}
            className="h-3.5 w-3.5 accent-accent-blue"
          />
          Use every stored bar — ignore the dates above and cover the whole record
        </label>
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={run}
            disabled={busy || !strategyId}
            className="rounded-md bg-accent-blue px-6 py-2.5 font-semibold text-white transition hover:bg-accent-blue/80 disabled:opacity-40"
          >
            {busy ? "Testing…" : "Run signal test"}
          </button>
          <p className="text-xs text-zinc-500">
            Finds every entry signal, treats each as day 0, measures the forward
            return — no exits, stops or sizing. Test the idea before the backtest.
          </p>
        </div>
      </section>

      {error && (
        <pre className="whitespace-pre-wrap rounded-md border border-accent-red/40 bg-accent-red/10 p-4 text-xs text-accent-red">
          {error}
        </pre>
      )}

      {result && result.signal_count === 0 && (
        <div className="rounded-md border border-border bg-bg-panel p-6 text-center text-sm text-zinc-400">
          No entry signals fired in this range. Widen the dates or check the
          strategy&apos;s entry conditions.
        </div>
      )}

      {result && result.signal_count > 0 && (
        <>
          <section className={SECTION}>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <Tile label="Signals" value={result.signal_count.toLocaleString()} />
              <Tile label="Win rate" value={`${(result.win_rate * 100).toFixed(1)}%`} tone={winTone} />
              <Tile label="Mean return" value={`${result.mean_return_pct.toFixed(2)}%`} tone={result.mean_return_pct >= 0 ? "pos" : "neg"} />
              <Tile label="Median" value={`${result.median_return_pct.toFixed(2)}%`} />
              <Tile label="Std dev" value={`${result.std_return_pct.toFixed(2)}%`} />
              <Tile label="Best / worst" value={`${result.best_return_pct.toFixed(1)} / ${result.worst_return_pct.toFixed(1)}%`} />
            </div>
            <p className="text-xs text-zinc-500">
              {result.bar_count.toLocaleString()} bars scored,{" "}
              {result.start.slice(0, 10)} → {result.end.slice(0, 10)}.{" "}
              Win rate is the share of signals positive at day {result.horizon}.
              A near-straight, rising path means the edge is persistent; if the
              mean and median are close, outliers aren&apos;t distorting it.
            </p>
          </section>

          <section className={SECTION}>
            <h2 className="text-sm font-semibold text-zinc-200">Average forward return path</h2>
            <ForwardPathChart path={result.avg_path_pct} />
          </section>

          <section className={SECTION}>
            <h2 className="text-sm font-semibold text-zinc-200">
              Terminal return distribution (day {result.horizon})
            </h2>
            <DistributionChart dist={result.distribution} />
          </section>
        </>
      )}
    </div>
  );
}
