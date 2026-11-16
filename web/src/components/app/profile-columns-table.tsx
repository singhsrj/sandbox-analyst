"use client";

import { formatCount } from "@/lib/format";
import { KIND_LABEL } from "@/lib/profile";
import type { ProfileTable } from "@/lib/types";

/** Every column of one table: kind, database type, missing values, distinct values, an example. */
export function ProfileColumnsTable({ table }: { table: ProfileTable }) {
  return (
    <div className="overflow-x-auto rounded-sm border">
      <table className="w-full text-xs">
        <caption className="sr-only">Columns of {table.name}</caption>
        <thead className="bg-muted/60 text-left text-muted-foreground">
          <tr>
            <th scope="col" className="px-2 py-1.5 font-medium">Column</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Kind</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Missing</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Distinct</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Example</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {table.columns.map((c) => (
            <tr key={c.name} className="align-top">
              <th scope="row" className="px-2 py-1.5 text-left font-normal">
                <span className="font-mono">{c.name}</span>
                {c.note ? <span className="block max-w-[28ch] text-muted-foreground">{c.note}</span> : null}
              </th>
              <td className="px-2 py-1.5 whitespace-nowrap">
                {KIND_LABEL[c.kind]}
                <span className="block font-mono text-muted-foreground">{c.type}</span>
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {c.missing ? `${c.missing_pct}%` : <span className="text-muted-foreground">0</span>}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatCount(c.distinct)}</td>
              <td className="max-w-[18ch] truncate px-2 py-1.5 font-mono text-muted-foreground" title={c.example ?? undefined}>
                {c.kind === "pii" ? <span className="font-sans italic">hidden</span> : (c.example ?? "–")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
