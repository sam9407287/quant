"use client";

// Visual strategy canvas: drag rule modules (Trigger / Filter), pick an
// indicator inside each, and the graph compiles to a StrategyDefinition
// you can save. Self-contained nodes (each module carries its own role +
// condition), so no fragile edge-resolution — the same params model the
// form builder uses, just laid out spatially.

import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { createContext, useCallback, useContext, useMemo, useState } from "react";

import type {
  Condition,
  ConditionOp,
  Operand,
  OperandKind,
  StrategyDefinition,
} from "@/lib/strategies";
import { createStrategy } from "@/lib/strategies";
import { TIMEFRAMES, type Timeframe } from "@/lib/types";

// ── Rule role → strategy slot ─────────────────────────────────────

type Role = "entry_long" | "entry_short" | "exit_long" | "exit_short" | "filter";

const ROLE_LABEL: Record<Role, string> = {
  entry_long: "Entry LONG",
  entry_short: "Entry SHORT",
  exit_long: "Exit LONG",
  exit_short: "Exit SHORT",
  filter: "Filter",
};

interface OperandState {
  kind: OperandKind;
  window: number;
  window2: number;
  value: number;
}

interface RuleState {
  role: Role;
  op: ConditionOp;
  left: OperandState;
  right: OperandState;
}

const DEFAULT_OPERAND: OperandState = { kind: "ema", window: 20, window2: 26, value: 0 };

function defaultRule(role: Role): RuleState {
  return {
    role,
    op: "cross_above",
    left: { ...DEFAULT_OPERAND, kind: "ema", window: 20 },
    right: { ...DEFAULT_OPERAND, kind: "ema", window: 60 },
  };
}

const OPERAND_KINDS: { kind: OperandKind; label: string }[] = [
  { kind: "price", label: "Price" },
  { kind: "ema", label: "EMA" },
  { kind: "sma", label: "SMA" },
  { kind: "rsi", label: "RSI" },
  { kind: "macd", label: "MACD line" },
  { kind: "macd_signal", label: "MACD signal" },
  { kind: "atr", label: "ATR" },
  { kind: "roc", label: "ROC %" },
  { kind: "bollinger_upper", label: "Bollinger up" },
  { kind: "bollinger_lower", label: "Bollinger low" },
  { kind: "highest_high", label: "Highest high" },
  { kind: "lowest_low", label: "Lowest low" },
  { kind: "const", label: "Constant" },
];
const MACD_KINDS = new Set(["macd", "macd_signal"]);
const BOLL_KINDS = new Set(["bollinger_upper", "bollinger_lower"]);

function toOperand(s: OperandState): Operand {
  if (s.kind === "price") return { kind: "price" };
  if (s.kind === "const") return { kind: "const", value: s.value };
  if (MACD_KINDS.has(s.kind)) return { kind: s.kind, window: s.window, window2: s.window2 };
  if (BOLL_KINDS.has(s.kind)) return { kind: s.kind, window: s.window, value: s.value };
  return { kind: s.kind, window: s.window };
}

function toCondition(r: RuleState): Condition {
  return { op: r.op, left: toOperand(r.left), right: toOperand(r.right) };
}

// ── Canvas param context ──────────────────────────────────────────

interface CanvasState {
  rules: Record<string, RuleState>;
  setRule: (id: string, patch: Partial<RuleState>) => void;
  timeframe: Timeframe;
}

const Ctx = createContext<CanvasState | null>(null);
const useCanvas = () => {
  const c = useContext(Ctx);
  if (!c) throw new Error("canvas ctx missing");
  return c;
};

// ── Node chrome ───────────────────────────────────────────────────

const FIELD =
  "nodrag rounded border border-border bg-bg-hover px-2 py-1 font-mono text-xs " +
  "text-zinc-100 focus:border-accent-blue focus:outline-none";
const NLABEL = "font-mono text-[10px] uppercase tracking-wider text-zinc-500";

