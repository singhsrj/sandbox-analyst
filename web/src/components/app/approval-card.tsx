"use client";

import { createContext, useContext, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import type { ApprovalDecision } from "@/lib/types";

interface ApprovalContextValue {
  decide: (approvalId: string, decision: ApprovalDecision) => void;
  /** False while a request is in flight or for read-only history. */
  enabled: boolean;
}

export const ApprovalContext = createContext<ApprovalContextValue>({
  decide: () => {},
  enabled: false,
});

type Mode = "review" | "edit" | "reject";

/** Shown inside a query step that is waiting for a human. The query does not run until answered. */
export function ApprovalCard({
  approvalId,
  query,
  reason,
}: {
  approvalId: string;
  query: string;
  reason?: string;
}) {
  const { decide, enabled } = useContext(ApprovalContext);
  const [mode, setMode] = useState<Mode>("review");
  const [draft, setDraft] = useState(query);
  const [why, setWhy] = useState("");
  const sqlId = useId();
  const whyId = useId();
  const unchanged = draft.trim() === query.trim();

  return (
    <section
      className="grid gap-3 rounded-sm border border-foreground/40 bg-card p-3"
      aria-label="Approval needed"
      data-testid="approval-card"
    >
      <div className="grid gap-1">
        <p className="text-sm font-medium">This query needs your approval before it runs.</p>
        {reason ? <p className="text-xs text-muted-foreground">{reason}</p> : null}
      </div>

      {mode === "edit" ? (
        <div className="grid gap-1.5">
          <label htmlFor={sqlId} className="text-xs font-medium">
            Edit the SQL (it is still checked: read-only, analytics tables only)
          </label>
          <textarea
            id={sqlId}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={Math.min(14, Math.max(4, draft.split("\n").length + 1))}
            spellCheck={false}
            maxLength={20_000}
            className="w-full rounded-sm border bg-background p-2 font-mono text-xs leading-5"
          />
        </div>
      ) : null}

      {mode === "reject" ? (
        <div className="grid gap-1.5">
          <label htmlFor={whyId} className="text-xs font-medium">
            Why? (optional; the analyst reads this and tries another way)
          </label>
          <input
            id={whyId}
            value={why}
            onChange={(e) => setWhy(e.target.value)}
            maxLength={500}
            className="w-full rounded-sm border bg-background px-2 py-1.5 text-sm"
            placeholder="For example: filter to March 2025 first"
          />
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {mode === "review" ? (
          <>
            <Button size="sm" disabled={!enabled} onClick={() => decide(approvalId, { approved: true })}>
              Run query
            </Button>
            <Button size="sm" variant="outline" disabled={!enabled} onClick={() => setMode("edit")}>
              Edit SQL
            </Button>
            <Button size="sm" variant="ghost" disabled={!enabled} onClick={() => setMode("reject")}>
              Reject
            </Button>
          </>
        ) : null}
        {mode === "edit" ? (
          <>
            <Button
              size="sm"
              disabled={!enabled || !draft.trim()}
              onClick={() =>
                decide(approvalId, unchanged ? { approved: true } : { approved: true, editedQuery: draft.trim() })
              }
            >
              {unchanged ? "Run query" : "Run edited query"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setMode("review")}>
              Cancel
            </Button>
          </>
        ) : null}
        {mode === "reject" ? (
          <>
            <Button
              size="sm"
              variant="destructive"
              disabled={!enabled}
              onClick={() => decide(approvalId, { approved: false, reason: why.trim() || undefined })}
            >
              Reject query
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setMode("review")}>
              Cancel
            </Button>
          </>
        ) : null}
      </div>
    </section>
  );
}
