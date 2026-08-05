"use client";

/**
 * Price-axis controls, parked in the chart's bottom-right corner the way
 * TradingView does — the control belongs next to the axis it governs, not
 * up in the toolbar with the instrument pickers.
 *
 * The menu opens upward because the button already sits at the bottom edge.
 */

import { useEffect, useRef, useState } from "react";

export type ScaleMode = "normal" | "log" | "pct";

const MODES: { mode: ScaleMode; short: string; label: string; hint: string }[] = [
  { mode: "normal", short: "Lin", label: "Arithmetic", hint: "Equal price steps" },
  { mode: "log", short: "Log", label: "Logarithmic", hint: "Equal percentage steps" },
  { mode: "pct", short: "%", label: "Percent", hint: "Move from the first visible bar" },
];

export function PriceScaleMenu({
  mode,
  onMode,
  onFit,
}: {
  mode: ScaleMode;
  onMode: (mode: ScaleMode) => void;
  onFit: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const current = MODES.find((m) => m.mode === mode) ?? MODES[0];

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="absolute bottom-2 right-2 z-20 flex items-center gap-1">
      <button
        type="button"
        title="Reset the price-axis zoom"
        onClick={onFit}
        className="rounded border border-border bg-bg-panel/90 px-2 py-1 font-mono text-[11px] text-zinc-500 backdrop-blur transition hover:text-zinc-100"
      >
        Fit
      </button>

      <div className="relative">
        <button
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          title="Price scale"
          onClick={() => setOpen((o) => !o)}
          className="rounded border border-border bg-bg-panel/90 px-2 py-1 font-mono text-[11px] text-zinc-300 backdrop-blur transition hover:text-white"
        >
          {current.short}
        </button>

        {open && (
          <div
            role="listbox"
            className="absolute bottom-full right-0 mb-1 w-44 overflow-hidden rounded-lg border border-border bg-bg-panel p-1 shadow-2xl"
          >
            {MODES.map((m) => (
              <button
                key={m.mode}
                type="button"
                role="option"
                aria-selected={m.mode === mode}
                onClick={() => {
                  onMode(m.mode);
                  setOpen(false);
                }}
                className={`flex w-full items-baseline gap-2 rounded-md px-2 py-1.5 text-left transition ${
                  m.mode === mode
                    ? "bg-accent-blue/15 text-accent-blue"
                    : "text-zinc-300 hover:bg-bg-hover hover:text-white"
                }`}
              >
                <span className="w-7 shrink-0 font-mono text-[11px]">{m.short}</span>
                <span className="flex-1">
                  <span className="block text-xs">{m.label}</span>
                  <span className="block text-[10px] text-zinc-600">{m.hint}</span>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
