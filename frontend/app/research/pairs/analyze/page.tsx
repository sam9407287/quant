import type { Metadata } from "next";
import { Suspense } from "react";

import { PairAnalyzer } from "@/components/pairs/analyze";
import { PairsHeader } from "@/components/pairs/subnav";

export const metadata: Metadata = { title: "Analyze pair" };

export default function AnalyzePage() {
  return (
    <div className="space-y-6">
      <PairsHeader title="Analyze a pair">
        The evidence for one Y/X pair: every cointegration test side by side, the spread and z-score through time with
        strictly backward-looking parameters, how β and the p-value drifted, and what actually happened to the spread
        after each z level. This is the page to read before trusting any backtest of the pair.
      </PairsHeader>
      <Suspense fallback={null}>
        <PairAnalyzer />
      </Suspense>
    </div>
  );
}
