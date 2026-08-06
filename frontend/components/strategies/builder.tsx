"use client";

import { useCallback, useEffect, useState } from "react";

import type {
  Condition,
  ConditionOp,
  Operand,
  OperandKind,
  StrategyDefinition,
  StrategyRecord,
} from "@/lib/strategies";
import {
  conditionLabel,
  createStrategy,
  deleteStrategy,
  listStrategies,
  updateStrategy,
} from "@/lib/strategies";
import { STRATEGY_TEMPLATES, type StrategyTemplate } from "@/lib/strategy-templates";
import { TIMEFRAMES, type Timeframe } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { copyStrategy } from "@/lib/strategies";
import { SharingPanel } from "@/components/strategies/sharing";

// Session, killzone and per-session limits have no editor on this page —
// they are canvas modules. This form still has to carry them through an
// edit untouched, or opening a canvas-built strategy here and pressing
// Save would quietly delete half of it.
type IntradayParts = Pick<
  StrategyDefinition,
  "session" | "stop_entry" | "max_trades_per_session"
>;

const NO_INTRADAY: IntradayParts = {
  session: null,
  stop_entry: null,
  max_trades_per_session: null,
};

const intradayOf = (d: StrategyDefinition): IntradayParts => ({
  session: d.session ?? null,
  stop_entry: d.stop_entry ?? null,
  max_trades_per_session: d.max_trades_per_session ?? null,
});

const SECTION_CLASS =
  "rounded-lg border border-border bg-bg-panel p-5 space-y-4";
const LABEL_CLASS =
  "block text-xs font-mono uppercase tracking-wider text-zinc-500 mb-1";
const INPUT_CLASS =
  "w-full rounded-md border border-border bg-bg-hover px-3 py-2 text-sm font-mono " +
  "text-zinc-100 focus:border-accent-blue focus:outline-none";
const PILL_BTN =
  "rounded-md px-3 py-1.5 font-mono text-xs uppercase tracking-wider transition";

// ── Editable state shapes (looser than the wire types while typing) ──

interface OperandState {
  kind: OperandKind;
  window: number;
  window2: number;
  value: number;
}

interface ConditionState {
  enabled: boolean;
  op: ConditionOp;
  left: OperandState;
  right: OperandState;
}

interface BracketState {
  enabled: boolean;
  mode: "pct" | "points";
  value: number;
}

const DEFAULT_OPERAND: OperandState = { kind: "price", window: 14, window2: 26, value: 0 };

function emptyCondition(): ConditionState {
  return {
    enabled: false,
    op: "cross_above",
    left: { ...DEFAULT_OPERAND, kind: "ema", window: 20 },
    right: { ...DEFAULT_OPERAND, kind: "ema", window: 60 },
  };
}

function toOperand(s: OperandState): Operand {
  if (s.kind === "price") return { kind: "price" };
  if (s.kind === "const") return { kind: "const", value: s.value };
  if (s.kind === "macd" || s.kind === "macd_signal")
    return { kind: s.kind, window: s.window, window2: s.window2 };
  if (s.kind === "bollinger_upper" || s.kind === "bollinger_lower")
    return { kind: s.kind, window: s.window, value: s.value };
  return { kind: s.kind, window: s.window };
}

function fromOperand(o: Operand | undefined): OperandState {
  if (!o) return { ...DEFAULT_OPERAND };
  return {
    kind: o.kind,
    window: o.window ?? 14,
    window2: o.window2 ?? 26,
    value: o.value ?? 0,
  };
}

function toCondition(s: ConditionState): Condition | null {
  if (!s.enabled) return null;
  return { op: s.op, left: toOperand(s.left), right: toOperand(s.right) };
}

function fromCondition(c: Condition | null): ConditionState {
  if (!c) return emptyCondition();
  return {
    enabled: true,
    op: c.op,
    left: fromOperand(c.left),
    right: fromOperand(c.right),
  };
}

// ── Small editors ────────────────────────────────────────────────

const OPERAND_KINDS: { kind: OperandKind; label: string }[] = [
  { kind: "price", label: "Price" },
  { kind: "ema", label: "EMA" },
  { kind: "sma", label: "SMA" },
  { kind: "rsi", label: "RSI" },
  { kind: "highest_high", label: "Highest high (prior N)" },
  { kind: "lowest_low", label: "Lowest low (prior N)" },
  { kind: "macd", label: "MACD line" },
  { kind: "macd_signal", label: "MACD signal" },
  { kind: "atr", label: "ATR" },
  { kind: "roc", label: "Rate of change %" },
  { kind: "bollinger_upper", label: "Bollinger upper" },
  { kind: "bollinger_lower", label: "Bollinger lower" },
  { kind: "const", label: "Constant" },
];

