/**
 * A fake backend for component tests: same URLs, same wire formats as api/app/api/routes.py,
 * and the SSE body is the REAL recorded agent run (see scripts/dump_chunks.py).
 */
import fixture from "../../test-fixtures/chunks.json";

type Chunk = Record<string, unknown>;
const runs = fixture as unknown as Record<string, Chunk[]>;
export const realRun = runs.real_run;
export const toolErrorRun = runs.tool_error_run;
export const approvalPaused = runs.approval_paused;
export const approvalApproved = runs.approval_resumed_approved;
export const approvalRejected = runs.approval_resumed_rejected;

export const ACCESS_CODE = "open-sesame";
export const TOKEN = "tok-abc.sig-xyz";

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

export interface FakeApiOptions {
  /** Chunks streamed for POST /api/chat. */
  chat?: Chunk[];
  /** Successive POST /api/chat responses (one stream per request), e.g. pause then resume. */
  chatSequence?: Chunk[][];
  /** Respond to POST /api/chat with this status instead of streaming. */
  chatStatus?: { status: number; detail: string };
  threads?: unknown[];
  schemaFails?: boolean;
}

export function createFakeApi(options: FakeApiOptions = {}) {
  const requests: RecordedRequest[] = [];
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
    if (url.pathname === "/api/schema") {
      if (options.schemaFails) return json({ detail: "down" }, 500);
      return json({
        tables: [
          {
            name: "orders",
            approx_rows: 50021,
            description: "One row per order.",
            columns: [{ name: "status", type: "text", nullable: false, note: "delivered | cancelled" }],
          },
        ],
      });
    }
    if (url.pathname === "/api/session" && method === "POST") {
      const sent = (body as { code?: string }).code;
      if (sent !== ACCESS_CODE) return json({ detail: "Invalid access code." }, 401);
      return json({ token: TOKEN, expires_at: Math.floor(Date.now() / 1000) + 7200, client_id: "client-test-0001" });
    }
    if (url.pathname === "/api/threads" && method === "GET") return json({ threads: options.threads ?? [] });
    if (url.pathname === "/api/chat" && method === "POST") {
      if (headers.get("authorization") !== `Bearer ${TOKEN}`) return json({ detail: "Missing access token." }, 401);
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
