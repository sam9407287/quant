"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ColorType,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type SeriesType,
  type Time,
  type UTCTimestamp,
  createChart,
} from "lightweight-charts";

import { TradeBoxesPrimitive, type TradeBox } from "@/components/chart/trade-overlay";
import {
  CHART_KINDS,
  GROUP_LABEL,
  buildChart,
  type ChartKind,
  type SeriesBuild,
} from "@/lib/chart-series";
import { GOOGLE_CLIENT_ID, useAuth } from "@/lib/auth";
import { fetchCoverage, fetchKBars } from "@/lib/api";
import type { EvaluateResponse, StrategyRecord } from "@/lib/strategies";
import { evaluateStrategy, listStrategies } from "@/lib/strategies";
import type { AssetClass, Instrument, KBar, Timeframe } from "@/lib/types";
import {
  ASSET_CLASSES,
  ASSET_CLASS_LABEL,
  INSTRUMENT_META,
  INSTRUMENTS_BY_CLASS,
  TIMEFRAMES,
} from "@/lib/types";

interface Props {
  initialInstrument: Instrument;
  initialTimeframe: Timeframe;
}

// Default lookback windows per timeframe, sized so the user gets a useful
// number of candles on first load without overshooting the 50 000-bar API
// cap. Numbers are calibrated against CME Globex session density.
//
// The window ends at the newest bar the backend actually holds, NOT at
// wall-clock now. Anchoring to now produced an empty chart for every
// instrument whenever the fetcher fell behind by more than the lookback —
// at 1m (2 days) that was the whole instrument list within 48 hours.
const DEFAULT_LOOKBACK_DAYS: Record<Timeframe, number> = {
  "1m": 2,
  "5m": 7,
  "15m": 14,
  "1h": 60,
  "4h": 180,
  "1d": 365 * 2,
  "1w": 365 * 5,
};

