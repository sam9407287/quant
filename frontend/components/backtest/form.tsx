"use client";

import { useState } from "react";

import {
  EquityChart,
  MonteCarloBars,
  SeasonalityBars,
} from "@/components/backtest/charts";
import type {
  BacktestParams,
  DirectionMode,
  MonteCarloResponse,
  OffsetMode,
  RunResponse,
  SeasonalityResponse,
} from "@/lib/backtest";
import { fetchMonteCarlo, fetchSeasonality, runBacktest } from "@/lib/backtest";
import { INSTRUMENTS, type Instrument } from "@/lib/types";

const SECTION_CLASS =
  "rounded-lg border border-border bg-bg-panel p-5 space-y-4";
const LABEL_CLASS =
  "block text-xs font-mono uppercase tracking-wider text-zinc-500 mb-1";
const INPUT_CLASS =
  "w-full rounded-md border border-border bg-bg-hover px-3 py-2 text-sm font-mono " +
  "text-zinc-100 focus:border-accent-blue focus:outline-none";
const PILL_BTN =
  "rounded-md px-3 py-1.5 font-mono text-xs uppercase tracking-wider transition";

function SectionHeader({ n, title }: { n: number; title: string }) {
  return (
    <h2 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
      <span className="flex h-5 w-5 items-center justify-center rounded bg-accent-blue/20 font-mono text-xs text-accent-blue">
        {n}
      </span>
      {title}
    </h2>
  );
}

function defaultDates(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end.getTime() - 60 * 86400_000);
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  };
}

