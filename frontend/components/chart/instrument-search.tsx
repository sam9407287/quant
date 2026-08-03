"use client";

/**
 * Instrument picker: a search dialog with type-to-filter and the project's
 * own asset-class pills. Categories are the ten in `lib/types.ts` — this
 * component does not invent its own taxonomy.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ASSET_CLASSES,
  ASSET_CLASS_LABEL,
  INSTRUMENTS,
  INSTRUMENT_META,
  type AssetClass,
  type Instrument,
} from "@/lib/types";

const G = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function ClassGlyph({ cls, size = 16 }: { cls: AssetClass; size?: number }) {
  const p = { width: size, height: size, viewBox: "0 0 24 24", "aria-hidden": true };
  switch (cls) {
    case "equity_index":
      return (
        <svg {...p}>
          <g {...G}>
            <path d="M4 19h16" />
            <path d="M7 19v-5M12 19V9M17 19v-8" />
          </g>
        </svg>
      );
    case "intl_index":
      return (
        <svg {...p}>
          <g {...G}>
            <circle cx="12" cy="12" r="8.5" />
            <path d="M3.5 12h17" />
            <path d="M12 3.5c2.6 2.6 2.6 14.4 0 17-2.6-2.6-2.6-14.4 0-17z" />
          </g>
        </svg>
      );
    case "rates":
      return (
        <svg {...p}>
          <g {...G}>
            <path d="M6 18L18 6" />
            <circle cx="7.5" cy="7.5" r="2.5" />
            <circle cx="16.5" cy="16.5" r="2.5" />
          </g>
        </svg>
      );
    case "fx":
      return (
        <svg {...p}>
          <g {...G}>
            <path d="M4 9h13l-3-3M20 15H7l3 3" />
          </g>
        </svg>
      );
    case "metal":
      return (
        <svg {...p}>
          <g {...G}>
            <ellipse cx="12" cy="7.5" rx="7" ry="3" />
            <path d="M5 7.5v9c0 1.7 3.1 3 7 3s7-1.3 7-3v-9" />
            <path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" />
          </g>
        </svg>
      );
    case "energy":
      return (
        <svg {...p}>
          <path {...G} d="M12 3.5c3.5 4.2 5.5 6.8 5.5 9.5a5.5 5.5 0 11-11 0c0-2.7 2-5.3 5.5-9.5z" />
        </svg>
      );
    case "grain":
      return (
        <svg {...p}>
          <g {...G}>
            <path d="M12 21V8" />
            <path d="M12 8c0-2 1.4-4 3.5-4.5C15.5 5.5 14.1 7.5 12 8z" />
            <path d="M12 8C12 6 10.6 4 8.5 3.5 8.5 5.5 9.9 7.5 12 8z" />
            <path d="M12 14c0-2 1.4-4 3.5-4.5C15.5 11.5 14.1 13.5 12 14z" />
            <path d="M12 14c0-2-1.4-4-3.5-4.5C8.5 11.5 9.9 13.5 12 14z" />
          </g>
        </svg>
      );
    case "soft":
      return (
        <svg {...p}>
          <g {...G}>
            <path d="M20 4c0 8-5 12-11 12H5c0-8 5-12 11-12z" />
            <path d="M5 20c1.5-4 4-6.5 8-8.5" />
          </g>
        </svg>
      );
    case "livestock":
      return (
        <svg {...p}>
          <g {...G}>
            <path d="M5 6c0 0 1 1.5 2.5 2M19 6c0 0-1 1.5-2.5 2" />
            <path d="M6.5 8.5c0 5 2.4 9 5.5 9s5.5-4 5.5-9c0-1.4-2.5-2.5-5.5-2.5S6.5 7.1 6.5 8.5z" />
            <path d="M10 12h.01M14 12h.01" />
          </g>
        </svg>
      );
    case "crypto":
      return (
        <svg {...p}>
          <g {...G}>
            <path d="M12 3l7.5 4.5v9L12 21l-7.5-4.5v-9z" />
            <path d="M9.5 8.5h4a2 2 0 010 4h-4h4a2 2 0 010 4h-4z" />
            <path d="M11 7v1.5M11 15.5V17" />
          </g>
        </svg>
      );
  }
}

const CLASS_TINT: Record<AssetClass, string> = {
  equity_index: "text-accent-blue",
  intl_index: "text-accent-blue",
  rates: "text-emerald-400",
  fx: "text-cyan-400",
  metal: "text-amber-400",
  energy: "text-orange-400",
  grain: "text-lime-400",
  soft: "text-rose-400",
  livestock: "text-pink-400",
  crypto: "text-violet-400",
};

export function InstrumentSearch({
  value,
  onChange,
}: {
  value: Instrument;
  onChange: (instrument: Instrument) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cls, setCls] = useState<AssetClass | "all">("all");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    return INSTRUMENTS.filter((sym) => {
      const meta = INSTRUMENT_META[sym];
      if (cls !== "all" && meta.assetClass !== cls) return false;
      if (!q) return true;
      return (
        sym.toLowerCase().includes(q) ||
        meta.name.toLowerCase().includes(q) ||
        meta.exchange.toLowerCase().includes(q)
      );
    });
  }, [query, cls]);

  useEffect(() => setCursor(0), [query, cls]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setCls("all");
    setCursor(0);
    // Focus after paint so the dialog is mounted.
    const id = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setCursor((c) => Math.min(c + 1, results.length - 1));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setCursor((c) => Math.max(c - 1, 0));
      }
      if (e.key === "Enter" && results[cursor]) {
        onChange(results[cursor]);
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, results, cursor, onChange]);

  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>(`[data-idx="${cursor}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const meta = INSTRUMENT_META[value];

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Search instruments"
        className="flex items-center gap-2 rounded-md border border-border bg-bg-hover px-2.5 py-1.5 font-mono text-xs text-zinc-100 transition hover:text-white focus:border-accent-blue focus:outline-none"
      >
        <span className={CLASS_TINT[meta.assetClass]}>
          <ClassGlyph cls={meta.assetClass} />
        </span>
        <span className="font-semibold">{value}</span>
        <span className="text-zinc-500">▾</span>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[60] flex items-start justify-center bg-black/70 p-4 pt-[8vh] backdrop-blur-sm"
          onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Instrument search"
            className="flex max-h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-border bg-bg-panel shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <h2 className="text-sm font-semibold text-zinc-100">Instrument search</h2>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded px-2 py-1 text-zinc-500 transition hover:text-zinc-100"
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 border-b border-border p-4">
              <div className="flex items-center gap-2 rounded-lg border border-border bg-bg-hover px-3 py-2">
                <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" className="text-zinc-500">
                  <g {...G}>
                    <circle cx="10.5" cy="10.5" r="6.5" />
                    <path d="M15.5 15.5L20 20" />
                  </g>
                </svg>
                <input
                  ref={inputRef}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Symbol, name or exchange…"
                  className="w-full bg-transparent font-mono text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none"
                />
                {query && (
                  <button
                    type="button"
                    onClick={() => setQuery("")}
                    className="text-zinc-600 transition hover:text-zinc-300"
                    aria-label="Clear"
                  >
                    ✕
                  </button>
                )}
              </div>

              <div className="flex flex-wrap gap-1.5">
                <button
                  type="button"
                  onClick={() => setCls("all")}
                  className={`rounded-full px-3 py-1 text-xs transition ${
                    cls === "all"
                      ? "bg-zinc-100 font-medium text-zinc-900"
                      : "border border-border text-zinc-400 hover:text-zinc-100"
                  }`}
                >
                  All
                </button>
                {ASSET_CLASSES.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setCls(c)}
                    className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs transition ${
                      cls === c
                        ? "bg-zinc-100 font-medium text-zinc-900"
                        : "border border-border text-zinc-400 hover:text-zinc-100"
                    }`}
                  >
                    <span className={cls === c ? "" : CLASS_TINT[c]}>
                      <ClassGlyph cls={c} size={13} />
                    </span>
                    {ASSET_CLASS_LABEL[c]}
                  </button>
                ))}
              </div>
            </div>

            <div ref={listRef} className="flex-1 overflow-y-auto p-1">
              {results.length === 0 ? (
                <p className="px-4 py-10 text-center text-sm text-zinc-500">
                  Nothing matches “{query}”.
                </p>
              ) : (
                results.map((sym, i) => {
                  const m = INSTRUMENT_META[sym];
                  return (
                    <button
                      key={sym}
                      data-idx={i}
                      type="button"
                      onMouseEnter={() => setCursor(i)}
                      onClick={() => {
                        onChange(sym);
                        setOpen(false);
                      }}
                      className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition ${
                        i === cursor ? "bg-bg-hover" : ""
                      }`}
                    >
                      <span
                        className={`grid h-7 w-7 shrink-0 place-items-center rounded-full border border-border ${CLASS_TINT[m.assetClass]}`}
                      >
                        <ClassGlyph cls={m.assetClass} size={15} />
                      </span>
                      <span
                        className={`w-14 shrink-0 font-mono text-sm font-semibold ${
                          sym === value ? "text-accent-blue" : "text-zinc-100"
                        }`}
                      >
                        {sym}
                      </span>
                      <span className="flex-1 truncate text-sm text-zinc-300">{m.name}</span>
                      <span className="shrink-0 text-xs text-zinc-600">
                        {ASSET_CLASS_LABEL[m.assetClass]}
                      </span>
                      <span className="w-16 shrink-0 text-right font-mono text-xs text-zinc-500">
                        {m.exchange}
                      </span>
                    </button>
                  );
                })
              )}
            </div>

            <div className="border-t border-border px-4 py-2 font-mono text-[10px] text-zinc-600">
              {results.length} of {INSTRUMENTS.length} · ↑↓ to move · ↵ to select · esc to close
            </div>
          </div>
        </div>
      )}
    </>
  );
}
