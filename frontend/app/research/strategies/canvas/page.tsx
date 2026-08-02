import Link from "next/link";

import { RequireAuth } from "@/components/auth/require-auth";
import { StrategyCanvas } from "@/components/strategies/canvas";

export default function StrategyCanvasPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Strategy Canvas</h1>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">
          Drag rule modules — Triggers (entries/exits) and Filters — and pick an
          indicator inside each (EMA, SMA, RSI, MACD, ATR, ROC, Bollinger,
          Donchian). The graph compiles to a saved strategy you can{" "}
          <Link href="/research/signal-test" className="text-accent-blue hover:underline">
            signal-test
          </Link>{" "}
          and{" "}
          <Link href="/research/strategies" className="text-accent-blue hover:underline">
            manage on the form
          </Link>
          . A Trigger is a discrete cross; a Filter is a standing gate every entry
          must also pass.
        </p>
      </header>
      <RequireAuth>
        <StrategyCanvas />
      </RequireAuth>
    </div>
  );
}
