"use client";

import { useMemo, useState } from "react";

import {
  type FeatureKind,
  type FeatureSpec,
  FEATURE_CATALOGUE,
  MODELS_BY_TASK,
  type TargetKind,
  type TaskType,
  type TrainConfig,
  type TrainResponse,
  trainModel,
} from "@/lib/ml";
import type { Instrument, Timeframe } from "@/lib/types";
import { INSTRUMENTS, TIMEFRAMES } from "@/lib/types";
import { ResultPanel } from "./result-panel";

const TARGET_OPTIONS_BY_TASK: Record<TaskType, TargetKind[]> = {
  regression: ["log_return", "simple_return", "volatility"],
  classification: ["direction"],
  clustering: ["log_return", "simple_return", "volatility"],
};

function defaultDateRange(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end);
  start.setUTCDate(end.getUTCDate() - 90);
  // ISO without seconds, consumed by datetime-local inputs as UTC
  const fmt = (d: Date) =>
    new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  return { start: fmt(start), end: fmt(end) };
}

const SECTION_CLASS =
  "rounded-lg border border-border bg-bg-panel p-5 space-y-4";
const LABEL_CLASS = "block text-xs font-mono uppercase tracking-wider text-zinc-500 mb-1";
const INPUT_CLASS =
  "w-full rounded-md border border-border bg-bg-hover px-3 py-2 text-sm font-mono " +
  "text-zinc-100 focus:border-accent-blue focus:outline-none";
const PILL_BTN =
  "rounded-md px-3 py-1.5 font-mono text-xs uppercase tracking-wider transition";

