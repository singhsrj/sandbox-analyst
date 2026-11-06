/**
 * Rebuild chat messages from stored UI-stream chunks. The server saves every turn as the chunks the
 * browser originally received, so history, replay and live streaming all share one code path:
 * the AI SDK's own reducer (`readUIMessageStream`).
 *
 * A run paused for human approval is continued by a later run (`summary.resumes`). Live, the
 * browser appends that run to the same assistant message; here we do the same by feeding both
 * runs' chunks through the reducer as one stream.
 */
import { readUIMessageStream, type UIMessageChunk } from "ai";
import type { AnalystMessage, StoredRun } from "./types";

export async function chunksToMessage(
  chunks: Array<Record<string, unknown>>,
): Promise<AnalystMessage | null> {
  const stream = new ReadableStream<UIMessageChunk>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk as UIMessageChunk);
      controller.close();
    },
  });
  let last: AnalystMessage | null = null;
  for await (const snapshot of readUIMessageStream<AnalystMessage>({ stream })) last = snapshot;
  return last;
}

export async function runsToMessages(runs: StoredRun[]): Promise<AnalystMessage[]> {
  // Group each run with the runs that resumed it.
  const turns: { first: StoredRun; chunks: Array<Record<string, unknown>> }[] = [];
  for (const run of runs) {
    const previous = turns[turns.length - 1];
    if (run.summary?.resumes && previous) previous.chunks = [...previous.chunks, ...run.chunks];
    else turns.push({ first: run, chunks: [...run.chunks] });
  }

  const messages: AnalystMessage[] = [];
  for (const { first, chunks } of turns) {
    messages.push({
      id: `user-${first.run_id}`,
      role: "user",
      parts: [{ type: "text", text: first.question }],
    });
    const assistant = await chunksToMessage(chunks);
    if (assistant) messages.push({ ...assistant, id: `assistant-${first.run_id}` });
  }
  return messages;
}
