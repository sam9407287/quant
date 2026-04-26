import { fetchCoverage } from "@/lib/api";
import type { CoverageRecord } from "@/lib/types";
import { CoverageTable } from "@/components/coverage-table";

export const dynamic = "force-dynamic";

export default async function CoveragePage() {
  let rows: CoverageRecord[] = [];
  let error: string | null = null;
  try {
    rows = await fetchCoverage("all", { cache: "no-store" });
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Coverage</h1>
        <p className="mt-2 text-sm text-zinc-400">
          One row per (instrument, timeframe). 1m bars are written by the
          fetcher; higher timeframes are TimescaleDB Continuous Aggregates,
          so their counts derive from the same underlying data.
        </p>
      </header>

      {error ? (
        <div className="rounded-md border border-accent-red/40 bg-accent-red/10 p-4 text-sm text-accent-red">
          Failed to reach the API: <span className="font-mono">{error}</span>
        </div>
      ) : (
        <CoverageTable rows={rows} />
      )}
    </div>
  );
}
