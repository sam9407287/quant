"use client";

/**
 * Interval picker: grouped presets plus a free-text custom interval.
 *
 * Intervals the API stores directly are marked; the rest are folded in the
 * browser from the largest stored timeframe that divides them. Ticks and
 * seconds are absent on purpose — the database holds nothing below 1m.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  PRESET_GROUPS,
  parseInterval,
  type Interval,
} from "@/lib/timeframes";

function ClockGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
        <circle cx="12" cy="12" r="8.5" />
        <path d="M12 7v5.2l3.2 2" />
      </g>
    </svg>
  );
}

export function TimeframeMenu({
  value,
  onChange,
}: {
  value: Interval;
  onChange: (interval: Interval) => void;
}) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState("");
  const [customError, setCustomError] = useState("");
  const rootRef = useRef<HTMLDivElement | null>(null);

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

  const parsed = useMemo(() => (custom ? parseInterval(custom) : null), [custom]);

  function applyCustom() {
    const interval = parseInterval(custom);
    if (!interval) {
      setCustomError("Use a number plus m, h, d, w — or 1M. Nothing below 1m exists.");
      return;
    }
    onChange(interval);
    setCustom("");
    setCustomError("");
    setOpen(false);
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Interval"
        className="flex items-center gap-2 rounded-md border border-border bg-bg-hover px-2 py-1.5 font-mono text-xs text-zinc-200 transition hover:text-white focus:border-accent-blue focus:outline-none"
      >
        <ClockGlyph />
        <span className="min-w-[28px] text-left">{value.id}</span>
        <span className="text-zinc-500">▾</span>
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute left-0 z-50 mt-1 max-h-[70vh] w-56 overflow-y-auto rounded-lg border border-border bg-bg-panel p-1 shadow-2xl"
        >
          <div className="border-b border-border p-2">
            <div className="flex gap-1">
              <input
                value={custom}
                onChange={(e) => {
                  setCustom(e.target.value);
                  setCustomError("");
                }}
                onKeyDown={(e) => e.key === "Enter" && applyCustom()}
                placeholder="Custom — 45m, 8h, 3d"
                className="w-full rounded border border-border bg-bg-hover px-2 py-1 font-mono text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-accent-blue focus:outline-none"
              />
              <button
                type="button"
                onClick={applyCustom}
                className="rounded bg-bg-hover px-2 font-mono text-xs text-zinc-300 transition hover:text-white"
              >
                +
              </button>
            </div>
            {customError && <p className="mt-1 text-[10px] text-accent-red">{customError}</p>}
            {parsed && !customError && (
              <p className="mt-1 font-mono text-[10px] text-zinc-500">
                {parsed.label}
                {parsed.native ? " · stored" : ` · folded from ${parsed.base}`}
              </p>
            )}
          </div>

          {PRESET_GROUPS.map((group) => (
            <div key={group.title}>
              <div className="px-2 pt-2 font-mono text-[10px] uppercase tracking-wider text-zinc-600">
                {group.title}
              </div>
              {group.intervals.map((interval) => (
                <button
                  key={interval.id}
                  type="button"
                  role="option"
                  aria-selected={interval.id === value.id}
                  onClick={() => {
                    onChange(interval);
                    setOpen(false);
                  }}
                  className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-xs transition ${
                    interval.id === value.id
                      ? "bg-accent-blue/15 text-accent-blue"
                      : "text-zinc-300 hover:bg-bg-hover hover:text-white"
                  }`}
                >
                  <span>{interval.label}</span>
                  <span className="font-mono text-[10px] text-zinc-600">
                    {interval.native ? interval.id : `↺ ${interval.base}`}
                  </span>
                </button>
              ))}
            </div>
          ))}

          <p className="border-t border-border px-2 py-2 text-[10px] leading-snug text-zinc-600">
            ↺ = folded in the browser from a stored timeframe. Ticks and seconds
            are unavailable: the database holds no data below 1m.
          </p>
        </div>
      )}
    </div>
  );
}
