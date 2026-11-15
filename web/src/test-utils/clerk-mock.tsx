/**
 * Stand-in for `@clerk/nextjs` in component tests (installed in vitest.setup.ts). It keeps the
 * sign-in state in a tiny external store so components re-render on sign-in/out like the real
 * thing. `openSignIn` signs straight in, as if the person completed Clerk's modal, unless a test
 * sets `clerk.autoSignIn = false`.
 */
import { useSyncExternalStore, type ReactElement, type ReactNode } from "react";
import { cloneElement, isValidElement } from "react";
import { vi } from "vitest";

export const CLERK_TOKEN = "clerk-session-token.test";
export const CLERK_USER_ID = "user_test_clerk1";

const listeners = new Set<() => void>();
let signedIn = false;
let loaded = true;

function set(value: boolean) {
  signedIn = value;
  listeners.forEach((listener) => listener());
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export const clerk = {
  autoSignIn: true,
  /** false = Clerk never finishes loading (blocked script, slow network). */
  setLoaded(value: boolean) {
    loaded = value;
    listeners.forEach((listener) => listener());
  },
  openSignIn: vi.fn(() => {
    if (clerk.autoSignIn) set(true);
  }),
  signOut: vi.fn(async () => set(false)),
  signIn: () => set(true),
  get signedIn() {
    return signedIn;
  },
  reset() {
    clerk.autoSignIn = true;
    clerk.openSignIn.mockClear();
    clerk.signOut.mockClear();
    loaded = true;
    set(false);
  },
};

const getToken = async () => (signedIn ? CLERK_TOKEN : null);

export function useAuth() {
  const isSignedIn = useSyncExternalStore(subscribe, () => signedIn, () => false);
  const isLoaded = useSyncExternalStore(subscribe, () => loaded, () => false);
  return {
    isLoaded,
    isSignedIn,
    userId: isSignedIn ? CLERK_USER_ID : null,
    getToken,
    signOut: clerk.signOut,
  };
}

export function useClerk() {
  return { openSignIn: clerk.openSignIn, signOut: clerk.signOut };
}

export function SignInButton({ children }: { children?: ReactNode; mode?: string }) {
  if (isValidElement(children))
    return cloneElement(children as ReactElement<{ onClick?: () => void }>, {
      onClick: () => clerk.openSignIn(),
    });
  return <button onClick={() => clerk.openSignIn()}>Sign in</button>;
}

export function UserButton() {
  return (
    <button type="button" onClick={() => void clerk.signOut()}>
      Account
    </button>
  );
}

export function ClerkProvider({ children }: { children?: ReactNode }) {
  return <>{children}</>;
}
