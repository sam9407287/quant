import { ChartView } from "@/components/chart-view";
import type { Instrument, Timeframe } from "@/lib/types";
import { INSTRUMENTS, TIMEFRAMES } from "@/lib/types";

interface PageProps {
  searchParams?: { instrument?: string; timeframe?: string };
}

function pickInstrument(raw: string | undefined): Instrument {
  return INSTRUMENTS.includes(raw as Instrument)
    ? (raw as Instrument)
    : "NQ";
}

function pickTimeframe(raw: string | undefined): Timeframe {
  return TIMEFRAMES.includes(raw as Timeframe)
    ? (raw as Timeframe)
    : "1h";
}

export default function ChartPage({ searchParams }: PageProps) {
  const instrument = pickInstrument(searchParams?.instrument);
  const timeframe = pickTimeframe(searchParams?.timeframe);
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Chart</h1>
        <p className="mt-2 text-sm text-zinc-400">
          Candlesticks at any of the seven supported timeframes. Pricing comes
          straight from the <code>/api/v1/kbars</code> endpoint with
          ratio-adjusted contract rolls applied server-side.
        </p>
      </header>
      <ChartView initialInstrument={instrument} initialTimeframe={timeframe} />
    </div>
  );
}
