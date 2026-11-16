"use client";

import { SparklesIcon, XIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { getProfile } from "@/lib/api";
import { formatCount } from "@/lib/format";
import type { DataProfile } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ColumnDistribution } from "./column-distribution";
import { CorrelationMatrix } from "./correlation-matrix";
import { ErDiagram } from "./er-diagram";
import { FeatureImportanceChart } from "./feature-importance-chart";
import { ProfileColumnsTable } from "./profile-columns-table";
import { ProfileOutliers } from "./profile-outliers";

interface DataProfilePanelProps {
  /** Which dataset to describe ("sample" for the shop data). */
  dataset: string;
  onClose: () => void;
}

type Loaded = { dataset: string; profile: DataProfile } | { dataset: string; error: string };

const SECTIONS = [
  ["summary", "Summary"],
  ["relationships", "ER diagram"],
  ["importance", "Feature importance"],
  ["columns", "Columns"],
  ["distributions", "Distributions"],
  ["outliers", "Outliers"],
  ["correlations", "Correlations"],
] as const;

/** Statistical profile of the data, shown beside the chat so both can be read at once. */
export function DataProfilePanel({ dataset, onClose }: DataProfilePanelProps) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [tableName, setTableName] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getProfile(dataset)
      .then((profile) => {
        if (!cancelled) setLoaded({ dataset, profile });
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setLoaded({
            dataset,
            error: err instanceof Error ? err.message : "Could not load the data profile.",
          });
      });
    return () => {
      cancelled = true;
    };
  }, [dataset]);

  const current = loaded?.dataset === dataset ? loaded : null;
  const profile = current && "profile" in current ? current.profile : null;
  const table = profile ? (profile.tables.find((t) => t.name === tableName) ?? largest(profile)) : null;

  // Scroll only the panel: scrollIntoView would also scroll the page around it.
  const scroller = useRef<HTMLDivElement>(null);
  const jump = (id: string) => {
    const box = scroller.current;
    const target = document.getElementById(`profile-${id}`);
    if (!box || !target) return;
    const top = target.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop - 16;
    box.scrollTo({ top, behavior: "smooth" });
  };

  return (
    <section aria-labelledby="profile-title" className="@container flex h-full min-h-0 flex-col bg-background">
      <header className="flex items-start justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <h2 id="profile-title" className="text-sm font-semibold">
            Data profile
          </h2>
          <p className="truncate text-xs text-muted-foreground">
            {profile
              ? `${profile.dataset.name} · ${profile.dataset.tables} tables · ${formatCount(profile.dataset.rows)} rows`
              : "Statistics about the data you are asking about"}
          </p>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close data profile">
          <XIcon />
        </Button>
      </header>

      {profile ? (
        <nav aria-label="Profile sections" className="flex gap-3 overflow-x-auto border-b px-4 py-2 text-xs">
          {SECTIONS.map(([id, label]) => (
            <button
              key={id}
              onClick={() => jump(id)}
              className="shrink-0 text-muted-foreground hover:text-foreground"
            >
              {label}
            </button>
          ))}
        </nav>
      ) : null}

      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
        {!current ? (
          <p role="status" className="p-4 text-sm text-muted-foreground">
            Loading…
          </p>
        ) : "error" in current ? (
          <p role="alert" className="p-4 text-sm text-destructive">
            {current.error}
          </p>
        ) : profile && table ? (
          <div className="grid gap-8 px-4 py-5">
            <Block id="summary" title="Summary">
              {profile.summary ? (
                <div className="grid gap-2">
                  <p className="text-sm leading-6">{profile.summary.text}</p>
                  <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <SparklesIcon className="size-3.5" aria-hidden="true" />
                    Written by {profile.summary.model} from the statistics below, not from the rows. Check it
                    against them.
                  </p>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No summary yet.</p>
              )}
              <dl className="mt-1 grid grid-cols-3 gap-px overflow-hidden rounded-sm border bg-border text-center">
                {(
                  [
                    ["Tables", profile.dataset.tables],
                    ["Rows", profile.dataset.rows],
                    ["Columns", profile.dataset.columns],
                  ] as const
                ).map(([label, value]) => (
                  <div key={label} className="bg-card px-2 py-2">
                    <dt className="text-xs text-muted-foreground">{label}</dt>
                    <dd className="text-sm font-medium tabular-nums">{formatCount(value)}</dd>
                  </div>
                ))}
              </dl>
            </Block>

            <Block id="relationships" title="ER diagram">
              <ErDiagram tables={profile.tables} relationships={profile.relationships} />
            </Block>

            <Block id="importance" title="Feature importance">
              {profile.feature_importance ? (
                <FeatureImportanceChart importance={profile.feature_importance} />
              ) : (
                <p className="text-sm text-muted-foreground">Not computed for this dataset.</p>
              )}
            </Block>

            <div className="grid gap-3 border-t pt-6">
              <h3 className="text-sm font-semibold">Table details</h3>
              <div role="group" aria-label="Choose a table" className="flex flex-wrap gap-1.5">
                {profile.tables.map((t) => (
                  <button
                    key={t.name}
                    aria-pressed={t.name === table.name}
                    onClick={() => setTableName(t.name)}
                    className={cn(
                      "rounded-sm border px-2 py-1 font-mono text-xs",
                      t.name === table.name
                        ? "border-foreground bg-foreground text-background"
                        : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                    )}
                  >
                    {t.name}
                  </button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                {formatCount(table.rows)} rows{table.description ? ` · ${table.description}` : ""}
              </p>
            </div>

            <Block id="columns" title={`Columns of ${table.name}`}>
              <ProfileColumnsTable table={table} />
            </Block>

            <Block id="distributions" title="Distributions">
              <div className="grid gap-px overflow-hidden rounded-sm border bg-border @lg:grid-cols-2">
                {table.columns.map((c) => (
                  <ColumnDistribution key={c.name} column={c} />
                ))}
              </div>
            </Block>

            <Block id="outliers" title="Outliers">
              <ProfileOutliers table={table} />
            </Block>

            <Block id="correlations" title="Correlations">
              {table.correlations ? (
                <CorrelationMatrix correlations={table.correlations} />
              ) : (
                <p className="text-sm text-muted-foreground">
                  {table.name} has fewer than two numeric columns, so there is nothing to correlate.
                </p>
              )}
            </Block>

            <p className="text-xs text-muted-foreground">
              Computed {profile.dataset.generated_at.slice(0, 10)} from the full data, by code. Personal-data
              columns show counts only.
            </p>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function Block({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={`profile-${id}`} aria-labelledby={`profile-${id}-title`} className="grid scroll-mt-4 gap-3">
      <h3 id={`profile-${id}-title`} className="text-sm font-semibold">
        {title}
      </h3>
      {children}
    </section>
  );
}

/** Start on the biggest table: it is usually the one questions are about. */
function largest(profile: DataProfile) {
  return profile.tables.reduce((a, b) => (b.rows > a.rows ? b : a));
}