const MACD_KINDS = new Set(["macd", "macd_signal"]);
const BOLL_KINDS = new Set(["bollinger_upper", "bollinger_lower"]);

function OperandEditor({
  state,
  onChange,
}: {
  state: OperandState;
  onChange: (s: OperandState) => void;
}) {
  return (
    <div className="flex gap-2">
      <select
        className={INPUT_CLASS}
        value={state.kind}
        onChange={(e) => onChange({ ...state, kind: e.target.value as OperandKind })}
      >
        {OPERAND_KINDS.map((o) => (
          <option key={o.kind} value={o.kind}>
            {o.label}
          </option>
        ))}
      </select>
      {state.kind === "const" && (
        <input
          type="number"
          step="any"
          className={INPUT_CLASS}
          value={state.value}
          onChange={(e) => onChange({ ...state, value: Number(e.target.value) })}
        />
      )}
      {state.kind !== "const" && state.kind !== "price" && (
        <input
          type="number"
          min={1}
          max={500}
          className={INPUT_CLASS}
          title={MACD_KINDS.has(state.kind) ? "fast period" : "window"}
          value={state.window}
          onChange={(e) => onChange({ ...state, window: Number(e.target.value) })}
        />
      )}
      {MACD_KINDS.has(state.kind) && (
        <input
          type="number"
          min={1}
          max={500}
          className={INPUT_CLASS}
          title="slow period"
          value={state.window2}
          onChange={(e) => onChange({ ...state, window2: Number(e.target.value) })}
        />
      )}
      {BOLL_KINDS.has(state.kind) && (
        <input
          type="number"
          min={0.1}
          step={0.1}
          className={INPUT_CLASS}
          title="std multiple"
          value={state.value}
          onChange={(e) => onChange({ ...state, value: Number(e.target.value) })}
        />
      )}
    </div>
  );
}

function ConditionEditor({
  title,
  state,
  onChange,
}: {
  title: string;
  state: ConditionState;
  onChange: (s: ConditionState) => void;
}) {
  return (
    <div className="rounded-md border border-border bg-bg-hover/40 p-3">
      <label className="flex items-center gap-2 text-sm text-zinc-200">
        <input
          type="checkbox"
          checked={state.enabled}
          onChange={(e) => onChange({ ...state, enabled: e.target.checked })}
        />
        {title}
      </label>
      {state.enabled && (
        <div className="mt-3 grid gap-2 lg:grid-cols-[1fr_auto_1fr]">
          <OperandEditor state={state.left} onChange={(left) => onChange({ ...state, left })} />
          <select
            className={INPUT_CLASS}
            value={state.op}
            onChange={(e) => onChange({ ...state, op: e.target.value as ConditionOp })}
          >
            <option value="cross_above">crosses above</option>
            <option value="cross_below">crosses below</option>
            <option value="gt">&gt;</option>
            <option value="lt">&lt;</option>
          </select>
          <OperandEditor state={state.right} onChange={(right) => onChange({ ...state, right })} />
        </div>
      )}
    </div>
  );
}

function BracketEditor({
  title,
  state,
  onChange,
}: {
  title: string;
  state: BracketState;
  onChange: (s: BracketState) => void;
}) {
  return (
    <div className="rounded-md border border-border bg-bg-hover/40 p-3">
      <label className="flex items-center gap-2 text-sm text-zinc-200">
        <input
          type="checkbox"
          checked={state.enabled}
          onChange={(e) => onChange({ ...state, enabled: e.target.checked })}
        />
        {title}
      </label>
      {state.enabled && (
        <div className="mt-3 flex gap-2">
          <select
            className={INPUT_CLASS}
            value={state.mode}
            onChange={(e) => onChange({ ...state, mode: e.target.value as "pct" | "points" })}
          >
            <option value="points">points</option>
            <option value="pct">% of entry</option>
          </select>
          <input
            type="number"
            min={0.01}
            step="any"
            className={INPUT_CLASS}
            value={state.value}
            onChange={(e) => onChange({ ...state, value: Number(e.target.value) })}
          />
        </div>
      )}
    </div>
  );
}

// ── Main manager ─────────────────────────────────────────────────

