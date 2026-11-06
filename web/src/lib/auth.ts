/**
 * Access-code login (ADR-006): the code is exchanged for a short-lived bearer token.
 *
 * - `clientId` identifies this browser's threads. It is stored in localStorage and is not a secret.
 * - The token lives in sessionStorage (cleared when the tab closes). Reading it requires script
 *   access, so the app avoids dangerouslySetInnerHTML on model output; expiry is short.
 */
import { API_BASE_URL } from "./config";

const CLIENT_ID_KEY = "sa.clientId";
const TOKEN_KEY = "sa.token";

export interface StoredSession {
  token: string;
  expiresAt: number; // unix seconds
}

function safeGet(storage: "localStorage" | "sessionStorage", key: string): string | null {
  try {
    return window[storage].getItem(key);
  } catch {
    return null; // private mode / blocked storage: the app still works, just without persistence
  }
}

function safeSet(storage: "localStorage" | "sessionStorage", key: string, value: string | null) {
  try {
    if (value === null) window[storage].removeItem(key);
    else window[storage].setItem(key, value);
  } catch {
    /* ignore */
  }
}

export function getClientId(): string {
  const existing = safeGet("localStorage", CLIENT_ID_KEY);
  if (existing && /^[A-Za-z0-9_-]{8,64}$/.test(existing)) return existing;
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const id = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  safeSet("localStorage", CLIENT_ID_KEY, id);
  return id;
}

function parseSession(raw: string | null, now: number): StoredSession | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as StoredSession;
    if (typeof parsed.token !== "string" || typeof parsed.expiresAt !== "number") return null;
    return parsed.expiresAt > now + 5 ? parsed : null;
  } catch {
    return null;
  }
}

export function getSession(now = Date.now() / 1000): StoredSession | null {
  return parseSession(safeGet("sessionStorage", TOKEN_KEY), now);
}

// --- change notification so React can subscribe with useSyncExternalStore -------------------
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((listener) => listener());

export function subscribeSession(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

let cachedRaw: string | null | undefined;
let cachedSession: StoredSession | null = null;

/** Stable snapshot: the same object until the stored token (or its expiry) changes. */
export function getSessionSnapshot(): StoredSession | null {
  const raw = safeGet("sessionStorage", TOKEN_KEY);
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    cachedSession = parseSession(raw, Date.now() / 1000);
  } else if (cachedSession && cachedSession.expiresAt <= Date.now() / 1000 + 5) {
    cachedSession = null;
  }
  return cachedSession;
}

export function getToken(): string | null {
  return getSession()?.token ?? null;
}

export function clearSession(): void {
  safeSet("sessionStorage", TOKEN_KEY, null);
  notify();
}

export class LoginError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly retryAfter?: number,
  ) {
    super(message);
  }
}

export async function login(code: string, fetchImpl: typeof fetch = fetch): Promise<StoredSession> {
  let response: Response;
  try {
    response = await fetchImpl(`${API_BASE_URL}/api/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, client_id: getClientId() }),
    });
  } catch {
    throw new LoginError("Can't reach the server. Check your connection and try again.", 0);
  }
  if (!response.ok) {
    const retry = Number(response.headers.get("Retry-After")) || undefined;
    const message =
      response.status === 401
        ? "That access code isn't right."
        : response.status === 429
          ? `Too many attempts. Try again in ${retry ?? 60} seconds.`
          : response.status === 503
            ? "Live runs aren't enabled on this server."
            : "Sign-in failed. Try again.";
    throw new LoginError(message, response.status, retry);
  }
  const body = (await response.json()) as { token: string; expires_at: number; client_id: string };
  const session = { token: body.token, expiresAt: body.expires_at };
  safeSet("sessionStorage", TOKEN_KEY, JSON.stringify(session));
  notify();
  if (/^[A-Za-z0-9_-]{8,64}$/.test(body.client_id)) safeSet("localStorage", CLIENT_ID_KEY, body.client_id);
  return session;
}
