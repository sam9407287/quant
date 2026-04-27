"use client";

import type { TaskType, TrainResponse } from "@/lib/ml";

import {
  ClusterScatter,
  FeatureImportanceBar,
  PredictedVsActualScatter,
  RegressionTimeSeries,
} from "./charts";

interface Props {
  result: TrainResponse;
  task: TaskType;
}

export function ResultPanel({ result, task }: Props) {
  return (
    <section className="space-y-4 rounded-lg border border-border bg-bg-panel p-5">
      <h2 className="text-base font-semibold text-zinc-100">Results</h2>
      <MetricsRow metrics={result.metrics} />

      {task === "regression" && result.sample_predictions.length > 0 && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card title="Predicted vs Actual (time)">
            <RegressionTimeSeries data={result.sample_predictions} />
          </Card>
          <Card title="Predicted vs Actual (scatter)">
            <PredictedVsActualScatter data={result.sample_predictions} />
          </Card>
        </div>
      )}

      {task === "classification" && result.sample_predictions.length > 0 && (
        <Card title="Sample predictions (first 50)">
          <ClassificationSamplesTable
            data={result.sample_predictions.slice(0, 50)}
          />
        </Card>
      )}

      {task === "clustering" && result.projection && (
        <Card title="Cluster scatter (PCA → 2D)">
          <ClusterScatter points={result.projection} />
        </Card>
      )}

      {result.feature_importance && (
        <Card title="Feature importance">
          <FeatureImportanceBar importance={result.feature_importance} />
        </Card>
      )}
    </section>
  );
}

function MetricsRow({ metrics }: { metrics: Record<string, number> }) {
  const entries = Object.entries(metrics);
  if (entries.length === 0) return null;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {entries.map(([k, v]) => (
        <div
          key={k}
          className="rounded-md border border-border bg-bg-hover p-3"
        >
          <div className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">
            {k}
          </div>
          <div className="mt-1 font-mono text-lg text-zinc-100">
            {fmtMetric(v)}
          </div>
        </div>
      ))}
    </div>
  );
}

function fmtMetric(v: number): string {
  if (Math.abs(v) >= 100) return v.toFixed(2);
  if (Math.abs(v) >= 1) return v.toFixed(4);
  return v.toExponential(3);
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-bg-hover/30 p-4">
      <div className="mb-2 font-mono text-xs uppercase tracking-wider text-zinc-500">
        {title}
      </div>
      {children}
    </div>
  );
}

function ClassificationSamplesTable({
  data,
}: {
  data: { ts: string; actual: number; predicted: number }[];
}) {
  return (
    <div className="overflow-hidden rounded-md border border-border">
      <table className="min-w-full text-xs font-mono">
        <thead className="bg-bg-hover/60 text-zinc-400">
          <tr>
            <th className="px-3 py-2 text-left">Timestamp</th>
            <th className="px-3 py-2 text-right">Actual</th>
            <th className="px-3 py-2 text-right">Predicted</th>
            <th className="px-3 py-2 text-right">Match</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {data.map((d, i) => (
            <tr key={i}>
              <td className="px-3 py-1.5 text-zinc-400">
                {d.ts.replace("T", " ").slice(0, 16)}
              </td>
              <td className="px-3 py-1.5 text-right">{d.actual}</td>
              <td className="px-3 py-1.5 text-right">{d.predicted}</td>
              <td className="px-3 py-1.5 text-right">
                {d.actual === d.predicted ? (
                  <span className="text-accent-green">✓</span>
                ) : (
                  <span className="text-accent-red">✗</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
