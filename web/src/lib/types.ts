import type { UIMessage } from "ai";

export interface TodoItem {
  content: string;
  status: "pending" | "in_progress" | "completed" | string;
}

export interface ArtifactItem {
  name: string;
  mime: string;
  size: number;
  url: string; // path on the API, requires the bearer token
}

export type ApprovalMode = "off" | "normal" | "strict";

export interface RunInfo {
  status: "ok" | "error" | "budget_exceeded" | "step_limit" | "aborted" | "awaiting_approval" | string;
  model: string;
  provider: string;
  seconds: number;
  trace_url: string | null;
  sql_queries: number;
  empty_reply_nudges: number;
  unverified_file_claims: string[];
  approval_mode: ApprovalMode | string;
  usage: {
    llm_calls: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    cost_usd: number | null;
  };
}

/** Fill defaults so a partial or older run summary can never break the page. */
export function normalizeRun(raw: Partial<RunInfo> | undefined | null): RunInfo | null {
  if (!raw || typeof raw !== "object") return null;
  return {
    status: raw.status ?? "ok",
    model: raw.model ?? "unknown model",
    provider: raw.provider ?? "",
    seconds: typeof raw.seconds === "number" ? raw.seconds : 0,
    trace_url: raw.trace_url ?? null,
    sql_queries: raw.sql_queries ?? 0,
    empty_reply_nudges: raw.empty_reply_nudges ?? 0,
    unverified_file_claims: Array.isArray(raw.unverified_file_claims) ? raw.unverified_file_claims : [],
    approval_mode: raw.approval_mode ?? "off",
    usage: {
      llm_calls: raw.usage?.llm_calls ?? 0,
      input_tokens: raw.usage?.input_tokens ?? 0,
      output_tokens: raw.usage?.output_tokens ?? 0,
      total_tokens: raw.usage?.total_tokens ?? 0,
      cost_usd: raw.usage?.cost_usd ?? null,
    },
  };
}

/** Custom data parts our backend streams (see api/app/streaming/adapter.py). */
export type AnalystDataParts = {
  todos: { todos: TodoItem[] };
  artifacts: { items: ArtifactItem[] };
  run: RunInfo;
};

export type AnalystMessage = UIMessage<unknown, AnalystDataParts>;

export interface ThreadSummary {
  thread_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface StoredRun {
  run_id: string;
  question: string;
  status: string;
  model: string;
  final_answer: string;
  chunks: Array<Record<string, unknown>>;
  created_at: string;
  /** `resumes`: this run continued the previous run's message after a human approval. */
  summary?: { resumes?: boolean } & Record<string, unknown>;
}

/** What the reviewer decided on an approval card. */
export interface ApprovalDecision {
  approved: boolean;
  reason?: string;
  /** Set when the reviewer changed the SQL before approving it. */
  editedQuery?: string;
}

export interface SchemaColumn {
  name: string;
  type: string;
  nullable: boolean;
  note: string;
}
export interface SchemaTable {
  name: string;
  approx_rows: number;
  description: string;
  columns: SchemaColumn[];
}
