"use client";

import { nanoid } from "nanoid";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "@/hooks/use-session";
import {
  AuthRequiredError,
  deleteThread,
  getExamples,
  getReplay,
  getSchema,
  getThread,
  listReplays,
  listThreads,
} from "@/lib/api";
import { THREAD_ID_PATTERN } from "@/lib/config";
import { runsToMessages } from "@/lib/replay";
import type { AnalystMessage, ReplaySummary, SchemaTable, ThreadSummary } from "@/lib/types";
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
  /** Set when this is a recorded run (read-only). */
  replay?: ReplaySummary;
}

const REPLAY_ID = /^[a-z0-9][a-z0-9-]{1,59}$/;

export function Workspace({ fetchImpl }: { fetchImpl?: typeof fetch }) {
  const { signedIn, liveAccess, accessKnown, ready, openSignIn, unlock } = useSession();
  const [opened, setOpened] = useState<Opened | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [schema, setSchema] = useState<SchemaTable[] | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [examples, setExamples] = useState<string[]>(FALLBACK_EXAMPLES);
  const [replays, setReplays] = useState<ReplaySummary[]>([]);
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
        setLoadError(err instanceof Error ? err.message : "Could not open that conversation.");
        startNew();
      }
    },
    [startNew],
  );

  const openReplay = useCallback(
    async (id: string) => {
      setMenuOpen(false);
      setLoadError(null);
      try {
        const replay = await getReplay(id);
        const { runs, ...summary } = replay;
        setOpened({ id: `replay-${id}`, messages: await runsToMessages(runs), replay: summary });
        window.history.replaceState(null, "", `?replay=${id}`);
      } catch (err) {
        setLoadError(err instanceof Error ? err.message : "Could not open that recorded run.");
        startNew();
      }
    },
    [startNew],
  );

  const refreshThreads = useCallback(async () => {
    try {
      setThreads(await listThreads());
    } catch {
      /* the list stays as it was; a 401 surfaces on the next action */
    }
  }, []);

  // Public data: examples and the schema never need an access code.
  useEffect(() => {
    getExamples()
      .then(setExamples)
      .catch(() => undefined); // the built-in examples stay
    listReplays()
      .then(setReplays)
      .catch(() => undefined); // replay mode is optional
    getSchema()
      .then(setSchema)
      .catch(() => setSchemaError("Could not load the schema. Is the API running?"));
  }, []);

  // First load: reopen the thread named in the URL if we can, otherwise start a new one.
  // (Deferred past an await so state is not set synchronously inside the effect.)
  // Only a saved conversation (?t=) waits for Clerk: it needs the account. A recorded run or a
  // new question opens at once, so the public parts work even if Clerk is slow or blocked.
  const booted = useRef(false);
  useEffect(() => {
    if (booted.current) return;
    const params = new URLSearchParams(window.location.search);
    const wanted = params.get("t");
    const replay = params.get("replay");
    const needsAccount = !(replay && REPLAY_ID.test(replay)) && wanted && THREAD_ID_PATTERN.test(wanted);
    if (needsAccount && !ready) return;
    booted.current = true;
    void (async () => {
      await Promise.resolve();
      if (replay && REPLAY_ID.test(replay)) await openReplay(replay);
      else if (needsAccount && wanted && signedIn) await openThread(wanted);
      else startNew();
    })();
  }, [ready, signedIn, openThread, openReplay, startNew]);

  useEffect(() => {
    if (!signedIn) return;
    let cancelled = false;
    listThreads()
      .then((list) => {
        if (!cancelled) setThreads(list);
      })
      .catch((err: unknown) => {
        if (!cancelled && !(err instanceof AuthRequiredError)) setThreads([]);
      });
    return () => {
      cancelled = true;
    };
  }, [signedIn]);

  // Signing out (Clerk's user menu) leaves the account's conversation on screen otherwise.
  const wasSignedIn = useRef(signedIn);
  useEffect(() => {
    if (wasSignedIn.current && !signedIn) {
      setThreads([]);
      startNew();
    }
    wasSignedIn.current = signedIn;
  }, [signedIn, startNew]);

  // Signed out, or the sign-in expired: Clerk's sign-in. Signed in without the code: the dialog.
  // A question asked while signed out waits; once the account is known to lack the code, the
  // dialog opens by itself, so one click on a question leads all the way to an answer.
  const [codeAfterSignIn, setCodeAfterSignIn] = useState(false);
  const requestSignIn = useCallback(
    (reason?: string) => {
      if (!signedIn || (reason && /sign in|expired/i.test(reason))) {
        setCodeAfterSignIn(true);
        openSignIn();
        return;
      }
      setSignInReason(reason ?? null);
      setSignInOpen(true);
    },
    [signedIn, openSignIn],
  );
  if (codeAfterSignIn && accessKnown) {
    // Adjusting state during render (React's pattern for reacting to a changed value).
    setCodeAfterSignIn(false);
    if (!liveAccess) {
      setSignInReason(null);
      setSignInOpen(true);
    }
  }

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
      liveAccess={liveAccess}
      onRequestSignIn={openSignIn}
      onRequestAccess={() => requestSignIn()}
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
            canRunLive={liveAccess}
            examples={examples}
            replay={opened.replay}
            replays={replays}
            onOpenReplay={(id) => void openReplay(id)}
            onExitReplay={startNew}
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
        onSubmit={unlock}
        reason={signInReason}
      />
    </div>
  );
}
