"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { MenuIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { getToken } from "@/lib/auth";
import { API_BASE_URL } from "@/lib/config";
import type { AnalystMessage } from "@/lib/types";
import { ArtifactPanel } from "./artifact-panel";
import { AssistantTurn, organize } from "./assistant-turn";

interface ChatSessionProps {
  threadId: string;
  initialMessages: AnalystMessage[];
  signedIn: boolean;
  examples: string[];
  onNeedSignIn: (reason?: string) => void;
  onTurnFinished: () => void;
  onOpenMenu: () => void;
  /** Injected in tests; the browser's fetch otherwise. */
  fetchImpl?: typeof fetch;
}

const AUTH_PROBLEM = /access token|expired|Missing access/i;

/** The server answers errors with {"detail": "..."}; the SDK hands us that raw text. */
export function friendlyError(error: Error): { message: string; authProblem: boolean } {
  let message = error.message;
  try {
    const parsed = JSON.parse(message) as { detail?: unknown };
    if (typeof parsed.detail === "string") message = parsed.detail;
  } catch {
    /* plain text */
  }
  if (/failed to fetch|networkerror|load failed/i.test(message))
    message = "Can't reach the server. Check your connection and try again.";
  return { message, authProblem: AUTH_PROBLEM.test(message) };
}

