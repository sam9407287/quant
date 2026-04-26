import type { CoverageRecord } from "@/lib/types";

function fmtTs(ts: string | null): string {
  if (!ts) return "—";
  return ts.replace("T", " ").slice(0, 16) + "Z";
}

export function CoverageTable({ rows }: { rows: CoverageRecord[] }) {
  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-border bg-bg-panel p-6 text-sm text-zinc-400">
        No coverage rows. The fetcher may not have written any data yet.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-bg-panel">
      <table className="min-w-full text-sm">
        <thead className="border-b border-border bg-bg-hover/50 text-left text-xs uppercase tracking-wider text-zinc-400">
          <tr>
            <th className="px-4 py-3">Instrument</th>
            <th className="px-4 py-3">Timeframe</th>
            <th className="px-4 py-3">Earliest</th>
            <th className="px-4 py-3">Latest</th>
            <th className="px-4 py-3 text-right">Bars</th>
            <th className="px-4 py-3 text-right">Gaps</th>
            <th className="px-4 py-3">Last fetch</th>
            <th className="px-4 py-3">OK?</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border font-mono">
          {rows.map((r) => (
            <tr
              key={`${r.instrument}-${r.timeframe}`}
              className="transition hover:bg-bg-hover"
            >
              <td className="px-4 py-2.5 font-semibold text-zinc-100">
                {r.instrument}
              </td>
              <td className="px-4 py-2.5 text-zinc-300">{r.timeframe}</td>
              <td className="px-4 py-2.5 text-zinc-400">{fmtTs(r.earliest_ts)}</td>
              <td className="px-4 py-2.5 text-zinc-400">{fmtTs(r.latest_ts)}</td>
              <td className="px-4 py-2.5 text-right text-zinc-200">
                {r.bar_count.toLocaleString()}
              </td>
              <td className="px-4 py-2.5 text-right text-zinc-500">
                {r.gap_count}
              </td>
              <td className="px-4 py-2.5 text-zinc-500">
                {fmtTs(r.last_fetch_ts)}
              </td>
              <td className="px-4 py-2.5">
                {r.last_fetch_ok ? (
                  <span className="text-accent-green">●</span>
                ) : (
                  <span className="text-accent-red">●</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
