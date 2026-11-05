"use client";

// Pairs dashboard: data coverage, the latest scan (qualification + z), the
// live state the daily job maintains, the signal feed and job history.

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { RequireAuth } from "@/components/auth/require-auth";
import {
  type CoverageItem,
  type JobRun,
  type PairState,
  type PairStats,
  type ScanResponse,
  type Signal,
  type WatchlistItem,
  addWatchlistPair,
  defaultScanConfig,
  fetchCoverage,
  fetchJobs,
  fetchLatestScan,
  fetchSignals,
  fetchState,
  fetchWatchlist,
  fmt,
  refreshData,
  removeWatchlistPair,
  runDailyJob,
  runScan,
  seedDefaultWatchlist,
  shortTicker,
  toggleWatchlistPair,
  zTone,
} from "@/lib/pairs";

import { BTN, BTN_GHOST, Empty, ErrorBox, INPUT, LABEL, SECTION, TD, TH, Tile } from "./subnav";

type SortKey = "pair_name" | "z" | "eg_pvalue" | "half_life" | "stability_ratio" | "beta" | "eg_qvalue";

export function PairsDashboard() {
  const [coverage, setCoverage] = useState<CoverageItem[]>([]);
  const [watch, setWatch] = useState<WatchlistItem[]>([]);
  const [scan, setScan] = useState<ScanResponse | null>(null);
  const [states, setStates] = useState<PairState[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [jobs, setJobs] = useState<JobRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [scanMode, setScanMode] = useState<"watchlist" | "universe">("watchlist");
  const [formation, setFormation] = useState(504);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "z", dir: -1 });
  const [onlyQualified, setOnlyQualified] = useState(false);
  const [newY, setNewY] = useState("");
  const [newX, setNewX] = useState("");

  const load = useCallback(async () => {
    setError(null);
    const [c, w, s, st, sg, j] = await Promise.allSettled([
      fetchCoverage(),
      fetchWatchlist(),
      fetchLatestScan(),
      fetchState(),
      fetchSignals(50),
      fetchJobs(10),
    ]);
    if (c.status === "fulfilled") setCoverage(c.value);
    if (w.status === "fulfilled") setWatch(w.value);
    if (s.status === "fulfilled") setScan(s.value);
    if (st.status === "fulfilled") setStates(st.value);
    if (sg.status === "fulfilled") setSignals(sg.value);
    if (j.status === "fulfilled") setJobs(j.value);
    const failed = [c, w, s, st, sg, j].find((r) => r.status === "rejected") as PromiseRejectedResult | undefined;
    if (failed) setError(failed.reason instanceof Error ? failed.reason.message : String(failed.reason));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(label: string, fn: () => Promise<string | void>) {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      const msg = await fn();
      if (msg) setNotice(msg);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const rows = useMemo(() => {
    const list = (scan?.results ?? []).filter((r) => !onlyQualified || r.qualified);
    const val = (r: PairStats): number | string => {
      const v = r[sort.key];
      if (v === null || v === undefined) return sort.dir === 1 ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY;
      if (sort.key === "z") return Math.abs(v as number);
      return v as number | string;
    };
    return [...list].sort((a, b) => {
      const av = val(a);
      const bv = val(b);
      if (av < bv) return -sort.dir;
      if (av > bv) return sort.dir;
      return 0;
    });
  }, [scan, sort, onlyQualified]);

  const latestDate = coverage.length ? coverage.map((c) => c.last_date).sort().at(-1) : null;
  const earliest = coverage.length ? coverage.map((c) => c.first_date).sort()[0] : null;

  return (
    <div className="space-y-6">
      <ErrorBox error={error} />
      {notice && <div className="rounded-md border border-accent-green/40 bg-accent-green/10 p-3 font-mono text-xs text-accent-green">{notice}</div>}

      {/* ── Data + actions ─────────────────────────────────────────── */}
      <section className={SECTION}>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold text-zinc-200">1 · Data</h2>
            <p className="mt-1 text-xs text-zinc-500">
              Daily settlement / adjusted closes for the pairs universe, separate from the 1m store. New tickers load up to ten years; existing ones refresh a 14-day overlap.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <Tile label="tickers" value={String(coverage.length)} />
            <Tile label="earliest" value={earliest ?? "—"} />
            <Tile label="latest" value={latestDate ?? "—"} />
          </div>
        </div>
        <RequireAuth>
          <div className="flex flex-wrap items-end gap-3">
            <button className={BTN} disabled={busy !== null} onClick={() => act("refresh", async () => {
              const r = await refreshData({});
              return `Refreshed ${r.tickers} tickers · ${r.rows_written} rows · ${r.issues.length} quality flags · latest ${r.latest_date ?? "—"} (${(r.runtime_ms / 1000).toFixed(1)}s)`;
            })}>
              {busy === "refresh" ? "Refreshing…" : "Refresh data"}
            </button>
            <button className={BTN_GHOST} disabled={busy !== null} onClick={() => act("seed", async () => {
              const r = await seedDefaultWatchlist();
              return `Seeded ${r.inserted} default pair(s).`;
            })}>
              Seed default pairs
            </button>
            <div className="ml-auto flex items-end gap-2">
              <div>
                <label className={LABEL}>Scan</label>
                <select className={INPUT} value={scanMode} onChange={(e) => setScanMode(e.target.value as "watchlist" | "universe")}>
                  <option value="watchlist">watchlist</option>
                  <option value="universe">whole universe (slow)</option>
                </select>
              </div>
              <div className="w-28">
                <label className={LABEL}>Formation</label>
                <input className={INPUT} type="number" min={60} max={2520} value={formation} onChange={(e) => setFormation(Number(e.target.value))} />
              </div>
              <button className={BTN} disabled={busy !== null} onClick={() => act("scan", async () => {
                const cfg = defaultScanConfig(scanMode);
                cfg.formation_window = formation;
                if (scanMode === "universe") cfg.stability_step = 5;
                const r = await runScan(cfg);
                return `Scanned ${r.pair_count} pair(s) as of ${r.as_of}: ${r.qualified_count} qualified (${(r.runtime_ms / 1000).toFixed(1)}s).`;
              })}>
                {busy === "scan" ? "Scanning…" : "Run scan"}
              </button>
              <button className={BTN_GHOST} disabled={busy !== null} title="Admin only: runs the daily job now as a dry run (no Discord push)" onClick={() => act("job", async () => {
                const r = await runDailyJob(true);
                return `Daily job (dry run): ${JSON.stringify(r)}`;
              })}>
                Dry-run daily job
              </button>
            </div>
          </div>
        </RequireAuth>
      </section>

      {/* ── Latest scan ────────────────────────────────────────────── */}
      <section className={SECTION}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-zinc-200">2 · Latest scan</h2>
            {scan ? (
              <p className="mt-1 text-xs text-zinc-500">
                {scan.trigger} · as of {scan.as_of} · {scan.pair_count} pairs · {scan.qualified_count} qualified · formation {scan.config.formation_window}d
              </p>
            ) : (
              <p className="mt-1 text-xs text-zinc-500">No scan yet. Refresh data, then run one.</p>
            )}
          </div>
          <label className="flex items-center gap-2 text-xs text-zinc-400">
            <input type="checkbox" checked={onlyQualified} onChange={(e) => setOnlyQualified(e.target.checked)} /> qualified only
          </label>
        </div>
        {rows.length === 0 ? (
          <Empty>{scan ? "No rows match." : "Nothing scanned yet."}</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead className="border-b border-border">
                <tr>
                  {(
                    [
                      ["pair_name", "Pair"],
                      ["z", "z"],
                      ["eg_pvalue", "EG p"],
                      ["eg_qvalue", "BH q"],
                      ["half_life", "HL (d)"],
                      ["beta", "β"],
                      ["stability_ratio", "Stability"],
                    ] as [SortKey, string][]
                  ).map(([k, label]) => (
                    <th key={k} className={`${TH} cursor-pointer select-none hover:text-zinc-300`} onClick={() => setSort((s) => ({ key: k, dir: s.key === k ? (s.dir === 1 ? -1 : 1) : -1 }))}>
                      {label}
                      {sort.key === k ? (sort.dir === 1 ? " ↑" : " ↓") : ""}
                    </th>
                  ))}
                  <th className={TH}>Johansen</th>
                  <th className={TH}>Status</th>
                  <th className={TH}></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((r) => (
                  <tr key={`${r.y_ticker}-${r.x_ticker}`} className="transition hover:bg-bg-hover">
                    <td className={`${TD} font-semibold text-zinc-100`}>{r.pair_name}</td>
                    <td className={`${TD} ${zTone(r.z)}`}>{fmt(r.z)}</td>
                    <td className={`${TD} ${r.eg_pvalue < 0.05 ? "text-zinc-200" : "text-zinc-500"}`}>{fmt(r.eg_pvalue, 3)}</td>
                    <td className={`${TD} text-zinc-400`}>{fmt(r.eg_qvalue, 3)}</td>
                    <td className={`${TD} text-zinc-300`}>{fmt(r.half_life, 1)}</td>
                    <td className={`${TD} text-zinc-300`}>{fmt(r.beta, 3)}</td>
                    <td className={`${TD} text-zinc-300`}>{r.stability_ratio === null ? "—" : `${(r.stability_ratio * 100).toFixed(0)}%`}</td>
                    <td className={`${TD} ${r.johansen_pass ? "text-accent-green" : "text-zinc-500"}`}>{r.johansen_pass ? "✓" : "✗"}</td>
                    <td className={TD}>
                      {r.qualified ? (
                        <span className="rounded bg-accent-green/15 px-2 py-0.5 text-[10px] uppercase tracking-wider text-accent-green">qualified</span>
                      ) : (
                        <span className="text-[10px] text-zinc-500" title={r.reasons.join("\n")}>
                          {r.reasons[0] ?? "—"}
                          {r.reasons.length > 1 ? ` (+${r.reasons.length - 1})` : ""}
                        </span>
                      )}
                      {r.roll_gap_days > 0 && (
                        <span className="ml-2 text-[10px] text-accent-amber" title="large single-day moves inside the window — likely roll gaps on a front-month series">
                          {r.roll_gap_days} gap{r.roll_gap_days > 1 ? "s" : ""}
                        </span>
                      )}
                    </td>
                    <td className={TD}>
                      <Link href={`/research/pairs/analyze?y=${encodeURIComponent(r.y_ticker)}&x=${encodeURIComponent(r.x_ticker)}`} className="text-accent-blue hover:underline">
                        analyze →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* ── Watchlist ───────────────────────────────────────────── */}
        <section className={SECTION}>
          <h2 className="text-sm font-semibold text-zinc-200">3 · Watchlist</h2>
          <p className="text-xs text-zinc-500">The pairs the daily job scans and alerts on. Disabled pairs stay listed but are skipped.</p>
          {watch.length === 0 ? (
            <Empty>Empty — seed the defaults or add a pair below.</Empty>
          ) : (
            <ul className="divide-y divide-border">
              {watch.map((w) => (
                <li key={w.id} className="flex items-center gap-3 py-2 text-xs">
                  <span className={`font-mono font-semibold ${w.enabled ? "text-zinc-100" : "text-zinc-500 line-through"}`}>{w.name}</span>
                  <span className="truncate text-zinc-500">{w.rationale}</span>
                  <span className="ml-auto flex items-center gap-2">
                    <Link href={`/research/pairs/analyze?y=${encodeURIComponent(w.y_ticker)}&x=${encodeURIComponent(w.x_ticker)}`} className="text-accent-blue hover:underline">
                      analyze
                    </Link>
                    <RequireAuth>
                      <button className="text-zinc-400 hover:text-zinc-100" onClick={() => act("toggle", () => toggleWatchlistPair(w.id, !w.enabled).then(() => undefined))}>
                        {w.enabled ? "disable" : "enable"}
                      </button>
                      <button className="text-accent-red/80 hover:text-accent-red" onClick={() => act("remove", () => removeWatchlistPair(w.id))}>
                        remove
                      </button>
                    </RequireAuth>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <RequireAuth>
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <label className={LABEL}>Y ticker</label>
                <input className={INPUT} placeholder="e.g. GLD" value={newY} onChange={(e) => setNewY(e.target.value.trim())} />
              </div>
              <div className="flex-1">
                <label className={LABEL}>X ticker</label>
                <input className={INPUT} placeholder="e.g. GC=F" value={newX} onChange={(e) => setNewX(e.target.value.trim())} />
              </div>
              <button className={BTN_GHOST} disabled={!newY || !newX || busy !== null} onClick={() => act("add", async () => {
                await addWatchlistPair({ name: `${shortTicker(newY)}/${shortTicker(newX)}`, y_ticker: newY, x_ticker: newX });
                setNewY("");
                setNewX("");
                return `Added ${newY}/${newX}.`;
              })}>
                Add
              </button>
            </div>
          </RequireAuth>
        </section>

        {/* ── Live state ──────────────────────────────────────────── */}
        <section className={SECTION}>
          <h2 className="text-sm font-semibold text-zinc-200">4 · Live state</h2>
          <p className="text-xs text-zinc-500">What the daily job currently holds per pair, with the parameters frozen at entry.</p>
          {states.length === 0 ? (
            <Empty>No state yet — the daily job writes it after its first run.</Empty>
          ) : (
            <table className="min-w-full">
              <thead className="border-b border-border">
                <tr>
                  <th className={TH}>Pair</th>
                  <th className={TH}>Side</th>
                  <th className={TH}>Since</th>
                  <th className={TH}>Held</th>
                  <th className={TH}>Last z</th>
                  <th className={TH}>Entry β</th>
                  <th className={TH}>As of</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {states.map((s) => (
                  <tr key={s.pair_name}>
                    <td className={`${TD} font-semibold text-zinc-100`}>{s.pair_name}</td>
                    <td className={`${TD} ${s.side === "flat" ? "text-zinc-500" : s.side === "long_spread" ? "text-accent-green" : "text-accent-red"}`}>{s.side.replace("_", " ")}</td>
                    <td className={`${TD} text-zinc-400`}>{s.entered_on ?? "—"}</td>
                    <td className={`${TD} text-zinc-400`}>{s.side === "flat" ? "—" : `${s.days_held}d`}</td>
                    <td className={`${TD} ${zTone(s.last_z)}`}>{fmt(s.last_z)}</td>
                    <td className={`${TD} text-zinc-400`}>{fmt(s.entry_params?.beta ?? null, 3)}</td>
                    <td className={`${TD} text-zinc-500`}>{s.as_of ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* ── Signals ─────────────────────────────────────────────── */}
        <section className={SECTION}>
          <h2 className="text-sm font-semibold text-zinc-200">5 · Signal feed</h2>
          <p className="text-xs text-zinc-500">Every state change the job recorded. “pushed” means the Discord alert went out.</p>
          {signals.filter((s) => s.event !== "digest").length === 0 ? (
            <Empty>No signals yet.</Empty>
          ) : (
            <ul className="divide-y divide-border">
              {signals.filter((s) => s.event !== "digest").map((s) => (
                <li key={s.id} className="flex items-center gap-3 py-2 font-mono text-xs">
                  <span className="text-zinc-500">{s.signal_date}</span>
                  <EventBadge event={s.event} />
                  <span className="font-semibold text-zinc-100">{s.pair_name}</span>
                  <span className="text-zinc-400">{s.side.replace("_", " ")}</span>
                  <span className="text-zinc-500">z {fmt((s.payload as { z_used?: number | null }).z_used ?? null)}</span>
                  <span className={`ml-auto text-[10px] uppercase tracking-wider ${s.notified_at ? "text-accent-green" : "text-zinc-600"}`}>{s.notified_at ? "pushed" : "not pushed"}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* ── Jobs ────────────────────────────────────────────────── */}
        <section className={SECTION}>
          <h2 className="text-sm font-semibold text-zinc-200">6 · Daily job runs</h2>
          <p className="text-xs text-zinc-500">Scheduled 23:00 UTC on weekdays (configurable). “no_data” is the expected outcome on a US holiday.</p>
          {jobs.length === 0 ? (
            <Empty>No runs recorded.</Empty>
          ) : (
            <ul className="divide-y divide-border">
              {jobs.map((j) => (
                <li key={j.id} className="flex items-center gap-3 py-2 font-mono text-xs">
                  <span className="text-zinc-500">{j.started_at.replace("T", " ").slice(0, 16)}Z</span>
                  <span className={j.status === "ok" ? "text-accent-green" : j.status === "error" ? "text-accent-red" : "text-accent-amber"}>{j.status}</span>
                  {j.dry_run && <span className="text-zinc-500">dry</span>}
                  <span className="truncate text-zinc-400" title={JSON.stringify(j.summary)}>
                    {summarise(j.summary)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function EventBadge({ event }: { event: string }) {
  const tone: Record<string, string> = {
    entry: "bg-accent-green/15 text-accent-green",
    exit: "bg-accent-blue/15 text-accent-blue",
    stop: "bg-accent-red/15 text-accent-red",
    time_stop: "bg-accent-amber/15 text-accent-amber",
    breakdown: "bg-accent-amber/15 text-accent-amber",
  };
  return <span className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wider ${tone[event] ?? "bg-bg-hover text-zinc-400"}`}>{event.replace("_", " ")}</span>;
}

function summarise(s: Record<string, unknown> | null): string {
  if (!s) return "";
  const parts: string[] = [];
  if (typeof s.pairs_scanned === "number") parts.push(`${s.pairs_scanned} scanned`);
  if (typeof s.qualified === "number") parts.push(`${s.qualified} qualified`);
  if (Array.isArray(s.events)) parts.push(`${s.events.length} event(s)`);
  if (typeof s.pushed === "number") parts.push(`${s.pushed} pushed`);
  if (typeof s.error === "string") parts.push(s.error);
  if (typeof s.expected === "string") parts.push(`expected ${s.expected}, latest ${String(s.latest ?? "—")}`);
  return parts.join(" · ");
}
