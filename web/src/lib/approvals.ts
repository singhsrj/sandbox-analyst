/**
 * Human approval on the client (ADR-022). The server pauses a run before a flagged query and streams
 * the AI SDK's own `tool-approval-request`; the card answers with `addToolApprovalResponse`, and once
 * every card in the message is answered we send ONE request that resumes the run.
 *
 * The SDK's approve/reject has no "edit", so edited SQL is kept here by approval id and sent next to
 * the decision. The server re-validates everything: ids must match what is actually pending, and an
 * edited query still goes through the SQL validator and the read-only database role.
 */
import { isToolUIPart } from "ai";
import type { AnalystMessage } from "./types";

export interface ApprovalAnswerBody {
  id: string;
  approved: boolean;
  reason?: string;
  edited_query?: string;
}

interface ApprovalLike {
  id: string;
  approved?: boolean;
  reason?: string;
}

function approvalParts(message: AnalystMessage | undefined) {
  if (!message || message.role !== "assistant") return [];
  return message.parts.filter(isToolUIPart).map((part) => ({
    state: part.state as string,
    approval: (part as { approval?: ApprovalLike }).approval,
  }));
}

/** True while the newest assistant message has a card nobody has answered yet. */
export function awaitingApproval(messages: AnalystMessage[]): boolean {
  return approvalParts(messages[messages.length - 1]).some((p) => p.state === "approval-requested");
}

/** Answered cards of the newest message that the server has not received yet. */
export function unsentAnswers(
  messages: AnalystMessage[],
  sent: ReadonlySet<string>,
  edits: ReadonlyMap<string, string>,
): ApprovalAnswerBody[] {
  return approvalParts(messages[messages.length - 1])
    .filter((p) => p.state === "approval-responded" && p.approval && !sent.has(p.approval.id))
    .map(({ approval }) => {
      const { id, approved = false, reason } = approval!;
      const edited = approved ? edits.get(id) : undefined;
      return {
        id,
        approved,
        ...(reason ? { reason } : {}),
        ...(edited ? { edited_query: edited } : {}),
      };
    });
}

/**
 * Per-conversation approval bookkeeping read by the chat transport when it builds a request:
 * which answers were already sent, which queries the reviewer edited, and strict mode.
 */
export class ApprovalBook {
  private readonly sent = new Set<string>();
  private readonly edits = new Map<string, string>();
  private strictMode = false;

  setStrict(value: boolean): void {
    this.strictMode = value;
  }

  get strict(): boolean {
    return this.strictMode;
  }

  recordEdit(approvalId: string, query: string): void {
    this.edits.set(approvalId, query);
  }

  /** The answers to send now (each answer is handed out once). */
  takeAnswers(messages: AnalystMessage[]): ApprovalAnswerBody[] {
    const answers = unsentAnswers(messages, this.sent, this.edits);
    answers.forEach((a) => this.sent.add(a.id));
    return answers;
  }

  shouldResume(messages: AnalystMessage[]): boolean {
    return readyToResume(messages, this.sent, this.edits);
  }
}

/** Resume once every card is answered and at least one answer is still unsent. */
export function readyToResume(
  messages: AnalystMessage[],
  sent: ReadonlySet<string>,
  edits: ReadonlyMap<string, string> = new Map(),
): boolean {
  return !awaitingApproval(messages) && unsentAnswers(messages, sent, edits).length > 0;
}
