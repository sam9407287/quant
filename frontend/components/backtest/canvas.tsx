"use client";

// QuantFlow-concept node canvas (ADR-003 B7): a typed node graph that
// compiles to the same BacktestParams JSON the form page sends. The
// engine and API never know which surface produced the params.
//
// Param state lives in a React context, NOT in React Flow node data:
// node data stays empty (id/type/position only), so dragging never
// fights the field edits and the compile step is a plain context read.
// Nodes themselves are controlled state so modules can be added,
// duplicated and deleted from the toolbar — every node type edits the
// same shared params, so duplicates are just extra editing handles.

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

import { EquityChart } from "@/components/backtest/charts";
import type {
  BacktestParams,
  DirectionMode,
  OffsetMode,
  RunResponse,
} from "@/lib/backtest";
import { runBacktest } from "@/lib/backtest";
import { INSTRUMENTS, type Instrument } from "@/lib/types";

// ── Shared param state ────────────────────────────────────────────

function defaultParams(): BacktestParams {
  const end = new Date();
  const start = new Date(end.getTime() - 60 * 86400_000);
  return {
    instrument: "NQ",
    point_value_usd: 2,
    contracts: 1,
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
    clock: {
      tz: "America/New_York",
      range_start: "09:00",
      range_end: "09:30",
      orders_place: "09:30",
      eod_flat: "15:55",
    },
    direction_mode: "fade",
    entry_offset_mode: "points",
    entry_offset_value: 0,
    sl_mode: "points",
    sl_value: 100,
    rrr: 2,
    tp_points: null,
    atr_period: 14,
    slippage_points_per_side: 0,
    commission_usd_per_rt: 0,
  };
}

interface CanvasState {
  params: BacktestParams;
  update: (patch: Partial<BacktestParams>) => void;
  updateClock: (patch: Partial<BacktestParams["clock"]>) => void;
  busy: boolean;
  error: string | null;
  result: RunResponse | null;
  run: () => void;
}

const Ctx = createContext<CanvasState | null>(null);

function useCanvas(): CanvasState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("canvas context missing");
  return ctx;
}

// ── Node chrome ───────────────────────────────────────────────────

const FIELD =
  "nodrag w-full rounded border border-border bg-bg-hover px-2 py-1 " +
  "font-mono text-xs text-zinc-100 focus:border-accent-blue focus:outline-none";
const NLABEL =
  "block font-mono text-[10px] uppercase tracking-wider text-zinc-500";

function Shell({
  title,
  children,
  input,
  output,
}: {
  title: string;
  children: React.ReactNode;
  input?: boolean;
  output?: boolean;
}) {
  return (
    <div className="w-56 rounded-lg border border-border bg-bg-panel shadow-lg">
      {input && <Handle type="target" position={Position.Left} />}
      <div className="rounded-t-lg border-b border-border bg-bg-hover px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-accent-blue">
        {title}
      </div>
      <div className="space-y-2 p-3">{children}</div>
      {output && <Handle type="source" position={Position.Right} />}
    </div>
  );
}

// ── Nodes ─────────────────────────────────────────────────────────

function UniverseNode() {
  const { params, update } = useCanvas();
  return (
    <Shell title="Universe" output>
      <label className={NLABEL}>Instrument</label>
      <select
        className={FIELD}
        value={params.instrument}
        onChange={(e) => update({ instrument: e.target.value as Instrument })}
      >
        {INSTRUMENTS.map((i) => (
          <option key={i}>{i}</option>
        ))}
      </select>
      <label className={NLABEL}>Start / End</label>
      <input type="date" className={FIELD} value={params.start} onChange={(e) => update({ start: e.target.value })} />
      <input type="date" className={FIELD} value={params.end} onChange={(e) => update({ end: e.target.value })} />
      <label className={NLABEL}>Point value $ · Contracts</label>
      <div className="flex gap-2">
        <input type="number" step={0.1} className={FIELD} value={params.point_value_usd} onChange={(e) => update({ point_value_usd: Number(e.target.value) })} />
        <input type="number" min={1} className={FIELD} value={params.contracts} onChange={(e) => update({ contracts: Number(e.target.value) })} />
      </div>
    </Shell>
  );
}

