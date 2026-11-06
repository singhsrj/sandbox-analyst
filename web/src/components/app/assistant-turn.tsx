"use client";

import { getToolName, isToolUIPart } from "ai";
import { CheckIcon, CircleDashedIcon, CircleDotIcon, FilesIcon } from "lucide-react";
import type { ReactNode } from "react";
import { MessageResponse } from "@/components/ai-elements/message";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { Button } from "@/components/ui/button";
import { formatCount, formatSeconds, replaceSandboxImages } from "@/lib/format";
import { normalizeRun, type AnalystMessage, type ArtifactItem, type RunInfo, type TodoItem } from "@/lib/types";
import { TrailStep, ToolStep, type ToolPartLike } from "./tool-steps";

type Item =
  | { kind: "text"; text: string }
  | { kind: "plan" }
  | { kind: "tool"; part: ToolPartLike; name: string };

/** Split an assistant message into trail items (in order) and the final answer text. */
export function organize(message: AnalystMessage): {
  trail: Item[];
  answer: string;
  todos: TodoItem[];
  artifacts: ArtifactItem[];
  run: RunInfo | null;
} {
  const items: Item[] = [];
  let todos: TodoItem[] = [];
  let artifacts: ArtifactItem[] = [];
  let run: RunInfo | null = null;
  let planPlaced = false;

  for (const part of message.parts) {
    if (part.type === "text") {
      if (part.text.trim()) items.push({ kind: "text", text: part.text });
    } else if (part.type === "data-todos") {
      todos = part.data.todos;
      if (!planPlaced) {
        items.push({ kind: "plan" });
        planPlaced = true;
      }
    } else if (part.type === "data-artifacts") {
      artifacts = part.data.items;
    } else if (part.type === "data-run") {
      run = normalizeRun(part.data);
    } else if (isToolUIPart(part)) {
      const name = getToolName(part);
      if (name === "write_todos") {
        if (!planPlaced) {
          items.push({ kind: "plan" });
          planPlaced = true;
        }
      } else {
        items.push({ kind: "tool", part: part as unknown as ToolPartLike, name });
      }
    }
  }

  // Everything after the last tool/plan step is the answer; text before it is narration.
  let lastStep = -1;
  items.forEach((item, i) => {
    if (item.kind !== "text") lastStep = i;
  });
  const trail = items.slice(0, lastStep + 1);
  const answer = items
    .slice(lastStep + 1)
    .map((item) => (item.kind === "text" ? item.text : ""))
    .join("\n\n")
    .trim();
  return { trail, answer, todos, artifacts, run };
}

const STATUS_NOTE: Record<string, string> = {
  budget_exceeded: "Stopped: this question used up its token budget before finishing.",
  step_limit: "Stopped: the agent reached its step limit before finishing.",
  aborted: "Stopped before finishing.",
  error: "The run failed before an answer was ready.",
};

function PlanStep({ todos, running }: { todos: TodoItem[]; running: boolean }) {
  const done = todos.filter((t) => t.status === "completed").length;
  return (
    <TrailStep
      state={running && done < todos.length ? "running" : "done"}
      title="Plan"
      meta={`${done} of ${todos.length} done`}
      defaultOpen={running}
      testId="step-plan"
    >
      <ul className="grid gap-1.5" aria-label="Plan">
        {todos.map((todo, i) => (
          <li key={i} className="flex items-start gap-2 text-sm">
            {todo.status === "completed" ? (
              <CheckIcon className="mt-0.5 size-3.5 shrink-0 text-ok" aria-label="Done" />
            ) : todo.status === "in_progress" ? (
              <CircleDotIcon className="mt-0.5 size-3.5 shrink-0" aria-label="In progress" />
            ) : (
              <CircleDashedIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-label="Not started" />
            )}
            <span className={todo.status === "completed" ? "text-muted-foreground" : undefined}>
              {todo.content}
            </span>
          </li>
        ))}
      </ul>
    </TrailStep>
  );
}

