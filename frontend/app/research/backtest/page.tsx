import Link from "next/link";

import { RequireAuth } from "@/components/auth/require-auth";

import { BacktestWorkbench } from "@/components/backtest/form";

export default function BacktestPage() {
  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Backtest</h1>
          <p className="mt-2 max-w-3xl text-sm text-zinc-400">
            Rule-based intraday backtests: killzone OCO (ICT Judas Swing).
            Set the reference range, order timing and bracket, run against
            stored 1m bars, then read the equity curve, seasonality and
            Monte Carlo risk bands — in USD, after slippage and commission.
            To combine a killzone with indicator rules instead, build it on
            the{" "}
            <Link
              href="/research/strategies/canvas"
              className="text-accent-blue hover:underline"
            >
              strategy canvas
            </Link>
            .
          </p>
        </div>
      </header>
      <RequireAuth>
        <BacktestWorkbench />
      </RequireAuth>
    </div>
  );
}
