"use client";

import { useAuth, useClerk } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { getMe } from "@/lib/api";
import { enterAccessCode, setTokenProvider, type Me } from "@/lib/auth";

/**
 * Who is signed in (Clerk) and whether their account can run live questions (access code).
 * Browsing the schema, the examples and recorded runs never needs either.
 */
export function useSession() {
  const { isLoaded, isSignedIn, userId, getToken, signOut } = useAuth();
  const clerk = useClerk();
  // Tagged with the Clerk user it belongs to: after signing out (or into another account) a
  // stale answer is simply ignored instead of reset inside an effect.
  const [fetched, setFetched] = useState<{ userId: string; me: Me } | null>(null);
  const me = fetched && fetched.userId === userId ? fetched.me : null;

  // Install Clerk's token getter for the API client and the chat transport. Effects run in
  // declaration order, so this happens before the workspace's own effects make requests.
  useEffect(() => {
    setTokenProvider(isSignedIn ? () => getToken() : async () => null);
  }, [isSignedIn, getToken]);

  useEffect(() => {
    if (!isSignedIn || !userId) return;
    let cancelled = false;
    getMe()
      .then((value) => {
        if (!cancelled) setFetched({ userId, me: value });
      })
      .catch(() => undefined); // unknown stays unknown; the server still enforces access
    return () => {
      cancelled = true;
    };
  }, [isSignedIn, userId]);

  const unlock = useCallback(
    async (code: string) => {
      await enterAccessCode(code);
      setFetched((current) =>
        current && current.userId === userId
          ? { ...current, me: { ...current.me, live_access: true } }
          : current,
      );
    },
    [userId],
  );

  const openSignIn = useCallback(() => clerk.openSignIn(), [clerk]);
  const leave = useCallback(() => {
    void signOut();
  }, [signOut]);

  const signedIn = Boolean(isSignedIn);
  return {
    ready: isLoaded,
    signedIn,
    /** Signed in, and this account has entered the access code. */
    liveAccess: signedIn && Boolean(me?.live_access),
    /** The server has told us whether this account has live access (so the answer is known). */
    accessKnown: signedIn && me !== null,
    openSignIn,
    unlock,
    signOut: leave,
  };
}
