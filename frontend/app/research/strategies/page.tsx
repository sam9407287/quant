import Link from "next/link";

import { RequireAuth } from "@/components/auth/require-auth";

import { StrategyManager } from "@/components/strategies/builder";

export default function StrategiesPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Strategies</h1>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">
          Start from a template below, or build one from scratch: indicator
          conditions for the entries and exits, an optional SL/TP bracket, and
          filters that gate every entry. Prefer dragging modules — or need a
          trading session and a killzone? Use the <Link href="/research/strategies/canvas" className="text-accent-blue hover:underline">strategy canvas</Link>. Apply a saved strategy on the{" "}
          <Link href="/chart" className="text-accent-blue hover:underline">
            chart
          </Link>{" "}
          to see every trade, with position boxes for the bracket.
        </p>
      </header>
      <RequireAuth>
        <StrategyManager />
      </RequireAuth>
    </div>
  );
}
