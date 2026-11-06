// Mock API for looking at the UI without a model: node e2e/mock-api.mjs [port]
//
// It serves a REAL earlier agent run: the recorded tool steps (test-fixtures/chunks.json), the real
// answer/report/charts/CSV that a model produced (e2e/mock-assets), and the real schema.
// Used for visual review and for the browser smoke test when the live stack is unavailable.
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import path from "node:path";

const PORT = Number(process.argv[2] ?? 8010);
const ORIGINS = new Set(["http://localhost:3100", "http://127.0.0.1:3100"]);
const here = import.meta.dirname;
const asset = (name) => readFileSync(path.join(here, "mock-assets", name));
const fixture = JSON.parse(readFileSync(path.join(here, "..", "test-fixtures", "chunks.json"), "utf-8"));
const schema = JSON.parse(readFileSync(path.join(here, "..", "test-fixtures", "schema.json"), "utf-8"));
const ANSWER = asset("answer.md").toString("utf-8");
const CODE = "demo";
const TOKEN = "mock-token.mock-signature";

const FILES = [
  { name: "daily_revenue_march_2025.png", mime: "image/png" },
  { name: "monthly_revenue_by_region.png", mime: "image/png" },
  { name: "march_vs_feb_revenue_by_region.csv", mime: "text/csv" },
  { name: "report.md", mime: "text/plain" },
].map((f) => ({ ...f, size: asset(f.name).length, url: `/api/threads/__THREAD__/artifacts/${f.name}` }));

const threads = new Map(); // id -> { title, runs[] }

function buildChunks(threadId) {
  const out = [];
  let textDone = false;
  for (const chunk of fixture.real_run) {
    if (chunk.type === "text-start" || chunk.type === "text-end") continue;
    if (chunk.type === "text-delta") {
      if (!textDone) {
        out.push({ type: "text-start", id: "text-final" }, { type: "text-delta", id: "text-final", delta: ANSWER }, { type: "text-end", id: "text-final" });
        textDone = true;
      }
      continue;
    }
    if (chunk.type === "data-artifacts") {
      out.push({ ...chunk, data: { items: FILES.map((f) => ({ ...f, url: f.url.replace("__THREAD__", threadId) })) } });
      continue;
    }
    if (chunk.type === "data-run") {
      out.push({ ...chunk, data: { ...chunk.data, seconds: 48.3, sql_queries: 3, trace_url: "https://cloud.langfuse.com/project/demo/traces/abc", usage: { ...chunk.data.usage, total_tokens: 263954, input_tokens: 258100, output_tokens: 5854, llm_calls: 17 } } });
      continue;
    }
    out.push(chunk);
  }
  return out;
}

const send = (res, status, body, extra = {}) => {
  res.writeHead(status, { "content-type": "application/json", ...extra });
  res.end(JSON.stringify(body));
};

createServer(async (req, res) => {
  const origin = req.headers.origin;
  const cors = origin && ORIGINS.has(origin)
    ? { "access-control-allow-origin": origin, "access-control-allow-headers": "authorization,content-type", "access-control-allow-methods": "GET,POST,DELETE", vary: "Origin" }
    : {};
  if (req.method === "OPTIONS") { res.writeHead(204, cors); return res.end(); }
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const body = await new Promise((resolve) => { let d = ""; req.on("data", (c) => (d += c)); req.on("end", () => resolve(d ? JSON.parse(d) : null)); });
  const authed = req.headers.authorization === `Bearer ${TOKEN}`;

  if (url.pathname === "/api/health") return send(res, 200, { status: "ok", mock: true }, cors);
  if (url.pathname === "/api/examples")
    return send(res, 200, { questions: [
      "Why did revenue drop in March 2025, and which regions were affected?",
      "Which product category has the highest return rate, and what do its reviews say?",
      "Which customer segment churns the most, and how large is the gap?",
      "How does revenue seasonality look across 2024 and 2025?",
      "Which marketing channel brings in the most valuable customers?",
      "What will our revenue be in 2027?",
    ] }, cors);
  if (url.pathname === "/api/schema") return send(res, 200, schema, cors);
  if (url.pathname === "/api/session")
    return body?.code === CODE
      ? send(res, 200, { token: TOKEN, expires_at: Math.floor(Date.now() / 1000) + 7200, client_id: body.client_id ?? "mock-client-0001" }, cors)
      : send(res, 401, { detail: "Invalid access code." }, cors);

  if (!authed && url.pathname.startsWith("/api/")) return send(res, 401, { detail: "Missing access token." }, cors);

  if (url.pathname === "/api/threads" && req.method === "GET")
    return send(res, 200, { threads: [...threads].map(([id, t]) => ({ thread_id: id, title: t.title, created_at: t.at, updated_at: t.at })).reverse() }, cors);

  const art = /^\/api\/threads\/([^/]+)\/artifacts\/([^/]+)$/.exec(url.pathname);
  if (art) {
    const file = FILES.find((f) => f.name === art[2]);
    if (!file) return send(res, 404, { detail: "Not found." }, cors);
    res.writeHead(200, { "content-type": file.mime, ...cors });
    return res.end(asset(file.name));
  }
  const one = /^\/api\/threads\/([^/]+)$/.exec(url.pathname);
  if (one && req.method === "GET") {
    const t = threads.get(one[1]);
    return t ? send(res, 200, { thread: { thread_id: one[1], title: t.title, created_at: t.at, updated_at: t.at }, runs: t.runs }, cors) : send(res, 404, { detail: "Thread not found." }, cors);
  }
  if (one && req.method === "DELETE") { threads.delete(one[1]); res.writeHead(204, cors); return res.end(); }

  if (url.pathname === "/api/chat" && req.method === "POST") {
    const question = body.messages.at(-1).parts?.map((p) => p.text).join("") ?? "";
    const chunks = buildChunks(body.id);
    res.writeHead(200, { "content-type": "text/event-stream", "x-vercel-ai-ui-message-stream": "v1", "cache-control": "no-cache", ...cors });
    for (const chunk of chunks) {
      res.write(`data: ${JSON.stringify(chunk)}\n\n`);
      await new Promise((r) => setTimeout(r, chunk.type.startsWith("tool-output") ? 700 : 120));
    }
    res.write("data: [DONE]\n\n");
    res.end();
    const t = threads.get(body.id) ?? { title: question.slice(0, 80), at: new Date().toISOString(), runs: [] };
    t.runs.push({ run_id: `r${t.runs.length + 1}`, question, status: "ok", model: "mock", final_answer: ANSWER, chunks, created_at: new Date().toISOString() });
    threads.set(body.id, t);
    return;
  }
  send(res, 404, { detail: "not found" }, cors);
}).listen(PORT, () => console.log(`mock API on http://localhost:${PORT} (access code: ${CODE})`));