export function ResearchWizard() {
  // ── Step 1: Data ────────────────────────────────────────────────
  const dateDefault = useMemo(defaultDateRange, []);
  const [instrument, setInstrument] = useState<Instrument>("NQ");
  const [timeframe, setTimeframe] = useState<Timeframe>("1h");
  const [start, setStart] = useState<string>(dateDefault.start);
  const [end, setEnd] = useState<string>(dateDefault.end);

  // ── Step 2: Target & features ──────────────────────────────────
  const [task, setTask] = useState<TaskType>("regression");
  const [targetKind, setTargetKind] = useState<TargetKind>("log_return");
  const [horizon, setHorizon] = useState<number>(1);
  const [deadbandBps, setDeadbandBps] = useState<number>(0);
  const [features, setFeatures] = useState<FeatureSpec[]>([
    { kind: "lag_return", window: 1 },
    { kind: "lag_return", window: 2 },
    { kind: "rolling_std", window: 10 },
  ]);

  // ── Step 3: Preprocess ─────────────────────────────────────────
  const [standardize, setStandardize] = useState<boolean>(true);
  const [testSize, setTestSize] = useState<number>(0.2);
  const [downsampleStride, setDownsampleStride] = useState<number>(1);

  // ── Step 4: Model ──────────────────────────────────────────────
  const [model, setModel] = useState<string>("ridge");

  // ── Run state ──────────────────────────────────────────────────
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TrainResponse | null>(null);

  // Whenever the task changes, reset the target and model to a valid
  // default for that task — prevents impossible (task, target) combos
  // from sneaking past the server-side validator.
  function setTaskAndDefaults(t: TaskType) {
    setTask(t);
    setTargetKind(TARGET_OPTIONS_BY_TASK[t][0]);
    setModel(MODELS_BY_TASK[t][0].name);
  }

  function addFeature() {
    setFeatures((prev) => [...prev, { kind: "lag_return", window: 1 }]);
  }
  function updateFeature(i: number, patch: Partial<FeatureSpec>) {
    setFeatures((prev) => prev.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  }
  function removeFeature(i: number) {
    setFeatures((prev) => prev.filter((_, idx) => idx !== i));
  }

  async function runTraining() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const cfg: TrainConfig = {
        data: {
          instrument,
          timeframe,
          start: new Date(start).toISOString(),
          end: new Date(end).toISOString(),
        },
        target: {
          kind: targetKind,
          horizon,
          deadband_bps: targetKind === "direction" ? deadbandBps : 0,
        },
        features,
        preprocess: {
          standardize,
          test_size: testSize,
          downsample_stride: downsampleStride,
        },
        task,
        model: { name: model },
      };
      const res = await trainModel(cfg);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <SafetyBanner />

      {/* Step 1 — Data */}
      <section className={SECTION_CLASS}>
        <SectionHeader idx={1} title="Data" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className={LABEL_CLASS}>Instrument</label>
            <div className="flex gap-1">
              {INSTRUMENTS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setInstrument(s)}
                  className={`${PILL_BTN} flex-1 ${
                    instrument === s
                      ? "bg-accent-blue text-white"
                      : "bg-bg-hover text-zinc-400 hover:text-zinc-100"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className={LABEL_CLASS}>Timeframe</label>
            <select
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value as Timeframe)}
              className={INPUT_CLASS}
            >
              {TIMEFRAMES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={LABEL_CLASS}>Start (UTC)</label>
            <input
              type="datetime-local"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className={INPUT_CLASS}
            />
          </div>
          <div>
            <label className={LABEL_CLASS}>End (UTC)</label>
            <input
              type="datetime-local"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              className={INPUT_CLASS}
            />
          </div>
        </div>
      </section>

      {/* Step 2 — Target & features */}
      <section className={SECTION_CLASS}>
        <SectionHeader idx={2} title="Target & features" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className={LABEL_CLASS}>Task</label>
            <select
              value={task}
              onChange={(e) => setTaskAndDefaults(e.target.value as TaskType)}
              className={INPUT_CLASS}
            >
              <option value="regression">regression</option>
              <option value="classification">classification</option>
              <option value="clustering">clustering</option>
            </select>
          </div>
          <div>
            <label className={LABEL_CLASS}>Target</label>
            <select
              value={targetKind}
              onChange={(e) => setTargetKind(e.target.value as TargetKind)}
              className={INPUT_CLASS}
            >
              {TARGET_OPTIONS_BY_TASK[task].map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={LABEL_CLASS}>Horizon (bars ahead)</label>
            <input
              type="number"
              min={1}
              max={50}
              value={horizon}
              onChange={(e) => setHorizon(Number(e.target.value))}
              className={INPUT_CLASS}
            />
          </div>
          {targetKind === "direction" && (
            <div>
              <label className={LABEL_CLASS}>Deadband (bps)</label>
              <input
                type="number"
                min={0}
                max={500}
                value={deadbandBps}
                onChange={(e) => setDeadbandBps(Number(e.target.value))}
                className={INPUT_CLASS}
              />
            </div>
          )}
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className={LABEL_CLASS}>Features ({features.length})</span>
            <button
              type="button"
              onClick={addFeature}
              className="rounded-md bg-bg-hover px-3 py-1.5 text-xs font-mono text-accent-blue hover:bg-bg-hover/70"
            >
              + add feature
            </button>
          </div>
          {features.map((f, i) => (
            <div
              key={i}
              className="grid grid-cols-12 items-center gap-2 rounded-md bg-bg-hover px-3 py-2"
            >
              <select
                value={f.kind}
                onChange={(e) =>
                  updateFeature(i, { kind: e.target.value as FeatureKind })
                }
                className="col-span-7 rounded-md border border-border bg-bg-panel px-2 py-1.5 text-sm font-mono"
              >
                {FEATURE_CATALOGUE.map((c) => (
                  <option key={c.kind} value={c.kind}>
                    {c.label}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={1}
                max={500}
                value={f.window}
                onChange={(e) => updateFeature(i, { window: Number(e.target.value) })}
                className="col-span-3 rounded-md border border-border bg-bg-panel px-2 py-1.5 text-sm font-mono"
                placeholder="window"
              />
              <button
                type="button"
                onClick={() => removeFeature(i)}
                disabled={features.length === 1}
                className="col-span-2 rounded-md bg-bg-panel px-2 py-1.5 text-xs font-mono text-accent-red hover:bg-accent-red/20 disabled:opacity-30"
              >
                remove
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* Step 3 — Preprocess */}
      <section className={SECTION_CLASS}>
        <SectionHeader idx={3} title="Preprocess" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <label className="flex cursor-pointer items-center gap-3 rounded-md bg-bg-hover px-3 py-2 text-sm">
            <input
              type="checkbox"
              checked={standardize}
              onChange={(e) => setStandardize(e.target.checked)}
              className="accent-accent-blue"
            />
            <span className="font-mono">Standardize features</span>
            <span className="ml-auto text-xs text-zinc-500">fit on train only</span>
          </label>
          <div>
            <label className={LABEL_CLASS}>Test size</label>
            <input
              type="number"
              min={0.05}
              max={0.45}
              step={0.05}
              value={testSize}
              onChange={(e) => setTestSize(Number(e.target.value))}
              className={INPUT_CLASS}
            />
          </div>
          <div>
            <label className={LABEL_CLASS}>Downsample stride</label>
            <input
              type="number"
              min={1}
              max={100}
              value={downsampleStride}
              onChange={(e) => setDownsampleStride(Number(e.target.value))}
              className={INPUT_CLASS}
            />
          </div>
        </div>
      </section>

      {/* Step 4 — Model */}
      <section className={SECTION_CLASS}>
        <SectionHeader idx={4} title="Model" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className={LABEL_CLASS}>Model</label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className={INPUT_CLASS}
            >
              {MODELS_BY_TASK[task].map((m) => (
                <option key={m.name} value={m.name}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>
          <p className="self-end text-xs text-zinc-500">
            Hyperparameters use registry defaults. Tuning UI is intentionally
            out of scope until a tuned model proves useful — see ADR-002 §D7.
          </p>
        </div>
      </section>

      {/* Run */}
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={runTraining}
          disabled={busy || features.length === 0}
          className="rounded-md bg-accent-blue px-6 py-2.5 font-semibold text-white transition hover:bg-accent-blue/80 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "Training…" : "Train"}
        </button>
        {result && (
          <span className="text-xs font-mono text-zinc-500">
            experiment_id: {result.experiment_id} ({result.runtime_ms} ms)
          </span>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-accent-red/40 bg-accent-red/10 p-3 text-sm text-accent-red">
          <span className="font-mono">{error}</span>
        </div>
      )}

      {result && <ResultPanel result={result} task={task} />}
    </div>
  );
}

function SectionHeader({ idx, title }: { idx: number; title: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent-blue/20 text-xs font-semibold text-accent-blue">
        {idx}
      </span>
      <h2 className="text-base font-semibold text-zinc-100">{title}</h2>
    </div>
  );
}

function SafetyBanner() {
  return (
    <div className="rounded-md border border-accent-blue/30 bg-accent-blue/10 p-3 text-xs text-zinc-300">
      <span className="font-mono font-semibold text-accent-blue">
        Time-series ML mode
      </span>{" "}
      — train/test split is chronological (no shuffle), the standardiser is
      fit on train only, every feature is strictly backward-looking. These
      are non-negotiable per ADR-002 §D4.
    </div>
  );
}