function ClockNode() {
  const { params, updateClock } = useCanvas();
  const c = params.clock;
  return (
    <Shell title="Session clock" output>
      <label className={NLABEL}>Timezone</label>
      <input className={FIELD} value={c.tz} onChange={(e) => updateClock({ tz: e.target.value })} />
      <label className={NLABEL}>Range window</label>
      <div className="flex gap-2">
        <input type="time" className={FIELD} value={c.range_start} onChange={(e) => updateClock({ range_start: e.target.value })} />
        <input type="time" className={FIELD} value={c.range_end} onChange={(e) => updateClock({ range_end: e.target.value })} />
      </div>
      <label className={NLABEL}>Place orders · Force flat</label>
      <div className="flex gap-2">
        <input type="time" className={FIELD} value={c.orders_place} onChange={(e) => updateClock({ orders_place: e.target.value })} />
        <input type="time" className={FIELD} value={c.eod_flat} onChange={(e) => updateClock({ eod_flat: e.target.value })} />
      </div>
    </Shell>
  );
}

function EntryNode() {
  const { params, update } = useCanvas();
  return (
    <Shell title="Entry" input output>
      <label className={NLABEL}>Direction</label>
      <select className={FIELD} value={params.direction_mode} onChange={(e) => update({ direction_mode: e.target.value as DirectionMode })}>
        <option value="fade">fade (mean reversion)</option>
        <option value="breakout">breakout</option>
      </select>
      <label className={NLABEL}>Offset mode · value</label>
      <div className="flex gap-2">
        <select className={FIELD} value={params.entry_offset_mode} onChange={(e) => update({ entry_offset_mode: e.target.value as OffsetMode })}>
          <option value="points">pts</option>
          <option value="pct">%</option>
          <option value="atr">ATR×</option>
        </select>
        <input type="number" step={0.1} className={FIELD} value={params.entry_offset_value} onChange={(e) => update({ entry_offset_value: Number(e.target.value) })} />
      </div>
    </Shell>
  );
}

function RiskNode() {
  const { params, update } = useCanvas();
  return (
    <Shell title="Risk bracket" input output>
      <label className={NLABEL}>Stop mode · value</label>
      <div className="flex gap-2">
        <select className={FIELD} value={params.sl_mode} onChange={(e) => update({ sl_mode: e.target.value as OffsetMode })}>
          <option value="points">pts</option>
          <option value="pct">%</option>
          <option value="atr">ATR×</option>
        </select>
        <input type="number" min={0.1} step={0.1} className={FIELD} value={params.sl_value} onChange={(e) => update({ sl_value: Number(e.target.value) })} />
      </div>
      <label className={NLABEL}>RRR (TP = SL ×)</label>
      <input type="number" min={0.1} step={0.1} className={FIELD} value={params.rrr ?? 2} onChange={(e) => update({ rrr: Number(e.target.value) })} />
      {(params.sl_mode === "atr" || params.entry_offset_mode === "atr") && (
        <>
          <label className={NLABEL}>ATR period</label>
          <input type="number" min={1} className={FIELD} value={params.atr_period} onChange={(e) => update({ atr_period: Number(e.target.value) })} />
        </>
      )}
    </Shell>
  );
}

function RunNode() {
  const { busy, error, result, run } = useCanvas();
  return (
    <Shell title="Run" input>
      <button
        type="button"
        onClick={run}
        disabled={busy}
        className="nodrag w-full rounded-md bg-accent-blue px-3 py-2 text-sm font-semibold text-white transition hover:bg-accent-blue/80 disabled:opacity-40"
      >
        {busy ? "Running…" : "Run backtest"}
      </button>
      {error && (
        <p className="max-h-24 overflow-auto font-mono text-[10px] text-accent-red">
          {error}
        </p>
      )}
      {result && (
        <div className="space-y-1 font-mono text-xs">
          <p className={result.metrics.total_pnl_usd >= 0 ? "text-accent-green" : "text-accent-red"}>
            P&L ${result.metrics.total_pnl_usd.toFixed(0)}
          </p>
          <p className="text-zinc-400">
            {result.metrics.trade_count} trades · win{" "}
            {(result.metrics.win_rate * 100).toFixed(0)}%
          </p>
          <p className="text-zinc-400">
            maxDD ${result.metrics.max_drawdown_usd.toFixed(0)}
          </p>
        </div>
      )}
    </Shell>
  );
}

const NODE_TYPES: NodeTypes = {
  universe: UniverseNode,
  clock: ClockNode,
  entry: EntryNode,
  risk: RiskNode,
  run: RunNode,
};

const INITIAL_NODES: Node[] = [
  { id: "universe", type: "universe", position: { x: 0, y: 0 }, data: {} },
  { id: "clock", type: "clock", position: { x: 0, y: 330 }, data: {} },
  { id: "entry", type: "entry", position: { x: 320, y: 60 }, data: {} },
  { id: "risk", type: "risk", position: { x: 320, y: 360 }, data: {} },
  { id: "run", type: "run", position: { x: 640, y: 210 }, data: {} },
];

