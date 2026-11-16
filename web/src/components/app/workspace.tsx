"use client";

import { nanoid } from "nanoid";
import type { GroupImperativeHandle } from "react-resizable-panels";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useSession } from "@/hooks/use-session";
import {
  AuthRequiredError,
  deleteThread,
  getExamples,
  getReplay,
  getThread,
  listReplays,
  listThreads,
} from "@/lib/api";
import { THREAD_ID_PATTERN } from "@/lib/config";
import { loadLayout, saveLayout } from "@/lib/panel-layout";
import { SAMPLE_DATASET } from "@/lib/profile";
import { runsToMessages } from "@/lib/replay";
import type { AnalystMessage, ReplaySummary, ThreadSummary } from "@/lib/types";
import { AccessDialog } from "./access-dialog";
import { ChatSession } from "./chat-session";
import { DataProfilePanel } from "./data-profile-panel";
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

const PANELS_CLOSED = ["sidebar", "chat"];
const PANELS_OPEN = ["sidebar", "profile", "chat"];
const noSubscribe = () => () => undefined;

export function Workspace({ fetchImpl }: { fetchImpl?: typeof fetch }) {
  const { signedIn, liveAccess, accessKnown, ready, openSignIn, unlock } = useSession();
  const [opened, setOpened] = useState<Opened | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [examples, setExamples] = useState<string[]>(FALLBACK_EXAMPLES);
  const [replays, setReplays] = useState<ReplaySummary[]>([]);
  const [signInOpen, setSignInOpen] = useState(false);
  const [signInReason, setSignInReason] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const isDesktop = useMediaQuery("(min-width: 768px)");
  // The resizable layout depends on widths saved in this browser, so it is drawn only after
  // hydration; the server's HTML cannot know them.
  const hydrated = useSyncExternalStore(noSubscribe, () => true, () => false);
  const groupRef = useRef<GroupImperativeHandle | null>(null);
  const [initialLayout] = useState(() => loadLayout(false, PANELS_CLOSED));
  // Panels added after mount get default widths, so apply the remembered ones on open/close.
  // The new panel registers with the group a frame or two after it renders, so wait for it.
  useEffect(() => {
    const ids = profileOpen ? PANELS_OPEN : PANELS_CLOSED;
    const saved = loadLayout(profileOpen, ids);
    if (!saved) return;
    let frame = 0;
    let tries = 0;
    const apply = () => {
      const group = groupRef.current;
      const ready = group && Object.keys(group.getLayout()).sort().join() === [...ids].sort().join();
      if (ready) {
        try {
          group.setLayout(saved);
        } catch {
          /* keep the default widths */
        }
      } else if (tries++ < 10) frame = requestAnimationFrame(apply);
    };
    frame = requestAnimationFrame(apply);
    return () => cancelAnimationFrame(frame);
  }, [profileOpen, hydrated, isDesktop]);

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

  // Public data: examples and recorded runs never need an access code.
  useEffect(() => {
    getExamples()
      .then(setExamples)
      .catch(() => undefined); // the built-in examples stay
    listReplays()
      .then(setReplays)
      .catch(() => undefined); // replay mode is optional
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
      profileOpen={profileOpen}
      onToggleProfile={() => {
        setMenuOpen(false);
        setProfileOpen((open) => !open);
      }}
      signedIn={signedIn}
      liveAccess={liveAccess}
      onRequestSignIn={openSignIn}
      onRequestAccess={() => requestSignIn()}
      onClose={onClose}
    />
  );

  const chat = (
    <main className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
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
  );
  const profile = <DataProfilePanel dataset={SAMPLE_DATASET} onClose={() => setProfileOpen(false)} />;

  return (
    <div className="flex h-dvh w-full overflow-hidden">
      {!hydrated ? (
        <p className="p-6 text-sm text-muted-foreground" role="status">
          Loading…
        </p>
      ) : isDesktop ? (
        // Sidebar | data profile (when open) | chat, each divider draggable; widths are remembered.
        <ResizablePanelGroup
          orientation="horizontal"
          id="workspace"
          groupRef={groupRef}
          defaultLayout={initialLayout}
          onLayoutChanged={saveLayout}
        >
          <ResizablePanel id="sidebar" defaultSize="20" minSize={220} maxSize="35">
            {sidebar()}
          </ResizablePanel>
          <ResizableHandle />
          {profileOpen ? (
            <>
              <ResizablePanel id="profile" defaultSize="38" minSize={300}>
                {profile}
              </ResizablePanel>
              <ResizableHandle />
            </>
          ) : null}
          <ResizablePanel id="chat" minSize={360}>
            {chat}
          </ResizablePanel>
        </ResizablePanelGroup>
      ) : (
        <>
          {chat}
          {profileOpen ? (
            <div className="fixed inset-0 z-30" role="dialog" aria-modal="true" aria-label="Data profile">
              {profile}
            </div>
          ) : null}
        </>
      )}

      {menuOpen && !isDesktop ? (
        <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Menu">
          <button className="absolute inset-0 bg-black/40" aria-label="Close menu" onClick={() => setMenuOpen(false)} />
          <aside className="relative h-full w-[85%] max-w-xs border-r shadow-lg">{sidebar(() => setMenuOpen(false))}</aside>
        </div>
      ) : null}

      <AccessDialog
        open={signInOpen}
        onOpenChange={setSignInOpen}
        onSubmit={unlock}
        reason={signInReason}
      />
    </div>
  );
}