function toUtcSeconds(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

/** Maps a build spec onto the matching lightweight-charts constructor. */
function addSeries(chart: IChartApi, spec: SeriesBuild): ISeriesApi<SeriesType> {
  const options = spec.options as never;
  switch (spec.seriesKind) {
    case "Candlestick":
      return chart.addCandlestickSeries(options);
    case "Bar":
      return chart.addBarSeries(options);
    case "Line":
      return chart.addLineSeries(options);
    case "Area":
      return chart.addAreaSeries(options);
    case "Baseline":
      return chart.addBaselineSeries(options);
    case "Histogram":
      return chart.addHistogramSeries(options);
  }
}

export function ChartView({ initialInstrument, initialTimeframe }: Props) {
  const { user } = useAuth();
  const authed = !GOOGLE_CLIENT_ID || user !== null;
  const [instrument, setInstrument] = useState<Instrument>(initialInstrument);
  const [activeClass, setActiveClass] = useState<AssetClass>(
    INSTRUMENT_META[initialInstrument].assetClass,
  );
  const [timeframe, setTimeframe] = useState<Timeframe>(initialTimeframe);
  const [bars, setBars] = useState<KBar[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  const [strategies, setStrategies] = useState<StrategyRecord[]>([]);
  const [strategyId, setStrategyId] = useState<string>("");
  const [evalResult, setEvalResult] = useState<EvaluateResponse | null>(null);
  const [evalError, setEvalError] = useState<string | null>(null);
  const [evalLoading, setEvalLoading] = useState(false);

  const [chartKind, setChartKind] = useState<ChartKind>("candles");
  const [buildNote, setBuildNote] = useState<string | null>(null);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceRef = useRef<ISeriesApi<SeriesType> | null>(null);
  const extraRef = useRef<ISeriesApi<SeriesType>[]>([]);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const boxesRef = useRef<TradeBoxesPrimitive | null>(null);

  // Newest bar the backend holds for this instrument+timeframe. Null until
  // coverage loads, and null for combos the backend has never ingested.
  const [dataEnd, setDataEnd] = useState<Date | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDataEnd(null);
    fetchCoverage(instrument)
      .then((rows) => {
        if (cancelled) return;
        const row = rows.find((r) => r.timeframe === timeframe);
        setDataEnd(row?.latest_ts ? new Date(row.latest_ts) : null);
      })
      .catch(() => {
        // Coverage is an optimisation; fall back to wall-clock below.
        if (!cancelled) setDataEnd(null);
      });
    return () => {
      cancelled = true;
    };
  }, [instrument, timeframe]);

  const range = useMemo(() => {
    const end = dataEnd ?? new Date();
    const start = new Date(end);
    start.setUTCDate(end.getUTCDate() - DEFAULT_LOOKBACK_DAYS[timeframe]);
    // Ask slightly past the last bar so the newest one is never clipped.
    const paddedEnd = new Date(end.getTime() + 86_400_000);
    return { start, end: paddedEnd };
  }, [timeframe, dataEnd]);

  // Initialise the chart instance once and tear it down on unmount; resize
  // observation lives in the same effect so it registers exactly once.
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#13161d" },
        textColor: "#a1a7b3",
      },
      grid: {
        vertLines: { color: "#1c2029" },
        horzLines: { color: "#1c2029" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#262b36" },
      timeScale: { borderColor: "#262b36", timeVisible: true, secondsVisible: false },
      autoSize: true,
    });
    // The price series is created by the rebuild effect below, because it
    // depends on the selected chart type. Only the volume pane, which every
    // type shares, is set up here.
    const volumes = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "",
      color: "#5b8def66",
    });
    volumes.priceScale().applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    chartRef.current = chart;
    volumeRef.current = volumes;
    return () => {
      chart.remove();
      chartRef.current = null;
      priceRef.current = null;
      extraRef.current = [];
      volumeRef.current = null;
      boxesRef.current = null;
    };
  }, []);

  // Saved strategies for the overlay picker (only once signed in).
  useEffect(() => {
    if (!authed) {
      setStrategies([]);
      setStrategyId("");
      return;
    }
    listStrategies()
      .then(setStrategies)
      .catch(() => setStrategies([]));
  }, [authed]);

  // Aborts the in-flight bar request when the selection changes. Without
  // it, switching instruments quickly let a slower earlier response land
  // last and overwrite the chart with the wrong instrument's bars — or
  // blank it, if that earlier request was the one that failed.
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchKBars(
      {
        instrument,
        timeframe,
        start: range.start,
        end: range.end,
        adjustment: "ratio",
        limit: 50000,
      },
      { signal: controller.signal },
    )
      .then((res) => setBars(res.data))
      .catch((e: unknown) => {
        if (controller.signal.aborted) return; // superseded, not a failure
        setError(e instanceof Error ? e.message : String(e));
        setBars([]);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [instrument, timeframe, range]);

  // Evaluate the selected strategy over the same instrument/range the
  // chart is showing. Selecting a strategy forces the chart onto the
  // strategy's timeframe, so bar times and trade times line up exactly.
  useEffect(() => {
    if (!strategyId) {
      setEvalResult(null);
      setEvalError(null);
      return;
    }
    let cancelled = false;
    setEvalLoading(true);
    setEvalError(null);
    evaluateStrategy(strategyId, {
      instrument,
      start: range.start.toISOString(),
      end: range.end.toISOString(),
      adjustment: "ratio",
    })
      .then((res) => {
        if (!cancelled) setEvalResult(res);
      })
      .catch((e) => {
        if (!cancelled) {
          setEvalResult(null);
          setEvalError(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => {
        if (!cancelled) setEvalLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [strategyId, instrument, range]);

  function selectStrategy(id: string) {
    setStrategyId(id);
    if (id) {
      const s = strategies.find((x) => x.id === id);
      if (s) setTimeframe(s.definition.timeframe);
    }
  }

  function selectTimeframe(t: Timeframe) {
    setTimeframe(t);
    // A strategy is pinned to its own timeframe — switching away
    // removes the overlay rather than showing misaligned trades.
    const s = strategies.find((x) => x.id === strategyId);
    if (s && s.definition.timeframe !== t) setStrategyId("");
  }

  // Rebuild the price series whenever the bars or the chart type change.
  // Recreating rather than mutating keeps every type on the same code path
  // and avoids leftover options bleeding from the previous type.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !bars) return;

    if (priceRef.current) chart.removeSeries(priceRef.current);
    for (const s of extraRef.current) chart.removeSeries(s);
    priceRef.current = null;
    extraRef.current = [];
    boxesRef.current = null;

    const build = buildChart(chartKind, bars);
    setBuildNote(build.note ?? null);

    const created = build.series.map((spec) => {
      const series = addSeries(chart, spec);
      series.setData(spec.data as never[]);
      return series;
    });
    priceRef.current = created[0] ?? null;
    extraRef.current = created.slice(1);

    if (priceRef.current) {
      const boxes = new TradeBoxesPrimitive(chart, priceRef.current);
      priceRef.current.attachPrimitive(boxes);
      boxesRef.current = boxes;
    }

    // Derived types rewrite the x-axis, so per-bar volume no longer lines up.
    volumeRef.current?.setData(
      build.showVolume
        ? bars.map((b) => ({
            time: toUtcSeconds(b.ts),
            value: b.volume,
            color: b.close >= b.open ? "#26a69a55" : "#ef535055",
          }))
        : [],
    );
    chart.timeScale().fitContent();
  }, [bars, chartKind]);

  // Trade overlay: entry/exit markers + SL/TP position boxes.
  useEffect(() => {
    if (!priceRef.current || !boxesRef.current) return;
    if (!evalResult) {
      priceRef.current.setMarkers([]);
      boxesRef.current.setBoxes([]);
      return;
    }
    const markers: SeriesMarker<Time>[] = [];
    const boxes: TradeBox[] = [];
    const exitText: Record<string, string> = {
      sl: "SL",
      tp: "TP",
      signal: "EXIT",
      end: "END",
    };
    for (const t of evalResult.trades) {
      const entryTime = toUtcSeconds(t.entry_ts);
      const exitTime = toUtcSeconds(t.exit_ts);
      markers.push({
        time: entryTime,
        position: t.direction === "long" ? "belowBar" : "aboveBar",
        color: t.direction === "long" ? "#26a69a" : "#ef5350",
        shape: t.direction === "long" ? "arrowUp" : "arrowDown",
        text: t.direction.toUpperCase(),
      });
      markers.push({
        time: exitTime,
        position: t.direction === "long" ? "aboveBar" : "belowBar",
        color: t.exit_reason === "sl" ? "#ef5350" : t.exit_reason === "tp" ? "#26a69a" : "#a1a7b3",
        shape: t.exit_reason === "sl" ? "square" : "circle",
        text: exitText[t.exit_reason],
      });
      if (t.tp_level !== null) {
        boxes.push({
          from: entryTime,
          to: exitTime,
          priceA: t.entry_price,
          priceB: t.tp_level,
          kind: "profit",
        });
      }
      if (t.sl_level !== null) {
        boxes.push({
          from: entryTime,
          to: exitTime,
          priceA: t.entry_price,
          priceB: t.sl_level,
          kind: "risk",
        });
      }
    }
    markers.sort((a, b) => (a.time as number) - (b.time as number));
    priceRef.current.setMarkers(markers);
    boxesRef.current.setBoxes(boxes);
  }, [evalResult, bars]);

  return (
    <div className="space-y-4">
      <div className="space-y-2 rounded-lg border border-border bg-bg-panel p-3">
        {/* Level 1: asset-class tabs */}
        <div className="flex flex-wrap gap-1">
          {ASSET_CLASSES.map((cls) => (
            <button
              key={cls}
              type="button"
              onClick={() => {
                setActiveClass(cls);
                // Switching category selects its first instrument so the
                // chart always reflects the visible pill row.
                const first = INSTRUMENTS_BY_CLASS[cls][0];
                if (first && INSTRUMENT_META[instrument].assetClass !== cls) {
                  setInstrument(first);
                }
              }}
              className={`rounded-md px-3 py-1.5 font-mono text-xs uppercase tracking-wider transition ${
                activeClass === cls
                  ? "bg-accent-blue/20 text-accent-blue"
                  : "text-zinc-500 hover:bg-bg-hover hover:text-zinc-200"
              }`}
            >
              {ASSET_CLASS_LABEL[cls]}
            </button>
          ))}
        </div>
        {/* Level 2: instruments in the active class + timeframe + strategy */}
        <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1">
          {INSTRUMENTS_BY_CLASS[activeClass].map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setInstrument(s)}
              title={INSTRUMENT_META[s].name}
              className={`rounded-md px-3 py-1.5 font-mono text-xs uppercase tracking-wider transition ${
                instrument === s
                  ? "bg-accent-blue text-white"
                  : "bg-bg-hover text-zinc-400 hover:text-zinc-100"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="h-5 w-px bg-border" />
        <div className="flex gap-1">
          {TIMEFRAMES.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => selectTimeframe(t)}
              className={`rounded-md px-2.5 py-1.5 font-mono text-xs transition ${
                timeframe === t
                  ? "bg-accent-blue text-white"
                  : "bg-bg-hover text-zinc-400 hover:text-zinc-100"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="h-5 w-px bg-border" />
        <select
          value={chartKind}
          onChange={(e) => setChartKind(e.target.value as ChartKind)}
          className="rounded-md border border-border bg-bg-hover px-2 py-1.5 font-mono text-xs text-zinc-200 focus:border-accent-blue focus:outline-none"
          title="Chart type"
        >
          {(["bars", "lines", "areas", "columns", "derived"] as const).map((group) => (
            <optgroup key={group} label={GROUP_LABEL[group]}>
              {CHART_KINDS.filter((k) => k.group === group).map((k) => (
                <option key={k.kind} value={k.kind}>
                  {k.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <div className="h-5 w-px bg-border" />
        <select
          value={strategyId}
          onChange={(e) => selectStrategy(e.target.value)}
          disabled={!authed}
          className="rounded-md border border-border bg-bg-hover px-2 py-1.5 font-mono text-xs text-zinc-200 focus:border-accent-blue focus:outline-none disabled:opacity-50"
          title={authed ? "Overlay a saved strategy" : "Sign in to overlay your strategies"}
        >
          <option value="">{authed ? "No strategy" : "Sign in for strategies"}</option>
          {strategies.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.definition.timeframe})
            </option>
          ))}
        </select>
        <div className="ml-auto flex items-center gap-3 text-xs text-zinc-500">
          <span>
            {INSTRUMENT_META[instrument].name} ·{" "}
            <span className="text-zinc-400">
              {INSTRUMENT_META[instrument].exchange}
            </span>
          </span>
          <span>
            {loading || evalLoading ? "Loading…" : bars ? `${bars.length} bars` : ""}
          </span>
        </div>
        </div>
      </div>

      {evalError && (
        <div className="rounded-md border border-accent-red/40 bg-accent-red/10 p-3 text-sm text-accent-red">
          <span className="font-mono">{evalError}</span>
        </div>
      )}

      {evalResult && (
        <div className="flex flex-wrap gap-x-6 gap-y-1 rounded-lg border border-border bg-bg-panel px-4 py-2 font-mono text-xs text-zinc-400">
          <span>
            trades <span className="text-zinc-100">{evalResult.metrics.trade_count}</span>
          </span>
          <span>
            win rate{" "}
            <span className="text-zinc-100">
              {(evalResult.metrics.win_rate * 100).toFixed(1)}%
            </span>
          </span>
          <span>
            PF{" "}
            <span className="text-zinc-100">
              {evalResult.metrics.profit_factor?.toFixed(2) ?? "—"}
            </span>
          </span>
          <span>
            total{" "}
            <span
              className={
                evalResult.metrics.total_pnl_points >= 0
                  ? "text-accent-green"
                  : "text-accent-red"
              }
            >
              {evalResult.metrics.total_pnl_points.toFixed(1)} pts
            </span>
          </span>
          <span>
            maxDD{" "}
            <span className="text-accent-red">
              {evalResult.metrics.max_drawdown_points.toFixed(1)} pts
            </span>
          </span>
          <span>
            expectancy{" "}
            <span className="text-zinc-100">
              {evalResult.metrics.expectancy_points.toFixed(2)} pts
            </span>
          </span>
        </div>
      )}

      {error && (
        <div className="rounded-md border border-accent-red/40 bg-accent-red/10 p-3 text-sm text-accent-red">
          <span className="font-mono">{error}</span>
        </div>
      )}

      {buildNote && (
        <p className="rounded-md border border-border bg-bg-panel px-3 py-2 font-mono text-[11px] text-zinc-500">
          {buildNote}
        </p>
      )}

      <div className="relative">
        <div
          ref={containerRef}
          className="h-[560px] w-full overflow-hidden rounded-lg border border-border bg-bg-panel"
        />
        {/* A successful request that returns nothing used to render a blank
            panel with no explanation. Say so instead. */}
        {!loading && !error && bars !== null && bars.length === 0 && (
          <div className="pointer-events-none absolute inset-0 grid place-items-center px-6 text-center">
            <div>
              <p className="font-mono text-sm text-zinc-300">
                No {timeframe} bars for {instrument}
              </p>
              <p className="mt-1 text-xs text-zinc-500">
                {dataEnd
                  ? `The backend's newest ${timeframe} bar for this instrument is ${dataEnd
                      .toISOString()
                      .slice(0, 16)
                      .replace("T", " ")}Z. Try another timeframe.`
                  : "The backend has not ingested this instrument at this timeframe yet."}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