const INITIAL_EDGES: Edge[] = [
  { id: "u-e", source: "universe", target: "entry", animated: true },
  { id: "c-r", source: "clock", target: "risk", animated: true },
  { id: "e-run", source: "entry", target: "run", animated: true },
  { id: "r-run", source: "risk", target: "run", animated: true },
];

// Palette: which module types the user can add to the canvas, and a
// label for the toolbar. Every node type maps into the same shared
// params context, so duplicates are just extra editing handles.
const PALETTE: { type: string; label: string }[] = [
  { type: "universe", label: "Universe" },
  { type: "clock", label: "Session clock" },
  { type: "entry", label: "Entry" },
  { type: "risk", label: "Risk bracket" },
  { type: "run", label: "Run" },
];

// ── Canvas page component ─────────────────────────────────────────

export function BacktestCanvas() {
  const [params, setParams] = useState<BacktestParams>(defaultParams);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RunResponse | null>(null);

  const state = useMemo<CanvasState>(
    () => ({
      params,
      update: (patch) => setParams((p) => ({ ...p, ...patch })),
      updateClock: (patch) =>
        setParams((p) => ({ ...p, clock: { ...p.clock, ...patch } })),
      busy,
      error,
      result,
      run: async () => {
        setBusy(true);
        setError(null);
        setResult(null);
        try {
          setResult(await runBacktest(params));
        } catch (e) {
          setError(e instanceof Error ? e.message : String(e));
        } finally {
          setBusy(false);
        }
      },
    }),
    [params, busy, error, result],
  );

  // Controlled node/edge state so modules can be added, duplicated and
  // deleted (the uncontrolled defaultNodes could not change after mount).
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(INITIAL_EDGES);
  const [seq, setSeq] = useState(1);

  const addNode = useCallback(
    (type: string) => {
      const id = `${type}-${seq}`;
      setSeq((n) => n + 1);
      // Drop new nodes on a light diagonal cascade so they never land
      // exactly on top of an existing one.
      setNodes((ns) => [
        ...ns,
        {
          id,
          type,
          position: { x: 120 + (ns.length % 4) * 40, y: 120 + (ns.length % 6) * 40 },
          data: {},
        },
      ]);
    },
    [seq, setNodes],
  );

  const duplicateSelected = useCallback(() => {
    setNodes((ns) => {
      const selected = ns.filter((n) => n.selected);
      if (!selected.length) return ns;
      let s = seq;
      const copies = selected.map((n) => ({
        ...n,
        id: `${n.type}-${s++}`,
        position: { x: n.position.x + 40, y: n.position.y + 40 },
        selected: false,
      }));
      setSeq(s);
      return [...ns.map((n) => ({ ...n, selected: false })), ...copies];
    });
  }, [seq, setNodes]);

  const deleteSelected = useCallback(() => {
    setNodes((ns) => ns.filter((n) => !n.selected));
    setEdges((es) => es.filter((e) => !e.selected));
  }, [setNodes, setEdges]);

  const resetLayout = useCallback(() => {
    setNodes(INITIAL_NODES);
    setEdges(INITIAL_EDGES);
    setSeq(1);
  }, [setNodes, setEdges]);

  const TOOLBTN =
    "rounded-md bg-bg-hover px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider text-zinc-300 transition hover:text-white";

  return (
    <Ctx.Provider value={state}>
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-bg-panel p-2">
        <span className="px-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">
          Add module
        </span>
        {PALETTE.map((p) => (
          <button key={p.type} type="button" onClick={() => addNode(p.type)} className={TOOLBTN}>
            + {p.label}
          </button>
        ))}
        <div className="mx-1 h-4 w-px bg-border" />
        <button type="button" onClick={duplicateSelected} className={TOOLBTN}>
          Duplicate
        </button>
        <button
          type="button"
          onClick={deleteSelected}
          className={`${TOOLBTN} hover:bg-accent-red/20 hover:text-accent-red`}
        >
          Delete
        </button>
        <button type="button" onClick={resetLayout} className={TOOLBTN}>
          Reset
        </button>
        <span className="ml-auto px-1 text-[10px] text-zinc-600">
          click a node to select · Duplicate/Delete act on the selection
        </span>
      </div>
      <div className="h-[640px] rounded-lg border border-border bg-bg">
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
      {result && (
        <section className="rounded-lg border border-border bg-bg-panel p-5">
          <h2 className="mb-3 text-sm font-semibold text-zinc-200">
            Equity curve
          </h2>
          <EquityChart curve={result.equity_curve} />
        </section>
      )}
    </Ctx.Provider>
  );
}
