"use client";

import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiError, sendSuggestion } from "@/lib/api";

const MAX = 2000;
type State = { kind: "idle" } | { kind: "sending" } | { kind: "sent" } | { kind: "error"; message: string };

/** "What else should there be?" Anyone can write one; nothing identifies the writer. */
export function SuggestionBox() {
  const [text, setText] = useState("");
  const [website, setWebsite] = useState(""); // honeypot: people never see or fill this
  const [state, setState] = useState<State>({ kind: "idle" });
  const fieldId = useId();
  const hintId = useId();
  const tooShort = text.trim().length < 3;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (tooShort || state.kind === "sending") return;
    setState({ kind: "sending" });
    try {
      await sendSuggestion(text.trim(), website);
      setText("");
      setState({ kind: "sent" });
    } catch (err) {
      setState({
        kind: "error",
        message: err instanceof ApiError ? err.message : "That didn't send. Try again.",
      });
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-3" aria-label="Suggest a feature">
      <label htmlFor={fieldId} className="text-sm font-medium">
        Your idea
      </label>
      <textarea
        id={fieldId}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          if (state.kind !== "sending") setState({ kind: "idle" });
        }}
        rows={4}
        maxLength={MAX}
        aria-describedby={hintId}
        placeholder="For example: compare two date ranges side by side"
        className="w-full rounded-sm border bg-card p-3 text-sm leading-6"
      />
      <div className="absolute -left-[9999px]" aria-hidden="true">
        <label>
          Website
          <input
            tabIndex={-1}
            autoComplete="off"
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
          />
        </label>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p id={hintId} className="text-xs text-muted-foreground">
          No sign-in needed. Stored without your name, email or address.{" "}
          <span className="tabular-nums">
            {text.length.toLocaleString()} / {MAX.toLocaleString()}
          </span>
        </p>
        <Button type="submit" disabled={tooShort || state.kind === "sending"}>
          {state.kind === "sending" ? "Sending…" : "Send suggestion"}
        </Button>
      </div>
      {state.kind === "sent" ? (
        <p role="status" className="text-sm text-ok">
          Thanks, got it. Send another any time.
        </p>
      ) : null}
      {state.kind === "error" ? (
        <p role="alert" className="text-sm text-destructive">
          {state.message}
        </p>
      ) : null}
    </form>
  );
}
