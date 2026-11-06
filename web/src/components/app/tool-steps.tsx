"use client";

import { ChevronRightIcon } from "lucide-react";
import type { ReactNode } from "react";
import { CodeBlock } from "@/components/ai-elements/code-block";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { formatCount, stripAnsi } from "@/lib/format";
import { parseSqlOutput, splitEditNotice } from "@/lib/parse";
import { cn } from "@/lib/utils";
import { ApprovalCard } from "./approval-card";

/** The subset of an AI SDK tool part this UI relies on (static and dynamic tools share it). */
export interface ToolPartLike {
  type: string;
  toolCallId: string;
  state: string;
  input?: unknown;
  output?: unknown;
  errorText?: string;
  approval?: { id: string; approved?: boolean; reason?: string; requestReason?: string };
}

export type NodeState = "running" | "done" | "error" | "waiting" | "denied";

export function nodeStateOf(part: ToolPartLike): NodeState {
  if (part.state === "output-error") return "error";
  if (part.state === "output-denied") return "denied";
  if (part.state === "approval-requested") return "waiting";
  if (part.state === "output-available") return "done";
  return "running";
}

const STATE_LABEL: Record<NodeState, string> = {
  running: "In progress: ",
  done: "Done: ",
  error: "Failed: ",
  waiting: "Waiting for your approval: ",
  denied: "Not run: ",
};

interface StepProps {
  state: NodeState;
  title: ReactNode;
  meta?: ReactNode;
  children?: ReactNode;
  defaultOpen?: boolean;
  testId?: string;
  /** Always shown under the summary, whether the details are open or not (approval cards). */
  pinned?: ReactNode;
}

/** One entry on the evidence trail: a node on the line, a one-line summary, optional details. */
export function TrailStep({ state, title, meta, children, defaultOpen = false, testId, pinned }: StepProps) {
  const label = (
    <span className="flex min-w-0 flex-1 items-baseline gap-2">
      <span className="truncate text-sm font-medium">{title}</span>
      {meta ? (
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{meta}</span>
      ) : null}
    </span>
  );
  return (
    <li className="relative pb-3" data-testid={testId} data-state={state}>
      <span className="trail-node" data-state={state} aria-hidden="true" />
      <span className="sr-only">{STATE_LABEL[state]}</span>
      {children ? (
        <Collapsible defaultOpen={defaultOpen}>
          <CollapsibleTrigger className="group flex w-full items-center gap-1.5 rounded-sm py-0.5 text-left hover:bg-muted/60">
            {label}
            <ChevronRightIcon
              className="size-3.5 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-90"
              aria-hidden="true"
            />
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2">{children}</CollapsibleContent>
        </Collapsible>
      ) : (
        <div className="flex items-center gap-1.5 py-0.5">{label}</div>
      )}
      {pinned ? <div className="pt-2">{pinned}</div> : null}
    </li>
  );
}

function Pre({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <pre
      className={cn(
        "max-h-72 overflow-auto rounded-sm border bg-card p-3 font-mono text-xs leading-5 whitespace-pre-wrap break-words",
        className,
      )}
    >
      {children}
    </pre>
  );
}

