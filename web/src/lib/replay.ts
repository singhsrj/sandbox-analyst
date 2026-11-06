/**
 * Rebuild chat messages from stored UI-stream chunks. The server saves every turn as the chunks the
 * browser originally received, so history, replay and live streaming all share one code path:
 * the AI SDK's own reducer (`readUIMessageStream`).
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
  const messages: AnalystMessage[] = [];
  for (const run of runs) {
    messages.push({
      id: `user-${run.run_id}`,
      role: "user",
      parts: [{ type: "text", text: run.question }],
    });
    const assistant = await chunksToMessage(run.chunks);
    if (assistant) messages.push({ ...assistant, id: `assistant-${run.run_id}` });
  }
  return messages;
}
