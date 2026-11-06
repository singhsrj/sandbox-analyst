/**
 * Contract test: the chunks our Python backend emits must satisfy the REAL `ai` package.
 * Fixtures are regenerated with `uv run python scripts/dump_chunks.py` from the backend adapter
 * (which replays a genuinely recorded agent run), so protocol drift fails here, not in a browser.
 */
import { asSchema, uiMessageChunkSchema, UI_MESSAGE_STREAM_HEADERS } from "ai";
import { describe, expect, it } from "vitest";
import fixture from "../../../test-fixtures/chunks.json";
import { chunksToMessage, runsToMessages } from "../replay";
import type { AnalystMessage } from "../types";

type Chunk = Record<string, unknown>;
const runs = fixture as unknown as Record<string, Chunk[]>;

describe("chunks emitted by the backend adapter", () => {
  const schema = asSchema(uiMessageChunkSchema);

  for (const [name, chunks] of Object.entries(runs)) {
    it(`${name}: every chunk validates against the ai package schema`, async () => {
      expect(chunks.length).toBeGreaterThan(5);
      for (const chunk of chunks) {
        const result = await schema.validate!(chunk);
        expect(result.success, JSON.stringify(chunk).slice(0, 200)).toBe(true);
      }
    });
  }

  it("uses the stream header the AI SDK client requires", () => {
    expect(UI_MESSAGE_STREAM_HEADERS["x-vercel-ai-ui-message-stream"]).toBe("v1");
  });
});

function toolParts(message: AnalystMessage) {
  return message.parts.filter((p) => p.type.startsWith("tool-"));
}

describe("replaying stored chunks into a message", () => {
  it("builds tool parts that finished with outputs, text, todos, artifacts and run info", async () => {
    const message = await chunksToMessage(runs.real_run);
    expect(message?.role).toBe("assistant");
    const tools = toolParts(message!);
    expect(tools.length).toBeGreaterThanOrEqual(3);
    for (const tool of tools) expect(tool).toHaveProperty("state", "output-available");

    const types = message!.parts.map((p) => p.type);
    expect(types).toContain("text");
    expect(types).toContain("data-todos");
    expect(types).toContain("data-artifacts");
    expect(types).toContain("data-run");
  });

  it("data parts with the same id update in place instead of duplicating", async () => {
    const message = await chunksToMessage(runs.real_run);
    const todos = message!.parts.filter((p) => p.type === "data-todos");
    expect(todos).toHaveLength(1); // the agent rewrote its todo list several times
  });

  it("a coalesced (stored) run reads back identically to the live one", async () => {
    const live = await chunksToMessage(runs.real_run);
    const stored = await chunksToMessage(runs.real_run_coalesced);
    expect(stored?.parts).toEqual(live?.parts);
  });

  it("tool failures become error states, and the stream error is surfaced", async () => {
    const message = await chunksToMessage(runs.tool_error_run);
    const failed = toolParts(message!)[0];
    expect(failed).toHaveProperty("state", "output-error");
    expect(failed).toHaveProperty("errorText", "Traceback: boom");
  });

  it("a paused run shows the query waiting for approval, with the server's reason", async () => {
    const message = await chunksToMessage(runs.approval_paused);
    const [sql] = toolParts(message!);
    expect(sql).toHaveProperty("state", "approval-requested");
    expect(sql).toHaveProperty("approval.id", "approval-1");
    expect(sql).toHaveProperty("approval.requestReason", expect.stringContaining("raw rows"));
  });

  it("paused + approved resume reads back as one message with the query's result", async () => {
    const message = await chunksToMessage([...runs.approval_paused, ...runs.approval_resumed_approved]);
    const [sql] = toolParts(message!);
    expect(sql).toHaveProperty("state", "output-available");
    expect(sql).toHaveProperty("approval.approved", true);
    expect(message!.id).toBe("msg-contract"); // the resume did not replace the message id
  });

  it("paused + rejected resume shows the query as denied, with the reviewer's reason", async () => {
    const message = await chunksToMessage([...runs.approval_paused, ...runs.approval_resumed_rejected]);
    const [sql] = toolParts(message!);
    expect(sql).toHaveProperty("state", "output-denied");
    expect(sql).toHaveProperty("approval.approved", false);
    expect(sql).toHaveProperty("approval.reason", "Too big");
  });

  it("history merges a resumed run into the turn it continued", async () => {
    const base = { status: "ok", model: "m", final_answer: "", created_at: "2026-01-01T00:00:00Z" };
    const messages = await runsToMessages([
      { ...base, run_id: "r1", question: "Dump orders?", status: "awaiting_approval", chunks: runs.approval_paused },
      { ...base, run_id: "r2", question: "Dump orders?", chunks: runs.approval_resumed_approved, summary: { resumes: true } },
      { ...base, run_id: "r3", question: "Next question", chunks: runs.real_run_coalesced },
    ]);
    expect(messages.map((m) => m.role)).toEqual(["user", "assistant", "user", "assistant"]);
    expect(toolParts(messages[1])[0]).toHaveProperty("state", "output-available");
    expect(messages[2].parts[0]).toEqual({ type: "text", text: "Next question" });
  });

  it("turns saved runs into alternating user and assistant messages", async () => {
    const messages = await runsToMessages([
      {
        run_id: "r1",
        question: "How many orders?",
        status: "ok",
        model: "m",
        final_answer: "",
        chunks: runs.real_run_coalesced,
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    expect(messages.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(messages[0].parts[0]).toEqual({ type: "text", text: "How many orders?" });
    expect(messages[1].id).toBe("assistant-r1");
  });
});