function clip(text: string, limit = 4000): string {
  return text.length <= limit ? text : `${text.slice(0, limit)}\n… (${formatCount(text.length - limit)} more characters)`;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function baseName(path: string): string {
  return path.split("/").filter(Boolean).pop() ?? path;
}

function outputText(part: ToolPartLike): string {
  if (part.state === "output-error") return part.errorText ?? "The step failed.";
  return typeof part.output === "string" ? part.output : part.output ? JSON.stringify(part.output, null, 2) : "";
}

export function ResultTable({ header, rows }: { header: string[]; rows: string[][] }) {
  return (
    <div className="max-h-64 overflow-auto rounded-sm border bg-card">
      <table className="w-full border-collapse text-xs">
        <thead className="sticky top-0 bg-muted">
          <tr>
            {header.map((h, i) => (
              <th key={i} scope="col" className="px-2.5 py-1.5 text-left font-medium whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="border-t">
              {row.map((cell, c) => (
                <td key={c} className="px-2.5 py-1.5 whitespace-nowrap tabular-nums">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
/** What the reviewer decided, shown on the step afterwards (also when replaying history). */
function approvalNote(part: ToolPartLike): string | null {
  const approval = part.approval;
  if (!approval || approval.approved === undefined) return null;
  if (!approval.approved)
    return approval.reason ? `You rejected this query: “${approval.reason}”` : "You rejected this query.";
  if (approval.reason) return `You approved this query. ${approval.reason}`;
  return "You approved this query.";
}

function SqlStep({ part }: { part: ToolPartLike }) {
  const state = nodeStateOf(part);
  const { executedQuery, rest: text } = splitEditNotice(outputText(part));
  const proposed = str(asRecord(part.input).query);
  const query = executedQuery ?? proposed;
  const parsed = part.state === "output-available" ? parseSqlOutput(text) : null;
  const failed = state === "error" || (parsed !== null && parsed.kind !== "ok");
  const waiting = state === "waiting" && part.approval !== undefined;
  const note = approvalNote(part);

  let meta: ReactNode = state === "running" ? "running…" : undefined;
  let title: ReactNode = "Ran a query";
  if (waiting) title = "Query waiting for your approval";
  else if (state === "denied") title = "Query not run";
  else if (parsed?.kind === "ok") meta = `${formatCount(parsed.rows)} ${parsed.rows === 1 ? "row" : "rows"}`;
  else if (parsed?.kind === "rejected") title = "Query was rejected";
  else if (parsed?.kind === "timeout") title = "Query timed out";
  else if (parsed?.kind === "error" || state === "error") title = "Query failed";

  return (
    <TrailStep
      state={failed ? "error" : state}
      title={title}
      meta={meta}
      testId="step-sql"
      defaultOpen={failed}
      // The card must be visible even though this step first appeared collapsed as "running".
      pinned={
        waiting ? (
          <ApprovalCard approvalId={part.approval!.id} query={query} reason={part.approval!.requestReason} />
        ) : note ? (
          <p className="text-xs text-muted-foreground">{note}</p>
        ) : undefined
      }
    >
      <div className="grid grid-cols-1 gap-2">
        {query ? <CodeBlock className="wrap-code" code={query} language="sql" /> : null}
        {executedQuery !== null && executedQuery !== proposed ? (
          <p className="text-xs text-muted-foreground">
            You edited this query; the SQL above is what actually ran.
          </p>
        ) : null}
        {parsed?.kind === "ok" ? (
          <>
            {parsed.warning ? (
              <p className="text-xs text-destructive" role="status">
                {parsed.warning}
              </p>
            ) : null}
            {parsed.preview.length > 0 ? (
              <>
                <ResultTable header={parsed.header} rows={parsed.preview} />
                <p className="text-xs text-muted-foreground">
                  {parsed.preview.length < parsed.rows
                    ? `Showing ${parsed.preview.length} of ${formatCount(parsed.rows)} rows. `
                    : ""}
                  The full result is saved in the sandbox for analysis.
                </p>
              </>
            ) : (
              <p className="text-xs text-muted-foreground">The query returned no rows.</p>
            )}
          </>
        ) : text && part.state !== "input-available" ? (
          <p className="text-sm text-destructive" role="alert">
            {parsed ? parsed.message : text}
          </p>
        ) : null}
      </div>
    </TrailStep>
  );
}

function ExecuteStep({ part }: { part: ToolPartLike }) {
  const state = nodeStateOf(part);
  const command = str(asRecord(part.input).command);
  const output = stripAnsi(outputText(part));
  const exit = /exit code[: ]+(-?\d+)/i.exec(output)?.[1];
  const failed = state === "error" || (exit !== undefined && exit !== "0");
  return (
    <TrailStep
      state={failed ? "error" : state}
      title="Ran code in the sandbox"
      meta={state === "running" ? "running…" : exit !== undefined ? `exit ${exit}` : undefined}
      testId="step-execute"
      defaultOpen={failed}
    >
      <div className="grid grid-cols-1 gap-2">
        {command ? <CodeBlock className="wrap-code" code={command} language="bash" /> : null}
        {output ? <Pre>{clip(output)}</Pre> : null}
      </div>
    </TrailStep>
  );
}

const LANGUAGE_BY_EXTENSION: Record<string, "python" | "json" | "bash" | "sql"> = {
  py: "python",
  json: "json",
  sh: "bash",
  sql: "sql",
};

function FileWriteStep({ part, verb }: { part: ToolPartLike; verb: string }) {
  const input = asRecord(part.input);
  const path = str(input.file_path);
  const content = str(input.content) || str(input.new_string);
  const ext = path.split(".").pop() ?? "";
  const language = LANGUAGE_BY_EXTENSION[ext];
  const failed = part.state === "output-error" || /^error/i.test(outputText(part));
  return (
    <TrailStep
      state={failed ? "error" : nodeStateOf(part)}
      title={`${verb} ${baseName(path) || "a file"}`}
      testId="step-file"
      defaultOpen={failed}
    >
      {failed ? (
        <p className="text-sm text-destructive">{outputText(part)}</p>
      ) : content ? (
        language ? <CodeBlock className="wrap-code" code={content} language={language} /> : <Pre>{clip(content)}</Pre>
      ) : null}
    </TrailStep>
  );
}

function TextOutputStep({ part, title }: { part: ToolPartLike; title: string }) {
  const text = outputText(part);
  return (
    <TrailStep state={nodeStateOf(part)} title={title} testId="step-text">
      {text ? <Pre>{clip(text)}</Pre> : null}
    </TrailStep>
  );
}

/** Pick the right presentation for a tool call. Unknown tools still get an honest generic step. */
export function ToolStep({ part, name }: { part: ToolPartLike; name: string }) {
  const input = asRecord(part.input);
  switch (name) {
    case "run_sql":
      return <SqlStep part={part} />;
    case "execute":
      return <ExecuteStep part={part} />;
    case "write_file":
      return <FileWriteStep part={part} verb="Wrote" />;
    case "edit_file":
      return <FileWriteStep part={part} verb="Edited" />;
    case "list_tables":
      return <TextOutputStep part={part} title="Looked at the available tables" />;
    case "describe_table":
      return (
        <TextOutputStep
          part={part}
          title={`Looked at the ${str(input.table_name) || "table"} table`}
        />
      );
    case "read_file":
      return <TextOutputStep part={part} title={`Read ${baseName(str(input.file_path)) || "a file"}`} />;
    case "export_artifact":
      return (
        <TrailStep
          state={nodeStateOf(part)}
          title={`Exported ${baseName(str(input.path)) || "a file"}`}
          testId="step-export"
        />
      );
    default:
      return (
        <TextOutputStep part={part} title={name.replace(/_/g, " ")} />
      );
  }
}