export function StrategyManager() {
  const [strategies, setStrategies] = useState<StrategyRecord[]>([]);
  const { user } = useAuth();
  const myEmail = user?.email?.toLowerCase() ?? null;
  // Rows arrive newest-first across every visible owner; grouping keeps each
  // account's strategies together without disturbing that order inside a group.
  const grouped = strategies.reduce<Map<string, StrategyRecord[]>>((acc, s) => {
    const key = s.owner_email ?? "(unowned)";
    (acc.get(key) ?? acc.set(key, []).get(key)!).push(s);
    return acc;
  }, new Map());
  const ownedByMe = (s: StrategyRecord) =>
    myEmail !== null && s.owner_email?.toLowerCase() === myEmail;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | "new" | null>(null);
  const [busy, setBusy] = useState(false);

  // form state
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [timeframe, setTimeframe] = useState<Timeframe>("1h");
  const [lookback, setLookback] = useState(180);
  const [entryLong, setEntryLong] = useState<ConditionState>(emptyCondition());
  const [entryShort, setEntryShort] = useState<ConditionState>(emptyCondition());
  const [exitLong, setExitLong] = useState<ConditionState>(emptyCondition());
  const [exitShort, setExitShort] = useState<ConditionState>(emptyCondition());
  const [filters, setFilters] = useState<ConditionState[]>([]);
  const [sl, setSl] = useState<BracketState>({ enabled: false, mode: "points", value: 100 });
  const [tp, setTp] = useState<BracketState>({ enabled: false, mode: "points", value: 200 });
  const [intraday, setIntraday] = useState<IntradayParts>(NO_INTRADAY);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setStrategies(await listStrategies());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function startNew() {
    setEditingId("new");
    setName("");
    setDescription("");
    setTimeframe("1h");
    setLookback(180);
    const el = emptyCondition();
    el.enabled = true;
    setEntryLong(el);
    setEntryShort(emptyCondition());
    setExitLong(emptyCondition());
    setExitShort(emptyCondition());
    setFilters([]);
    setSl({ enabled: false, mode: "points", value: 100 });
    setTp({ enabled: false, mode: "points", value: 200 });
    setIntraday(NO_INTRADAY);
  }

  /** Fill the form from a definition — shared by editing and templates. */
  function loadDefinition(d: StrategyDefinition) {
    setTimeframe(d.timeframe);
    setLookback(d.default_lookback_days);
    setEntryLong(fromCondition(d.entry_long));
    setEntryShort(fromCondition(d.entry_short));
    setExitLong(fromCondition(d.exit_long));
    setExitShort(fromCondition(d.exit_short));
    setFilters((d.filters ?? []).map((c) => fromCondition(c)));
    setSl(d.sl ? { enabled: true, ...d.sl } : { enabled: false, mode: "points", value: 100 });
    setTp(d.tp ? { enabled: true, ...d.tp } : { enabled: false, mode: "points", value: 200 });
    setIntraday(intradayOf(d));
  }

  function startEdit(s: StrategyRecord) {
    setEditingId(s.id);
    setName(s.name);
    setDescription(s.description ?? "");
    loadDefinition(s.definition);
  }

  function startFromTemplate(t: StrategyTemplate) {
    setEditingId("new");
    setName(t.name);
    setDescription(t.blurb);
    loadDefinition(t.definition);
  }

  // A killzone strategy has no signal entry at all — its entry is a resting
  // order — so requiring one here would make it unsavable on this page.
  const canSave =
    name.trim().length > 0 &&
    (entryLong.enabled || entryShort.enabled || intraday.stop_entry !== null);

  async function save() {
    setBusy(true);
    setError(null);
    const definition: StrategyDefinition = {
      timeframe,
      default_lookback_days: lookback,
      entry_long: toCondition(entryLong),
      entry_short: toCondition(entryShort),
      exit_long: toCondition(exitLong),
      exit_short: toCondition(exitShort),
      filters: filters
        .map((f) => ({ ...f, enabled: true }))
        .map(toCondition)
        .filter((c): c is Condition => c !== null),
      sl: sl.enabled ? { mode: sl.mode, value: sl.value } : null,
      tp: tp.enabled ? { mode: tp.mode, value: tp.value } : null,
      // Carried through untouched — this form cannot edit them.
      ...intraday,
    };
    const body = { name: name.trim(), description: description.trim() || null, definition };
    try {
      if (editingId === "new") await createStrategy(body);
      else if (editingId) await updateStrategy(editingId, body);
      setEditingId(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  /** Read-plus-copy: the shared original is never touched. */
  async function duplicate(id: string) {
    setBusy(true);
    try {
      await copyStrategy(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    try {
      await deleteStrategy(id);
      if (editingId === id) setEditingId(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className={SECTION_CLASS}>
        <h2 className="text-sm font-semibold text-zinc-200">Start from a template</h2>
        <p className="mt-1 text-xs text-zinc-500">
          Textbook shapes with textbook parameters — a starting point to edit, not a
          recommendation. None of them has been fitted to anything.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {STRATEGY_TEMPLATES.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => startFromTemplate(t)}
              className="group rounded-lg border border-border bg-bg-hover/40 p-3 text-left transition hover:border-accent-blue/50 hover:bg-bg-hover"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-medium text-zinc-200 group-hover:text-white">
                  {t.label}
                </span>
                <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
                  {t.definition.timeframe}
                </span>
              </div>
              <p className="mt-1.5 text-xs leading-snug text-zinc-500">{t.blurb}</p>
              {t.definition.session && (
                <p className="mt-2 font-mono text-[10px] uppercase tracking-wider text-accent-amber">
                  session · edit on the canvas
                </p>
              )}
            </button>
          ))}
        </div>
      </section>

      <section className={SECTION_CLASS}>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-zinc-200">Saved strategies</h2>
          <button
            type="button"
            onClick={startNew}
            className="rounded-md bg-accent-blue px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-blue/80"
          >
            New strategy
          </button>
        </div>
        {loading ? (
          <p className="text-sm text-zinc-500">Loading…</p>
        ) : strategies.length === 0 ? (
          <p className="text-sm text-zinc-500">
            Nothing saved yet — build your first strategy below.
          </p>
        ) : (
          <div className="space-y-5">
            {[...grouped.entries()].map(([owner, rows]) => (
              <div key={owner}>
                <div className="mb-1 flex items-center gap-2 px-3">
                  <span className="font-mono text-[11px] text-zinc-400">{owner}</span>
                  {owner.toLowerCase() === myEmail ? (
                    <span className="rounded bg-accent-blue/15 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-accent-blue">
                      you
                    </span>
                  ) : (
                    <span className="rounded bg-emerald-400/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-emerald-300">
                      shared
                    </span>
                  )}
                  <span className="font-mono text-[10px] text-zinc-600">
                    {rows.length}
                  </span>
                </div>
                <table className="min-w-full font-mono text-xs">
                  <thead className="text-left text-zinc-500">
                    <tr>
                      {["Name", "TF", "Entry long", "Entry short", "SL/TP", ""].map((h) => (
                        <th key={h} className="px-3 py-2 font-normal uppercase tracking-wider">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border text-zinc-300">
                    {rows.map((s) => (
                      <tr key={s.id}>
                        <td className="px-3 py-2 text-zinc-100">{s.name}</td>
                        <td className="px-3 py-2">{s.definition.timeframe}</td>
                        <td className="px-3 py-2">{conditionLabel(s.definition.entry_long)}</td>
                        <td className="px-3 py-2">{conditionLabel(s.definition.entry_short)}</td>
                        <td className="px-3 py-2">
                          {s.definition.sl ? `SL ${s.definition.sl.value}${s.definition.sl.mode === "pct" ? "%" : "pt"}` : "—"}
                          {" / "}
                          {s.definition.tp ? `TP ${s.definition.tp.value}${s.definition.tp.mode === "pct" ? "%" : "pt"}` : "—"}
                        </td>
                        <td className="px-3 py-2 text-right">
                          {ownedByMe(s) || s.owner_email === null ? (
                            <>
                              <button type="button" onClick={() => startEdit(s)} className={`${PILL_BTN} bg-bg-hover text-zinc-300 hover:text-white`}>
                                Edit
                              </button>{" "}
                              <button type="button" onClick={() => void remove(s.id)} disabled={busy} className={`${PILL_BTN} bg-bg-hover text-accent-red hover:bg-accent-red/20`}>
                                Delete
                              </button>
                            </>
                          ) : (
                            /* Shared rows are read-plus-copy: no edit, no delete. */
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void duplicate(s.id)}
                              className={`${PILL_BTN} bg-bg-hover text-accent-blue hover:bg-accent-blue/20`}
                            >
                              Copy to mine
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}
      </section>

      <SharingPanel onChanged={() => void refresh()} />

      {error && (
        <pre className="whitespace-pre-wrap rounded-md border border-accent-red/40 bg-accent-red/10 p-4 text-xs text-accent-red">
          {error}
        </pre>
      )}

      {editingId !== null && (
        <section className={SECTION_CLASS}>
          <h2 className="text-sm font-semibold text-zinc-200">
            {editingId === "new" ? "New strategy" : "Edit strategy"}
          </h2>
          {(intraday.session || intraday.stop_entry) && (
            <p className="rounded-md border border-accent-amber/40 bg-accent-amber/10 p-2.5 text-xs text-accent-amber">
              This strategy has a session{intraday.stop_entry && " and a killzone entry"} — no
              editor for those here, but saving keeps them. Change them on the{" "}
              <a href="/research/strategies/canvas" className="underline">
                strategy canvas
              </a>
              .
            </p>
          )}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label className={LABEL_CLASS}>Name</label>
              <input className={INPUT_CLASS} value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label className={LABEL_CLASS}>Description</label>
              <input className={INPUT_CLASS} value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
            <div>
              <label className={LABEL_CLASS}>Timeframe</label>
              <select className={INPUT_CLASS} value={timeframe} onChange={(e) => setTimeframe(e.target.value as Timeframe)}>
                {TIMEFRAMES.map((tf) => (
                  <option key={tf}>{tf}</option>
                ))}
              </select>
            </div>
            <div>
              <label className={LABEL_CLASS}>Default lookback (days)</label>
              <input type="number" min={1} max={3650} className={INPUT_CLASS} value={lookback} onChange={(e) => setLookback(Number(e.target.value))} />
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <ConditionEditor title="Entry LONG when…" state={entryLong} onChange={setEntryLong} />
            <ConditionEditor title="Entry SHORT when…" state={entryShort} onChange={setEntryShort} />
            <ConditionEditor title="Exit LONG when…" state={exitLong} onChange={setExitLong} />
            <ConditionEditor title="Exit SHORT when…" state={exitShort} onChange={setExitShort} />
          </div>

          <div className="rounded-md border border-border bg-bg-hover/40 p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-200">
                Filters — every entry must also satisfy these
              </span>
              <button
                type="button"
                onClick={() =>
                  setFilters((fs) => [...fs, { ...emptyCondition(), enabled: true }])
                }
                className={`${PILL_BTN} bg-bg-hover text-zinc-300 hover:text-white`}
              >
                + Filter
              </button>
            </div>
            <div className="mt-3 space-y-3">
              {filters.length === 0 && (
                <p className="text-xs text-zinc-500">
                  No filters — entries fire on the trigger alone. Add one to gate
                  signals (e.g. only go long while price &gt; SMA 200).
                </p>
              )}
              {filters.map((f, i) => (
                <div key={i} className="grid gap-2 lg:grid-cols-[1fr_auto_1fr_auto]">
                  <OperandEditor
                    state={f.left}
                    onChange={(left) =>
                      setFilters((fs) => fs.map((x, j) => (j === i ? { ...x, left } : x)))
                    }
                  />
                  <select
                    className={INPUT_CLASS}
                    value={f.op}
                    onChange={(e) =>
                      setFilters((fs) =>
                        fs.map((x, j) =>
                          j === i ? { ...x, op: e.target.value as ConditionOp } : x,
                        ),
                      )
                    }
                  >
                    <option value="gt">&gt;</option>
                    <option value="lt">&lt;</option>
                    <option value="cross_above">crosses above</option>
                    <option value="cross_below">crosses below</option>
                  </select>
                  <OperandEditor
                    state={f.right}
                    onChange={(right) =>
                      setFilters((fs) => fs.map((x, j) => (j === i ? { ...x, right } : x)))
                    }
                  />
                  <button
                    type="button"
                    onClick={() => setFilters((fs) => fs.filter((_, j) => j !== i))}
                    className={`${PILL_BTN} bg-bg-hover text-accent-red hover:bg-accent-red/20`}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            <BracketEditor title="Stop loss" state={sl} onChange={setSl} />
            <BracketEditor title="Take profit" state={tp} onChange={setTp} />
          </div>
          <p className="text-xs text-zinc-500">
            Signals are evaluated on bar close and filled at the next bar&apos;s
            open. An opposite entry signal closes the position and reverses.
            Without SL/TP the position exits only on a signal (or end of data).
          </p>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={() => void save()}
              disabled={!canSave || busy}
              className="rounded-md bg-accent-blue px-6 py-2.5 font-semibold text-white transition hover:bg-accent-blue/80 disabled:opacity-40"
            >
              {busy ? "Saving…" : "Save strategy"}
            </button>
            <button
              type="button"
              onClick={() => setEditingId(null)}
              className={`${PILL_BTN} bg-bg-hover px-6 py-2.5 text-zinc-300`}
            >
              Cancel
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
