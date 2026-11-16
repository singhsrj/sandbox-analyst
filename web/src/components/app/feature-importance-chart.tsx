"use client";

import type { DataProfile } from "@/lib/types";

/** Mutual information between each feature and the target, as ranked bars. */
export function FeatureImportanceChart({
  importance,
}: {
  importance: NonNullable<DataProfile["feature_importance"]>;
}) {
  const max = Math.max(...importance.scores.map((s) => s.score), 1e-9);
  return (
    <div className="grid gap-3">
      <p className="text-sm leading-6 text-muted-foreground">
        {importance.description} Target: <span className="font-mono text-foreground">{importance.target}</span>{" "}
        in {importance.table}.
      </p>
      <ol className="grid gap-1.5" aria-label={`Features ranked by how much they tell you about ${importance.target}`}>
        {importance.scores.map((s, i) => (
          <li key={s.feature} className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_3.5rem] items-center gap-2 text-xs">
            <span className="truncate font-mono">{s.feature}</span>
            <span className="h-3 rounded-sm bg-muted">
              <span
                className={i === 0 ? "block h-full rounded-sm bg-marker" : "block h-full rounded-sm bg-chart-2"}
                style={{ width: `${Math.max(1, (s.score / max) * 100)}%` }}
              />
            </span>
            <span className="text-right tabular-nums text-muted-foreground">{s.score.toFixed(3)}</span>
          </li>
        ))}
      </ol>
      <p className="text-xs leading-5 text-muted-foreground">
        Mutual information on {importance.rows_used.toLocaleString("en-US")} rows: how much knowing a feature narrows
        down the target, including non-linear links. It shows association, not cause.
      </p>
    </div>
  );
}
