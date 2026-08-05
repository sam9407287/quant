"use client";

/**
 * Indicators & strategies picker, in the shape TradingView uses: one dialog,
 * two tabs, search across both. Strategies moved in here from a plain
 * <select> so there is a single place to ask "what should be on this chart".
 */

import { useEffect, useMemo, useRef, useState } from "react";

import {
  INDICATORS,
  INDICATOR_GROUPS,
  type IndicatorMeta,
} from "@/lib/indicator-registry";
import type { StrategyRecord } from "@/lib/strategies";

type Tab = "indicators" | "strategies";

function PaneChip({ pane }: { pane: IndicatorMeta["pane"] }) {
  return (
    <span
      title={pane === "price" ? "Drawn over the candles" : "Drawn in a pane below"}
      className={`rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ring-1 ring-inset ${
        pane === "price"
          ? "bg-accent-blue/10 text-accent-blue ring-accent-blue/30"
          : "bg-violet-400/10 text-violet-300 ring-violet-400/30"
      }`}
    >
      {pane === "price" ? "overlay" : "pane"}
    </span>
  );
}

export function IndicatorModal({
  open,
  onClose,
  onAddIndicator,
  strategies,
  strategyId,
  onSelectStrategy,
  authed,
}: {
  open: boolean;
  onClose: () => void;
  onAddIndicator: (id: string) => void;
  strategies: StrategyRecord[];
  strategyId: string;
  onSelectStrategy: (id: string) => void;
  authed: boolean;
}) {
  const [tab, setTab] = useState<Tab>("indicators");
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState<string | "all">("all");
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setGroup("all");
    const id = requestAnimationFrame(() => inputRef.current?.focus());
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => {
      cancelAnimationFrame(id);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  const q = query.trim().toLowerCase();

  const shownIndicators = useMemo(
    () =>
      INDICATORS.filter(
        (i) =>
          (group === "all" || i.group === group) &&
          (!q || i.name.toLowerCase().includes(q) || i.id.includes(q)),
      ),
    [q, group],
  );

  const shownStrategies = useMemo(
    () =>
      strategies.filter(
        (s) => !q || s.name.toLowerCase().includes(q) || (s.owner_email ?? "").toLowerCase().includes(q),
      ),
    [q, strategies],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center bg-black/70 p-4 pt-[8vh] backdrop-blur-sm"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Indicators and strategies"
        className="flex max-h-[80vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-border bg-bg-panel shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold text-zinc-100">Indicators & strategies</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded px-2 py-1 text-zinc-500 transition hover:text-zinc-100"
          >
            ✕
          </button>
        </div>

        <div className="space-y-3 border-b border-border p-4">
          <div className="flex items-center gap-2 rounded-lg border border-border bg-bg-hover px-3 py-2">
            <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" className="text-zinc-500">
              <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                <circle cx="10.5" cy="10.5" r="6.5" />
                <path d="M15.5 15.5L20 20" />
              </g>
            </svg>
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search indicators and strategies…"
              className="w-full bg-transparent font-mono text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none"
            />
          </div>

          <div className="flex gap-1">
            {(
              [
                ["indicators", `Indicators (${shownIndicators.length})`],
                ["strategies", `My strategies (${shownStrategies.length})`],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`rounded-full px-3 py-1 text-xs transition ${
                  tab === id
                    ? "bg-zinc-100 font-medium text-zinc-900"
                    : "border border-border text-zinc-400 hover:text-zinc-100"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === "indicators" && (
            <div className="flex flex-wrap gap-1.5">
              {(["all", ...INDICATOR_GROUPS] as const).map((g) => (
                <button
                  key={g}
                  type="button"
                  onClick={() => setGroup(g)}
                  className={`rounded-full px-2.5 py-1 text-[11px] transition ${
                    group === g
                      ? "bg-accent-blue/20 text-accent-blue"
                      : "border border-border text-zinc-500 hover:text-zinc-200"
                  }`}
                >
                  {g === "all" ? "All" : g}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-1">
          {tab === "indicators" ? (
            shownIndicators.length === 0 ? (
              <p className="px-4 py-10 text-center text-sm text-zinc-500">Nothing matches “{query}”.</p>
            ) : (
              shownIndicators.map((meta) => (
                <button
                  key={meta.id}
                  type="button"
                  onClick={() => {
                    onAddIndicator(meta.id);
                    onClose();
                  }}
                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition hover:bg-bg-hover"
                >
                  <span className="flex-1 text-sm text-zinc-100">{meta.name}</span>
                  <span className="font-mono text-[11px] text-zinc-600">
                    {meta.params.map((x) => x.value).join(", ")}
                  </span>
                  <span className="w-40 shrink-0 text-right text-xs text-zinc-600">{meta.group}</span>
                  <PaneChip pane={meta.pane} />
                </button>
              ))
            )
          ) : !authed ? (
            <p className="px-4 py-10 text-center text-sm text-zinc-500">
              Sign in to apply one of your saved strategies.
            </p>
          ) : (
            <>
              <button
                type="button"
                onClick={() => {
                  onSelectStrategy("");
                  onClose();
                }}
                className={`flex w-full items-center rounded-lg px-3 py-2.5 text-left text-sm transition hover:bg-bg-hover ${
                  strategyId === "" ? "text-accent-blue" : "text-zinc-300"
                }`}
              >
                No strategy
              </button>
              {shownStrategies.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => {
                    onSelectStrategy(s.id);
                    onClose();
                  }}
                  className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition hover:bg-bg-hover ${
                    s.id === strategyId ? "bg-accent-blue/10" : ""
                  }`}
                >
                  <span
                    className={`flex-1 truncate text-sm ${
                      s.id === strategyId ? "text-accent-blue" : "text-zinc-100"
                    }`}
                  >
                    {s.name}
                  </span>
                  <span className="font-mono text-[11px] text-zinc-600">{s.definition.timeframe}</span>
                  <span className="w-52 shrink-0 truncate text-right text-xs text-zinc-600">
                    {s.owner_email ?? "—"}
                  </span>
                </button>
              ))}
              {shownStrategies.length === 0 && (
                <p className="px-4 py-10 text-center text-sm text-zinc-500">
                  {query ? `Nothing matches “${query}”.` : "You have no saved strategies yet."}
                </p>
              )}
            </>
          )}
        </div>

        <div className="border-t border-border px-4 py-2 font-mono text-[10px] text-zinc-600">
          Every indicator is computed in the browser from the bars already loaded — no extra request.
        </div>
      </div>
    </div>
  );
}
