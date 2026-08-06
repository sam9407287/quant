"use client";

// The strategy canvas: drag modules, and the graph compiles to one
// StrategyDefinition you can save.
//
// Six module kinds, one engine. Trigger / Filter / Exit are indicator
// rules; Session, Killzone and Bracket are the intraday scaffolding
// (ADR-009) that lets an ICT-style setup be expressed here rather than
// in a separate canvas of its own. They compose — a Killzone entry and
// an RSI Filter end up in the same definition, gating the same position.
//
// Modules are self-contained (each carries its own role and params), so
// the compiler never reads the graph; edges are annotation.

import {
  Background,
  Controls,
  Handle,
  addEdge,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type ReactFlowInstance,
  type Node,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import type {
  Bracket,
  Condition,
  ConditionOp,
  Operand,
  OperandKind,
  StopEntry,
  StrategyDefinition,
} from "@/lib/strategies";
import { createStrategy } from "@/lib/strategies";
import { TIMEFRAMES, type Timeframe } from "@/lib/types";

// ── Module model ──────────────────────────────────────────────────

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
  kind: "rule";
  role: Role;
  op: ConditionOp;
  left: OperandState;
  right: OperandState;
}

interface SessionState {
  kind: "session";
  tz: string;
  open: string;   // "HH:MM"
  close: string;  // also the forced-flat time
  maxTrades: number;  // 0 = uncapped
}

interface KillzoneState {
  kind: "killzone";
  rangeStart: string;
  rangeEnd: string;
  activeFrom: string;
  mode: "breakout" | "fade";
  offsetMode: "points" | "pct" | "atr";
  offsetValue: number;
  oco: boolean;
}

interface BracketState {
  kind: "bracket";
  slMode: "points" | "pct";
  slValue: number;
  tpMode: "points" | "pct";
  tpValue: number;
}

type ModuleState = RuleState | SessionState | KillzoneState | BracketState;
type ModuleKind = ModuleState["kind"];

/** At most one of these may exist — they configure the strategy, not a rule. */
const SINGLETONS: ModuleKind[] = ["session", "killzone", "bracket"];

const DEFAULT_OPERAND: OperandState = { kind: "ema", window: 20, window2: 26, value: 0 };

function defaultRule(role: Role): RuleState {
  return {
    kind: "rule",
    role,
    op: "cross_above",
    left: { ...DEFAULT_OPERAND, kind: "ema", window: 20 },
    right: { ...DEFAULT_OPERAND, kind: "ema", window: 60 },
  };
}

// New York cash-session defaults: the killzone most ICT material is
// written around, and the numbers a first-time user should see.
function defaultModule(kind: ModuleKind, role: Role = "entry_long"): ModuleState {
  if (kind === "rule") return defaultRule(role);
  if (kind === "session")
    return { kind: "session", tz: "America/New_York", open: "09:30", close: "16:00", maxTrades: 1 };
  if (kind === "killzone")
    return {
      kind: "killzone",
      rangeStart: "09:30",
      rangeEnd: "10:00",
      activeFrom: "10:00",
      mode: "breakout",
      offsetMode: "points",
      offsetValue: 0,
      oco: true,
    };
  return { kind: "bracket", slMode: "points", slValue: 10, tpMode: "points", tpValue: 20 };
}

const TIMEZONES = [
  "America/New_York",
  "America/Chicago",
  "Europe/London",
  "Asia/Tokyo",
  "Asia/Taipei",
  "UTC",
];

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

/** The API takes full times; the inputs are "HH:MM". */
const hhmmss = (t: string) => `${t}:00`;

// ── Canvas context ────────────────────────────────────────────────

