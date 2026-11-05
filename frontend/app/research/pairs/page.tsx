import type { Metadata } from "next";
import Link from "next/link";

import { PairsDashboard } from "@/components/pairs/dashboard";
import { PairsHeader } from "@/components/pairs/subnav";

export const metadata: Metadata = { title: "Pairs lab" };

export default function PairsPage() {
  return (
    <div className="space-y-6">
      <PairsHeader title="Pairs lab">
        Cointegration-based statistical arbitrage research: scan a universe for pairs whose spread mean-reverts, size the
        hedge, backtest it walk-forward, and let the daily job watch the watchlist and push entries and exits to Discord.
        New here? Read the{" "}
        <Link href="/research/pairs/guide" className="text-accent-blue hover:underline">
          guide
        </Link>{" "}
        first — it explains every number on these pages.
      </PairsHeader>
      <PairsDashboard />
    </div>
  );
}
