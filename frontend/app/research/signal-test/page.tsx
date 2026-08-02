import Link from "next/link";

import { RequireAuth } from "@/components/auth/require-auth";
import { SignalTestPanel } from "@/components/signal-test/panel";

export default function SignalTestPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Signal Test</h1>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">
          Measure an idea in isolation before building a backtest. A backtest
          bundles the idea with exits, stops and position sizing — too many
          degrees of freedom to know if the idea itself has an edge. A signal
          test finds every entry signal, treats each as day 0, and measures the
          forward return across all of them. Promising here?{" "}
          <Link href="/research/strategies" className="text-accent-blue hover:underline">
            build the strategy
          </Link>{" "}
          and{" "}
          <Link href="/research/backtest" className="text-accent-blue hover:underline">
            backtest it
          </Link>
          .
        </p>
      </header>
      <RequireAuth>
        <SignalTestPanel />
      </RequireAuth>
    </div>
  );
}
