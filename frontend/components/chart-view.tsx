"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ColorType,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
  createChart,
} from "lightweight-charts";

import { fetchKBars } from "@/lib/api";
import type { Instrument, KBar, Timeframe } from "@/lib/types";
import { INSTRUMENTS, TIMEFRAMES } from "@/lib/types";

interface Props {
  initialInstrument: Instrument;
  initialTimeframe: Timeframe;
}

// Default lookback windows per timeframe, sized so the user gets a useful
// number of candles on first load without overshooting the 50 000-bar API
// cap. Numbers are calibrated against CME Globex session density.
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

export function ChartView({ initialInstrument, initialTimeframe }: Props) {
  const [instrument, setInstrument] = useState<Instrument>(initialInstrument);
  const [timeframe, setTimeframe] = useState<Timeframe>(initialTimeframe);
  const [bars, setBars] = useState<KBar[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  const range = useMemo(() => {
    const end = new Date();
    const start = new Date(end);
    start.setUTCDate(end.getUTCDate() - DEFAULT_LOOKBACK_DAYS[timeframe]);
    return { start, end };
  }, [timeframe]);

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
    const candles = chart.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderUpColor: "#26a69a",
      borderDownColor: "#ef5350",
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    });
    const volumes = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "",
      color: "#5b8def66",
    });
    volumes.priceScale().applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    chartRef.current = chart;
    candleRef.current = candles;
    volumeRef.current = volumes;
    return () => {
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
    };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchKBars({
        instrument,
        timeframe,
        start: range.start,
        end: range.end,
        adjustment: "ratio",
        limit: 50000,
      });
      setBars(res.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBars([]);
    } finally {
      setLoading(false);
    }
  }, [instrument, timeframe, range]);

  useEffect(() => {
    void load();
  }, [load]);

  // Re-render the chart series whenever a new bar set lands. Going through
  // setData rather than incremental updates keeps the chart deterministic
  // when the user toggles between instruments.
  useEffect(() => {
    if (!bars || !candleRef.current || !volumeRef.current || !chartRef.current) {
      return;
    }
    candleRef.current.setData(
      bars.map((b) => ({
        time: toUtcSeconds(b.ts),
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );
    volumeRef.current.setData(
      bars.map((b) => ({
        time: toUtcSeconds(b.ts),
        value: b.volume,
        color: b.close >= b.open ? "#26a69a55" : "#ef535055",
      })),
    );
    chartRef.current.timeScale().fitContent();
  }, [bars]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-bg-panel p-3">
        <div className="flex gap-1">
          {INSTRUMENTS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setInstrument(s)}
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
              onClick={() => setTimeframe(t)}
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
        <div className="ml-auto text-xs text-zinc-500">
          {loading ? "Loading…" : bars ? `${bars.length} bars` : ""}
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-accent-red/40 bg-accent-red/10 p-3 text-sm text-accent-red">
          <span className="font-mono">{error}</span>
        </div>
      )}

      <div
        ref={containerRef}
        className="h-[560px] w-full overflow-hidden rounded-lg border border-border bg-bg-panel"
      />
    </div>
  );
}
