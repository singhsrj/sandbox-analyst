"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { LoginError } from "@/lib/auth";

interface AccessDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (code: string) => Promise<void>;
  /** Why the dialog opened, e.g. the session expired. */
  reason?: string | null;
}

export function AccessDialog({ open, onOpenChange, onSubmit, reason }: AccessDialogProps) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!code.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(code.trim());
      setCode("");
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof LoginError ? err.message : "Sign-in failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <form onSubmit={handleSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Enter the access code</DialogTitle>
            <DialogDescription>
              {reason ??
                "Live questions run real queries and cost money, so they need a code. Browsing the data and the examples does not."}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <label htmlFor="access-code" className="text-sm font-medium">
              Access code
            </label>
            <Input
              id="access-code"
              type="password"
              autoComplete="off"
              autoFocus
              value={code}
              onChange={(e) => setCode(e.target.value)}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "access-code-error" : undefined}
            />
            {error ? (
              <p id="access-code-error" role="alert" className="text-sm text-destructive">
                {error}
              </p>
            ) : null}
          </div>
          <DialogFooter>
            <Button type="submit" disabled={!code.trim() || busy}>
              {busy ? "Checking…" : "Unlock live questions"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
