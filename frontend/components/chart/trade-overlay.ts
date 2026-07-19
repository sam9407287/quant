// TradingView-style position boxes as a lightweight-charts v4.2 series
// primitive: for every trade, a translucent box on the profit side
// (entry → TP) and one on the risk side (entry → SL), spanning entry
// time → exit time. A strategy with only one bracket side draws only
// that side — exactly the product spec.
//
// Coordinates are recomputed in updateAllViews() (the library calls it
// whenever the viewport changes); the renderer then just fills rects.

import type {
  IChartApi,
  ISeriesApi,
  ISeriesPrimitive,
  ISeriesPrimitivePaneRenderer,
  ISeriesPrimitivePaneView,
  Time,
  UTCTimestamp,
} from "lightweight-charts";

export interface TradeBox {
  from: UTCTimestamp;
  to: UTCTimestamp;
  priceA: number; // one edge (e.g. entry)
  priceB: number; // other edge (e.g. tp or sl level)
  kind: "profit" | "risk";
}

interface PixelBox {
  x1: number;
  x2: number;
  y1: number; // entry edge (priceA)
  y2: number;
  kind: "profit" | "risk";
}

// TradingView position-tool look: flat translucent fills, no border,
// and a bright line on the shared entry edge (priceA is always entry).
const FILL: Record<TradeBox["kind"], string> = {
  profit: "rgba(38, 166, 154, 0.22)",
  risk: "rgba(239, 83, 80, 0.20)",
};
const ENTRY_LINE = "rgba(255, 255, 255, 0.75)";

type DrawTarget = Parameters<ISeriesPrimitivePaneRenderer["draw"]>[0];

class BoxesRenderer implements ISeriesPrimitivePaneRenderer {
  constructor(private readonly _boxes: PixelBox[]) {}

  draw(target: DrawTarget): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      for (const b of this._boxes) {
        const x = Math.min(b.x1, b.x2);
        const y = Math.min(b.y1, b.y2);
        const w = Math.abs(b.x2 - b.x1);
        const h = Math.abs(b.y2 - b.y1);
        if (w <= 0 || h <= 0) continue;
        ctx.fillStyle = FILL[b.kind];
        ctx.fillRect(x, y, w, h);
        // Entry line on the shared edge (y1 = entry price).
        ctx.strokeStyle = ENTRY_LINE;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(x, b.y1);
        ctx.lineTo(x + w, b.y1);
        ctx.stroke();
      }
    });
  }
}

class BoxesPaneView implements ISeriesPrimitivePaneView {
  private _pixelBoxes: PixelBox[] = [];

  constructor(private readonly _owner: TradeBoxesPrimitive) {}

  update(): void {
    const { chart, series, boxes } = this._owner;
    if (!chart || !series) {
      this._pixelBoxes = [];
      return;
    }
    const timeScale = chart.timeScale();
    const visible = timeScale.getVisibleRange();
    const width = timeScale.width();
    const out: PixelBox[] = [];
    for (const b of boxes) {
      // Clamp times that scrolled off-screen to the pane edges so a
      // half-visible position still shows its box.
      let x1 = timeScale.timeToCoordinate(b.from as Time);
      let x2 = timeScale.timeToCoordinate(b.to as Time);
      if (x1 === null && visible && (b.from as number) < (visible.from as number)) {
        x1 = 0 as never;
      }
      if (x2 === null && visible && (b.to as number) > (visible.to as number)) {
        x2 = width as never;
      }
      const y1 = series.priceToCoordinate(b.priceA);
      const y2 = series.priceToCoordinate(b.priceB);
      if (x1 === null || x2 === null || y1 === null || y2 === null) continue;
      out.push({ x1, x2, y1, y2, kind: b.kind });
    }
    this._pixelBoxes = out;
  }

  renderer(): ISeriesPrimitivePaneRenderer {
    return new BoxesRenderer(this._pixelBoxes);
  }
}

export class TradeBoxesPrimitive implements ISeriesPrimitive<Time> {
  boxes: TradeBox[] = [];
  chart: IChartApi | null = null;
  series: ISeriesApi<"Candlestick"> | null = null;

  private readonly _view = new BoxesPaneView(this);

  constructor(chart: IChartApi, series: ISeriesApi<"Candlestick">) {
    this.chart = chart;
    this.series = series;
  }

  setBoxes(boxes: TradeBox[]): void {
    this.boxes = boxes;
    // Nudge the chart so the library schedules a repaint even when the
    // viewport itself did not move.
    this.series?.applyOptions({});
  }

  updateAllViews(): void {
    this._view.update();
  }

  paneViews(): readonly ISeriesPrimitivePaneView[] {
    return [this._view];
  }
}
