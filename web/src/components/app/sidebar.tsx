"use client";

import { PlusIcon, Trash2Icon, XIcon } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { formatCount, formatRelative } from "@/lib/format";
import type { SchemaTable, ThreadSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "./theme-toggle";

type Tab = "history" | "data";

interface SidebarProps {
  threads: ThreadSummary[];
  activeThreadId: string;
  onSelectThread: (id: string) => void;
  onNewThread: () => void;
  onDeleteThread: (id: string) => void;
  schema: SchemaTable[] | null;
  schemaError: string | null;
  signedIn: boolean;
  onRequestSignIn: () => void;
  onSignOut: () => void;
  onClose?: () => void;
}

export function Sidebar(props: SidebarProps) {
  const [tab, setTab] = useState<Tab>("history");
  return (
    <div className="flex h-full min-h-0 flex-col bg-sidebar text-sidebar-foreground">
      <div className="flex items-center justify-between px-4 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <span className="marked text-base font-semibold tracking-tight">SandboxAnalyst</span>
        </div>
        {props.onClose ? (
          <Button variant="ghost" size="icon-sm" onClick={props.onClose} aria-label="Close menu">
            <XIcon />
          </Button>
        ) : null}
      </div>

      <div className="px-3 pb-3">
        <Button variant="outline" className="w-full justify-start" onClick={props.onNewThread}>
          <PlusIcon aria-hidden="true" />
          New question
        </Button>
      </div>

      <div role="tablist" aria-label="Sidebar sections" className="flex gap-4 border-b px-4">
        {(
          [
            ["history", "History"],
            ["data", "The data"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            role="tab"
            id={`tab-${id}`}
            aria-selected={tab === id}
            aria-controls={`panel-${id}`}
            onClick={() => setTab(id)}
            className={cn(
              "-mb-px border-b-2 py-2 text-sm",
              tab === id
                ? "border-foreground font-medium"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto" role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "history" ? <ThreadList {...props} /> : <SchemaBrowser tables={props.schema} error={props.schemaError} />}
      </div>

      <div className="flex items-center justify-between border-t px-3 py-2">
        {props.signedIn ? (
          <button
            onClick={props.onSignOut}
            className="rounded-sm px-1 text-xs text-muted-foreground hover:text-foreground"
          >
            Live questions on · Lock
          </button>
        ) : (
          <button onClick={props.onRequestSignIn} className="rounded-sm px-1 text-xs underline underline-offset-2">
            Enter access code
          </button>
        )}
        <ThemeToggle />
      </div>
    </div>
  );
}

function ThreadList({ threads, activeThreadId, onSelectThread, onDeleteThread, signedIn, onRequestSignIn }: SidebarProps) {
  if (!signedIn) {
    return (
      <p className="p-4 text-sm text-muted-foreground">
        Your past questions appear here after you{" "}
        <button onClick={onRequestSignIn} className="underline underline-offset-2">
          enter the access code
        </button>
        .
      </p>
    );
  }
  if (threads.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">No questions yet. Ask one to start a history.</p>;
  }
  return (
    <ul className="grid py-1">
      {threads.map((thread) => (
        <li key={thread.thread_id} className="group relative">
          <button
            onClick={() => onSelectThread(thread.thread_id)}
            aria-current={thread.thread_id === activeThreadId ? "page" : undefined}
            className={cn(
              "w-full px-4 py-2 pr-10 text-left hover:bg-sidebar-accent",
              thread.thread_id === activeThreadId && "bg-sidebar-accent",
            )}
          >
            <span className="line-clamp-2 text-sm">{thread.title}</span>
            <span className="text-xs text-muted-foreground">{formatRelative(thread.updated_at)}</span>
          </button>
          <Button
            variant="ghost"
            size="icon-xs"
            className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100"
            onClick={() => onDeleteThread(thread.thread_id)}
            aria-label={`Delete "${thread.title}"`}
          >
            <Trash2Icon />
          </Button>
        </li>
      ))}
    </ul>
  );
}

export function SchemaBrowser({ tables, error }: { tables: SchemaTable[] | null; error: string | null }) {
  if (error) return <p className="p-4 text-sm text-destructive">{error}</p>;
  if (!tables) return <p className="p-4 text-sm text-muted-foreground">Loading the schema…</p>;
  return (
    <div className="grid py-1">
      <p className="px-4 py-2 text-xs text-muted-foreground">
        Synthetic shop data the agent can query. Read-only; nothing here is real customer data.
      </p>
      {tables.map((table) => (
        <details key={table.name} className="group border-t">
          <summary className="flex cursor-pointer list-none items-baseline justify-between gap-2 px-4 py-2 hover:bg-sidebar-accent">
            <span className="font-mono text-sm">{table.name}</span>
            <span className="text-xs tabular-nums text-muted-foreground">{formatCount(table.approx_rows)} rows</span>
          </summary>
          <div className="px-4 pb-3">
            {table.description ? <p className="pb-2 text-xs text-muted-foreground">{table.description}</p> : null}
            <ul className="grid gap-1">
              {table.columns.map((col) => (
                <li key={col.name} className="text-xs" title={col.note || undefined}>
                  <span className="font-mono">{col.name}</span>{" "}
                  <span className="text-muted-foreground">
                    {col.type}
                    {col.nullable ? ", may be empty" : ""}
                  </span>
                  {col.note ? <p className="text-muted-foreground">{col.note}</p> : null}
                </li>
              ))}
            </ul>
          </div>
        </details>
      ))}
    </div>
  );
}
