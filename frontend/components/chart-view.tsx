"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ColorType,
  CrosshairMode,
  PriceScaleMode,
  type AutoscaleInfo,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type SeriesType,
  type Time,
  type UTCTimestamp,
  createChart,
} from "lightweight-charts";

import { TradeBoxesPrimitive, type TradeBox } from "@/components/chart/trade-overlay";
import { ChartTypeMenu } from "@/components/chart/type-menu";
import { PriceScaleMenu, type ScaleMode } from "@/components/chart/price-scale-menu";
import { IndicatorModal } from "@/components/chart/indicator-modal";
import { OscillatorPane } from "@/components/chart/oscillator-pane";
import {
  defaultParams,
  findIndicator,
  type ActiveIndicator,
} from "@/lib/indicator-registry";
import { InstrumentSearch } from "@/components/chart/instrument-search";
import { TimeframeMenu } from "@/components/chart/timeframe-menu";
import {
  NATIVE_MINUTES,
  lookbackDays,
  makeInterval,
  resample,
  type Interval,
} from "@/lib/timeframes";
import { buildChart, type ChartKind, type SeriesBuild } from "@/lib/chart-series";
import { GOOGLE_CLIENT_ID, useAuth } from "@/lib/auth";
import { fetchCoverage, fetchKBars } from "@/lib/api";
import type { EvaluateResponse, StrategyRecord } from "@/lib/strategies";
import { evaluateStrategy, listStrategies } from "@/lib/strategies";
import type { Instrument, KBar, Timeframe } from "@/lib/types";
import { INSTRUMENT_META } from "@/lib/types";

interface Props {
  initialInstrument: Instrument;
  initialTimeframe: Timeframe;
}

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

/** Indicator values are bar-aligned with nulls for the warm-up window. */
function toLineData(bars: KBar[], values: (number | null)[]) {
  const out: { time: UTCTimestamp; value: number }[] = [];
  for (let i = 0; i < bars.length; i++) {
    const v = values[i];
    if (v !== null && Number.isFinite(v)) out.push({ time: toUtcSeconds(bars[i].ts), value: v });
  }
  return out;
}

