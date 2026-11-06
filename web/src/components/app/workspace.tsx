"use client";

import { nanoid } from "nanoid";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "@/hooks/use-session";
import {
  AuthRequiredError,
  deleteThread,
  getExamples,
  getSchema,
  getThread,
  listThreads,
} from "@/lib/api";
import { THREAD_ID_PATTERN } from "@/lib/config";
import { runsToMessages } from "@/lib/replay";
import type { AnalystMessage, SchemaTable, ThreadSummary } from "@/lib/types";
import { AccessDialog } from "./access-dialog";
import { ChatSession } from "./chat-session";
import { Sidebar } from "./sidebar";

const FALLBACK_EXAMPLES = [
  "Why did revenue drop in March 2025, and which regions were affected?",
  "Which product category has the highest return rate?",
  "Which customer segment churns the most?",
];

interface Opened {
  id: string;
  messages: AnalystMessage[];
}

export function Workspace({ fetchImpl }: { fetchImpl?: typeof fetch }) {
  const { signedIn, ready, signIn, signOut } = useSession();
  const [opened, setOpened] = useState<Opened | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [schema, setSchema] = useState<SchemaTable[] | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [examples, setExamples] = useState<string[]>(FALLBACK_EXAMPLES);
  const [signInOpen, setSignInOpen] = useState(false);
  const [signInReason, setSignInReason] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  const startNew = useCallback(() => {
    setLoadError(null);
    setOpened({ id: nanoid(16), messages: [] });
    setMenuOpen(false);
    try {
      window.history.replaceState(null, "", window.location.pathname);
    } catch {
      /* cosmetic */
    }
  }, []);

  const openThread = useCallback(
    async (id: string) => {
      setMenuOpen(false);
      setLoadError(null);
      try {
        const { runs } = await getThread(id);
        setOpened({ id, messages: await runsToMessages(runs) });
        window.history.replaceState(null, "", `?t=${id}`);
      } catch (err) {
        if (err instanceof AuthRequiredError) signOut();
        setLoadError(err instanceof Error ? err.message : "Could not open that conversation.");
        startNew();
      }
    },
    [signOut, startNew],
  );

  const refreshThreads = useCallback(async () => {
    try {
      const list = await listThreads();
      setThreads(list);
    } catch (err) {
      if (err instanceof AuthRequiredError) signOut();
    }
  }, [signOut]);

  // Public data: examples and the schema never need an access code.
  useEffect(() => {
    getExamples()
      .then(setExamples)
      .catch(() => undefined); // the built-in examples stay
    getSchema()
      .then(setSchema)
      .catch(() => setSchemaError("Could not load the schema. Is the API running?"));
  }, []);

  // First load: reopen the thread named in the URL if we can, otherwise start a new one.
  // (Deferred past an await so state is not set synchronously inside the effect.)
  const booted = useRef(false);
  useEffect(() => {
    if (!ready || booted.current) return;
    booted.current = true;
    void (async () => {
      await Promise.resolve();
      const wanted = new URLSearchParams(window.location.search).get("t");
      if (wanted && THREAD_ID_PATTERN.test(wanted) && signedIn) await openThread(wanted);
      else startNew();
    })();
  }, [ready, signedIn, openThread, startNew]);

  useEffect(() => {
    if (!signedIn) return;
    let cancelled = false;
    listThreads()
      .then((list) => {
        if (!cancelled) setThreads(list);
      })
      .catch((err: unknown) => {
        if (err instanceof AuthRequiredError) signOut();
      });
    return () => {
      cancelled = true;
    };
  }, [signedIn, signOut]);

  const requestSignIn = useCallback((reason?: string) => {
    setSignInReason(reason ?? null);
    setSignInOpen(true);
  }, []);

  async function handleDelete(id: string) {
    if (!window.confirm("Delete this conversation and its files? This cannot be undone.")) return;
    try {
      await deleteThread(id);
      setThreads((current) => current.filter((t) => t.thread_id !== id));
      if (opened?.id === id) startNew();
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not delete that conversation.");
    }
  }

  const sidebar = (onClose?: () => void) => (
    <Sidebar
      threads={signedIn ? threads : []}
      activeThreadId={opened?.id ?? ""}
      onSelectThread={(id) => void openThread(id)}
      onNewThread={startNew}
      onDeleteThread={(id) => void handleDelete(id)}
      schema={schema}
      schemaError={schemaError}
      signedIn={signedIn}
      onRequestSignIn={() => requestSignIn()}
      onSignOut={() => {
        signOut();
        startNew();
      }}
      onClose={onClose}
    />
  );

  return (
    <div className="flex h-dvh w-full overflow-hidden">
      <aside className="hidden w-72 shrink-0 border-r md:block">{sidebar()}</aside>

      {menuOpen ? (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button className="absolute inset-0 bg-black/40" aria-label="Close menu" onClick={() => setMenuOpen(false)} />
          <aside className="relative h-full w-[85%] max-w-xs border-r shadow-lg">{sidebar(() => setMenuOpen(false))}</aside>
        </div>
      ) : null}

      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        {loadError ? (
          <p role="alert" className="border-b px-5 py-2 text-sm text-destructive">
            {loadError}
          </p>
        ) : null}
        {opened ? (
          <ChatSession
            key={opened.id}
            threadId={opened.id}
            initialMessages={opened.messages}
            signedIn={signedIn}
            examples={examples}
            onNeedSignIn={requestSignIn}
            onTurnFinished={() => void refreshThreads()}
            onOpenMenu={() => setMenuOpen(true)}
            fetchImpl={fetchImpl}
          />
        ) : (
          <p className="p-6 text-sm text-muted-foreground" role="status">
            Loading…
          </p>
        )}
      </main>

      <AccessDialog
        open={signInOpen}
        onOpenChange={setSignInOpen}
        onSubmit={signIn}
        reason={signInReason}
      />
    </div>
  );
}
