"use client";

// One pair in depth: the evidence table, spread + z through time, how the
// hedge ratio and p-value drifted, and the conditional forward-return table.

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  type AnalysisResponse,
  type PriceSource,
  type UniverseItem,
  fetchAnalysis,
  fetchUniverse,
  fmt,
  shortTicker,
  zTone,
} from "@/lib/pairs";

import { ForwardBucketChart, RollingBetaPChart, SpreadZChart } from "./charts";
import { BTN, Empty, ErrorBox, INPUT, LABEL, SECTION, TD, TH, Tile } from "./subnav";

export function PairAnalyzer() {
  const params = useSearchParams();
  const router = useRouter();
  const [universe, setUniverse] = useState<UniverseItem[]>([]);
  const [y, setY] = useState(params.get("y") ?? "NQ=F");
  const [x, setX] = useState(params.get("x") ?? "ES=F");
  const [formation, setFormation] = useState(Number(params.get("formation_window") ?? 504));
  const [hedge, setHedge] = useState<"ols" | "tls">("ols");
  const [source, setSource] = useState<PriceSource>("settlement");
  const [multiple, setMultiple] = useState(4);
  const [horizon, setHorizon] = useState(10);
  const [data, setData] = useState<AnalysisResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchUniverse().then(setUniverse).catch(() => setUniverse([]));
  }, []);

  const run = useCallback(async () => {
    if (!y || !x || y === x) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetchAnalysis({ y, x, formation_window: formation, hedge_method: hedge, price_source: source, z_window_multiple: multiple });
      setData(res);
      router.replace(`/research/pairs/analyze?y=${encodeURIComponent(y)}&x=${encodeURIComponent(x)}&formation_window=${formation}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [y, x, formation, hedge, source, multiple, router]);

  // Auto-run when arriving with both legs in the URL (links from the dashboard / Discord).
  useEffect(() => {
    if (params.get("y") && params.get("x")) void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const grouped = useMemo(() => {
    const g: Record<string, UniverseItem[]> = {};
    for (const u of universe) (g[u.group] ??= []).push(u);
    return g;
  }, [universe]);

  const s = data?.stats;
  const horizons = useMemo(() => Array.from(new Set((data?.forward ?? []).map((b) => b.horizon))).sort((a, b) => a - b), [data]);

  return (
    <div className="space-y-6">
      <section className={SECTION}>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
          <TickerSelect label="Y (dependent leg)" value={y} onChange={setY} grouped={grouped} />
          <TickerSelect label="X (hedge leg)" value={x} onChange={setX} grouped={grouped} />
          <div>
            <label className={LABEL}>Formation (days)</label>
            <input className={INPUT} type="number" min={60} max={2520} value={formation} onChange={(e) => setFormation(Number(e.target.value))} />
          </div>
          <div>
            <label className={LABEL}>Hedge</label>
            <select className={INPUT} value={hedge} onChange={(e) => setHedge(e.target.value as "ols" | "tls")}>
              <option value="ols">OLS</option>
              <option value="tls">TLS (orthogonal)</option>
            </select>
          </div>
          <div>
            <label className={LABEL}>z window × HL</label>
            <input className={INPUT} type="number" min={1} max={20} step={0.5} value={multiple} onChange={(e) => setMultiple(Number(e.target.value))} />
          </div>
          <div>
            <label className={LABEL}>Price source</label>
            <select className={INPUT} value={source} onChange={(e) => setSource(e.target.value as PriceSource)}>
              <option value="settlement">daily settlement</option>
              <option value="snapshot_1m">15:00 ET snapshot (1m)</option>
            </select>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button className={BTN} disabled={busy || !y || !x || y === x} onClick={() => void run()}>
            {busy ? "Computing…" : "Analyze"}
          </button>
          <button className="text-xs text-zinc-400 hover:text-zinc-100" onClick={() => { setY(x); setX(y); }}>
            swap legs ⇄
          </button>
          {data && (
            <Link
              href={`/research/pairs/backtest?y=${encodeURIComponent(y)}&x=${encodeURIComponent(x)}`}
              className="ml-auto font-mono text-xs uppercase tracking-wider text-accent-blue hover:underline"
            >
              backtest this pair →
            </Link>
          )}
        </div>
        <ErrorBox error={error} />
      </section>

      {!data || !s ? (
        <Empty>Pick two legs and press Analyze. Links from the dashboard open with the pair preselected.</Empty>
      ) : (
        <>
          {data.settlement_note && (
            <div className="rounded-md border border-accent-amber/40 bg-accent-amber/10 p-3 text-xs text-accent-amber">{data.settlement_note}</div>
          )}

          <section className={SECTION}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-zinc-200">
                {data.pair_name} · as of {s.as_of} · {s.n_obs} obs
              </h2>
              {s.qualified ? (
                <span className="rounded bg-accent-green/15 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-accent-green">qualified</span>
              ) : (
                <span className="rounded bg-bg-hover px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-zinc-400">not qualified · {s.reasons.join(" · ")}</span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-8">
              <Tile label="z now" value={fmt(s.z)} tone={s.z !== null && Math.abs(s.z) >= 2 ? (s.z > 0 ? "neg" : "pos") : undefined} hint="spread vs its trailing window mean, in standard deviations" />
              <Tile label="β (OLS)" value={fmt(s.beta, 3)} hint="log Y = α + β log X" />
              <Tile label="β (TLS)" value={fmt(s.beta_tls, 3)} hint="orthogonal regression — symmetric in Y and X" />
              <Tile label="β (Johansen)" value={fmt(s.beta_johansen, 3)} hint="from the first cointegrating eigenvector" />
              <Tile label="half-life" value={s.half_life === null ? "none" : `${fmt(s.half_life, 1)}d`} tone={s.half_life === null ? "neg" : undefined} hint={`90% bootstrap interval ${fmt(s.half_life_ci_low, 1)} – ${fmt(s.half_life_ci_high, 1)}`} />
              <Tile label="z window" value={`${s.z_window}d`} hint="clip(multiple × HL, min, max)" />
              <Tile label="stability" value={s.stability_ratio === null ? "—" : `${(s.stability_ratio * 100).toFixed(0)}%`} hint="share of the last 60 days with EG p < 0.05 (only computed when the point-in-time filters pass)" />
              <Tile label="β drift (CV)" value={fmt(s.beta_cv, 2)} hint="std / mean of the rolling β over the stability window" />
            </div>
            <EvidenceTable s={s} />
          </section>

          <section className={SECTION}>
            <h2 className="text-sm font-semibold text-zinc-200">Spread and z-score</h2>
            <p className="text-xs text-zinc-500">
              Every point uses parameters estimated from the {formation} days strictly before it. Dashed lines are the ±2 entry and ±3.5 stop levels; amber verticals are roll dates from the roll calendar (equity index futures only).
            </p>
            <SpreadZChart data={data} />
          </section>

          <section className={SECTION}>
            <h2 className="text-sm font-semibold text-zinc-200">Rolling hedge ratio and Engle-Granger p-value</h2>
            <p className="text-xs text-zinc-500">A β that trends is a relationship that is changing; a p-value that lives above the red line is a pair that stopped being cointegrated.</p>
            <RollingBetaPChart data={data} />
          </section>

          <section className={SECTION}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-zinc-200">Conditional forward returns</h2>
                <p className="mt-1 text-xs text-zinc-500">
                  For every day in a z bucket: how the spread moved over the next N days. Mean bars should point back toward zero and the hit rate should sit well above 50 % in the outer buckets — otherwise there is no reversion to trade, whatever the p-value says.
                </p>
              </div>
              <div className="flex gap-1">
                {horizons.map((h) => (
                  <button key={h} className={`rounded px-2 py-1 font-mono text-xs ${h === horizon ? "bg-accent-blue/20 text-accent-blue" : "text-zinc-400 hover:bg-bg-hover"}`} onClick={() => setHorizon(h)}>
                    {h}d
                  </button>
                ))}
              </div>
            </div>
            {data.forward.length === 0 ? <Empty>Not enough history for the bucket table.</Empty> : <ForwardBucketChart buckets={data.forward} horizon={horizon} />}
            <ForwardTable rows={data.forward.filter((b) => b.horizon === horizon)} />
          </section>
        </>
      )}
    </div>
  );
}

function TickerSelect({ label, value, onChange, grouped }: { label: string; value: string; onChange: (v: string) => void; grouped: Record<string, UniverseItem[]> }) {
  return (
    <div>
      <label className={LABEL}>{label}</label>
      <select className={INPUT} value={value} onChange={(e) => onChange(e.target.value)}>
        {Object.keys(grouped).length === 0 && <option value={value}>{value}</option>}
        {Object.entries(grouped).map(([group, items]) => (
          <optgroup key={group} label={group.replace("_", " ")}>
            {items.map((u) => (
              <option key={u.ticker} value={u.ticker}>
                {shortTicker(u.ticker)} · {u.name}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}

function EvidenceTable({ s }: { s: AnalysisResponse["stats"] }) {
  const rows: { test: string; value: string; pass: boolean | null; note: string }[] = [
    { test: "Engle-Granger p (Y on X)", value: fmt(s.eg_pvalue, 4), pass: s.eg_pvalue < 0.05, note: "residual of log Y on log X is stationary" },
    { test: "Engle-Granger p (X on Y)", value: fmt(s.eg_pvalue_reverse, 4), pass: s.eg_pvalue_reverse < 0.05, note: "the test depends on direction; both should agree" },
    { test: "BH q-value", value: fmt(s.eg_qvalue, 4), pass: s.eg_qvalue === null ? null : s.eg_qvalue < 0.05, note: "false-discovery-rate adjusted across the scan family" },
    { test: "ADF on spread", value: fmt(s.adf_pvalue, 4), pass: s.adf_pvalue === null ? null : s.adf_pvalue < 0.05, note: "unit-root test on the OLS residual itself" },
    { test: "Johansen trace", value: `${fmt(s.johansen_trace, 1)} vs ${fmt(s.johansen_crit_95, 1)}`, pass: s.johansen_pass, note: "system-based test; above the 95 % critical value = at least one cointegrating vector" },
    { test: "Hurst exponent", value: fmt(s.hurst, 2), pass: s.hurst === null ? null : s.hurst < 0.5, note: "< 0.5 mean reverting, 0.5 random walk, > 0.5 trending (rough estimate)" },
    { test: "60-day return correlation", value: fmt(s.corr_returns_60d, 2), pass: null, note: "short-horizon co-movement; governs risk, not the drift" },
    { test: "Roll gaps in window", value: String(s.roll_gap_days), pass: s.roll_gap_days === 0 ? true : null, note: "large single-day moves — on a front-month series these are contract rolls polluting the spread" },
  ];
  return (
    <div className="overflow-x-auto"><table className="min-w-full">
      <thead className="border-b border-border">
        <tr>
          <th className={TH}>Evidence</th>
          <th className={TH}>Value</th>
          <th className={TH}></th>
          <th className={TH}>Meaning</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {rows.map((r) => (
          <tr key={r.test}>
            <td className={`${TD} text-zinc-200`}>{r.test}</td>
            <td className={`${TD} text-zinc-100`}>{r.value}</td>
            <td className={`${TD} ${r.pass === null ? "text-zinc-600" : r.pass ? "text-accent-green" : "text-accent-red"}`}>{r.pass === null ? "·" : r.pass ? "✓" : "✗"}</td>
            <td className={`${TD} text-zinc-500`}>{r.note}</td>
          </tr>
        ))}
      </tbody>
    </table></div>
  );
}

function ForwardTable({ rows }: { rows: AnalysisResponse["forward"] }) {
  if (rows.length === 0) return null;
  return (
    <div className="overflow-x-auto"><table className="min-w-full">
      <thead className="border-b border-border">
        <tr>
          <th className={TH}>z bucket</th>
          <th className={TH}>n</th>
          <th className={TH}>mean Δ</th>
          <th className={TH}>median Δ</th>
          <th className={TH}>IQR</th>
          <th className={TH}>hit rate</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {rows.map((b) => (
          <tr key={b.bucket}>
            <td className={`${TD} ${zTone((b.z_low + b.z_high) / 2)}`}>{b.bucket}</td>
            <td className={`${TD} text-zinc-400`}>{b.count}</td>
            <td className={`${TD} ${b.mean * ((b.z_low + b.z_high) / 2) < 0 ? "text-accent-green" : "text-zinc-300"}`}>{fmt(b.mean, 4)}</td>
            <td className={`${TD} text-zinc-300`}>{fmt(b.median, 4)}</td>
            <td className={`${TD} text-zinc-500`}>{fmt(b.p25, 4)} … {fmt(b.p75, 4)}</td>
            <td className={`${TD} ${b.hit_rate >= 0.6 ? "text-accent-green" : b.hit_rate <= 0.45 ? "text-accent-red" : "text-zinc-300"}`}>{(b.hit_rate * 100).toFixed(0)}%</td>
          </tr>
        ))}
      </tbody>
    </table></div>
  );
}
