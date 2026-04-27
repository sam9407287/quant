import Link from "next/link";

import { fetchCoverage } from "@/lib/api";
import type { CoverageRecord } from "@/lib/types";
import {
  ASSET_CLASS_LABEL,
  INSTRUMENT_META,
  INSTRUMENTS_BY_CLASS,
} from "@/lib/types";

// Refresh on every request so the dashboard reflects the most recent fetcher
// run. The backend is fast enough that pre-rendering buys nothing.
export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  let rows: CoverageRecord[] = [];
  let error: string | null = null;
  try {
    rows = await fetchCoverage("all", { cache: "no-store" });
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  // The 1m row carries the load-bearing freshness signal: it's what the
  // fetcher writes directly, and every higher timeframe rolls up from it.
  const latest1m = new Map<string, CoverageRecord>();
  for (const r of rows) {
    if (r.timeframe === "1m") latest1m.set(r.instrument, r);
  }

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">
          Live snapshot of the four CME index futures the platform tracks.
          Numbers below come from the live TimescaleDB instance via the
          FastAPI backend — same endpoints the chart and coverage pages use.
        </p>
      </section>

      {error && (
        <div className="rounded-md border border-accent-red/40 bg-accent-red/10 p-4 text-sm text-accent-red">
          Failed to reach the API: <span className="font-mono">{error}</span>
        </div>
      )}

      {(["equity_index", "metal", "energy"] as const).map((cls) => (
        <section key={cls} className="space-y-3">
          <h2 className="font-mono text-xs uppercase tracking-wider text-zinc-500">
            {ASSET_CLASS_LABEL[cls]}
          </h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {INSTRUMENTS_BY_CLASS[cls].map((sym) => {
              const r = latest1m.get(sym);
              const meta = INSTRUMENT_META[sym];
              return (
                <Link
                  key={sym}
                  href={{ pathname: "/chart", query: { instrument: sym } }}
                  className="rounded-lg border border-border bg-bg-panel p-5 transition hover:border-border-strong hover:bg-bg-hover"
                >
                  <div className="flex items-baseline justify-between">
                    <span className="font-mono text-sm font-semibold uppercase tracking-wider text-zinc-100">
                      {sym}
                    </span>
                    <span className="text-xs text-zinc-500">{meta.name}</span>
                  </div>
                  <div className="mt-2 text-2xl font-semibold">
                    {r ? r.bar_count.toLocaleString() : "—"}
                  </div>
                  <div className="text-xs text-zinc-500">1m bars stored</div>
                  <div className="mt-3 text-xs text-zinc-400">
                    Latest:{" "}
                    <span className="font-mono">
                      {r?.latest_ts
                        ? r.latest_ts.replace("T", " ").slice(0, 16)
                        : "—"}
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
        </section>
      ))}

      <section className="rounded-lg border border-border bg-bg-panel p-6">
        <h2 className="text-lg font-semibold">Quick links</h2>
        <ul className="mt-3 space-y-2 text-sm text-zinc-300">
          <li>
            <Link className="text-accent-blue hover:underline" href="/coverage">
              Full coverage table
            </Link>{" "}
            — every (instrument × timeframe) row from <code>data_coverage</code>.
          </li>
          <li>
            <Link className="text-accent-blue hover:underline" href="/chart">
              Interactive chart
            </Link>{" "}
            — candlesticks at any of the seven supported timeframes.
          </li>
          <li>
            <a
              className="text-accent-blue hover:underline"
              href={`${process.env.NEXT_PUBLIC_API_URL ?? "https://quant-production-d645.up.railway.app"}/docs`}
              target="_blank"
              rel="noreferrer"
            >
              FastAPI / OpenAPI docs
            </a>{" "}
            — the underlying REST contract.
          </li>
        </ul>
      </section>
    </div>
  );
}