export function ChatSession({
  threadId,
  initialMessages,
  signedIn,
  examples,
  onNeedSignIn,
  onTurnFinished,
  onOpenMenu,
  fetchImpl,
}: ChatSessionProps) {
  const transport = useMemo(
    () =>
      new DefaultChatTransport<AnalystMessage>({
        api: `${API_BASE_URL}/api/chat`,
        fetch: fetchImpl,
        headers: () => {
          const token = getToken();
          return token ? { Authorization: `Bearer ${token}` } : ({} as Record<string, string>);
        },
        // The server keeps the conversation (checkpointer); sending only the newest message keeps
        // requests small and means a tampered client history cannot change what the agent sees.
        prepareSendMessagesRequest: ({ id, messages, trigger, headers }) => ({
          body: { id, messages: messages.slice(-1), trigger },
          headers,
        }),
      }),
    [fetchImpl],
  );

  const { messages, sendMessage, status, stop, error, clearError } = useChat<AnalystMessage>({
    id: threadId,
    messages: initialMessages,
    transport,
    onFinish: () => onTurnFinished(),
  });

  const busy = status === "submitted" || status === "streaming";
  // A question typed before signing in waits here until the access code is accepted.
  const pendingQuestion = useRef<string | null>(null);
  const [filesOpen, setFilesOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const failure = error ? friendlyError(error) : null;

  const send = useCallback(
    (text: string) => {
      if (busy) return;
      if (!signedIn) {
        pendingQuestion.current = text;
        onNeedSignIn();
        return;
      }
      try {
        window.history.replaceState(null, "", `?t=${threadId}`);
      } catch {
        /* URL is cosmetic */
      }
      clearError();
      void sendMessage({ text });
    },
    [busy, signedIn, threadId, onNeedSignIn, clearError, sendMessage],
  );

  // ...and is sent as soon as the access code is accepted.
  useEffect(() => {
    if (signedIn && pendingQuestion.current) {
      const text = pendingQuestion.current;
      pendingQuestion.current = null;
      send(text);
    }
  }, [signedIn, send]);

  // An expired or rejected token: ask for the code again instead of showing a dead error.
  const handledError = useRef<Error | null>(null);
  useEffect(() => {
    if (error && failure?.authProblem && handledError.current !== error) {
      handledError.current = error;
      onNeedSignIn("Your session ended. Enter the access code to continue.");
    }
  }, [error, failure, onNeedSignIn]);

  // Files of the newest answer that produced any, unless the reader picked another turn.
  const withFiles = messages.filter(
    (m) => m.role === "assistant" && organize(m).artifacts.length + (organize(m).run ? 1 : 0) > 0,
  );
  const shown =
    withFiles.find((m) => m.id === selectedId) ?? withFiles[withFiles.length - 1] ?? null;
  const panel = shown ? organize(shown) : null;

  const lastAssistantId = [...messages].reverse().find((m) => m.role === "assistant")?.id;
  const empty = messages.length === 0;

  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      <section className="flex min-w-0 flex-1 flex-col" aria-label="Conversation">
        <header className="flex items-center gap-2 border-b px-3 py-2 md:hidden">
          <Button variant="ghost" size="icon-sm" onClick={onOpenMenu} aria-label="Open menu">
            <MenuIcon />
          </Button>
          <span className="marked text-sm font-semibold">SandboxAnalyst</span>
        </header>

        <Conversation className="min-h-0 flex-1">
          <ConversationContent className="mx-auto w-full max-w-[46rem] gap-0 px-5 py-8 md:py-12">
            {empty ? (
              <EmptyState examples={examples} onPick={send} />
            ) : (
              messages.map((message, index) => {
                if (message.role === "user") {
                  const text = message.parts.map((p) => (p.type === "text" ? p.text : "")).join("");
                  return (
                    <h2
                      key={message.id}
                      className={
                        index === 0
                          ? "pb-5 text-xl font-semibold tracking-tight text-balance"
                          : "mt-10 border-t pt-8 pb-5 text-xl font-semibold tracking-tight text-balance"
                      }
                    >
                      {text}
                    </h2>
                  );
                }
                return (
                  <AssistantTurn
                    key={message.id}
                    message={message}
                    streaming={busy && message.id === lastAssistantId}
                    selected={shown?.id === message.id}
                    onShowFiles={() => {
                      setSelectedId(message.id);
                      setFilesOpen(true);
                    }}
                  />
                );
              })
            )}
            {status === "submitted" && messages[messages.length - 1]?.role === "user" ? (
              <p className="pt-2 text-sm text-muted-foreground" role="status">
                Starting…
              </p>
            ) : null}
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>

        <div className="px-5 pb-5">
          <div className="mx-auto grid w-full max-w-[46rem] gap-2">
            {failure ? (
              <div
                role="alert"
                className="flex items-start justify-between gap-3 rounded-sm border border-destructive/40 px-3 py-2 text-sm"
              >
                <span className="text-destructive">{failure.message}</span>
                <Button variant="ghost" size="xs" onClick={() => clearError()}>
                  Dismiss
                </Button>
              </div>
            ) : null}
            <PromptInput
              onSubmit={({ text }) => {
                const value = text.trim();
                if (value) send(value);
              }}
              className="rounded-sm border bg-card"
            >
              <PromptInputBody>
                <PromptInputTextarea
                  placeholder={
                    signedIn ? "Ask about revenue, customers, returns…" : "Ask a question (you will be asked for the access code)"
                  }
                  maxLength={2000}
                  aria-label="Your question"
                />
              </PromptInputBody>
              <PromptInputFooter>
                <span className="text-xs text-muted-foreground">Enter to send. Shift+Enter for a new line.</span>
                <PromptInputSubmit status={status} onStop={stop} />
              </PromptInputFooter>
            </PromptInput>
          </div>
        </div>
      </section>

      {panel ? (
        <aside className="hidden w-[26rem] shrink-0 border-l bg-sidebar/40 xl:block" aria-label="Files and run details">
          <ArtifactPanel artifacts={panel.artifacts} run={panel.run} />
        </aside>
      ) : null}

      <Dialog open={filesOpen && panel !== null} onOpenChange={setFilesOpen}>
        <DialogContent className="h-[85dvh] max-w-2xl gap-0 overflow-hidden p-0 xl:hidden">
          <DialogTitle className="sr-only">Files and run details</DialogTitle>
          <DialogDescription className="sr-only">Charts, tables and the report for this answer</DialogDescription>
          {panel ? <ArtifactPanel artifacts={panel.artifacts} run={panel.run} onClose={() => setFilesOpen(false)} /> : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function EmptyState({ examples, onPick }: { examples: string[]; onPick: (q: string) => void }) {
  return (
    <div className="py-4 md:py-10">
      <h1 className="max-w-[22ch] text-3xl font-semibold tracking-tight text-balance">
        Ask a question about the shop&apos;s data.
      </h1>
      <p className="mt-3 max-w-[58ch] leading-7 text-muted-foreground">
        An analyst agent plans the work, queries the database read-only, analyses the result in an
        isolated sandbox, and shows every step it took, so you can check the numbers yourself.
      </p>
      <ul className="mt-8 divide-y border-y" aria-label="Example questions">
        {examples.map((question) => (
          <li key={question}>
            <button
              onClick={() => onPick(question)}
              className="w-full px-1 py-3 text-left text-[15px] leading-6 hover:bg-muted/60"
            >
              {question}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
