"use client";

/**
 * Chart legend row, TradingView-style: the indicator's name and current
 * params sit on the chart itself, with hide / settings / remove appearing
 * on hover so they never clutter the plot.
 */

import { findIndicator, type ActiveIndicator } from "@/lib/indicator-registry";

function Icon({ d, filled = false }: { d: string; filled?: boolean }) {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
      <g
        fill={filled ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d={d} />
      </g>
    </svg>
  );
}

const EYE = "M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6z M12 9.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5z";
const EYE_OFF = "M4 4l16 16 M9.9 5.2A9.7 9.7 0 0112 5c6.4 0 10 6 10 6a17 17 0 01-3.3 3.9M6.5 7.3A16.7 16.7 0 002 11s3.6 6 10 6c1.4 0 2.6-.3 3.7-.7";
const GEAR = "M12 15.2a3.2 3.2 0 100-6.4 3.2 3.2 0 000 6.4z M19.4 13.5l1.7 1.3-1.7 3-2-.8a7.6 7.6 0 01-1.9 1.1l-.3 2.1h-3.4l-.3-2.1a7.6 7.6 0 01-1.9-1.1l-2 .8-1.7-3 1.7-1.3a7.7 7.7 0 010-2.2L4 8.5l1.7-3 2 .8a7.6 7.6 0 011.9-1.1l.3-2.1h3.4l.3 2.1a7.6 7.6 0 011.9 1.1l2-.8 1.7 3-1.7 1.3a7.7 7.7 0 010 2.2z";
const TRASH = "M4 7h16 M9 7V5h6v2 M6 7l1 13h10l1-13";

const BTN =
  "pointer-events-auto rounded px-1 text-zinc-600 opacity-0 transition group-hover:opacity-100 focus:opacity-100";

export function IndicatorLegendRow({
  active,
  onToggle,
  onSettings,
  onRemove,
}: {
  active: ActiveIndicator;
  onToggle: () => void;
  onSettings: () => void;
  onRemove: () => void;
}) {
  const meta = findIndicator(active.id);
  if (!meta) return null;
  const args = meta.params.map((x) => active.params[x.key]).join(" ");

  return (
    <div className="group pointer-events-none flex items-center gap-1 rounded bg-bg-panel/70 px-1.5 py-0.5 font-mono text-[11px] backdrop-blur">
      <span className={active.hidden ? "text-zinc-600 line-through" : "text-zinc-300"}>
        {meta.name}
        {args && <span className="ml-1 text-zinc-500">{args}</span>}
      </span>
      <button
        type="button"
        onClick={onToggle}
        title={active.hidden ? "Show" : "Hide"}
        aria-label={active.hidden ? `Show ${meta.name}` : `Hide ${meta.name}`}
        className={`${BTN} hover:text-zinc-100 ${active.hidden ? "opacity-100" : ""}`}
      >
        <Icon d={active.hidden ? EYE_OFF : EYE} />
      </button>
      <button
        type="button"
        onClick={onSettings}
        title="Settings"
        aria-label={`${meta.name} settings`}
        className={`${BTN} hover:text-zinc-100`}
      >
        <Icon d={GEAR} />
      </button>
      <button
        type="button"
        onClick={onRemove}
        title="Remove"
        aria-label={`Remove ${meta.name}`}
        className={`${BTN} hover:text-accent-red`}
      >
        <Icon d={TRASH} />
      </button>
    </div>
  );
}
