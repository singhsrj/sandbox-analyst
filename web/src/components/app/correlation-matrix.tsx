"use client";

import { correlationStrength } from "@/lib/profile";
import type { ProfileTable } from "@/lib/types";

/** Spearman correlations between a table's numeric columns. Shade = strength; the sign is printed. */
export function CorrelationMatrix({ correlations }: { correlations: NonNullable<ProfileTable["correlations"]> }) {
  const { columns, matrix } = correlations;
  return (
    <div className="overflow-x-auto">
      <table className="border-separate border-spacing-0.5 text-xs">
        <caption className="sr-only">Spearman correlation between numeric columns</caption>
        <thead>
          <tr>
            <td />
            {columns.map((c) => (
              <th key={c} scope="col" className="max-w-20 truncate px-1 pb-1 text-left font-mono font-normal text-muted-foreground">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {columns.map((row, i) => (
            <tr key={row}>
              <th scope="row" className="max-w-28 truncate pr-2 text-left font-mono font-normal text-muted-foreground">
                {row}
              </th>
              {matrix[i].map((r, j) => (
                <td
                  key={columns[j]}
                  title={`${row} × ${columns[j]}: ${r ?? "–"} (${correlationStrength(r)})`}
                  className="relative h-8 w-14 min-w-14 rounded-sm text-center tabular-nums"
                >
                  <span
                    aria-hidden="true"
                    className="absolute inset-0 rounded-sm bg-foreground"
                    style={{ opacity: i === j || r === null ? 0.04 : 0.06 + Math.abs(r) * 0.6 }}
                  />
                  <span className={r !== null && Math.abs(r) > 0.55 && i !== j ? "relative text-background" : "relative"}>
                    {i === j ? "–" : r === null ? "–" : r.toFixed(2)}
                  </span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
