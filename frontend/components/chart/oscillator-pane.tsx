"use client";

/**
 * One oscillator, one pane.
 *
 * Sharing a pane between indicators looks tidy until you put RSI (0–100)
 * next to MACD (±400) and the RSI collapses into a flat line — they have no
 * common scale. TradingView gives each its own pane for the same reason, so
 * each instance here owns a chart and syncs its time axis to the price one.
 */

import { useEffect, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type SeriesType,
  type UTCTimestamp,
} from "lightweight-charts";

import { IndicatorLegendRow } from "@/components/chart/indicator-legend";
import { findIndicator, type ActiveIndicator } from "@/lib/indicator-registry";
import type { KBar } from "@/lib/types";

function seconds(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

export function OscillatorPane({
  bars,
  active,
  getMainChart,
  onRemove,
  onToggle,
  onSettings,
}: {
  bars: KBar[] | null;
  active: ActiveIndicator;
  getMainChart: () => IChartApi | null;
  onRemove: () => void;
  onToggle: () => void;
  onSettings: () => void;
}) {
  const boxRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<SeriesType>[]>([]);
  const meta = findIndicator(active.id);

  useEffect(() => {
    if (!boxRef.current) return;
    const chart = createChart(boxRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#13161d" }, textColor: "#a1a7b3" },
      grid: { vertLines: { color: "#1c2029" }, horzLines: { color: "#1c2029" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#262b36" },
      timeScale: { borderColor: "#262b36", timeVisible: true, secondsVisible: false, visible: false },
      autoSize: true,
    });
    chartRef.current = chart;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = [];
    };
  }, []);

  // Data + guides.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !meta) return;
    for (const s of seriesRef.current) chart.removeSeries(s);
    seriesRef.current = [];
    if (!bars?.length || active.hidden) return;

    // Indicator lines skip their warm-up bars, so on their own this pane
    // would span fewer points than the price chart and the two logical
    // index spaces would drift. A whitespace series over every bar time
    // pins them together, which is what makes the sync exact.
    const spacer = chart.addLineSeries({ visible: false, lastValueVisible: false, priceLineVisible: false });
    spacer.setData(bars.map((b) => ({ time: seconds(b.ts) })));
    seriesRef.current.push(spacer);

    let first = true;
    for (const line of meta.build(bars, active.params)) {
      const points = bars
        .map((b, i) => ({ time: seconds(b.ts), value: line.values[i] }))
        .filter((d): d is { time: UTCTimestamp; value: number } => d.value !== null && Number.isFinite(d.value));

      if (line.kind === "histogram") {
        const series = chart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
        series.setData(points.map((d) => ({ ...d, color: d.value >= 0 ? "#199e7099" : "#e6676799" })));
        seriesRef.current.push(series);
        continue;
      }

      const series = chart.addLineSeries({
        color: line.color,
        lineWidth: (line.lineWidth ?? 1) as 1 | 2 | 3 | 4,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      series.setData(points);
      if (first) {
        for (const level of meta.guides ?? []) {
          series.createPriceLine({
            price: level,
            color: "#2a3342",
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: false,
            title: "",
          });
        }
        first = false;
      }
      seriesRef.current.push(series);
    }

    // Feeding data auto-fits the pane, which would undo the sync — so
    // re-apply the price chart's range last.
    const range = getMainChart()?.timeScale().getVisibleLogicalRange();
    if (range) chart.timeScale().setVisibleLogicalRange(range);
  }, [bars, active, meta, getMainChart]);

  // Two-way time sync. The guard stops the subscriptions bouncing forever.
  useEffect(() => {
    const chart = chartRef.current;
    const main = getMainChart();
    if (!chart || !main) return;
    let syncing = false;
    const push = (to: IChartApi) => (range: unknown) => {
      if (syncing || !range) return;
      syncing = true;
      to.timeScale().setVisibleLogicalRange(range as never);
      syncing = false;
    };
    const fromMain = push(chart);
    const fromHere = push(main);
    main.timeScale().subscribeVisibleLogicalRangeChange(fromMain);
    chart.timeScale().subscribeVisibleLogicalRangeChange(fromHere);
    const current = main.timeScale().getVisibleLogicalRange();
    if (current) chart.timeScale().setVisibleLogicalRange(current);
    return () => {
      main.timeScale().unsubscribeVisibleLogicalRangeChange(fromMain);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(fromHere);
    };
  }, [bars, getMainChart]);

  if (!meta) return null;
  return (
    <div className="relative">
      <div
        ref={boxRef}
        className="h-[150px] w-full overflow-hidden rounded-lg border border-border bg-bg-panel"
      />
      <div className="absolute left-2 top-2 z-10">
        <IndicatorLegendRow
          active={active}
          onToggle={onToggle}
          onSettings={onSettings}
          onRemove={onRemove}
        />
      </div>
    </div>
  );
}
