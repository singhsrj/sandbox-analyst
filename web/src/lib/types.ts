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
  timezone: string;
  data_source?: string; // "sample" or a saved connection's id (older runs: absent)
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
    timezone: raw.timezone ?? "UTC",
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

/** A recorded, checked run that anyone can watch (GET /api/replays). */
export interface ReplaySummary {
  id: string;
  title: string;
  question: string;
  recorded_at: string;
  model: string;
  /** What was checked against the database before publishing. */
  verified: string;
}

export interface ReplayDetail extends ReplaySummary {
  runs: StoredRun[];
}

// --- data profile (GET /api/profiles/{dataset}) -------------------------------------------

export type ColumnKind = "id" | "pii" | "boolean" | "datetime" | "numeric" | "categorical" | "text";

export interface HistogramBin {
  start: number;
  end: number;
  count: number;
}

export interface TopValue {
  value: string | null;
  count: number;
  pct: number;
  /** The folded tail ("everything else"). */
  other?: boolean;
}

export interface ProfileColumn {
  name: string;
  type: string;
  kind: ColumnKind;
  note: string;
  missing: number;
  missing_pct: number;
  distinct: number;
  /** Never set for personal-data columns. */
  example: string | null;
  stats?: {
    min: number;
    p25: number;
    median: number;
    mean: number;
    p75: number;
    max: number;
    std: number | null;
    skew: number | null;
  };
  histogram?: HistogramBin[];
  outliers?: {
    method: "iqr";
    lower: number;
    upper: number;
    count: number;
    pct: number;
    examples: number[];
  };
  top_values?: TopValue[];
  date_range?: { min: string; max: string };
  timeline?: { unit: "day" | "month" | "year"; points: { period: string; count: number }[] };
  length?: { min: number; mean: number; max: number };
}

export interface ProfileTable {
  name: string;
  description: string;
  rows: number;
  columns: ProfileColumn[];
  correlations: { method: string; columns: string[]; matrix: (number | null)[][] } | null;
}

export interface ProfileRelationship {
  from_table: string;
  from_column: string;
  to_table: string;
  to_column: string;
  kind: "foreign_key" | "inferred";
  match_pct?: number;
}

export interface DataProfile {
  version: number;
  dataset: {
    id: string;
    name: string;
    source: string;
    generated_at: string;
    tables: number;
    rows: number;
    columns: number;
  };
  summary: { text: string; model: string; ai_generated: boolean } | null;
  tables: ProfileTable[];
  relationships: ProfileRelationship[];
  feature_importance: {
    table: string;
    target: string;
    task: "classification" | "regression";
    method: string;
    description: string;
    rows_used: number;
    scores: { feature: string; score: number }[];
  } | null;
}
