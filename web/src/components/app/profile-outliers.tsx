"use client";

import { formatCount, formatStat } from "@/lib/format";
import type { ProfileTable } from "@/lib/types";

/** Values outside 1.5 × IQR for each numeric column of a table. */
export function ProfileOutliers({ table }: { table: ProfileTable }) {
  const rows = table.columns.filter((c) => c.outliers);
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No numeric columns in {table.name}, so no outliers to check.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-sm border">
      <table className="w-full text-xs">
        <caption className="sr-only">Outliers per numeric column of {table.name}</caption>
        <thead className="bg-muted/60 text-left text-muted-foreground">
          <tr>
            <th scope="col" className="px-2 py-1.5 font-medium">Column</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Normal range</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Outliers</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Most extreme</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((c) => {
            const o = c.outliers!;
            return (
              <tr key={c.name}>
                <th scope="row" className="px-2 py-1.5 text-left font-mono font-normal">{c.name}</th>
                <td className="px-2 py-1.5 tabular-nums text-muted-foreground">
                  {formatStat(o.lower)} to {formatStat(o.upper)}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  {o.count ? (
                    <span className={o.pct >= 5 ? "marked" : undefined}>
                      {formatCount(o.count)} ({o.pct}%)
                    </span>
                  ) : (
                    <span className="text-muted-foreground">none</span>
                  )}
                </td>
                <td className="px-2 py-1.5 tabular-nums text-muted-foreground">
                  {o.examples.length ? o.examples.map(formatStat).join(", ") : "–"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="border-t px-2 py-1.5 text-xs text-muted-foreground">
        Outside 1.5 × the interquartile range. Highlighted: 5% or more of the rows.
      </p>
    </div>
  );
}
