"use client";

/**
 * Per-indicator settings dialog.
 *
 * Edits are held locally and only applied on Confirm, so a half-typed
 * period never repaints the chart — and Cancel really does put everything
 * back. Out-of-range values block the confirm rather than being silently
 * clamped, because silently changing what someone typed is worse than
 * telling them it is wrong.
 */

import { useEffect, useMemo, useState } from "react";

import { defaultParams, findIndicator, type ActiveIndicator } from "@/lib/indicator-registry";

export function IndicatorSettings({
  active,
  onClose,
  onApply,
}: {
  active: ActiveIndicator | null;
  onClose: () => void;
  onApply: (params: Record<string, number>) => void;
}) {
  const meta = active ? findIndicator(active.id) : undefined;
  const [draft, setDraft] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!active) return;
    setDraft(Object.fromEntries(Object.entries(active.params).map(([k, v]) => [k, String(v)])));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [active, onClose]);

  const errors = useMemo(() => {
    if (!meta) return {};
    const out: Record<string, string> = {};
    for (const param of meta.params) {
      const value = Number(draft[param.key]);
      if (!Number.isFinite(value)) out[param.key] = "Must be a number";
      else if (value < param.min || value > param.max)
        out[param.key] = `Between ${param.min} and ${param.max}`;
    }
    return out;
  }, [draft, meta]);

  if (!active || !meta) return null;
  const invalid = Object.keys(errors).length > 0;

  function confirm() {
    if (invalid || !meta) return;
    onApply(Object.fromEntries(meta.params.map((p) => [p.key, Number(draft[p.key])])));
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-[70] flex items-start justify-center bg-black/60 p-4 pt-[14vh] backdrop-blur-sm"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${meta.name} settings`}
        className="w-full max-w-md overflow-hidden rounded-xl border border-border bg-bg-panel shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-base font-semibold text-zinc-100">{meta.name}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded px-2 py-1 text-zinc-500 transition hover:text-zinc-100"
          >
            ✕
          </button>
        </div>

        <div className="space-y-4 px-5 py-5">
          {meta.params.length === 0 && (
            <p className="text-sm text-zinc-500">This indicator has no parameters.</p>
          )}
          {meta.params.map((param) => (
            <div key={param.key} className="flex items-center justify-between gap-4">
              <label htmlFor={`p-${param.key}`} className="text-sm text-zinc-300">
                {param.label}
              </label>
              <div className="w-40">
                <input
                  id={`p-${param.key}`}
                  type="number"
                  min={param.min}
                  max={param.max}
                  step={param.step ?? 1}
                  value={draft[param.key] ?? ""}
                  onChange={(e) => setDraft({ ...draft, [param.key]: e.target.value })}
                  onKeyDown={(e) => e.key === "Enter" && confirm()}
                  className={`w-full rounded-md border bg-bg-hover px-3 py-2 font-mono text-sm text-zinc-100 focus:outline-none ${
                    errors[param.key]
                      ? "border-accent-red focus:border-accent-red"
                      : "border-border focus:border-accent-blue"
                  }`}
                />
                {errors[param.key] && (
                  <p className="mt-1 text-[11px] text-accent-red">{errors[param.key]}</p>
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between border-t border-border px-5 py-3">
          <button
            type="button"
            onClick={() =>
              setDraft(
                Object.fromEntries(
                  Object.entries(defaultParams(meta)).map(([k, v]) => [k, String(v)]),
                ),
              )
            }
            className="rounded-md px-3 py-1.5 font-mono text-xs text-zinc-500 transition hover:text-zinc-200"
          >
            Defaults
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-border px-4 py-1.5 text-sm text-zinc-300 transition hover:text-white"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={confirm}
              disabled={invalid}
              className="rounded-md bg-accent-blue px-4 py-1.5 text-sm font-semibold text-white transition hover:bg-accent-blue/80 disabled:opacity-40"
            >
              Confirm
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
