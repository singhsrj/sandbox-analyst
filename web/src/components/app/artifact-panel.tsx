"use client";

import { CheckIcon, CopyIcon, DownloadIcon, XIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { MessageResponse } from "@/components/ai-elements/message";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { fetchArtifact } from "@/lib/api";
import { formatBytes, formatCount, formatSeconds, replaceSandboxImages } from "@/lib/format";
import { parseCsv } from "@/lib/parse";
import type { ArtifactItem, RunInfo } from "@/lib/types";
import { ResultTable } from "./tool-steps";

type Loaded =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; objectUrl: string; text: string | null };

const TEXT_EXTENSIONS = new Set(["csv", "md", "txt", "json"]);

function extensionOf(name: string): string {
  return name.split(".").pop()?.toLowerCase() ?? "";
}

/** Artifacts need the bearer token, so they are fetched with it and shown from a blob URL. */
function useArtifact(item: ArtifactItem): Loaded {
  // The result is stored with the key it belongs to, so a different file shows "loading"
  // immediately without resetting state inside the effect.
  const [result, setResult] = useState<{ key: string; value: Loaded } | null>(null);
  const key = `${item.url}|${item.name}`;

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    fetchArtifact(item.url)
      .then(async (blob) => {
        const text = TEXT_EXTENSIONS.has(extensionOf(item.name)) ? await blob.text() : null;
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setResult({ key, value: { state: "ready", objectUrl, text } });
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setResult({
            key,
            value: {
              state: "error",
              message: err instanceof Error ? err.message : "Could not load this file.",
            },
          });
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [item.url, item.name, key]);

  return result?.key === key ? result.value : { state: "loading" };
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the button simply does nothing */
    }
  }
  return (
    <Button variant="ghost" size="icon-xs" onClick={copy} aria-label={copied ? "Copied" : "Copy contents"}>
      {copied ? <CheckIcon /> : <CopyIcon />}
    </Button>
  );
}

/** Tap-to-zoom: the chart opens in an overlay at a readable size; scroll inside it to pan. */
function ZoomableImage({ src, name }: { src: string; name: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`Zoom ${name}`}
        className="block w-full min-w-0 cursor-zoom-in"
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- blob URL created at runtime */}
        <img src={src} alt={name} className="block h-auto w-full max-w-full bg-white" />
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="h-[90dvh] w-[calc(100%-1rem)] max-w-none gap-0 overflow-auto p-0 sm:max-w-none">
          <DialogTitle className="sr-only">{name}</DialogTitle>
          <DialogDescription className="sr-only">Enlarged chart. Scroll to pan.</DialogDescription>
          {/* eslint-disable-next-line @next/next/no-img-element -- blob URL created at runtime */}
          <img src={src} alt={name} className="block h-auto w-[max(100%,48rem)] max-w-none bg-white" />
        </DialogContent>
      </Dialog>
    </>
  );
}

function FilePreview({ item, loaded }: { item: ArtifactItem; loaded: Loaded }) {
  if (loaded.state === "loading") return <p className="p-3 text-sm text-muted-foreground">Loading…</p>;
  if (loaded.state === "error")
    return (
      <p role="alert" className="p-3 text-sm text-destructive">
        {loaded.message}
      </p>
    );
  const ext = extensionOf(item.name);
  if (ext === "png" || ext === "jpg" || ext === "jpeg") {
    return <ZoomableImage src={loaded.objectUrl} name={item.name} />;
  }
  if (ext === "csv" && loaded.text !== null) {
    const { header, rows, truncated } = parseCsv(loaded.text, 15);
    return (
      <div className="grid min-w-0 grid-cols-1 gap-2 p-3">
        <ResultTable header={header} rows={rows} />
        {truncated ? (
          <p className="text-xs text-muted-foreground">Showing the first {rows.length} rows. Download for the rest.</p>
        ) : null}
      </div>
    );
  }
  if (ext === "md" && loaded.text !== null) {
    return (
      <div className="max-h-[28rem] min-w-0 overflow-auto p-3 text-sm leading-6 [&_img]:h-auto [&_img]:max-w-full">
        <MessageResponse>{replaceSandboxImages(loaded.text)}</MessageResponse>
      </div>
    );
  }
  return (
    <pre className="max-h-72 overflow-auto p-3 font-mono text-xs leading-5 whitespace-pre-wrap">
      {loaded.text ?? ""}
    </pre>
  );
}

function FileCard({ item }: { item: ArtifactItem }) {
  const loaded = useArtifact(item);
  return (
    <section aria-label={item.name} className="min-w-0 shrink-0 overflow-hidden rounded-sm border bg-card" data-testid="file-card">
      <header className="flex items-center gap-2 border-b px-3 py-1.5">
        <h3 className="min-w-0 flex-1 truncate text-sm font-medium">{item.name}</h3>
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{formatBytes(item.size)}</span>
        {loaded.state === "ready" && loaded.text !== null ? <CopyButton text={loaded.text} /> : null}
        {loaded.state === "ready" ? (
          <Button asChild variant="ghost" size="icon-xs">
            <a href={loaded.objectUrl} download={item.name} aria-label={`Download ${item.name}`}>
              <DownloadIcon />
            </a>
          </Button>
        ) : null}
      </header>
      <FilePreview item={item} loaded={loaded} />
    </section>
  );
}

function RunDetails({ run }: { run: RunInfo }) {
  const { usage } = run;
  const rows: [string, string][] = [
    ["Model", run.model],
    ["Time", formatSeconds(run.seconds)],
    ["Model calls", formatCount(usage.llm_calls)],
    ["Queries", formatCount(run.sql_queries)],
    ["Tokens in / out", `${formatCount(usage.input_tokens)} / ${formatCount(usage.output_tokens)}`],
    ["Cost", usage.cost_usd === null ? "not priced yet" : `$${usage.cost_usd.toFixed(4)}`],
  ];
  return (
    <section aria-label="Run details" className="grid shrink-0 gap-1.5">
      <h3 className="text-sm font-medium">Run details</h3>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="text-right tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
      {run.trace_url ? (
        <a
          href={run.trace_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs underline underline-offset-2 hover:text-foreground"
        >
          View trace in Langfuse
        </a>
      ) : null}
    </section>
  );
}

interface ArtifactPanelProps {
  artifacts: ArtifactItem[];
  run: RunInfo | null;
  onClose?: () => void;
}

export function ArtifactPanel({ artifacts, run, onClose }: ArtifactPanelProps) {
  return (
    <div className="flex h-full min-h-0 w-full min-w-0 flex-col" data-testid="artifact-panel">
      <div className="flex items-center min-h-12 justify-between border-b pr-2 pl-4">
        <h2 className="text-sm font-semibold">Files{artifacts.length ? ` (${artifacts.length})` : ""}</h2>
        {onClose ? (
          <Button variant="ghost" size="icon" className="size-11" onClick={onClose} aria-label="Close files panel">
            <XIcon />
          </Button>
        ) : null}
      </div>
      {/* flex column, not grid: cards use overflow-hidden, so a fixed-height grid would shrink every
          row to the same height and crop charts and tables. shrink-0 keeps them at full size. */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        {artifacts.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Charts, tables and the written report appear here when an answer produces them.
          </p>
        ) : (
          artifacts.map((item) => <FileCard key={item.url} item={item} />)
        )}
        {run ? <RunDetails run={run} /> : null}
      </div>
    </div>
  );
}