function OperandFields({
  s,
  onChange,
}: {
  s: OperandState;
  onChange: (s: OperandState) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1">
      <select
        className={FIELD}
        value={s.kind}
        onChange={(e) => onChange({ ...s, kind: e.target.value as OperandKind })}
      >
        {OPERAND_KINDS.map((o) => (
          <option key={o.kind} value={o.kind}>
            {o.label}
          </option>
        ))}
      </select>
      {s.kind === "const" && (
        <input type="number" step="any" className={`${FIELD} w-16`} value={s.value}
          onChange={(e) => onChange({ ...s, value: Number(e.target.value) })} />
      )}
      {s.kind !== "const" && s.kind !== "price" && (
        <input type="number" min={1} className={`${FIELD} w-14`} title="window" value={s.window}
          onChange={(e) => onChange({ ...s, window: Number(e.target.value) })} />
      )}
      {MACD_KINDS.has(s.kind) && (
        <input type="number" min={1} className={`${FIELD} w-14`} title="slow" value={s.window2}
          onChange={(e) => onChange({ ...s, window2: Number(e.target.value) })} />
      )}
      {BOLL_KINDS.has(s.kind) && (
        <input type="number" min={0.1} step={0.1} className={`${FIELD} w-14`} title="std" value={s.value}
          onChange={(e) => onChange({ ...s, value: Number(e.target.value) })} />
      )}
    </div>
  );
}

