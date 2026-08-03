"use client";

/**
 * Chart-type picker.
 *
 * A native <select> cannot draw anything but text inside an <option>, so the
 * icons force a custom popover. Glyphs are inline SVG on a 24×24 grid using
 * `currentColor`, which keeps them in step with the row's hover/selected
 * colour and needs no asset pipeline.
 */

import { useEffect, useRef, useState } from "react";
import { CHART_KINDS, GROUP_LABEL, type ChartKind } from "@/lib/chart-series";

const S = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function Glyph({ kind }: { kind: ChartKind }) {
  const common = { width: 18, height: 18, viewBox: "0 0 24 24", "aria-hidden": true };
  switch (kind) {
    case "bar":
      return (
        <svg {...common}>
          <g {...S}>
            <path d="M8 4v14M8 8H5M8 13h3" />
            <path d="M16 7v13M16 11h-3M16 16h3" />
          </g>
        </svg>
      );
    case "candles":
      return (
        <svg {...common}>
          <g {...S}>
            <path d="M8 3v3M8 16v3" />
            <rect x="5.5" y="6" width="5" height="10" fill="currentColor" />
            <path d="M16 5v3M16 18v2" />
            <rect x="13.5" y="8" width="5" height="10" />
          </g>
        </svg>
      );
    case "hollow":
      return (
        <svg {...common}>
          <g {...S}>
            <path d="M8 3v3M8 16v3" />
            <rect x="5.5" y="6" width="5" height="10" />
            <path d="M16 5v3M16 18v2" />
            <rect x="13.5" y="8" width="5" height="10" />
          </g>
        </svg>
      );
    case "line":
      return (
        <svg {...common}>
          <path {...S} d="M3 17l5-6 4 4 4-7 5 5" />
        </svg>
      );
    case "line_markers":
      return (
        <svg {...common}>
          <path {...S} d="M3 17l5-6 4 4 4-7 5 5" />
          <g fill="currentColor">
            <circle cx="8" cy="11" r="1.8" />
            <circle cx="16" cy="8" r="1.8" />
          </g>
        </svg>
      );
    case "step":
      return (
        <svg {...common}>
          <path {...S} d="M3 18h4v-5h5v4h4V8h5" />
        </svg>
      );
    case "area":
      return (
        <svg {...common}>
          <path d="M3 18l5-7 4 4 4-6 5 4v6H3z" fill="currentColor" opacity="0.28" />
          <path {...S} d="M3 18l5-7 4 4 4-6 5 4" />
        </svg>
      );
    case "hlc_area":
      return (
        <svg {...common}>
          <g {...S}>
            <path d="M3 8l5-3 4 4 4-4 5 3" />
            <path d="M3 13l5-3 4 4 4-4 5 3" />
            <path d="M3 18l5-3 4 4 4-4 5 3" />
          </g>
        </svg>
      );
    case "baseline":
      return (
        <svg {...common}>
          <path {...S} strokeDasharray="2 2" d="M3 12h18" />
          <path {...S} d="M3 17l5-7 4 6 4-9 5 6" />
        </svg>
      );
    case "columns":
      return (
        <svg {...common}>
          <g {...S}>
            <path d="M5 20v-6M10 20V8M15 20v-9M20 20v-4" strokeWidth="2.4" />
          </g>
        </svg>
      );
    case "high_low":
      return (
        <svg {...common}>
          <g {...S}>
            <rect x="6" y="5" width="4" height="12" />
            <rect x="14" y="8" width="4" height="11" />
          </g>
        </svg>
      );
    case "heikin_ashi":
      return (
        <svg {...common}>
          <g {...S}>
            <path d="M7 5v2M7 15v2" />
            <rect x="4.5" y="7" width="5" height="8" fill="currentColor" />
            <path d="M14 8v2M14 18v1" />
            <rect x="11.5" y="10" width="5" height="8" />
            <path d="M20 6v2" />
            <rect x="18" y="8" width="4" height="7" fill="currentColor" />
          </g>
        </svg>
      );
    case "renko":
      return (
        <svg {...common}>
          <g {...S}>
            <rect x="3" y="14" width="5" height="5" />
            <rect x="8" y="9" width="5" height="5" />
            <rect x="13" y="4" width="5" height="5" />
            <rect x="18" y="9" width="3" height="5" />
          </g>
        </svg>
      );
    case "line_break":
      return (
        <svg {...common}>
          <g {...S}>
            <rect x="3" y="12" width="5" height="7" />
            <rect x="9" y="6" width="5" height="7" fill="currentColor" />
            <rect x="15" y="10" width="5" height="7" />
          </g>
        </svg>
      );
    case "kagi":
      return (
        <svg {...common}>
          <path {...S} d="M4 19V9h4v8h4V5h4v11h4" />
        </svg>
      );
    case "range":
      return (
        <svg {...common}>
          <g {...S}>
            <path d="M5 6v4M5 14v4" />
            <rect x="3" y="10" width="4" height="4" fill="currentColor" />
            <path d="M12 5v3M12 13v4" />
            <rect x="10" y="8" width="4" height="5" />
            <path d="M19 8v2M19 16v2" />
            <rect x="17" y="10" width="4" height="6" fill="currentColor" />
          </g>
        </svg>
      );
  }
}

const GROUPS = ["bars", "lines", "areas", "columns", "derived"] as const;

export function ChartTypeMenu({
  value,
  onChange,
}: {
  value: ChartKind;
  onChange: (kind: ChartKind) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const current = CHART_KINDS.find((k) => k.kind === value) ?? CHART_KINDS[1];

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
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Chart type"
        className="flex items-center gap-2 rounded-md border border-border bg-bg-hover px-2 py-1.5 font-mono text-xs text-zinc-200 transition hover:text-white focus:border-accent-blue focus:outline-none"
      >
        <Glyph kind={current.kind} />
        <span className="min-w-[104px] text-left">{current.label}</span>
        <span className="text-zinc-500">▾</span>
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute left-0 z-50 mt-1 max-h-[70vh] w-60 overflow-y-auto rounded-lg border border-border bg-bg-panel p-1 shadow-2xl"
        >
          {GROUPS.map((group, gi) => (
            <div key={group}>
              {gi > 0 && <div className="my-1 h-px bg-border" />}
              <div className="px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">
                {GROUP_LABEL[group]}
              </div>
              {CHART_KINDS.filter((k) => k.group === group).map((k) => (
                <button
                  key={k.kind}
                  type="button"
                  role="option"
                  aria-selected={k.kind === value}
                  onClick={() => {
                    onChange(k.kind);
                    setOpen(false);
                  }}
                  className={`flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-xs transition ${
                    k.kind === value
                      ? "bg-accent-blue/15 text-accent-blue"
                      : "text-zinc-300 hover:bg-bg-hover hover:text-white"
                  }`}
                >
                  <Glyph kind={k.kind} />
                  {k.label}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
