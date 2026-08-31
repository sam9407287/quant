"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ColorType,
  CrosshairMode,
  PriceScaleMode,
  type AutoscaleInfo,
  type IChartApi,
  type LogicalRange,
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
import { IndicatorLegendRow } from "@/components/chart/indicator-legend";
import { IndicatorSettings } from "@/components/chart/indicator-settings";
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

/**
 * Raw (unfolded) bars plus how far back they reach.
 *
 * The chart used to hold exactly one fixed lookback window, so it could only
 * ever draw a fixed number of candles — scrolling left ran into a wall of
 * empty canvas. Panning near the left edge now *extends* this backwards a
 * chunk at a time instead of replacing it, so history is bounded only by
 * what the backend actually stores.
 */
interface History {
  /** Selection these bars belong to; a mismatch means they are stale. */
  key: string;
  bars: KBar[];
  /** Earliest instant already requested — the next chunk ends here. */
  from: Date;
  /** Newest instant requested; `until - from` is the span loaded so far. */
  until: Date;
  /** Nothing older than `from` exists; stop asking. */
  exhausted: boolean;
}

/**
 * Start fetching once the viewport's left edge is within this many bars of
 * the oldest one held. Firing early keeps the request ahead of the pan, so
 * the wall never becomes visible.
 */
const BACKFILL_TRIGGER_BARS = 30;

/** Largest chunk that stays under the endpoint's own 50 000-bar ceiling. */
function chunkCeilingDays(interval: Interval): number {
  const barsPerDay = 1440 / NATIVE_MINUTES[interval.base];
  return Math.max(1, Math.floor(45_000 / barsPerDay));
}

/**
 * Days of history the next chunk should reach for.
 *
 * Fixed-size chunks are technically enough to reach the start of the data,
 * but at 1m that is a two-day step through months of bars — dozens of pans
 * to get anywhere. Each chunk instead spans what is already loaded, so the
 * history doubles every fetch and a handful of pans reaches the beginning
 * however much the backend ends up holding.
 */
