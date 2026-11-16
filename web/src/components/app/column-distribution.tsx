"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { formatCount, formatStat as fmt } from "@/lib/format";
import { KIND_LABEL } from "@/lib/profile";
import type { ProfileColumn, TopValue } from "@/lib/types";

const CONFIG = { count: { label: "Rows", color: "var(--chart-2)" } } satisfies ChartConfig;

/** One column's distribution: a histogram, its top values, a timeline, or why there is none. */
export function ColumnDistribution({ column }: { column: ProfileColumn }) {
  return (
    <article className="grid min-w-0 content-start gap-2 bg-card p-3">
      <header className="flex min-w-0 items-baseline justify-between gap-2">
        <h4 className="truncate font-mono text-xs font-medium">{column.name}</h4>
        <span className="shrink-0 text-xs text-muted-foreground">{KIND_LABEL[column.kind]}</span>
      </header>
      <Body column={column} />
      <p className="text-xs text-muted-foreground">
        {formatCount(column.distinct)} distinct
        {column.missing ? ` · ${column.missing_pct}% missing` : " · none missing"}
      </p>
    </article>
  );
}

function Body({ column }: { column: ProfileColumn }) {
  if (column.kind === "pii") {
    return <Note>Personal data: values are hidden, only counts are shown.</Note>;
  }
  if (column.kind === "id" && !column.top_values?.length) {
    return <Note>Identifier: a key that links or names rows, not a measurement.</Note>;
  }
  if (column.histogram && column.stats) {
    const bins = column.histogram.map((b) => ({
      label: b.start === b.end ? fmt(b.start) : `${fmt(b.start)}–${fmt(b.end)}`,
      count: b.count,
    }));
    return (
      <>
        <MiniBars data={bins} label={`Histogram of ${column.name}`} />
        <p className="text-xs text-muted-foreground tabular-nums">
          median {fmt(column.stats.median)} · mean {fmt(column.stats.mean)} · range {fmt(column.stats.min)}
          –{fmt(column.stats.max)}
          {column.stats.skew !== null && Math.abs(column.stats.skew) >= 1
            ? ` · ${column.stats.skew > 0 ? "right" : "left"}-skewed`
            : ""}
        </p>
      </>
    );
  }
  if (column.timeline && column.date_range) {
    const unit = column.timeline.unit;
    return (
      <>
        <MiniBars
          data={column.timeline.points.map((p) => ({ label: p.period, count: p.count }))}
          label={`Rows per ${unit} for ${column.name}`}
        />
        <p className="text-xs text-muted-foreground tabular-nums">
          {column.date_range.min.slice(0, 10)} to {column.date_range.max.slice(0, 10)} · rows per {unit}
        </p>
      </>
    );
  }
  if (column.top_values?.length) return <TopValues values={column.top_values} />;
  if (column.length) {
    return (
      <Note>
        Free text, {column.length.min}–{column.length.max} characters (mean {column.length.mean}).
      </Note>
    );
  }
  return <Note>No values to show.</Note>;
}

function MiniBars({ data, label }: { data: { label: string; count: number }[]; label: string }) {
  return (
    <ChartContainer config={CONFIG} className="aspect-auto h-28 w-full" aria-label={label} role="img">
      <BarChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }} barCategoryGap={1}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="label" hide />
        <YAxis hide />
        <ChartTooltip cursor={false} content={<ChartTooltipContent hideIndicator />} />
        <Bar dataKey="count" fill="var(--color-count)" radius={1} isAnimationActive={false} />
      </BarChart>
    </ChartContainer>
  );
}

function TopValues({ values }: { values: TopValue[] }) {
  const max = Math.max(...values.map((v) => v.pct), 1);
  return (
    <ul className="grid gap-1" aria-label="Most common values">
      {values.map((v) => (
        <li key={v.other ? "__other" : v.value} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 text-xs">
          <span className="relative min-w-0 overflow-hidden rounded-sm py-0.5">
            <span
              aria-hidden="true"
              className={v.other ? "absolute inset-y-0 left-0 bg-muted" : "absolute inset-y-0 left-0 bg-chart-4/60"}
              style={{ width: `${(v.pct / max) * 100}%` }}
            />
            <span className={v.other ? "relative px-1 text-muted-foreground italic" : "relative block truncate px-1"}>
              {v.other ? "everything else" : v.value || "(empty)"}
            </span>
          </span>
          <span className="tabular-nums text-muted-foreground">{v.pct}%</span>
        </li>
      ))}
    </ul>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <p className="text-xs leading-5 text-muted-foreground">{children}</p>;
}