interface CanvasState {
  modules: Record<string, ModuleState>;
  setModule: (id: string, patch: Record<string, unknown>) => void;
  removeModule: (id: string) => void;
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
const ROW = "flex items-center justify-between gap-2";

function Field({
  label,
  stack = false,
  children,
}: {
  label: string;
  stack?: boolean;
  children: React.ReactNode;
}) {
  if (stack) {
    return (
      <div className="space-y-1">
        <span className={`${NLABEL} block`}>{label}</span>
        {children}
      </div>
    );
  }
  return (
    <div className={ROW}>
      <span className={NLABEL}>{label}</span>
      {children}
    </div>
  );
}

// A <input type="time"> renders its locale's own text — "上午09:30" under
// zh-TW is far wider than "09:30 AM" — so time fields get a fixed, generous
// width rather than one tuned to English.
const TIMEIN = `${FIELD} w-[7.5rem]`;

/**
 * Shared module frame. In preview mode it drops its handles — a <Handle>
 * rendered outside a ReactFlow tree registers with a store that is not
 * there — and its delete button, which would have nothing to delete.
 */
function Shell({
  id,
  title,
  accent,
  preview,
  children,
}: {
  id: string;
  title: React.ReactNode;
  accent: string;
  preview: boolean;
  children: React.ReactNode;
}) {
  const { removeModule } = useCanvas();
  return (
    <div
      className={`w-72 rounded-lg border ${accent} bg-bg-panel shadow-lg ${
        preview ? "pointer-events-none select-none" : ""
      }`}
    >
      {!preview && <Handle type="target" position={Position.Left} />}
      <div className="flex items-center justify-between rounded-t-lg border-b border-border bg-bg-hover px-3 py-1.5">
        {title}
        {!preview && (
          <button
            type="button"
            onClick={() => removeModule(id)}
            title="Remove module"
            aria-label="Remove module"
            className="nodrag rounded px-1 text-zinc-600 transition hover:text-accent-red"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M4 7h16 M9 7V5h6v2 M6 7l1 13h10l1-13"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        )}
      </div>
      <div className="space-y-2 p-3">{children}</div>
      {!preview && <Handle type="source" position={Position.Right} />}
    </div>
  );
}

const StaticTitle = ({ text, tone }: { text: string; tone: string }) => (
  <span className={`font-mono text-xs uppercase tracking-wider ${tone}`}>{text}</span>
);

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

// Every node takes an optional `preview` state: the palette ghost renders
// a module that is not on the canvas yet, so the id lookup finds nothing.
type NodeProps<T> = { id: string; preview?: T };

function useModule<T extends ModuleState>(id: string, preview?: T): T | null {
  const { modules } = useCanvas();
  return (preview ?? (modules[id] as T | undefined)) ?? null;
}

function RuleNode({ id, preview }: NodeProps<RuleState>) {
  const { setModule } = useCanvas();
  const r = useModule<RuleState>(id, preview);
  if (!r) return null;
  const isFilter = r.role === "filter";
  return (
    <Shell
      id={id}
      preview={preview !== undefined}
      accent={isFilter ? "border-accent-blue/40" : "border-border"}
      title={
        <select
          className="nodrag bg-transparent font-mono text-xs uppercase tracking-wider text-accent-blue focus:outline-none"
          value={r.role}
          onChange={(e) => setModule(id, { role: e.target.value as Role })}
        >
          {(Object.keys(ROLE_LABEL) as Role[]).map((role) => (
            <option key={role} value={role} className="text-zinc-900">
              {ROLE_LABEL[role]}
            </option>
          ))}
        </select>
      }
    >
      <span className={NLABEL}>When</span>
      <OperandFields s={r.left} onChange={(left) => setModule(id, { left })} />
      <select
        className={FIELD}
        value={r.op}
        onChange={(e) => setModule(id, { op: e.target.value as ConditionOp })}
      >
        <option value="cross_above">crosses above</option>
        <option value="cross_below">crosses below</option>
        <option value="gt">&gt;</option>
        <option value="lt">&lt;</option>
      </select>
      <OperandFields s={r.right} onChange={(right) => setModule(id, { right })} />
    </Shell>
  );
}

function SessionNode({ id, preview }: NodeProps<SessionState>) {
  const { setModule } = useCanvas();
  const s = useModule<SessionState>(id, preview);
  if (!s) return null;
  return (
    <Shell
      id={id}
      preview={preview !== undefined}
      accent="border-accent-green/40"
      title={<StaticTitle text="Session" tone="text-accent-green" />}
    >
      <Field label="Timezone">
        <select className={`${FIELD} w-44`} value={s.tz}
          onChange={(e) => setModule(id, { tz: e.target.value })}>
          {TIMEZONES.map((z) => <option key={z}>{z}</option>)}
        </select>
      </Field>
      <Field label="Open">
        <input type="time" className={TIMEIN} value={s.open}
          onChange={(e) => setModule(id, { open: e.target.value })} />
      </Field>
      <Field label="Close">
        <input type="time" className={TIMEIN} value={s.close}
          onChange={(e) => setModule(id, { close: e.target.value })} />
      </Field>
      <Field label="Max trades">
        <input type="number" min={0} max={100} className={`${FIELD} w-16`} value={s.maxTrades}
          onChange={(e) => setModule(id, { maxTrades: Number(e.target.value) })} />
      </Field>
      <p className="text-[10px] leading-snug text-zinc-600">
        Positions are flattened at Close — never carried overnight. 0 max trades = uncapped.
      </p>
    </Shell>
  );
}

function KillzoneNode({ id, preview }: NodeProps<KillzoneState>) {
  const { setModule } = useCanvas();
  const k = useModule<KillzoneState>(id, preview);
  if (!k) return null;
  return (
    <Shell
      id={id}
      preview={preview !== undefined}
      accent="border-accent-amber/40"
      title={<StaticTitle text="Killzone · OCO" tone="text-accent-amber" />}
    >
      <Field label="Range window" stack>
        <span className="flex gap-1">
          <input type="time" className={TIMEIN} value={k.rangeStart}
            onChange={(e) => setModule(id, { rangeStart: e.target.value })} />
          <input type="time" className={TIMEIN} value={k.rangeEnd}
            onChange={(e) => setModule(id, { rangeEnd: e.target.value })} />
        </span>
      </Field>
      <Field label="Orders from">
        <input type="time" className={TIMEIN} value={k.activeFrom}
          onChange={(e) => setModule(id, { activeFrom: e.target.value })} />
      </Field>
      <Field label="Direction">
        <select className={`${FIELD} w-32`} value={k.mode}
          onChange={(e) => setModule(id, { mode: e.target.value })}>
          <option value="breakout">Breakout</option>
          <option value="fade">Fade</option>
        </select>
      </Field>
      <Field label="Offset">
        <span className="flex gap-1">
          <input type="number" step="any" min={0} className={`${FIELD} w-16`} value={k.offsetValue}
            onChange={(e) => setModule(id, { offsetValue: Number(e.target.value) })} />
          <select className={`${FIELD} w-20`} value={k.offsetMode}
            onChange={(e) => setModule(id, { offsetMode: e.target.value })}>
            <option value="points">points</option>
            <option value="pct">%</option>
            <option value="atr">×ATR</option>
          </select>
        </span>
      </Field>
      <label className={`${ROW} cursor-pointer`}>
        <span className={NLABEL}>One cancels other</span>
        <input type="checkbox" className="nodrag accent-accent-blue" checked={k.oco}
          onChange={(e) => setModule(id, { oco: e.target.checked })} />
      </label>
      <p className="text-[10px] leading-snug text-zinc-600">
        Rests a buy above the range high and a sell below the low. Needs a Session module.
      </p>
    </Shell>
  );
}

function BracketNode({ id, preview }: NodeProps<BracketState>) {
  const { setModule } = useCanvas();
  const b = useModule<BracketState>(id, preview);
  if (!b) return null;
  const pair = (
    valueKey: "slValue" | "tpValue",
    modeKey: "slMode" | "tpMode",
  ) => (
    <span className="flex gap-1">
      <input type="number" step="any" min={0} className={`${FIELD} w-16`} value={b[valueKey]}
        onChange={(e) => setModule(id, { [valueKey]: Number(e.target.value) })} />
      <select className={`${FIELD} w-20`} value={b[modeKey]}
        onChange={(e) => setModule(id, { [modeKey]: e.target.value })}>
        <option value="points">points</option>
        <option value="pct">%</option>
      </select>
    </span>
  );
  return (
    <Shell
      id={id}
      preview={preview !== undefined}
      accent="border-accent-red/40"
      title={<StaticTitle text="Bracket" tone="text-accent-red" />}
    >
      <Field label="Stop loss">{pair("slValue", "slMode")}</Field>
      <Field label="Take profit">{pair("tpValue", "tpMode")}</Field>
      <p className="text-[10px] leading-snug text-zinc-600">
        0 disables that side. A bar touching both books the loss.
      </p>
    </Shell>
  );
}

const NODE_TYPES: NodeTypes = {
  rule: RuleNode,
  session: SessionNode,
  killzone: KillzoneNode,
  bracket: BracketNode,
};

/** The ghost that follows the cursor — the real node, made inert. */
function ModulePreview({ kind, role }: { kind: ModuleKind; role: Role }) {
  const state = defaultModule(kind, role);
  if (state.kind === "rule") return <RuleNode id="__preview" preview={state} />;
  if (state.kind === "session") return <SessionNode id="__preview" preview={state} />;
  if (state.kind === "killzone") return <KillzoneNode id="__preview" preview={state} />;
  return <BracketNode id="__preview" preview={state} />;
}

// Palette entries carry both the node type and, for rules, the slot the
// new module starts in.
const PALETTE: { key: string; label: string; kind: ModuleKind; role: Role }[] = [
  { key: "trigger", label: "Trigger", kind: "rule", role: "entry_long" },
  { key: "filter", label: "Filter", kind: "rule", role: "filter" },
  { key: "exit", label: "Exit", kind: "rule", role: "exit_long" },
  { key: "session", label: "Session", kind: "session", role: "entry_long" },
  { key: "killzone", label: "Killzone", kind: "killzone", role: "entry_long" },
  { key: "bracket", label: "Bracket", kind: "bracket", role: "entry_long" },
];

const INITIAL_NODES: Node[] = [{ id: "m1", type: "rule", position: { x: 40, y: 40 }, data: {} }];

// ── Canvas component ──────────────────────────────────────────────

export function StrategyCanvas() {
  const [modules, setModules] = useState<Record<string, ModuleState>>({
    m1: defaultRule("entry_long"),
  });
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const seq = useRef(2);
  const [timeframe, setTimeframe] = useState<Timeframe>("5m");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Edges here are annotation, not wiring: each module carries its own role
  // and params, so the compiled StrategyDefinition does not read the graph.
  // Drawing them still has to work — a canvas whose handles refuse to
  // connect reads as broken.
  const onConnect = useCallback(
    (c: Connection) => setEdges((es) => addEdge({ ...c, animated: true }, es)),
    [setEdges],
  );

  const setModule = useCallback((id: string, patch: Record<string, unknown>) => {
    setModules((ms) => (ms[id] ? { ...ms, [id]: { ...ms[id], ...patch } as ModuleState } : ms));
  }, []);

  const removeModule = useCallback(
    (id: string) => {
      setNodes((ns) => ns.filter((n) => n.id !== id));
      setEdges((es) => es.filter((e) => e.source !== id && e.target !== id));
      setModules((ms) => Object.fromEntries(Object.entries(ms).filter(([k]) => k !== id)));
    },
    [setNodes, setEdges],
  );

  const state = useMemo<CanvasState>(
    () => ({ modules, setModule, removeModule }),
    [modules, setModule, removeModule],
  );

  const present = useCallback(
    (kind: ModuleKind) => Object.values(modules).some((m) => m.kind === kind),
    [modules],
  );

  // The instance converts a screen point into canvas coordinates, so a
  // dropped module lands under the cursor regardless of pan and zoom.
  const [flow, setFlow] = useState<ReactFlowInstance | null>(null);

  // Hovering a palette entry floats a translucent copy of the module under
  // the cursor, so what you are about to place is visible before committing
  // to the drag.
  const [hover, setHover] = useState<{ kind: ModuleKind; role: Role } | null>(null);
  const [cursor, setCursor] = useState({ x: 0, y: 0 });
  const ghostRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!hover) return;
    const track = (e: MouseEvent) => setCursor({ x: e.clientX, y: e.clientY });
    window.addEventListener("mousemove", track);
    return () => window.removeEventListener("mousemove", track);
  }, [hover]);

