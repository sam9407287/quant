import Link from "next/link";

import { RequireAuth } from "@/components/auth/require-auth";

import { BacktestCanvas } from "@/components/backtest/canvas";

export default function BacktestCanvasPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Backtest canvas</h1>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">
          Node view of the same strategy config: edit the blocks, then hit
          Run. The graph compiles to the exact params JSON the{" "}
          <Link href="/research/backtest" className="text-accent-blue hover:underline">
            form page
          </Link>{" "}
          sends — same engine, same API.
        </p>
      </header>
      <RequireAuth>
        <BacktestCanvas />
      </RequireAuth>
    </div>
  );
}
