import Link from "next/link";

import { RequireAuth } from "@/components/auth/require-auth";
import { StrategyCanvas } from "@/components/strategies/canvas";

export default function StrategyCanvasPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Strategy Canvas</h1>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">
          Drag modules; the graph compiles to one saved strategy you can{" "}
          <Link href="/research/signal-test" className="text-accent-blue hover:underline">
            signal-test
          </Link>{" "}
          and{" "}
          <Link href="/research/strategies" className="text-accent-blue hover:underline">
            manage on the form
          </Link>
          . <span className="text-zinc-300">Trigger</span> is a discrete cross,{" "}
          <span className="text-zinc-300">Filter</span> a standing gate every entry
          must also pass, <span className="text-zinc-300">Exit</span> a close signal.
        </p>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">
          For intraday setups, add <span className="text-accent-green">Session</span>{" "}
          (trading hours, forced flat at the close),{" "}
          <span className="text-accent-amber">Killzone</span> (rests a buy above the
          range high and a sell below the low, first touch wins), and{" "}
          <span className="text-accent-red">Bracket</span> (SL/TP). An ICT killzone
          and an RSI filter combine into the same strategy — same engine, same
          position.
        </p>
        <p className="mt-2 max-w-3xl text-xs text-zinc-500">
          Results here are scored in points, before slippage and commission. For
          USD P&amp;L on the dedicated session engine use the{" "}
          <Link href="/research/backtest" className="text-accent-blue hover:underline">
            backtest runner
          </Link>
          .
        </p>
      </header>
      <RequireAuth>
        <StrategyCanvas />
      </RequireAuth>
    </div>
  );
}
