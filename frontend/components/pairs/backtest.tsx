"use client";

// Walk-forward pairs backtest: configure pairs, rules, costs and capital;
// read the equity curve, honest metrics, attribution, correlation and the
// sensitivity grid; reopen earlier runs.

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  type BacktestConfig,
  type BacktestRunDetail,
  type BacktestRunRecord,
  type UniverseItem,
  type WatchlistItem,
  defaultBacktestConfig,
  fetchPairsBacktest,
  fetchPairsBacktests,
  fetchUniverse,
  fetchWatchlist,
  fmt,
  pct,
  runPairsBacktest,
  shortTicker,
  usd,
} from "@/lib/pairs";

import { AttributionBars, CorrelationHeatmap, EquityDrawdownChart, SensitivityHeatmap } from "./charts";
import { BTN, BTN_GHOST, Empty, ErrorBox, INPUT, LABEL, SECTION, TD, TH, Tile } from "./subnav";

type Num = (v: number) => void;

export function PairsBacktestWorkbench() {
  const params = useSearchParams();
  const initialPair: [string, string] | null = params.get("y") && params.get("x") ? [params.get("y") as string, params.get("x") as string] : null;
  const [cfg, setCfg] = useState<BacktestConfig>(() => defaultBacktestConfig(initialPair ? [initialPair] : []));
  const [universe, setUniverse] = useState<UniverseItem[]>([]);
  const [watch, setWatch] = useState<WatchlistItem[]>([]);
  const [newY, setNewY] = useState("NQ=F");
  const [newX, setNewX] = useState("ES=F");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<BacktestRunDetail | null>(null);
  const [history, setHistory] = useState<BacktestRunRecord[]>([]);
  const [sensMetric, setSensMetric] = useState<"sharpe" | "total_return" | "max_drawdown">("sharpe");
  const [showTrades, setShowTrades] = useState(false);

  const loadHistory = useCallback(() => fetchPairsBacktests(30).then(setHistory).catch(() => setHistory([])), []);

  useEffect(() => {
    fetchUniverse().then(setUniverse).catch(() => setUniverse([]));
    fetchWatchlist().then(setWatch).catch(() => setWatch([]));
    void loadHistory();
  }, [loadHistory]);

  const set = <K extends keyof BacktestConfig>(k: K, v: BacktestConfig[K]) => setCfg((c) => ({ ...c, [k]: v }));
  const setRule = <K extends keyof BacktestConfig["rules"]>(k: K, v: BacktestConfig["rules"][K]) => setCfg((c) => ({ ...c, rules: { ...c.rules, [k]: v } }));
  const setCost = <K extends keyof BacktestConfig["costs"]>(k: K, v: BacktestConfig["costs"][K]) => setCfg((c) => ({ ...c, costs: { ...c.costs, [k]: v } }));
  const setPort = <K extends keyof BacktestConfig["portfolio"]>(k: K, v: BacktestConfig["portfolio"][K]) => setCfg((c) => ({ ...c, portfolio: { ...c.portfolio, [k]: v } }));
  const setQual = <K extends keyof BacktestConfig["qualification"]>(k: K, v: BacktestConfig["qualification"][K]) =>
    setCfg((c) => ({ ...c, qualification: { ...c.qualification, [k]: v } }));

  function addPair(y: string, x: string) {
    if (!y || !x || y === x) return;
    setCfg((c) => (c.pairs.some(([a, b]) => a === y && b === x) ? c : { ...c, pairs: [...c.pairs, [y, x]] }));
  }

  async function execute() {
    setBusy(true);
    setError(null);
    try {
      const res = await runPairsBacktest(cfg, notes || undefined);
      setRun(res);
      void loadHistory();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function open(id: string) {
    setError(null);
    try {
      const r = await fetchPairsBacktest(id);
      setRun(r);
      setCfg(r.config);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const tickers = useMemo(() => universe.map((u) => u.ticker), [universe]);
  const m = run?.metrics;

  return (
    <div className="space-y-6">
      {/* ── Pairs ───────────────────────────────────────────────── */}
      <section className={SECTION}>
        <h2 className="text-sm font-semibold text-zinc-200">1 · Pairs</h2>
        <div className="flex flex-wrap gap-2">
          {cfg.pairs.length === 0 && <span className="text-xs text-zinc-500">No pairs yet — add from the watchlist or by ticker.</span>}
          {cfg.pairs.map(([y, x]) => (
            <span key={`${y}/${x}`} className="flex items-center gap-2 rounded border border-border bg-bg-hover px-2 py-1 font-mono text-xs text-zinc-100">
              {shortTicker(y)}/{shortTicker(x)}
              <button className="text-zinc-500 hover:text-accent-red" onClick={() => set("pairs", cfg.pairs.filter(([a, b]) => !(a === y && b === x)))}>
                ×
              </button>
            </span>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className={LABEL}>Y</label>
            <input className={INPUT} list="pairs-tickers" value={newY} onChange={(e) => setNewY(e.target.value.trim())} />
          </div>
          <div>
            <label className={LABEL}>X</label>
            <input className={INPUT} list="pairs-tickers" value={newX} onChange={(e) => setNewX(e.target.value.trim())} />
          </div>
          <datalist id="pairs-tickers">
            {tickers.map((t) => (
              <option key={t} value={t} />
            ))}
          </datalist>
          <button className={BTN_GHOST} onClick={() => addPair(newY, newX)}>
            Add pair
          </button>
          <button className={BTN_GHOST} disabled={watch.length === 0} onClick={() => watch.filter((w) => w.enabled).forEach((w) => addPair(w.y_ticker, w.x_ticker))}>
            Add whole watchlist
          </button>
          <button className={BTN_GHOST} disabled={cfg.pairs.length === 0} onClick={() => set("pairs", [])}>
            Clear
          </button>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* ── Estimation ──────────────────────────────────────────── */}
        <section className={SECTION}>
          <h2 className="text-sm font-semibold text-zinc-200">2 · Estimation</h2>
          <NumberField label="Formation window (days)" value={cfg.formation_window} onChange={(v) => set("formation_window", v)} min={60} max={2520} />
          <div className="grid grid-cols-3 gap-2">
            <NumberField label="z win × HL" value={cfg.z_window_multiple} onChange={(v) => set("z_window_multiple", v)} step={0.5} min={1} />
            <NumberField label="z win min" value={cfg.z_window_min} onChange={(v) => set("z_window_min", v)} min={5} />
            <NumberField label="z win max" value={cfg.z_window_max} onChange={(v) => set("z_window_max", v)} min={10} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={LABEL}>Hedge</label>
              <select className={INPUT} value={cfg.hedge_method} onChange={(e) => set("hedge_method", e.target.value as "ols" | "tls")}>
                <option value="ols">OLS</option>
                <option value="tls">TLS</option>
              </select>
            </div>
            <div>
              <label className={LABEL}>Fill</label>
              <select className={INPUT} value={cfg.fill} onChange={(e) => set("fill", e.target.value as BacktestConfig["fill"])}>
                <option value="next_open">next open</option>
                <option value="next_close">next close</option>
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={LABEL}>Start (optional)</label>
              <input className={INPUT} type="date" value={cfg.start ?? ""} onChange={(e) => set("start", e.target.value || null)} />
            </div>
            <div>
              <label className={LABEL}>End (optional)</label>
              <input className={INPUT} type="date" value={cfg.end ?? ""} onChange={(e) => set("end", e.target.value || null)} />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <NumberField label="EG p max" value={cfg.qualification.eg_pvalue_max} onChange={(v) => setQual("eg_pvalue_max", v)} step={0.01} />
            <NumberField label="HL min" value={cfg.qualification.half_life_min} onChange={(v) => setQual("half_life_min", v)} />
            <NumberField label="HL max" value={cfg.qualification.half_life_max} onChange={(v) => setQual("half_life_max", v)} />
          </div>
          <Toggle label="Only trade when qualified (gate)" checked={cfg.rules.require_qualified} onChange={(v) => setRule("require_qualified", v)} />
        </section>

        {/* ── Rules ───────────────────────────────────────────────── */}
        <section className={SECTION}>
          <h2 className="text-sm font-semibold text-zinc-200">3 · Signal rules</h2>
          <div className="grid grid-cols-3 gap-2">
            <NumberField label="Entry |z|" value={cfg.rules.entry_z} onChange={(v) => setRule("entry_z", v)} step={0.1} />
            <NumberField label="Exit |z|" value={cfg.rules.exit_z} onChange={(v) => setRule("exit_z", v)} step={0.1} />
            <NumberField label="Stop |z|" value={cfg.rules.stop_z} onChange={(v) => setRule("stop_z", v)} step={0.1} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={LABEL}>Exit rule</label>
              <select className={INPUT} value={cfg.rules.exit_rule} onChange={(e) => setRule("exit_rule", e.target.value as BacktestConfig["rules"]["exit_rule"])}>
                <option value="threshold">|z| ≤ exit</option>
                <option value="cross_zero">z crosses zero</option>
              </select>
            </div>
            <NumberField label="Time stop (× HL)" value={cfg.rules.time_stop_half_lives} onChange={(v) => setRule("time_stop_half_lives", v)} step={0.5} />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <NumberField label="Breakdown p >" value={cfg.rules.breakdown_pvalue} onChange={(v) => setRule("breakdown_pvalue", v)} step={0.01} />
            <NumberField label="for N days" value={cfg.rules.breakdown_days} onChange={(v) => setRule("breakdown_days", v)} />
            <NumberField label="Cooldown (days)" value={cfg.rules.cooldown_days} onChange={(v) => setRule("cooldown_days", v)} />
          </div>
          <Toggle label="Freeze β / mean / std at entry" checked={cfg.rules.freeze_params} onChange={(v) => setRule("freeze_params", v)} />
          <h3 className="pt-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">Costs</h3>
          <div className="grid grid-cols-3 gap-2">
            <NumberField label="$ / contract / side" value={cfg.costs.commission_per_contract} onChange={(v) => setCost("commission_per_contract", v)} step={0.25} />
            <NumberField label="Slippage (ticks)" value={cfg.costs.slippage_ticks} onChange={(v) => setCost("slippage_ticks", v)} step={0.5} />
            <NumberField label="Roll $ / contract" value={cfg.costs.roll_cost_per_contract} onChange={(v) => setCost("roll_cost_per_contract", v)} step={0.5} />
          </div>
        </section>

        {/* ── Capital ─────────────────────────────────────────────── */}
        <section className={SECTION}>
          <h2 className="text-sm font-semibold text-zinc-200">4 · Capital and sizing</h2>
          <div className="grid grid-cols-2 gap-2">
            <NumberField label="Capital ($)" value={cfg.portfolio.capital} onChange={(v) => setPort("capital", v)} step={10000} />
            <NumberField label="Gross leverage" value={cfg.portfolio.gross_leverage} onChange={(v) => setPort("gross_leverage", v)} step={0.5} min={0.1} max={10} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={LABEL}>Weights</label>
              <select className={INPUT} value={cfg.portfolio.weight_scheme} onChange={(e) => setPort("weight_scheme", e.target.value as BacktestConfig["portfolio"]["weight_scheme"])}>
                <option value="equal">equal</option>
                <option value="inverse_vol">inverse spread vol</option>
              </select>
            </div>
            <NumberField label="Max concurrent" value={cfg.portfolio.max_concurrent} onChange={(v) => setPort("max_concurrent", v)} min={1} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={LABEL}>Sizing</label>
              <select className={INPUT} value={cfg.portfolio.sizing} onChange={(e) => setPort("sizing", e.target.value as BacktestConfig["portfolio"]["sizing"])}>
                <option value="fractional">fractional (ideal)</option>
                <option value="integer">integer contracts</option>
              </select>
            </div>
            <div className="pt-5">
              <Toggle label="Prefer micros" checked={cfg.portfolio.prefer_micro} onChange={(v) => setPort("prefer_micro", v)} />
            </div>
          </div>
          <h3 className="pt-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">Sensitivity</h3>
          <Toggle label="Run the entry-z × formation × exit-rule grid" checked={cfg.sensitivity} onChange={(v) => set("sensitivity", v)} />
          {cfg.sensitivity && (
            <div className="grid grid-cols-2 gap-2">
              <ListField label="Entry z values" value={cfg.sensitivity_entry_z} onChange={(v) => set("sensitivity_entry_z", v)} />
              <ListField label="Formation windows" value={cfg.sensitivity_formation} onChange={(v) => set("sensitivity_formation", v)} />
            </div>
          )}
          <div>
            <label className={LABEL}>Notes</label>
            <input className={INPUT} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="what is this run testing?" />
          </div>
          <button className={`${BTN} w-full`} disabled={busy || cfg.pairs.length === 0} onClick={() => void execute()}>
            {busy ? "Running walk-forward…" : `Run backtest (${cfg.pairs.length} pair${cfg.pairs.length === 1 ? "" : "s"})`}
          </button>
          <ErrorBox error={error} />
        </section>
      </div>

      {/* ── Results ─────────────────────────────────────────────── */}
      {run && m && (
        <>
          <section className={SECTION}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-zinc-200">
                Results · {run.config.pairs.length} pair(s) · {run.result.equity[0]?.date} → {run.result.equity.at(-1)?.date} · {(run.runtime_ms / 1000).toFixed(1)}s
              </h2>
              <span className="font-mono text-[10px] text-zinc-500">run {run.id.slice(0, 8)}</span>
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
              <Tile label="total return" value={pct(m.total_return)} tone={m.total_return >= 0 ? "pos" : "neg"} />
              <Tile label="annual return" value={pct(m.annual_return)} />
              <Tile label="Sharpe" value={fmt(m.sharpe)} hint={`bootstrap 90% CI ${fmt(m.sharpe_ci_low)} – ${fmt(m.sharpe_ci_high)}`} tone={m.sharpe !== null && m.sharpe > 1 ? "pos" : undefined} />
              <Tile label="deflated Sharpe p" value={pct(m.deflated_sharpe_p, 0)} hint={`probability the true Sharpe beats the best-of-${m.trials} null`} tone={m.deflated_sharpe_p !== null && m.deflated_sharpe_p < 0.9 ? "warn" : "pos"} />
              <Tile label="max drawdown" value={pct(m.max_drawdown)} tone="neg" hint={`${m.max_drawdown_days} days peak-to-recovery`} />
              <Tile label="Calmar" value={fmt(m.calmar)} />
              <Tile label="Sortino" value={fmt(m.sortino)} />
              <Tile label="CVaR 95 (daily)" value={pct(m.cvar_95)} />
              <Tile label="trades" value={String(m.trade_count)} hint={Object.entries(m.exit_mix).map(([k, v]) => `${k}: ${v}`).join(" · ")} />
              <Tile label="win rate" value={pct(m.win_rate, 0)} />
              <Tile label="profit factor" value={fmt(m.profit_factor)} />
              <Tile label="avg hold" value={m.avg_hold_days === null ? "—" : `${m.avg_hold_days.toFixed(1)}d`} />
              <Tile label="time in market" value={pct(m.time_in_market, 0)} />
              <Tile label="benchmark (hold Y)" value={pct(m.benchmark_return)} hint={`max DD ${pct(m.benchmark_max_drawdown)}`} />
              <Tile label="annual vol" value={pct(m.annual_vol)} />
              {m.tradeability_tax !== null && <Tile label="tradeability tax" value={pct(m.tradeability_tax)} hint="fractional return − integer-contract return" tone="warn" />}
            </div>
            <div className="flex flex-wrap gap-2 text-[10px] font-mono uppercase tracking-wider text-zinc-500">
              {Object.entries(m.exit_mix).map(([k, v]) => (
                <span key={k} className="rounded border border-border px-2 py-0.5">
                  {k.replace("_", " ")}: {v}
                </span>
              ))}
            </div>
          </section>

          <section className={SECTION}>
            <h2 className="text-sm font-semibold text-zinc-200">Equity and drawdown</h2>
            <EquityDrawdownChart curve={run.result.equity} />
          </section>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <section className={SECTION}>
              <h2 className="text-sm font-semibold text-zinc-200">Per-pair attribution</h2>
              <AttributionBars rows={run.result.attribution} />
              <div className="overflow-x-auto"><table className="min-w-full">
                <thead className="border-b border-border">
                  <tr>
                    <th className={TH}>Pair</th>
                    <th className={TH}>Net</th>
                    <th className={TH}>Trades</th>
                    <th className={TH}>Win</th>
                    <th className={TH}>Sharpe</th>
                    <th className={TH}>Max DD</th>
                    <th className={TH}>Qualified days</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {run.result.attribution.map((a) => (
                    <tr key={a.pair_name}>
                      <td className={`${TD} font-semibold text-zinc-100`}>{a.pair_name}</td>
                      <td className={`${TD} ${a.net_pnl >= 0 ? "text-accent-green" : "text-accent-red"}`}>{usd(a.net_pnl)}</td>
                      <td className={`${TD} text-zinc-300`}>{a.trade_count}</td>
                      <td className={`${TD} text-zinc-300`}>{pct(a.win_rate, 0)}</td>
                      <td className={`${TD} text-zinc-300`}>{fmt(a.sharpe)}</td>
                      <td className={`${TD} text-zinc-300`}>{pct(a.max_drawdown)}</td>
                      <td className={`${TD} text-zinc-500`}>
                        {a.qualified_days}/{a.total_days}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            </section>
            <section className={SECTION}>
              <h2 className="text-sm font-semibold text-zinc-200">P&amp;L correlation between pairs</h2>
              <p className="text-xs text-zinc-500">High positive values mean the pairs are the same bet twice; the portfolio drawdown will be deeper than any single pair suggests.</p>
              {run.result.correlation.pairs.length >= 2 ? (
                <CorrelationHeatmap pairs={run.result.correlation.pairs} matrix={run.result.correlation.matrix} />
              ) : (
                <Empty>Add a second pair to see correlations.</Empty>
              )}
            </section>
          </div>

          {run.result.sensitivity.length > 0 && (
            <section className={SECTION}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-zinc-200">Sensitivity</h2>
                  <p className="mt-1 text-xs text-zinc-500">Pick parameters from a stable plateau, not the single best cell. The grid size ({run.result.sensitivity.length} trials) is what the deflated Sharpe above discounts for.</p>
                </div>
                <div className="flex gap-1">
                  {(["sharpe", "total_return", "max_drawdown"] as const).map((k) => (
                    <button key={k} className={`rounded px-2 py-1 font-mono text-xs ${k === sensMetric ? "bg-accent-blue/20 text-accent-blue" : "text-zinc-400 hover:bg-bg-hover"}`} onClick={() => setSensMetric(k)}>
                      {k.replace("_", " ")}
                    </button>
                  ))}
                </div>
              </div>
              <SensitivityHeatmap cells={run.result.sensitivity} metric={sensMetric} />
            </section>
          )}

          <section className={SECTION}>
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-zinc-200">Trades ({run.result.trades.length})</h2>
              <button className="text-xs text-accent-blue hover:underline" onClick={() => setShowTrades((v) => !v)}>
                {showTrades ? "hide" : "show"}
              </button>
            </div>
            {showTrades && (
              <div className="max-h-[480px] overflow-auto">
                <div className="overflow-x-auto"><table className="min-w-full">
                  <thead className="sticky top-0 border-b border-border bg-bg-panel">
                    <tr>
                      <th className={TH}>Pair</th>
                      <th className={TH}>Side</th>
                      <th className={TH}>Entry</th>
                      <th className={TH}>Exit</th>
                      <th className={TH}>z in → out</th>
                      <th className={TH}>Reason</th>
                      <th className={TH}>Held</th>
                      <th className={TH}>Legs</th>
                      <th className={TH}>Gross</th>
                      <th className={TH}>Costs</th>
                      <th className={TH}>Net</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {run.result.trades.map((t, i) => (
                      <tr key={i}>
                        <td className={`${TD} text-zinc-100`}>{t.pair_name}</td>
                        <td className={`${TD} ${t.side === "long_spread" ? "text-accent-green" : "text-accent-red"}`}>{t.side.replace("_spread", "")}</td>
                        <td className={`${TD} text-zinc-400`}>{t.entry_date}</td>
                        <td className={`${TD} text-zinc-400`}>{t.exit_date ?? "open"}</td>
                        <td className={`${TD} text-zinc-300`}>
                          {fmt(t.entry_z, 1)} → {fmt(t.exit_z, 1)}
                        </td>
                        <td className={`${TD} text-zinc-400`}>{t.exit_reason?.replace("_", " ") ?? "—"}</td>
                        <td className={`${TD} text-zinc-400`}>{t.days_held}d</td>
                        <td className={`${TD} text-zinc-500`}>
                          {fmt(t.y_qty, 1)} {t.y_contract} / {fmt(t.x_qty, 1)} {t.x_contract}
                          {t.rounding_error_pct !== null && t.rounding_error_pct > 0 ? ` (±${t.rounding_error_pct.toFixed(0)}%)` : ""}
                        </td>
                        <td className={`${TD} text-zinc-300`}>{usd(t.gross_pnl)}</td>
                        <td className={`${TD} text-zinc-500`}>{usd(-t.costs)}</td>
                        <td className={`${TD} ${t.net_pnl >= 0 ? "text-accent-green" : "text-accent-red"}`}>{usd(t.net_pnl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              </div>
            )}
          </section>
        </>
      )}

      {/* ── History ─────────────────────────────────────────────── */}
      <section className={SECTION}>
        <h2 className="text-sm font-semibold text-zinc-200">Previous runs</h2>
        {history.length === 0 ? (
          <Empty>No saved runs yet. Sign in and run a backtest.</Empty>
        ) : (
          <div className="overflow-x-auto"><table className="min-w-full">
            <thead className="border-b border-border">
              <tr>
                <th className={TH}>When</th>
                <th className={TH}>Pairs</th>
                <th className={TH}>Return</th>
                <th className={TH}>Sharpe</th>
                <th className={TH}>DSR p</th>
                <th className={TH}>Max DD</th>
                <th className={TH}>Trades</th>
                <th className={TH}>Notes</th>
                <th className={TH}></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {history.map((h) => (
                <tr key={h.id} className="transition hover:bg-bg-hover">
                  <td className={`${TD} text-zinc-400`}>{h.created_at.replace("T", " ").slice(0, 16)}</td>
                  <td className={`${TD} text-zinc-200`}>{h.config.pairs.map(([a, b]) => `${shortTicker(a)}/${shortTicker(b)}`).join(", ")}</td>
                  <td className={`${TD} ${h.metrics.total_return >= 0 ? "text-accent-green" : "text-accent-red"}`}>{pct(h.metrics.total_return)}</td>
                  <td className={`${TD} text-zinc-300`}>{fmt(h.metrics.sharpe)}</td>
                  <td className={`${TD} text-zinc-300`}>{pct(h.metrics.deflated_sharpe_p, 0)}</td>
                  <td className={`${TD} text-zinc-300`}>{pct(h.metrics.max_drawdown)}</td>
                  <td className={`${TD} text-zinc-400`}>{h.metrics.trade_count}</td>
                  <td className={`${TD} truncate text-zinc-500`}>{h.notes}</td>
                  <td className={TD}>
                    <button className="text-accent-blue hover:underline" onClick={() => void open(h.id)}>
                      open
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </section>
    </div>
  );
}

function NumberField({ label, value, onChange, step = 1, min, max }: { label: string; value: number; onChange: Num; step?: number; min?: number; max?: number }) {
  return (
    <div>
      <label className={LABEL}>{label}</label>
      <input className={INPUT} type="number" value={value} step={step} min={min} max={max} onChange={(e) => onChange(Number(e.target.value))} />
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-xs text-zinc-300">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function ListField({ label, value, onChange }: { label: string; value: number[]; onChange: (v: number[]) => void }) {
  return (
    <div>
      <label className={LABEL}>{label}</label>
      <input
        className={INPUT}
        value={value.join(", ")}
        onChange={(e) =>
          onChange(
            e.target.value
              .split(",")
              .map((s) => Number(s.trim()))
              .filter((n) => Number.isFinite(n) && n > 0),
          )
        }
      />
    </div>
  );
}