interface AssistantTurnProps {
  message: AnalystMessage;
  /** The model is still working on this message. */
  streaming: boolean;
  selected: boolean;
  onShowFiles: () => void;
}

export function AssistantTurn({ message, streaming, selected, onShowFiles }: AssistantTurnProps) {
  const { trail, answer, todos, artifacts, run } = organize(message);
  const waiting = streaming && trail.length === 0 && !answer;

  return (
    <article className="grid grid-cols-1 gap-4" aria-label="Answer" data-testid="assistant-turn">
      {waiting ? (
        <Shimmer className="text-sm">Planning the work…</Shimmer>
      ) : trail.length > 0 ? (
        <ol className="trail" aria-label="Steps the analyst took">
          {trail.map((item, i) => {
            if (item.kind === "plan") return <PlanStep key={i} todos={todos} running={streaming} />;
            if (item.kind === "text")
              return (
                <li key={i} className="pb-3 text-sm text-muted-foreground">
                  {item.text}
                </li>
              );
            return <ToolStep key={item.part.toolCallId} part={item.part} name={item.name} />;
          })}
          {streaming && !answer ? (
            <li className="relative pb-1">
              <span className="trail-node" data-state="running" aria-hidden="true" />
              <Shimmer className="text-sm">Working…</Shimmer>
            </li>
          ) : null}
        </ol>
      ) : null}

      {answer ? (
        <div className="answer max-w-[68ch] text-[15px] leading-7" data-testid="answer">
          <MessageResponse isAnimating={streaming}>{replaceSandboxImages(answer)}</MessageResponse>
        </div>
      ) : null}

      <RunFooter
        run={run}
        artifacts={artifacts}
        selected={selected}
        onShowFiles={onShowFiles}
        // From the parts, not the run status: the status is the paused run's until a resume ends.
        waitingForApproval={trail.some((item) => item.kind === "tool" && item.part.state === "approval-requested")}
      />
    </article>
  );
}

function RunFooter({
  run,
  artifacts,
  selected,
  onShowFiles,
  waitingForApproval,
}: {
  run: RunInfo | null;
  artifacts: ArtifactItem[];
  selected: boolean;
  onShowFiles: () => void;
  waitingForApproval: boolean;
}) {
  if (!run && artifacts.length === 0) return null;
  const facts: ReactNode[] = [];
  if (run) {
    facts.push(formatSeconds(run.seconds));
    if (run.sql_queries > 0) facts.push(`${run.sql_queries} ${run.sql_queries === 1 ? "query" : "queries"}`);
    if (run.usage.total_tokens > 0) facts.push(`${formatCount(run.usage.total_tokens)} tokens`);
    facts.push(run.model);
  }
  return (
    <footer className="grid gap-2 text-xs text-muted-foreground">
      {run && STATUS_NOTE[run.status] ? (
        <p role="status" className="text-destructive">
          {STATUS_NOTE[run.status]}
        </p>
      ) : null}
      {waitingForApproval ? (
        <p role="status" className="text-foreground">
          Paused: a query above is waiting for your approval.
        </p>
      ) : null}
      {run && run.unverified_file_claims.length > 0 ? (
        <p role="status" className="text-destructive">
          The answer mentions files that were not produced: {run.unverified_file_claims.join(", ")}.
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {facts.map((fact, i) => (
          <span key={i} className="tabular-nums">
            {fact}
          </span>
        ))}
        {run?.trace_url ? (
          <a
            href={run.trace_url}
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2 hover:text-foreground"
          >
            View trace
          </a>
        ) : null}
        {artifacts.length > 0 ? (
          <Button
            variant="outline"
            size="xs"
            onClick={onShowFiles}
            aria-pressed={selected}
            className="ml-auto xl:hidden"
          >
            <FilesIcon aria-hidden="true" />
            Files ({artifacts.length})
          </Button>
        ) : null}
      </div>
    </footer>
  );
}