function chunkDays(interval: Interval, held: History): number {
  const loaded = (held.until.getTime() - held.from.getTime()) / 86_400_000;
  const want = Math.max(lookbackDays(interval), Math.round(loaded));
  return Math.min(want, chunkCeilingDays(interval));
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
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [backfilling, setBackfilling] = useState(false);
  // Folding is cheap and pure, so the raw bars are what is stored and the
  // displayed series is derived. A backfill therefore re-folds across the
  // join, which is the only way a group straddling the seam comes out whole.
  const bars = useMemo(
    () => (history ? resample(history.bars, interval) : null),
    [history, interval],
  );

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
  const [settingsUid, setSettingsUid] = useState<string | null>(null);
  const toggleIndicator = (uid: string) =>
    setIndicators((list) => list.map((x) => (x.uid === uid ? { ...x, hidden: !x.hidden } : x)));
  const removeIndicator = (uid: string) =>
    setIndicators((list) => list.filter((x) => x.uid !== uid));
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
  const [anchor, setAnchor] = useState<
    { key: string; latest: string; earliest: string } | null
  >(null);
  const anchorReady = anchor?.key === selectionKey;

  useEffect(() => {
    let cancelled = false;
    fetchCoverage(instrument)
      .then((rows) => {
        if (cancelled) return;
        const row = rows.find((r) => r.timeframe === timeframe);
        setAnchor({
          key: `${instrument}|${timeframe}`,
          latest: row?.latest_ts ?? "",
          earliest: row?.earliest_ts ?? "",
        });
      })
      .catch(() => {
        // Coverage is an optimisation — fall back to wall-clock, but still
        // tag the selection so the bar fetch is unblocked.
        if (!cancelled) {
          setAnchor({ key: `${instrument}|${timeframe}`, latest: "", earliest: "" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [instrument, timeframe]);

  const range = useMemo(() => {
    if (!anchorReady || !anchor) return null;
    const end = anchor.latest ? new Date(anchor.latest) : new Date();
    const start = new Date(end);
    start.setUTCDate(end.getUTCDate() - lookbackDays(interval));
    // Ask slightly past the last bar so the newest one is never clipped.
    return { start, end: new Date(end.getTime() + 86_400_000) };
  }, [anchorReady, anchor, interval]);

  // Oldest bar the backend holds: the hard floor for backfill, so panning
  // left stops asking instead of walking off into empty centuries.
  const floor = useMemo(
    () => (anchor?.earliest ? new Date(anchor.earliest) : null),
    [anchor],
  );

  // Raw bars only depend on instrument + stored timeframe, but the size of a
  // chunk is per-interval, so a folded interval gets its own history.
  const historyKey = `${instrument}|${interval.id}`;

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
      timeScale: {
        borderColor: "#262b36",
        timeVisible: true,
        secondsVisible: false,
        // The library's default floor of 0.5px per bar caps how far the
        // chart can zoom out at (plot width / 0.5) bars — about 2 500 here,
        // regardless of how many are loaded. That is a hard wall you hit by
        // scrolling out, and it reads exactly like "the chart only ever
        // shows a fixed number of candles". Dropped low enough that the
        // whole record fits however large it grows; a year of 1m bars is
        // ~370 000, and even that stays above this floor.
        minBarSpacing: 0.001,
      },
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
        setHistory({
          key: historyKey,
          bars: res.data,
          from: range.start,
          until: range.end,
          exhausted: floor !== null && range.start <= floor,
        });
      })
      .catch((e: unknown) => {
        // `superseded` rather than signal.aborted alone: a cancelled request
        // can reject with the server's own error (Railway logs an aborted
        // request as 503) before the abort is observable here, and that
        // stale rejection must never overwrite the newer request's state.
        if (superseded || controller.signal.aborted) return;
        setError(e instanceof Error ? e.message : String(e));
        setHistory({
          key: historyKey,
          bars: [],
          from: range.start,
          until: range.end,
          exhausted: true,
        });
      })
      .finally(() => {
        if (!superseded) setLoading(false);
      });
    return () => {
      superseded = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instrument, timeframe, interval, range]);

  // ── Backfill on pan ───────────────────────────────────────────────
  // Reading the current history through a ref rather than closing over it
  // keeps the staleness check synchronous: by the time an await resolves,
  // the user may have switched instrument or already pulled another chunk.
  const historyRef = useRef<History | null>(null);
  historyRef.current = history;
  const backfillingRef = useRef(false);
  // Set when older bars are prepended, so the rebuild below holds the
  // viewport still instead of fitting the whole (now longer) series.
  const preserveViewRef = useRef(false);

  /**
   * Fetch the chunk immediately older than `held` and return the extended
   * history, or null if there is nothing to add. Pure with respect to
   * component state so both the pan trigger and "load all" can drive it.
   */
  const fetchOlder = useCallback(
    async (held: History): Promise<History | null> => {
      const end = held.from;
      const start = new Date(end);
      start.setUTCDate(end.getUTCDate() - chunkDays(interval, held));
      const from = floor && start < floor ? floor : start;
      if (from >= end) return null;

      const res = await fetchKBars({
        instrument,
        timeframe,
        start: from,
        end,
        adjustment: "ratio",
        limit: 50_000,
      });
      return {
        key: held.key,
        bars: [...res.data, ...held.bars],
        from,
        until: held.until,
        // An empty chunk also ends it: coverage may lag the bars, and
        // walking back forever through nothing is worse than stopping a
        // little early.
        exhausted: res.data.length === 0 || (floor !== null && from <= floor),
      };
    },
    [interval, instrument, timeframe, floor],
  );

  /** True while `held` is still the history on screen. */
  const stillCurrent = useCallback(
    (held: History) => {
      const now = historyRef.current;
      return (
        now !== null &&
        now.key === held.key &&
        now.key === historyKey &&
        now.from.getTime() === held.from.getTime()
      );
    },
    [historyKey],
  );

  const backfill = useCallback(async () => {
    if (backfillingRef.current) return;
    const held = historyRef.current;
    if (!held || held.key !== historyKey || held.exhausted) return;

    backfillingRef.current = true;
    setBackfilling(true);
    try {
      const next = await fetchOlder(held);
      // Superseded while in flight — drop the chunk rather than splicing it
      // into a history it no longer belongs to.
      if (!next || !stillCurrent(held)) return;
      preserveViewRef.current = true;
      historyRef.current = next;
      setHistory(next);
    } catch {
      // A failed chunk is not fatal. Keep what is drawn; the next pan retries.
    } finally {
      backfillingRef.current = false;
      setBackfilling(false);
    }
  }, [historyKey, fetchOlder, stillCurrent]);

  /**
   * Pull chunks until the backend has nothing older.
   *
   * Panning already extends the history a chunk at a time, but "show me
   * everything you have" is a thing people want to ask for outright rather
   * than by dragging until it stops moving. The loop rides `historyRef`
   * forward itself instead of waiting for React to commit each step, so the
   * fetches queue back to back while the chart repaints between them.
   */
  const loadAll = useCallback(async () => {
    if (backfillingRef.current) return;
    backfillingRef.current = true;
    setBackfilling(true);
    try {
      let held = historyRef.current;
      while (held && held.key === historyKey && !held.exhausted) {
        const next = await fetchOlder(held);
        if (!next || !stillCurrent(held)) break;
        preserveViewRef.current = true;
        historyRef.current = next;
        setHistory(next);
        held = next;
      }
    } catch {
      // Keep whatever landed; the button stays available to resume.
    } finally {
      backfillingRef.current = false;
      setBackfilling(false);
    }
  }, [historyKey, fetchOlder, stillCurrent]);

  // The subscription is registered once, so it reaches the current callback
  // through a ref — re-subscribing on every dependency change would drop
  // range events during the swap.
  const backfillRef = useRef(backfill);
  backfillRef.current = backfill;

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const scale = chart.timeScale();
    const onRange = (r: LogicalRange | null) => {
      // `from` is a bar index into the series and goes negative once the
      // user scrolls past the oldest bar.
      if (r && r.from < BACKFILL_TRIGGER_BARS) void backfillRef.current();
    };
    scale.subscribeVisibleLogicalRangeChange(onRange);
    return () => scale.unsubscribeVisibleLogicalRangeChange(onRange);
  }, []);

  // Evaluate the selected strategy over EVERY stored bar, not the window
  // on screen: the trades and metrics are a property of the strategy, not
  // of how far the user happens to have scrolled. Sending no range asks the
  // backend to resolve it against the table, so this keeps covering
  // everything as more history is ingested. Markers outside the loaded
  // bars simply do not draw yet. Selecting a strategy forces the chart onto
  // the strategy's timeframe, so bar times and trade times line up exactly.
  useEffect(() => {
    if (!strategyId) {
      setEvalResult(null);
      setEvalError(null);
      return;
    }
    let cancelled = false;
    setEvalLoading(true);
    setEvalError(null);
    evaluateStrategy(strategyId, { instrument, adjustment: "ratio" })
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
  }, [strategyId, instrument]);

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

    // Read before the series are torn down and rebuilt. A *time* range
    // rather than a bar-index one: the sixteen chart types do not all draw
    // one point per bar — Renko, Kagi, range bars and 3-line break rewrite
    // the x-axis entirely — so "shift the view by N bars" only holds for
    // the 1:1 types. The window the user is looking at is the same stretch
    // of clock either way.
    const before = chart.timeScale().getVisibleRange();

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

    // A backfill only adds bars *older* than the ones on screen, so the
    // stretch of time the user is looking at is untouched — put it back.
    // Fitting here instead would yank the view out to the whole series on
    // every chunk, which is what made panning feel like it hit a wall.
    if (preserveViewRef.current && before) {
      chart.timeScale().setVisibleRange(before);
    } else {
      chart.timeScale().fitContent();
    }
    preserveViewRef.current = false;
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
      if (active.hidden) continue;
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
    // chartKind matters even though nothing here reads it: switching type
    // tears down and rebuilds the price series, and the markers live ON
    // that series. Without it the trades silently vanished on every type
    // change while the strategy pill still claimed they were there.
  }, [evalResult, bars, chartKind]);

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
            {loading || evalLoading
              ? "Loading…"
              : bars
                ? `${bars.length} bars${backfilling ? " · loading history…" : ""}`
                : ""}
          </span>
          {/* Panning already pulls history a chunk at a time; this is for
              asking outright rather than dragging until the chart stops
              moving. It disappears once the backend has nothing older. */}
          {history && !history.exhausted && !loading && (
            <button
              type="button"
              onClick={loadAll}
              disabled={backfilling}
              title="Fetch every older bar the backend holds at this timeframe"
              className="rounded border border-border px-2 py-0.5 font-mono text-[11px] text-zinc-400 transition hover:border-accent-blue hover:text-accent-blue disabled:opacity-40"
            >
              Load all history
            </button>
          )}
        </div>
      </div>

      {strategyId && (
        <div className="flex flex-wrap items-center gap-1.5">
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
        </div>
      )}

      <div className="relative">
        <div
          ref={containerRef}
          className="h-[560px] w-full overflow-hidden rounded-lg border border-border bg-bg-panel"
        />
        <div className="pointer-events-none absolute left-2 top-2 z-10 flex flex-col items-start gap-0.5">
          {overlays.map((active) => (
            <IndicatorLegendRow
              key={active.uid}
              active={active}
              onToggle={() => toggleIndicator(active.uid)}
              onSettings={() => setSettingsUid(active.uid)}
              onRemove={() => removeIndicator(active.uid)}
            />
          ))}
        </div>

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
                {anchor?.latest
                  ? `The backend's newest ${timeframe} bar for this instrument is ${anchor.latest
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
          onRemove={() => removeIndicator(active.uid)}
          onToggle={() => toggleIndicator(active.uid)}
          onSettings={() => setSettingsUid(active.uid)}
        />
      ))}

      <IndicatorSettings
        active={indicators.find((x) => x.uid === settingsUid) ?? null}
        onClose={() => setSettingsUid(null)}
        onApply={(params) =>
          setIndicators((list) =>
            list.map((x) => (x.uid === settingsUid ? { ...x, params } : x)),
          )
        }
      />

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
