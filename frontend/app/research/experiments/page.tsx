import Link from "next/link";

import { type ExperimentRecord, listExperiments } from "@/lib/ml";

export const dynamic = "force-dynamic";

export default async function ExperimentsPage() {
  let rows: ExperimentRecord[] = [];
  let error: string | null = null;
  try {
    rows = await listExperiments(100);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Experiments</h1>
        <p className="mt-2 text-sm text-zinc-400">
          Every wizard run on{" "}
          <Link href="/research" className="text-accent-blue hover:underline">
            /research
          </Link>{" "}
          appends a row here. Sorted newest first.
        </p>
      </header>

      {error ? (
        <div className="rounded-md border border-accent-red/40 bg-accent-red/10 p-4 text-sm text-accent-red">
          Failed to load: <span className="font-mono">{error}</span>
        </div>
      ) : rows.length === 0 ? (
        <EmptyState />
      ) : (
        <ExperimentsTable rows={rows} />
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-md border border-border bg-bg-panel p-6 text-sm text-zinc-400">
      No experiments yet.{" "}
      <Link href="/research" className="text-accent-blue hover:underline">
        Run your first one
      </Link>
      .
    </div>
  );
}

function ExperimentsTable({ rows }: { rows: ExperimentRecord[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-bg-panel">
      <table className="min-w-full text-sm">
        <thead className="border-b border-border bg-bg-hover/50 text-left text-xs uppercase tracking-wider text-zinc-400">
          <tr>
            <th className="px-4 py-3">Created</th>
            <th className="px-4 py-3">Task</th>
            <th className="px-4 py-3">Model</th>
            <th className="px-4 py-3">Instrument</th>
            <th className="px-4 py-3">TF</th>
            <th className="px-4 py-3 text-right">Runtime</th>
            <th className="px-4 py-3">Top metric</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border font-mono">
          {rows.map((r) => (
            <tr key={r.id} className="transition hover:bg-bg-hover">
              <td className="px-4 py-2.5 text-zinc-400">
                {r.created_at.replace("T", " ").slice(0, 19)}
              </td>
              <td className="px-4 py-2.5 text-zinc-300">{r.config?.task}</td>
              <td className="px-4 py-2.5 text-zinc-300">{r.config?.model?.name}</td>
              <td className="px-4 py-2.5 text-zinc-300">
                {r.config?.data?.instrument}
              </td>
              <td className="px-4 py-2.5 text-zinc-500">
                {r.config?.data?.timeframe}
              </td>
              <td className="px-4 py-2.5 text-right text-zinc-400">
                {r.runtime_ms} ms
              </td>
              <td className="px-4 py-2.5 text-zinc-200">
                {topMetric(r.metrics)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function topMetric(m: Record<string, number>): string {
  // Pick the metric most relevant per task: r2 for regression,
  // accuracy for classification, silhouette for clustering.
  for (const k of ["r2", "accuracy", "silhouette"]) {
    if (k in m) return `${k} = ${formatNum(m[k])}`;
  }
  // Fall back to first key.
  const [k, v] = Object.entries(m)[0] ?? ["", 0];
  return k ? `${k} = ${formatNum(v)}` : "";
}

function formatNum(v: number): string {
  if (Math.abs(v) >= 1) return v.toFixed(4);
  if (Math.abs(v) >= 0.001) return v.toFixed(5);
  return v.toExponential(3);
}
