"use client";

import { UserButton } from "@clerk/nextjs";
import { ChartColumnIcon, PlusIcon, Trash2Icon, XIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatRelative } from "@/lib/format";
import type { ThreadSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "./theme-toggle";

interface SidebarProps {
  threads: ThreadSummary[];
  activeThreadId: string;
  onSelectThread: (id: string) => void;
  onNewThread: () => void;
  onDeleteThread: (id: string) => void;
  /** The data profile panel is open beside the chat. */
  profileOpen: boolean;
  onToggleProfile: () => void;
  signedIn: boolean;
  /** Signed in and the access code entered. */
  liveAccess: boolean;
  onRequestSignIn: () => void;
  onRequestAccess: () => void;
  onClose?: () => void;
}

export function Sidebar(props: SidebarProps) {
  return (
    <nav aria-label="Workspace" className="flex h-full min-h-0 flex-col bg-sidebar text-sidebar-foreground">
      <div className="flex items-center justify-between px-4 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <span className="marked text-base font-semibold tracking-tight">SandboxAnalyst</span>
        </div>
        {props.onClose ? (
          <Button variant="ghost" size="icon-sm" onClick={props.onClose} aria-label="Close menu">
            <XIcon />
          </Button>
        ) : null}
      </div>

      <div className="grid gap-1.5 px-3 pb-3">
        <Button variant="outline" className="w-full justify-start" onClick={props.onNewThread}>
          <PlusIcon aria-hidden="true" />
          New question
        </Button>
        <Button
          variant="ghost"
          className="w-full justify-start aria-pressed:bg-sidebar-accent aria-pressed:font-medium"
          onClick={props.onToggleProfile}
          aria-pressed={props.profileOpen}
        >
          <ChartColumnIcon aria-hidden="true" />
          Data profile
        </Button>
      </div>

      <h2 className="border-b px-4 pb-2 text-xs font-medium text-muted-foreground">History</h2>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <ThreadList {...props} />
      </div>

      <div className="flex items-center justify-between gap-2 border-t px-3 py-2">
        {props.signedIn ? (
          <div className="flex min-w-0 items-center gap-2">
            <UserButton />
            {props.liveAccess ? (
              <span className="truncate text-xs text-muted-foreground">Live questions on</span>
            ) : (
              <button
                onClick={props.onRequestAccess}
                className="truncate rounded-sm px-1 text-xs underline underline-offset-2"
              >
                Enter access code
              </button>
            )}
          </div>
        ) : (
          <Button variant="outline" size="sm" onClick={props.onRequestSignIn}>
            Sign in
          </Button>
        )}
        <ThemeToggle />
      </div>
    </nav>
  );
}

function ThreadList({ threads, activeThreadId, onSelectThread, onDeleteThread, signedIn, onRequestSignIn }: SidebarProps) {
  if (!signedIn) {
    return (
      <p className="p-4 text-sm text-muted-foreground">
        <button onClick={onRequestSignIn} className="underline underline-offset-2">
          Sign in
        </button>{" "}
        to keep your questions. They stay with your account on any device.
      </p>
    );
  }
  if (threads.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">No questions yet. Ask one to start a history.</p>;
  }
  return (
    <ul className="grid py-1">
      {threads.map((thread) => (
        <li key={thread.thread_id} className="group relative">
          <button
            onClick={() => onSelectThread(thread.thread_id)}
            aria-current={thread.thread_id === activeThreadId ? "page" : undefined}
            className={cn(
              "w-full px-4 py-2 pr-10 text-left hover:bg-sidebar-accent",
              thread.thread_id === activeThreadId && "bg-sidebar-accent",
            )}
          >
            <span className="line-clamp-2 text-sm">{thread.title}</span>
            <span className="text-xs text-muted-foreground">{formatRelative(thread.updated_at)}</span>
          </button>
          <Button
            variant="ghost"
            size="icon-xs"
            className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100"
            onClick={() => onDeleteThread(thread.thread_id)}
            aria-label={`Delete "${thread.title}"`}
          >
            <Trash2Icon />
          </Button>
        </li>
      ))}
    </ul>
  );
}