function RuleNode({ id }: { id: string }) {
  const { rules, setRule } = useCanvas();
  const r = rules[id];
  if (!r) return null;
  const isFilter = r.role === "filter";
  return (
    <div className={`w-72 rounded-lg border ${isFilter ? "border-accent-blue/40" : "border-border"} bg-bg-panel shadow-lg`}>
      <Handle type="target" position={Position.Left} />
      <div className="flex items-center justify-between rounded-t-lg border-b border-border bg-bg-hover px-3 py-1.5">
        <select
          className="nodrag bg-transparent font-mono text-xs uppercase tracking-wider text-accent-blue focus:outline-none"
          value={r.role}
          onChange={(e) => setRule(id, { role: e.target.value as Role })}
        >
          {(Object.keys(ROLE_LABEL) as Role[]).map((role) => (
            <option key={role} value={role} className="text-zinc-900">
              {ROLE_LABEL[role]}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-2 p-3">
        <span className={NLABEL}>When</span>
        <OperandFields s={r.left} onChange={(left) => setRule(id, { left })} />
        <select
          className={FIELD}
          value={r.op}
          onChange={(e) => setRule(id, { op: e.target.value as ConditionOp })}
        >
          <option value="cross_above">crosses above</option>
          <option value="cross_below">crosses below</option>
          <option value="gt">&gt;</option>
          <option value="lt">&lt;</option>
        </select>
        <OperandFields s={r.right} onChange={(right) => setRule(id, { right })} />
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const NODE_TYPES: NodeTypes = { rule: RuleNode };

const INITIAL_NODES: Node[] = [
  { id: "r1", type: "rule", position: { x: 40, y: 40 }, data: {} },
];

// ── Canvas component ──────────────────────────────────────────────

export function StrategyCanvas() {
  const [rules, setRules] = useState<Record<string, RuleState>>({
    r1: defaultRule("entry_long"),
  });
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(INITIAL_NODES);
  const [edges, , onEdgesChange] = useEdgesState<Edge>([]);
  const [seq, setSeq] = useState(2);
  const [timeframe, setTimeframe] = useState<Timeframe>("1h");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const setRule = useCallback((id: string, patch: Partial<RuleState>) => {
    setRules((rs) => ({ ...rs, [id]: { ...rs[id], ...patch } }));
  }, []);

  const state = useMemo<CanvasState>(
    () => ({ rules, setRule, timeframe }),
    [rules, setRule, timeframe],
  );

  const addRule = useCallback(
    (role: Role) => {
      const id = `r${seq}`;
      setSeq((n) => n + 1);
      setRules((rs) => ({ ...rs, [id]: defaultRule(role) }));
      setNodes((ns) => [
        ...ns,
        {
          id,
          type: "rule",
          position: { x: 80 + (ns.length % 3) * 60, y: 80 + (ns.length % 5) * 60 },
          data: {},
        },
      ]);
    },
    [seq, setNodes],
  );

  const deleteSelected = useCallback(() => {
    setNodes((ns) => {
      const keep = ns.filter((n) => !n.selected);
      const keepIds = new Set(keep.map((n) => n.id));
      setRules((rs) => Object.fromEntries(Object.entries(rs).filter(([k]) => keepIds.has(k))));
      return keep;
    });
  }, [setNodes]);

  function compile(): StrategyDefinition {
    const bySlot = (role: Role): Condition | null => {
      const hit = Object.values(rules).find((r) => r.role === role);
      return hit ? toCondition(hit) : null;
    };
    return {
      timeframe,
      default_lookback_days: 180,
      entry_long: bySlot("entry_long"),
      entry_short: bySlot("entry_short"),
      exit_long: bySlot("exit_long"),
      exit_short: bySlot("exit_short"),
      filters: Object.values(rules).filter((r) => r.role === "filter").map(toCondition),
      sl: null,
      tp: null,
    };
  }

  const hasEntry = Object.values(rules).some(
    (r) => r.role === "entry_long" || r.role === "entry_short",
  );

  async function save() {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const rec = await createStrategy({
        name: name.trim() || "Untitled canvas strategy",
        description: "Built on the strategy canvas",
        definition: compile(),
      });
      setMsg(`Saved "${rec.name}". Open it on the Strategies page or chart.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const TOOLBTN =
    "rounded-md bg-bg-hover px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider text-zinc-300 transition hover:text-white";

  return (
    <Ctx.Provider value={state}>
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-bg-panel p-2">
        <span className="px-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">Add module</span>
        <button type="button" onClick={() => addRule("entry_long")} className={TOOLBTN}>+ Trigger</button>
        <button type="button" onClick={() => addRule("filter")} className={TOOLBTN}>+ Filter</button>
        <button type="button" onClick={() => addRule("exit_long")} className={TOOLBTN}>+ Exit</button>
        <div className="mx-1 h-4 w-px bg-border" />
        <button type="button" onClick={deleteSelected} className={`${TOOLBTN} hover:bg-accent-red/20 hover:text-accent-red`}>Delete</button>
        <div className="mx-1 h-4 w-px bg-border" />
        <select className={FIELD} value={timeframe} onChange={(e) => setTimeframe(e.target.value as Timeframe)}>
          {TIMEFRAMES.map((t) => <option key={t}>{t}</option>)}
        </select>
        <input className={`${FIELD} w-48`} placeholder="strategy name" value={name} onChange={(e) => setName(e.target.value)} />
        <button
          type="button"
          onClick={save}
          disabled={busy || !hasEntry}
          className="rounded-md bg-accent-blue px-4 py-1 font-mono text-[11px] uppercase tracking-wider text-white transition hover:bg-accent-blue/80 disabled:opacity-40"
        >
          {busy ? "Saving…" : "Save strategy"}
        </button>
        <span className="ml-auto px-1 text-[10px] text-zinc-600">
          each module = one rule · a module&apos;s role sets its slot
        </span>
      </div>

      {msg && <div className="rounded-md border border-accent-green/40 bg-accent-green/10 p-3 text-xs text-accent-green">{msg}</div>}
      {error && <pre className="whitespace-pre-wrap rounded-md border border-accent-red/40 bg-accent-red/10 p-3 text-xs text-accent-red">{error}</pre>}

      <div className="h-[600px] rounded-lg border border-border bg-bg">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={NODE_TYPES}
          fitView
          proOptions={{ hideAttribution: true }}
          colorMode="dark"
        >
          <Background gap={24} color="#1c2029" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </Ctx.Provider>
  );
}