export function ChartView({ initialInstrument, initialTimeframe }: Props) {
  const { user } = useAuth();
  const authed = !GOOGLE_CLIENT_ID || user !== null;
  const [instrument, setInstrument] = useState<Instrument>(initialInstrument);
  const [interval, setInterval] = useState<Interval>(() =>
    makeInterval(NATIVE_MINUTES[initialTimeframe]),
  );
  // The stored timeframe actually requested; folded intervals borrow theirs.
  const timeframe: Timeframe = interval.base;
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
  const [scaleMode, setScaleMode] = useState<ScaleMode>("normal");
  const [indicators, setIndicators] = useState<ActiveIndicator[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const oscillators = indicators.filter((a) => findIndicator(a.id)?.pane === "oscillator");
  const overlays = indicators.filter((a) => findIndicator(a.id)?.pane === "price");
  // Vertical zoom factor for the price axis; 1 = fit the data exactly.
  const priceZoomRef = useRef(1);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceRef = useRef<ISeriesApi<SeriesType> | null>(null);
  const extraRef = useRef<ISeriesApi<SeriesType>[]>([]);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const boxesRef = useRef<TradeBoxesPrimitive | null>(null);
  const overlayRef = useRef<ISeriesApi<SeriesType>[]>([]);
  // Panes read the price chart through a getter so they never hold a stale
  // reference across a remount.
  const getMainChart = useCallback(() => chartRef.current, []);

  // Newest bar the backend holds, tagged with the selection it belongs to.
  // Bars are NOT fetched until this matches the current selection: firing a
  // wall-clock-anchored request first and correcting it once coverage landed
  // meant every switch issued a doomed request (an empty window, so zero
  // bars) whose failure could overwrite the good response that followed.
  const selectionKey = `${instrument}|${timeframe}`;
  const [anchor, setAnchor] = useState<{ key: string; iso: string } | null>(null);
  const anchorReady = anchor?.key === selectionKey;

  useEffect(() => {
    let cancelled = false;
    fetchCoverage(instrument)
      .then((rows) => {
        if (cancelled) return;
        const row = rows.find((r) => r.timeframe === timeframe);
        setAnchor({ key: `${instrument}|${timeframe}`, iso: row?.latest_ts ?? "" });
      })
      .catch(() => {
        // Coverage is an optimisation — fall back to wall-clock, but still
        // tag the selection so the bar fetch is unblocked.
        if (!cancelled) setAnchor({ key: `${instrument}|${timeframe}`, iso: "" });
      });
    return () => {
      cancelled = true;
    };
  }, [instrument, timeframe]);

  const range = useMemo(() => {
    if (!anchorReady || !anchor) return null;
    const end = anchor.iso ? new Date(anchor.iso) : new Date();
    const start = new Date(end);
    start.setUTCDate(end.getUTCDate() - lookbackDays(interval));
    // Ask slightly past the last bar so the newest one is never clipped.
    return { start, end: new Date(end.getTime() + 86_400_000) };
  }, [anchorReady, anchor, interval]);

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

  // Shrinks the auto-computed price range around its midpoint. Reading the
  // factor from a ref means zooming never has to rebuild the series.
  const zoomProvider = useCallback(
    (base: () => AutoscaleInfo | null): AutoscaleInfo | null => {
      const info = base();
      const zoom = priceZoomRef.current;
      if (!info?.priceRange || zoom === 1) return info;
      const { minValue, maxValue } = info.priceRange;
      const mid = (minValue + maxValue) / 2;
      const half = (maxValue - minValue) / 2 / zoom;
      return { ...info, priceRange: { minValue: mid - half, maxValue: mid + half } };
    },
    [],
  );

  // A *new* function identity per call is what invalidates the cached
  // autoscale info; re-applying the same reference is treated as no change
  // and the axis never moves.
  const refreshPriceZoom = useCallback(() => {
    priceRef.current?.applyOptions({
      autoscaleInfoProvider: (base: () => AutoscaleInfo | null) => zoomProvider(base),
    });
  }, [zoomProvider]);

  // Arithmetic / logarithmic / percentage price axis.
  useEffect(() => {
    chartRef.current?.priceScale("right").applyOptions({
      mode:
        scaleMode === "log"
          ? PriceScaleMode.Logarithmic
          : scaleMode === "pct"
            ? PriceScaleMode.Percentage
            : PriceScaleMode.Normal,
    });
  }, [scaleMode]);

  // Wheel over the price axis zooms it. lightweight-charts only scales the
  // price axis by dragging it, so the wheel is wired here and applied by
  // narrowing the autoscale range through the series' own provider — the
  // only public hook that changes the visible price span.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const chart = chartRef.current;
      if (!chart) return;
      const rect = el.getBoundingClientRect();
      const axisWidth = chart.priceScale("right").width();
      // Over the plot: leave it alone, the library's own horizontal (time)
      // zoom is what should happen there.
      if (e.clientX < rect.right - axisWidth) return;
      // Over the axis: price only. Stopping propagation in the capture
      // phase is what keeps lightweight-charts from also zooming time —
      // preventDefault alone still let both fire.
      e.preventDefault();
      e.stopPropagation();
      const factor = e.deltaY > 0 ? 1 / 1.1 : 1.1;
      priceZoomRef.current = Math.min(20, Math.max(0.2, priceZoomRef.current * factor));
      refreshPriceZoom();
    };
    el.addEventListener("wheel", onWheel, { passive: false, capture: true });
    return () => el.removeEventListener("wheel", onWheel, { capture: true });
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
    setLoading(true);
    if (!range) return; // waiting on coverage; nothing to request yet
    const controller = new AbortController();
    let superseded = false;
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
      .then((res) => {
        if (superseded) return;
        // Native intervals pass straight through; the rest are folded here.
        setBars(resample(res.data, interval));
      })
      .catch((e: unknown) => {
        // `superseded` rather than signal.aborted alone: a cancelled request
        // can reject with the server's own error (Railway logs an aborted
        // request as 503) before the abort is observable here, and that
        // stale rejection must never overwrite the newer request's state.
        if (superseded || controller.signal.aborted) return;
        setError(e instanceof Error ? e.message : String(e));
        setBars([]);
      })
      .finally(() => {
        if (!superseded) setLoading(false);
      });
    return () => {
      superseded = true;
      controller.abort();
    };
  }, [instrument, timeframe, interval, range]);

  // Evaluate the selected strategy over the same instrument/range the
  // chart is showing. Selecting a strategy forces the chart onto the
  // strategy's timeframe, so bar times and trade times line up exactly.
  useEffect(() => {
    if (!strategyId || !range) {
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
      if (s) setInterval(makeInterval(NATIVE_MINUTES[s.definition.timeframe]));
    }
  }

  function selectInterval(next: Interval) {
    setInterval(next);
    // A strategy is pinned to its own timeframe — moving off it removes the
    // overlay rather than drawing trades against bars they never traded on.
    const s = strategies.find((x) => x.id === strategyId);
    if (s && NATIVE_MINUTES[s.definition.timeframe] !== next.minutes) setStrategyId("");
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
    priceRef.current?.applyOptions({ autoscaleInfoProvider: zoomProvider });

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
  }, [bars, chartKind, zoomProvider]);

  // Price-pane overlays. Rebuilt wholesale whenever the bars or the active
  // set change — cheaper to reason about than diffing, and these are a
  // handful of line series.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    for (const s of overlayRef.current) chart.removeSeries(s);
    overlayRef.current = [];
    if (!bars) return;
    for (const active of overlays) {
      const meta = findIndicator(active.id);
      if (!meta) continue;
      for (const line of meta.build(bars, active.params)) {
        const series = chart.addLineSeries({
          color: line.color,
          lineWidth: (line.lineWidth ?? 1) as 1 | 2 | 3 | 4,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        series.setData(toLineData(bars, line.values));
        overlayRef.current.push(series);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, indicators, chartKind]);

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
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-bg-panel p-2">
        <InstrumentSearch value={instrument} onChange={setInstrument} />
        <TimeframeMenu value={interval} onChange={selectInterval} />
        <ChartTypeMenu value={chartKind} onChange={setChartKind} />

        <button
          type="button"
          onClick={() => setPickerOpen(true)}
          title="Indicators & strategies"
          className="flex items-center gap-2 rounded-md border border-border bg-bg-hover px-2 py-1.5 font-mono text-xs text-zinc-200 transition hover:text-white focus:border-accent-blue focus:outline-none"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
            <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 20h16" />
              <path d="M4 16l4-5 4 3 4-7 4 4" />
            </g>
          </svg>
          Indicators
          {(indicators.length > 0 || strategyId) && (
            <span className="rounded bg-accent-blue/20 px-1 font-mono text-[10px] text-accent-blue">
              {indicators.length + (strategyId ? 1 : 0)}
            </span>
          )}
        </button>

        <div className="ml-auto flex items-center gap-3 text-xs text-zinc-500">
          <span>
            {INSTRUMENT_META[instrument].name} ·{" "}
            <span className="text-zinc-400">{INSTRUMENT_META[instrument].exchange}</span>
          </span>
          <span>
            {loading || evalLoading ? "Loading…" : bars ? `${bars.length} bars` : ""}
          </span>
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

      {(indicators.length > 0 || strategyId) && (
        <div className="flex flex-wrap items-center gap-1.5">
          {strategyId && (
            <span className="flex items-center gap-1.5 rounded-md border border-accent-blue/30 bg-accent-blue/10 px-2 py-1 text-[11px] text-accent-blue">
              {strategies.find((s) => s.id === strategyId)?.name ?? "strategy"}
              <button
                type="button"
                onClick={() => selectStrategy("")}
                aria-label="Remove strategy overlay"
                className="text-accent-blue/60 transition hover:text-accent-blue"
              >
                ✕
              </button>
            </span>
          )}
          {indicators.map((active) => {
            const meta = findIndicator(active.id);
            if (!meta) return null;
            return (
              <span
                key={active.uid}
                className="flex items-center gap-1.5 rounded-md border border-border bg-bg-panel px-2 py-1 text-[11px] text-zinc-300"
              >
                <span>{meta.name}</span>
                {meta.params.map((param) => (
                  <input
                    key={param.key}
                    type="number"
                    min={param.min}
                    max={param.max}
                    step={param.step ?? 1}
                    value={active.params[param.key]}
                    title={param.label}
                    onChange={(e) => {
                      const next = Number(e.target.value);
                      if (!Number.isFinite(next) || next < param.min || next > param.max) return;
                      setIndicators((list) =>
                        list.map((x) =>
                          x.uid === active.uid
                            ? { ...x, params: { ...x.params, [param.key]: next } }
                            : x,
                        ),
                      );
                    }}
                    className="w-12 rounded border border-border bg-bg-hover px-1 py-0.5 text-center font-mono text-[11px] text-zinc-100 focus:border-accent-blue focus:outline-none"
                  />
                ))}
                <button
                  type="button"
                  onClick={() => setIndicators((list) => list.filter((x) => x.uid !== active.uid))}
                  aria-label={`Remove ${meta.name}`}
                  className="text-zinc-600 transition hover:text-accent-red"
                >
                  ✕
                </button>
              </span>
            );
          })}
        </div>
      )}

      <div className="relative">
        <div
          ref={containerRef}
          className="h-[560px] w-full overflow-hidden rounded-lg border border-border bg-bg-panel"
        />
        <PriceScaleMenu
          mode={scaleMode}
          onMode={setScaleMode}
          onFit={() => {
            priceZoomRef.current = 1;
            refreshPriceZoom();
          }}
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
                {anchor?.iso
                  ? `The backend's newest ${timeframe} bar for this instrument is ${anchor.iso
                      .slice(0, 16)
                      .replace("T", " ")}Z. Try another timeframe.`
                  : "The backend has not ingested this instrument at this timeframe yet."}
              </p>
            </div>
          </div>
        )}
      </div>

      {oscillators.map((active) => (
        <OscillatorPane
          key={active.uid}
          bars={bars}
          active={active}
          getMainChart={getMainChart}
          onRemove={() => setIndicators((list) => list.filter((x) => x.uid !== active.uid))}
        />
      ))}

      <IndicatorModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onAddIndicator={(id) => {
          const meta = findIndicator(id);
          if (!meta) return;
          setIndicators((list) => [
            ...list,
            // uid keeps two copies of the same indicator independent.
            { uid: `${id}-${list.length}-${meta.params.map((x) => x.value).join("_")}`, id, params: defaultParams(meta) },
          ]);
        }}
        strategies={strategies}
        strategyId={strategyId}
        onSelectStrategy={selectStrategy}
        authed={authed}
      />
    </div>
  );
}
