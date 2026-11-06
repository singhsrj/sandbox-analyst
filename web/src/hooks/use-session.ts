"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";
import { clearSession, getSessionSnapshot, login, subscribeSession } from "@/lib/auth";

const noopSubscribe = () => () => {};

/** Access state for live runs. Browsing the schema and examples never needs a session. */
export function useSession() {
  // Storage only exists in the browser: the server render (and hydration) see "signed out".
  const session = useSyncExternalStore(subscribeSession, getSessionSnapshot, () => null);
  const ready = useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );

  // Drop the session the moment the token expires so the UI asks for the code again.
  useEffect(() => {
    if (!session) return;
    const remaining = session.expiresAt * 1000 - Date.now();
    const timer = setTimeout(clearSession, Math.max(0, remaining));
    return () => clearTimeout(timer);
  }, [session]);

  const signIn = useCallback(async (code: string) => {
    await login(code);
  }, []);

  return { signedIn: session !== null, ready, signIn, signOut: clearSession };
}