  const addModule = useCallback(
    (kind: ModuleKind, role: Role, position?: { x: number; y: number }) => {
      const id = `m${seq.current++}`;
      setModules((ms) => ({ ...ms, [id]: defaultModule(kind, role) }));
      setNodes((ns) => [
        ...ns,
        {
          id,
          type: kind,
          // Clicked modules tile on a grid wider than a module (288px) and
          // taller than the tallest one, so a click never buries the module
          // added before it. Dropped ones land wherever the cursor was.
          position: position ?? { x: 40 + (ns.length % 3) * 320, y: 40 + Math.floor(ns.length / 3) * 300 },
          data: {},
        },
      ]);
    },
    [setNodes],
  );

  /** Placing a Killzone brings its Session along — the pair is the setup. */
  const place = useCallback(
    (kind: ModuleKind, role: Role, position?: { x: number; y: number }) => {
      if (SINGLETONS.includes(kind) && present(kind)) return;
      if (kind === "killzone" && !present("session")) {
        addModule("session", role, position && { x: position.x - 300, y: position.y });
      }
      addModule(kind, role, position);
    },
    [addModule, present],
  );

  const onDragStart = (event: React.DragEvent, kind: ModuleKind, role: Role) => {
    event.dataTransfer.setData("application/reactflow", `${kind}:${role}`);
    event.dataTransfer.effectAllowed = "move";
  };

