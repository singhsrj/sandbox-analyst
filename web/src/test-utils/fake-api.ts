/**
 * A fake backend for component tests: same URLs, same wire formats as api/app/api/routes.py,
 * and the SSE body is the REAL recorded agent run (see scripts/dump_chunks.py).
 */
import fixture from "../../test-fixtures/chunks.json";
import type { DataProfile } from "@/lib/types";

type Chunk = Record<string, unknown>;
const runs = fixture as unknown as Record<string, Chunk[]>;
export const realRun = runs.real_run;
export const toolErrorRun = runs.tool_error_run;
export const approvalPaused = runs.approval_paused;
export const approvalApproved = runs.approval_resumed_approved;
export const approvalRejected = runs.approval_resumed_rejected;

export const ACCESS_CODE = "open-sesame";

export const REPLAY_SUMMARY = {
  id: "cancelled-orders",
  title: "How many orders were cancelled in 2025?",
  question: "How many orders were cancelled in 2025?",
  recorded_at: "2026-11-06",
  model: "openai.gpt-oss-120b",
  verified: "1,086 matches the database",
};
// The real recorded run, with its file links pointing at the public replay URLs (as exported).
const replayRun = {
  run_id: "r1",
  question: REPLAY_SUMMARY.question,
  status: "ok",
  model: REPLAY_SUMMARY.model,
  final_answer: "",
  created_at: "2026-11-06T10:00:00Z",
  summary: { resumes: false },
  chunks: realRunPublic(),
};
function realRunPublic(): Chunk[] {
  return runs.real_run.map((c) =>
    c.type === "data-artifacts"
      ? {
          ...c,
          data: {
            items: (c.data as { items: { name: string }[] }).items.map((i) => ({
              ...i,
              url: `/api/replays/cancelled-orders/files/${i.name}`,
            })),
          },
        }
      : c,
  );
}
export { CLERK_TOKEN as TOKEN } from "./clerk-mock";
import { CLERK_TOKEN } from "./clerk-mock";

export function sseBody(chunks: Chunk[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(`data: ${JSON.stringify(chunk)}\n\n`));
      controller.enqueue(encoder.encode("data: [DONE]\n\n"));
      controller.close();
    },
  });
}

export interface RecordedRequest {
  method: string;
  path: string;
  headers: Headers;
  body: unknown;
}

/** A small, valid data profile: two tables, one join, every column kind the panel draws. */
export const SAMPLE_PROFILE: DataProfile = {
  version: 1,
  dataset: { id: "sample", name: "Sample shop data", source: "postgres", generated_at: "2026-11-16T00:00:00+00:00", tables: 2, rows: 50050, columns: 6 },
  summary: { text: "Orders from a synthetic shop, 2024 to 2025.", model: "openai.gpt-oss-120b", ai_generated: true },
  tables: [
    {
      name: "customers",
      description: "One row per customer.",
      rows: 50,
      correlations: null,
      columns: [
        { name: "customer_id", type: "integer", kind: "id", note: "", missing: 0, missing_pct: 0, distinct: 50, example: "1" },
        { name: "email", type: "text", kind: "pii", note: "", missing: 0, missing_pct: 0, distinct: 50, example: null },
      ],
    },
    {
      name: "orders",
      description: "One row per order.",
      rows: 50000,
      columns: [
        { name: "order_id", type: "integer", kind: "id", note: "", missing: 0, missing_pct: 0, distinct: 50000, example: "1" },
        { name: "customer_id", type: "integer", kind: "id", note: "", missing: 0, missing_pct: 0, distinct: 50, example: "7" },
        {
          name: "status", type: "text", kind: "categorical", note: "delivered | cancelled", missing: 0, missing_pct: 0, distinct: 2, example: "delivered",
          top_values: [{ value: "delivered", count: 48000, pct: 96 }, { value: "cancelled", count: 2000, pct: 4 }],
        },
        {
          name: "total_amount", type: "numeric(12,2)", kind: "numeric", note: "", missing: 0, missing_pct: 0, distinct: 4000, example: "12.5",
          stats: { min: 4, p25: 60, median: 170, mean: 290, p75: 390, max: 3900, std: 350, skew: 2.6 },
          histogram: [{ start: 4, end: 200, count: 30000 }, { start: 200, end: 3900, count: 20000 }],
          outliers: { method: "iqr", lower: -430, upper: 886, count: 2985, pct: 5.97, examples: [3900, 3600] },
        },
      ],
      correlations: { method: "spearman", columns: ["total_amount", "quantity"], matrix: [[1, 0.62], [0.62, 1]] },
    },
  ],
  relationships: [{ from_table: "orders", from_column: "customer_id", to_table: "customers", to_column: "customer_id", kind: "foreign_key" }],
  feature_importance: {
    table: "order lines", target: "is_returned", task: "classification", method: "mutual_information",
    description: "What relates to returns.", rows_used: 50000,
    scores: [{ feature: "category", score: 0.043 }, { feature: "unit_price", score: 0.022 }],
  },
};

