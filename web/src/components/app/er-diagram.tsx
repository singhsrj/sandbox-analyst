"use client";

import { useMemo } from "react";
import type { ProfileRelationship, ProfileTable } from "@/lib/types";

const BOX_W = 176;
const HEADER_H = 26;
const ROW_H = 18;
const GAP_X = 72;
const GAP_Y = 20;
const PAD = 8;

interface Box {
  table: ProfileTable;
  x: number;
  y: number;
  h: number;
}

/**
 * Tables as boxes, joins as lines. Referenced tables sit to the left, the tables that point at
 * them to the right (a column per "depth"), so lines mostly run one way. Guessed joins (uploads
 * without declared keys) are dashed.
 */
export function ErDiagram({
  tables,
  relationships,
}: {
  tables: ProfileTable[];
  relationships: ProfileRelationship[];
}) {
  const layout = useMemo(() => layOut(tables, relationships), [tables, relationships]);
  const keys = useMemo(() => {
    const k = new Map<string, "PK" | "FK">();
    for (const r of relationships) {
      k.set(`${r.to_table}.${r.to_column}`, "PK");
      k.set(`${r.from_table}.${r.from_column}`, "FK");
    }
    return k;
  }, [relationships]);

  const rowY = (box: Box, column: string) => {
    const i = box.table.columns.findIndex((c) => c.name === column);
    return box.y + HEADER_H + (Math.max(i, 0) + 0.5) * ROW_H;
  };

  return (
    <figure className="grid gap-2">
      <div className="overflow-x-auto rounded-sm border bg-card">
        <svg
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          width={layout.width}
          height={layout.height}
          role="img"
          aria-labelledby="er-title"
          className="block max-w-none text-foreground"
        >
          <title id="er-title">
            {`Entity relationship diagram: ${tables.length} tables, ${relationships.length} joins`}
          </title>
          {relationships.map((r) => {
            const child = layout.boxes.get(r.from_table);
            const parent = layout.boxes.get(r.to_table);
            if (!child || !parent) return null;
            const leftToRight = parent.x < child.x;
            const x1 = leftToRight ? child.x : child.x + BOX_W;
            const x2 = leftToRight ? parent.x + BOX_W : parent.x;
            const y1 = rowY(child, r.from_column);
            const y2 = rowY(parent, r.to_column);
            const bend = Math.max(24, Math.abs(x1 - x2) / 2);
            const c1 = leftToRight ? x1 - bend : x1 + bend;
            const c2 = leftToRight ? x2 + bend : x2 - bend;
            return (
              <path
                key={`${r.from_table}.${r.from_column}->${r.to_table}`}
                d={`M ${x1} ${y1} C ${c1} ${y1}, ${c2} ${y2}, ${x2} ${y2}`}
                fill="none"
                className="stroke-muted-foreground"
                strokeWidth={1}
                strokeDasharray={r.kind === "inferred" ? "4 3" : undefined}
              />
            );
          })}
          {[...layout.boxes.values()].map((box) => (
            <g key={box.table.name}>
              <rect
                x={box.x}
                y={box.y}
                width={BOX_W}
                height={box.h}
                rx={3}
                className="fill-card stroke-border"
              />
              <rect x={box.x} y={box.y} width={BOX_W} height={HEADER_H} rx={3} className="fill-muted" />
              <text x={box.x + 8} y={box.y + 17} className="fill-foreground font-mono text-[11px] font-semibold">
                {box.table.name}
              </text>
              <text
                x={box.x + BOX_W - 8}
                y={box.y + 17}
                textAnchor="end"
                className="fill-muted-foreground text-[10px]"
              >
                {compact(box.table.rows)}
              </text>
              {box.table.columns.map((col, i) => {
                const key = keys.get(`${box.table.name}.${col.name}`);
                const y = box.y + HEADER_H + (i + 0.5) * ROW_H + 3.5;
                return (
                  <g key={col.name}>
                    <text x={box.x + 8} y={y} className="fill-foreground font-mono text-[10px]">
                      {truncate(col.name, 20)}
                    </text>
                    {key ? (
                      <text
                        x={box.x + BOX_W - 8}
                        y={y}
                        textAnchor="end"
                        className={key === "PK" ? "fill-foreground text-[9px] font-semibold" : "fill-muted-foreground text-[9px]"}
                      >
                        {key}
                      </text>
                    ) : null}
                  </g>
                );
              })}
            </g>
          ))}
        </svg>
      </div>
      <figcaption className="text-xs text-muted-foreground">
        {relationships.length === 0
          ? "No joins between tables."
          : relationships.some((r) => r.kind === "inferred")
            ? "Dashed lines are joins guessed from matching column names and values, not declared keys."
            : "Lines are the database's declared foreign keys (FK → PK)."}
      </figcaption>
    </figure>
  );
}

function layOut(tables: ProfileTable[], relationships: ProfileRelationship[]) {
  const parents = new Map<string, string[]>();
  for (const r of relationships) {
    if (r.from_table === r.to_table) continue;
    parents.set(r.from_table, [...(parents.get(r.from_table) ?? []), r.to_table]);
  }
  const depth = new Map<string, number>();
  const visit = (name: string, seen: Set<string>): number => {
    const known = depth.get(name);
    if (known !== undefined) return known;
    if (seen.has(name)) return 0; // a cycle: break it here
    seen.add(name);
    const up = (parents.get(name) ?? []).map((p) => visit(p, seen) + 1);
    const d = up.length ? Math.max(...up) : 0;
    depth.set(name, d);
    return d;
  };
  for (const t of tables) visit(t.name, new Set());

  const columns = new Map<number, ProfileTable[]>();
  for (const t of tables) {
    const d = depth.get(t.name) ?? 0;
    columns.set(d, [...(columns.get(d) ?? []), t]);
  }
  const boxes = new Map<string, Box>();
  let height = 0;
  const depths = [...columns.keys()].sort((a, b) => a - b);
  depths.forEach((d, col) => {
    let y = PAD;
    for (const table of columns.get(d) ?? []) {
      const h = HEADER_H + table.columns.length * ROW_H + 4;
      boxes.set(table.name, { table, x: PAD + col * (BOX_W + GAP_X), y, h });
      y += h + GAP_Y;
    }
    height = Math.max(height, y - GAP_Y + PAD);
  });
  const width = PAD * 2 + depths.length * BOX_W + Math.max(0, depths.length - 1) * GAP_X;
  return { boxes, width, height };
}

function truncate(text: string, max: number) {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

function compact(n: number) {
  return new Intl.NumberFormat("en-US", { notation: "compact" }).format(n);
}
