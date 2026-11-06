import { describe, expect, it } from "vitest";
import fixture from "../../../test-fixtures/chunks.json";
import { ApprovalBook, awaitingApproval, readyToResume, unsentAnswers } from "../approvals";
import { chunksToMessage } from "../replay";
import type { AnalystMessage } from "../types";

type Chunk = Record<string, unknown>;
const runs = fixture as unknown as Record<string, Chunk[]>;

async function pausedMessage(): Promise<AnalystMessage> {
  return (await chunksToMessage(runs.approval_paused))!;
}

/** What `addToolApprovalResponse` does to the message. */
function answer(message: AnalystMessage, approved: boolean, reason?: string): AnalystMessage {
  return {
    ...message,
    parts: message.parts.map((part) =>
      "approval" in part && part.state === "approval-requested"
        ? ({
            ...part,
            state: "approval-responded",
            approval: { ...part.approval, approved, reason },
          } as unknown as typeof part)
        : part,
    ),
  };
}

const user: AnalystMessage = { id: "u", role: "user", parts: [{ type: "text", text: "q" }] };

describe("approval bookkeeping", () => {
  it("a paused message is waiting and not ready to resume until answered", async () => {
    const messages = [user, await pausedMessage()];
    expect(awaitingApproval(messages)).toBe(true);
    expect(readyToResume(messages, new Set())).toBe(false);
  });

  it("once answered, the answer is sent exactly once", async () => {
    const messages = [user, answer(await pausedMessage(), true)];
    const book = new ApprovalBook();
    expect(awaitingApproval(messages)).toBe(false);
    expect(book.shouldResume(messages)).toBe(true);
    expect(book.takeAnswers(messages)).toEqual([{ id: "approval-1", approved: true }]);
    expect(book.shouldResume(messages)).toBe(false); // no second resume for the same answer
    expect(book.takeAnswers(messages)).toEqual([]);
  });

  it("an edited query travels with the approval, never with a rejection", async () => {
    const approved = [user, answer(await pausedMessage(), true)];
    const edits = new Map([["approval-1", "SELECT 1"]]);
    expect(unsentAnswers(approved, new Set(), edits)).toEqual([
      { id: "approval-1", approved: true, edited_query: "SELECT 1" },
    ]);
    const rejected = [user, answer(await pausedMessage(), false, "too big")];
    expect(unsentAnswers(rejected, new Set(), edits)).toEqual([
      { id: "approval-1", approved: false, reason: "too big" },
    ]);
  });

  it("a finished message or a user message never triggers a resume", async () => {
    const done = (await chunksToMessage(runs.real_run))!;
    expect(readyToResume([user, done], new Set())).toBe(false);
    expect(readyToResume([user], new Set())).toBe(false);
  });

  it("strict mode is remembered for the next question", () => {
    const book = new ApprovalBook();
    expect(book.strict).toBe(false);
    book.setStrict(true);
    expect(book.strict).toBe(true);
  });
});