export interface FakeApiOptions {
  /** Chunks streamed for POST /api/chat. */
  chat?: Chunk[];
  /** Successive POST /api/chat responses (one stream per request), e.g. pause then resume. */
  chatSequence?: Chunk[][];
  /** Respond to POST /api/chat with this status instead of streaming. */
  chatStatus?: { status: number; detail: string };
  threads?: unknown[];
  /** GET /api/profiles/sample fails with a 500. */
  profileFails?: boolean;
  /** Recorded runs served by GET /api/replays (public). */
  replays?: boolean;
  /** The signed-in account has already entered the access code. */
  liveAccess?: boolean;
}

export function createFakeApi(options: FakeApiOptions = {}) {
  const requests: RecordedRequest[] = [];
  let liveAccess = options.liveAccess ?? false;
  const json = (data: unknown, status = 200, headers: Record<string, string> = {}) =>
    new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json", ...headers } });

  const fetchImpl: typeof fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    const method = (init?.method ?? "GET").toUpperCase();
    const headers = new Headers(init?.headers);
    let body: unknown = undefined;
    if (typeof init?.body === "string") body = JSON.parse(init.body);
    requests.push({ method, path: url.pathname, headers, body });

    if (url.pathname === "/api/examples")
      return json({ questions: ["Why did revenue drop in March 2025?", "Which category returns most?"] });
    if (url.pathname === "/api/profiles/sample") {
      if (options.profileFails) return json({ detail: "down" }, 500);
      return json(SAMPLE_PROFILE);
    }
    if (url.pathname === "/api/replays") return json({ replays: options.replays ? [REPLAY_SUMMARY] : [] });
    if (url.pathname === `/api/replays/${REPLAY_SUMMARY.id}` && options.replays)
      return json({ ...REPLAY_SUMMARY, runs: [replayRun] });
    if (url.pathname === "/api/suggestions" && method === "POST") return new Response(null, { status: 204 });
    const signedIn = headers.get("authorization") === `Bearer ${CLERK_TOKEN}`;
    const authed = ["/api/me", "/api/access", "/api/threads", "/api/chat"].includes(url.pathname);
    if (authed && !signedIn) return json({ detail: "Sign in to continue." }, 401);
    if (url.pathname === "/api/me")
      return json({ user_id: "u_0123456789abcdef01234567", live_access: liveAccess, live_runs_enabled: true });
    if (url.pathname === "/api/access" && method === "POST") {
      if ((body as { code?: string }).code !== ACCESS_CODE) return json({ detail: "Invalid access code." }, 401);
      liveAccess = true;
      return json({ live_access: true });
    }
    if (url.pathname === "/api/threads" && method === "GET") return json({ threads: options.threads ?? [] });
    if (url.pathname === "/api/chat" && method === "POST") {
      if (!liveAccess) return json({ detail: "Enter the access code to run live questions." }, 403);
      if (options.chatStatus) return json({ detail: options.chatStatus.detail }, options.chatStatus.status);
      const next = options.chatSequence?.shift();
      return new Response(sseBody(next ?? options.chat ?? realRun), {
        status: 200,
        headers: { "content-type": "text/event-stream", "x-vercel-ai-ui-message-stream": "v1" },
      });
    }
    if (/\/artifacts\//.test(url.pathname))
      // plain bytes, like a real server (jsdom's Blob cannot be wrapped in a Response)
      return new Response(new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), {
        status: 200,
        headers: { "content-type": "image/png" },
      });
    return json({ detail: "not found" }, 404);
  };

  return { fetchImpl, requests };
}
