import type { Metadata } from "next";
import { Suspense } from "react";

import { RequireAuth } from "@/components/auth/require-auth";
import { PairsBacktestWorkbench } from "@/components/pairs/backtest";
import { PairsHeader } from "@/components/pairs/subnav";

export const metadata: Metadata = { title: "Pairs backtest" };

export default function PairsBacktestPage() {
  return (
    <div className="space-y-6">
      <PairsHeader title="Walk-forward pairs backtest">
        Parameters are re-estimated every day from the trailing formation window, signals fire at the close and fill the
        next day, costs are explicit, and capital is split across concurrently qualified pairs. Metrics come with a
        bootstrap interval and a deflated Sharpe so the search that found the parameters is paid for.
      </PairsHeader>
      <RequireAuth>
        <Suspense fallback={null}>
          <PairsBacktestWorkbench />
        </Suspense>
      </RequireAuth>
    </div>
  );
}