  // preventDefault on dragover is what marks the canvas as a valid drop
  // target; without it the browser refuses the drop entirely.
  const onDragOver = (event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  };

  const onDrop = (event: React.DragEvent) => {
    event.preventDefault();
    const payload = event.dataTransfer.getData("application/reactflow");
    if (!payload || !flow) return;
    const [kind, role] = payload.split(":") as [ModuleKind, Role];
    place(kind, role, flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
  };

  // ── Compile ─────────────────────────────────────────────────────

  const find = <T extends ModuleState>(kind: ModuleKind) =>
    Object.values(modules).find((m) => m.kind === kind) as T | undefined;

  function compile(): StrategyDefinition {
    const rules = Object.values(modules).filter((m): m is RuleState => m.kind === "rule");
    const bySlot = (role: Role): Condition | null => {
      const hit = rules.find((r) => r.role === role);
      return hit ? toCondition(hit) : null;
    };
    const sess = find<SessionState>("session");
    const kz = find<KillzoneState>("killzone");
    const br = find<BracketState>("bracket");

    const bracket = (mode: "points" | "pct", value: number): Bracket | null =>
      value > 0 ? { mode, value } : null;

    // A killzone reads the range's extremes, which only exist inside a
    // session — without one the module cannot compile and is dropped.
    let stopEntry: StopEntry | null = null;
    if (kz && sess) {
      const window = { time_start: hhmmss(kz.rangeStart), time_end: hhmmss(kz.rangeEnd) };
      stopEntry = {
        upper_level: { kind: "session_high", ...window },
        lower_level: { kind: "session_low", ...window },
        mode: kz.mode,
        offset_mode: kz.offsetMode,
        offset_value: kz.offsetValue,
        atr_period: 14,
        active_from: hhmmss(kz.activeFrom),
        oco: kz.oco,
      };
    }

    return {
      timeframe,
      default_lookback_days: 180,
      entry_long: bySlot("entry_long"),
      entry_short: bySlot("entry_short"),
      exit_long: bySlot("exit_long"),
      exit_short: bySlot("exit_short"),
      filters: rules.filter((r) => r.role === "filter").map(toCondition),
      sl: br ? bracket(br.slMode, br.slValue) : null,
      tp: br ? bracket(br.tpMode, br.tpValue) : null,
      session: sess ? { tz: sess.tz, open: hhmmss(sess.open), close: hhmmss(sess.close) } : null,
      stop_entry: stopEntry,
      max_trades_per_session: sess && sess.maxTrades > 0 ? sess.maxTrades : null,
    };
  }

  // What the canvas will not let you save, said before you press it.
  const problem = useMemo<string | null>(() => {
    const rules = Object.values(modules).filter((m): m is RuleState => m.kind === "rule");
    const hasKillzone = present("killzone");
    if (hasKillzone && !present("session"))
      return "A Killzone needs a Session module — it reads the range inside one.";
    const hasTrigger = rules.some((r) => r.role === "entry_long" || r.role === "entry_short");
    if (!hasTrigger && !hasKillzone)
      return "Add an entry: a Trigger module, or a Killzone.";
    return null;
  }, [modules, present]);

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
        {PALETTE.map(({ key, label, kind, role }) => {
          const taken = SINGLETONS.includes(kind) && present(kind);
          return (
            <button
              key={key}
              type="button"
              draggable={!taken}
              disabled={taken}
              title={taken ? `Only one ${label} module per strategy` : undefined}
              onMouseEnter={(e) => {
                if (taken) return;
                setCursor({ x: e.clientX, y: e.clientY });
                setHover({ kind, role });
              }}
              onMouseLeave={() => setHover(null)}
              onDragStart={(e) => {
                onDragStart(e, kind, role);
                // Drag the module itself rather than a picture of the button.
                if (ghostRef.current) e.dataTransfer.setDragImage(ghostRef.current, 24, 24);
              }}
              onDragEnd={() => setHover(null)}
              onClick={() => place(kind, role)}
              className={`${TOOLBTN} cursor-grab active:cursor-grabbing disabled:cursor-not-allowed disabled:opacity-30`}
            >
              + {label}
            </button>
          );
        })}
        <div className="mx-1 h-4 w-px bg-border" />
        <select className={FIELD} value={timeframe} onChange={(e) => setTimeframe(e.target.value as Timeframe)}>
          {TIMEFRAMES.map((t) => <option key={t}>{t}</option>)}
        </select>
        <input className={`${FIELD} w-48`} placeholder="strategy name" value={name} onChange={(e) => setName(e.target.value)} />
        <button
          type="button"
          onClick={save}
          disabled={busy || problem !== null}
          title={problem ?? undefined}
          className="rounded-md bg-accent-blue px-4 py-1 font-mono text-[11px] uppercase tracking-wider text-white transition hover:bg-accent-blue/80 disabled:opacity-40"
        >
          {busy ? "Saving…" : "Save strategy"}
        </button>
        <span className="ml-auto px-1 text-[10px] text-zinc-600">
          {problem ?? "modules compile to one strategy · delete on the module"}
        </span>
      </div>

      {msg && <div className="rounded-md border border-accent-green/40 bg-accent-green/10 p-3 text-xs text-accent-green">{msg}</div>}
      {error && <pre className="whitespace-pre-wrap rounded-md border border-accent-red/40 bg-accent-red/10 p-3 text-xs text-accent-red">{error}</pre>}

      {hover && (
        <div
          ref={ghostRef}
          aria-hidden
          className="pointer-events-none fixed z-50 opacity-60 drop-shadow-2xl"
          style={{ left: cursor.x + 18, top: cursor.y + 18 }}
        >
          <ModulePreview kind={hover.kind} role={hover.role} />
        </div>
      )}

      {/* overflow-hidden: React Flow does not clip its own pane, so a node
          dropped near the edge would otherwise render outside the frame and
          over the toolbar. */}
      <div
        className="h-[600px] overflow-hidden rounded-lg border border-border bg-bg"
        onDrop={onDrop}
        onDragOver={onDragOver}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onInit={setFlow}
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