export function BacktestWorkbench() {
  const dates = defaultDates();
  // ── Universe ────────────────────────────────────────────────────
  const [instrument, setInstrument] = useState<Instrument>("NQ");
  const [start, setStart] = useState(dates.start);
  const [end, setEnd] = useState(dates.end);
  const [pointValue, setPointValue] = useState(2); // MNQ $/pt
  const [contracts, setContracts] = useState(1);
  // ── Session clock ───────────────────────────────────────────────
  const [tz, setTz] = useState("America/New_York");
  const [rangeStart, setRangeStart] = useState("09:00");
  const [rangeEnd, setRangeEnd] = useState("09:30");
  const [ordersPlace, setOrdersPlace] = useState("09:30");
  const [eodFlat, setEodFlat] = useState("15:55");
  // ── Entry / exit ────────────────────────────────────────────────
  const [directionMode, setDirectionMode] = useState<DirectionMode>("fade");
  const [offsetMode, setOffsetMode] = useState<OffsetMode>("points");
  const [offsetValue, setOffsetValue] = useState(0);
  const [slMode, setSlMode] = useState<OffsetMode>("points");
  const [slValue, setSlValue] = useState(100);
  const [rrr, setRrr] = useState(2);
  const [atrPeriod, setAtrPeriod] = useState(14);
  // ── Run state ───────────────────────────────────────────────────
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RunResponse | null>(null);
  const [monthly, setMonthly] = useState<SeasonalityResponse | null>(null);
  const [weekday, setWeekday] = useState<SeasonalityResponse | null>(null);
  const [mc, setMc] = useState<MonteCarloResponse | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    setResult(null);
    setMonthly(null);
    setWeekday(null);
    setMc(null);
    const params: BacktestParams = {
      instrument,
      point_value_usd: pointValue,
      contracts,
      start,
      end,
      clock: {
        tz,
        range_start: rangeStart,
        range_end: rangeEnd,
        orders_place: ordersPlace,
        eod_flat: eodFlat,
      },
      direction_mode: directionMode,
      entry_offset_mode: offsetMode,
      entry_offset_value: offsetValue,
      sl_mode: slMode,
      sl_value: slValue,
      rrr,
      tp_points: null,
      atr_period: atrPeriod,
      slippage_points_per_side: 0,
      commission_usd_per_rt: 0,
    };
    try {
      const res = await runBacktest(params);
      setResult(res);
      // Analysis endpoints are independent — fire together, tolerate
      // individual failures (e.g. too few trades for stats).
      const [m, w, monte] = await Promise.allSettled([
        fetchSeasonality(res.run_id, "month"),
        fetchSeasonality(res.run_id, "weekday"),
        fetchMonteCarlo(res.run_id, { nSims: 5000 }),
      ]);
      if (m.status === "fulfilled") setMonthly(m.value);
      if (w.status === "fulfilled") setWeekday(w.value);
      if (monte.status === "fulfilled") setMc(monte.value);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className={SECTION_CLASS}>
        <SectionHeader n={1} title="Universe" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <div>
            <label className={LABEL_CLASS}>Instrument</label>
            <select
              value={instrument}
              onChange={(e) => setInstrument(e.target.value as Instrument)}
              className={INPUT_CLASS}
            >
              {INSTRUMENTS.map((i) => (
                <option key={i}>{i}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={LABEL_CLASS}>Start</label>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className={INPUT_CLASS} />
          </div>
          <div>
            <label className={LABEL_CLASS}>End</label>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className={INPUT_CLASS} />
          </div>
          <div>
            <label className={LABEL_CLASS}>Point value $</label>
            <input type="number" min={0.1} step={0.1} value={pointValue} onChange={(e) => setPointValue(Number(e.target.value))} className={INPUT_CLASS} />
          </div>
          <div>
            <label className={LABEL_CLASS}>Contracts</label>
            <input type="number" min={1} value={contracts} onChange={(e) => setContracts(Number(e.target.value))} className={INPUT_CLASS} />
          </div>
        </div>
      </section>

      <section className={SECTION_CLASS}>
        <SectionHeader n={2} title="Session clock" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <div>
            <label className={LABEL_CLASS}>Timezone</label>
            <input value={tz} onChange={(e) => setTz(e.target.value)} className={INPUT_CLASS} />
          </div>
          <div>
            <label className={LABEL_CLASS}>Range start</label>
            <input type="time" value={rangeStart} onChange={(e) => setRangeStart(e.target.value)} className={INPUT_CLASS} />
          </div>
          <div>
            <label className={LABEL_CLASS}>Range end</label>
            <input type="time" value={rangeEnd} onChange={(e) => setRangeEnd(e.target.value)} className={INPUT_CLASS} />
          </div>
          <div>
            <label className={LABEL_CLASS}>Place orders at</label>
            <input type="time" value={ordersPlace} onChange={(e) => setOrdersPlace(e.target.value)} className={INPUT_CLASS} />
          </div>
          <div>
            <label className={LABEL_CLASS}>Force flat at</label>
            <input type="time" value={eodFlat} onChange={(e) => setEodFlat(e.target.value)} className={INPUT_CLASS} />
          </div>
        </div>
        <p className="text-xs text-zinc-500">
          Orders are placed from the range window&apos;s high/low; entries may
          trigger until force-flat, which also cancels unfilled orders.
        </p>
      </section>

      <section className={SECTION_CLASS}>
        <SectionHeader n={3} title="Entry & exit" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-6">
          <div>
            <label className={LABEL_CLASS}>Direction</label>
            <div className="flex gap-2">
              {(["fade", "breakout"] as const).map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setDirectionMode(d)}
                  className={`${PILL_BTN} flex-1 ${
                    directionMode === d
                      ? "bg-accent-blue text-white"
                      : "bg-bg-hover text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  {d}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className={LABEL_CLASS}>Offset mode</label>
            <select value={offsetMode} onChange={(e) => setOffsetMode(e.target.value as OffsetMode)} className={INPUT_CLASS}>
              <option value="points">points</option>
              <option value="pct">% of level</option>
              <option value="atr">ATR ×</option>
            </select>
          </div>
          <div>
            <label className={LABEL_CLASS}>Offset value</label>
            <input type="number" step={0.1} value={offsetValue} onChange={(e) => setOffsetValue(Number(e.target.value))} className={INPUT_CLASS} />
          </div>
          <div>
            <label className={LABEL_CLASS}>Stop mode</label>
            <select value={slMode} onChange={(e) => setSlMode(e.target.value as OffsetMode)} className={INPUT_CLASS}>
              <option value="points">points</option>
              <option value="pct">% of entry</option>
              <option value="atr">ATR ×</option>
            </select>
          </div>
          <div>
            <label className={LABEL_CLASS}>Stop value</label>
            <input type="number" min={0.1} step={0.1} value={slValue} onChange={(e) => setSlValue(Number(e.target.value))} className={INPUT_CLASS} />
          </div>
          <div>
            <label className={LABEL_CLASS}>RRR (TP = SL ×)</label>
            <input type="number" min={0.1} step={0.1} value={rrr} onChange={(e) => setRrr(Number(e.target.value))} className={INPUT_CLASS} />
          </div>
        </div>
        {(offsetMode === "atr" || slMode === "atr") && (
          <div className="w-40">
            <label className={LABEL_CLASS}>ATR period (days)</label>
            <input type="number" min={1} value={atrPeriod} onChange={(e) => setAtrPeriod(Number(e.target.value))} className={INPUT_CLASS} />
          </div>
        )}
      </section>

      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={run}
          disabled={busy}
          className="rounded-md bg-accent-blue px-6 py-2.5 font-semibold text-white transition hover:bg-accent-blue/80 disabled:opacity-40"
        >
          {busy ? "Running…" : "Run backtest"}
        </button>
        {result && (
          <span className="font-mono text-xs text-zinc-500">
            {result.metrics.session_count} sessions · {result.runtime_ms} ms ·
            run {result.run_id.slice(0, 8)}
          </span>
        )}
      </div>

      {error && (
        <pre className="whitespace-pre-wrap rounded-md border border-accent-red/40 bg-accent-red/10 p-4 text-xs text-accent-red">
          {error}
        </pre>
      )}

      {result && (
        <>
          <section className={SECTION_CLASS}>
            <SectionHeader n={4} title="Results" />
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <Metric label="Total P&L" value={`$${result.metrics.total_pnl_usd.toFixed(0)}`} highlight={result.metrics.total_pnl_usd >= 0 ? "pos" : "neg"} />
              <Metric label="Trades" value={String(result.metrics.trade_count)} />
              <Metric label="Win rate" value={`${(result.metrics.win_rate * 100).toFixed(1)}%`} />
              <Metric label="Profit factor" value={result.metrics.profit_factor?.toFixed(2) ?? "—"} />
              <Metric label="Max drawdown" value={`$${result.metrics.max_drawdown_usd.toFixed(0)}`} highlight="neg" />
              <Metric label="Sharpe (ann.)" value={result.metrics.sharpe_annualized?.toFixed(2) ?? "—"} />
            </div>
            <EquityChart curve={result.equity_curve} />
          </section>

          <div className="grid gap-6 lg:grid-cols-2">
            {monthly && monthly.buckets.length > 0 && (
              <section className={SECTION_CLASS}>
                <SectionHeader n={5} title="P&L by month" />
                <SeasonalityBars data={monthly} />
              </section>
            )}
            {weekday && weekday.buckets.length > 0 && (
              <section className={SECTION_CLASS}>
                <SectionHeader n={6} title="P&L by weekday" />
                <SeasonalityBars data={weekday} />
              </section>
            )}
          </div>

          {mc && (
            <section className={SECTION_CLASS}>
              <SectionHeader n={7} title={`Monte Carlo (${mc.n_sims.toLocaleString()} sims, ${mc.method})`} />
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Metric label="P(loss)" value={`${(mc.prob_terminal_loss * 100).toFixed(1)}%`} />
                <Metric label="Median terminal" value={`$${mc.terminal_pnl_percentiles["50"]?.toFixed(0)}`} />
                <Metric label="p95 drawdown" value={`$${mc.max_drawdown_percentiles["95"]?.toFixed(0)}`} highlight="neg" />
              </div>
              <MonteCarloBars data={mc} />
            </section>
          )}

          <section className={SECTION_CLASS}>
            <SectionHeader n={8} title="Trades" />
            <TradesTable trades={result.trades} />
          </section>
        </>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: "pos" | "neg";
}) {
  const color =
    highlight === "pos"
      ? "text-accent-green"
      : highlight === "neg"
        ? "text-accent-red"
        : "text-zinc-100";
  return (
    <div className="rounded-md border border-border bg-bg-hover p-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-zinc-500">
        {label}
      </div>
      <div className={`mt-1 font-mono text-lg ${color}`}>{value}</div>
    </div>
  );
}

function TradesTable({ trades }: { trades: RunResponse["trades"] }) {
  const traded = trades.filter((t) => t.direction !== null);
  if (traded.length === 0) {
    return <p className="text-sm text-zinc-500">No fills in this range.</p>;
  }
  return (
    <div className="max-h-96 overflow-auto">
      <table className="min-w-full font-mono text-xs">
        <thead className="sticky top-0 bg-bg-panel text-left text-zinc-500">
          <tr>
            {["Date", "Dir", "Entry", "Exit", "Reason", "P&L pts", "P&L $", "MAE", "MFE"].map((h) => (
              <th key={h} className="px-3 py-2 font-normal uppercase tracking-wider">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border text-zinc-300">
          {traded.map((t) => (
            <tr key={t.session_date}>
              <td className="px-3 py-1.5">{t.session_date}</td>
              <td className={`px-3 py-1.5 ${t.direction === "long" ? "text-accent-green" : "text-accent-red"}`}>
                {t.direction}
              </td>
              <td className="px-3 py-1.5">{t.entry_price?.toFixed(2)}</td>
              <td className="px-3 py-1.5">{t.exit_price?.toFixed(2)}</td>
              <td className="px-3 py-1.5">{t.exit_reason}</td>
              <td className="px-3 py-1.5">{t.pnl_points.toFixed(2)}</td>
              <td className={`px-3 py-1.5 ${t.pnl_usd >= 0 ? "text-accent-green" : "text-accent-red"}`}>
                {t.pnl_usd.toFixed(2)}
              </td>
              <td className="px-3 py-1.5">{t.mae_points.toFixed(1)}</td>
              <td className="px-3 py-1.5">{t.mfe_points.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
