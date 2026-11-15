/**
 * Accounts (ADR-028): people sign in with Clerk; the API verifies Clerk's short-lived session
 * token, sent as `Authorization: Bearer` (ADR-006: no cross-site cookies).
 *
 * - The token comes from Clerk (`useAuth().getToken()`, which refreshes it). `useSession` installs
 *   that function here, so the API client and the chat transport never touch Clerk directly and
 *   tests can install a fake.
 * - Signing in says who you are. Live questions cost money, so an account also enters the access
 *   code once (`enterAccessCode`); the server remembers it.
 * - Nothing is stored in localStorage or sessionStorage by this module.
 */
import { API_BASE_URL } from "./config";

export type TokenProvider = () => Promise<string | null>;

let tokenProvider: TokenProvider = async () => null;

export function setTokenProvider(provider: TokenProvider): void {
  tokenProvider = provider;
}

/** The current session token, or null when signed out (or when Clerk cannot refresh it). */
export async function getToken(): Promise<string | null> {
  try {
    return await tokenProvider();
  } catch {
    return null;
  }
}

export interface Me {
  user_id: string;
  live_access: boolean;
  live_runs_enabled: boolean;
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

/** Unlock live questions for this account. Throws LoginError with a message for the dialog. */
export async function enterAccessCode(code: string, fetchImpl: typeof fetch = fetch): Promise<void> {
  const token = await getToken();
  if (!token) throw new LoginError("Sign in first, then enter the code.", 401);
  let response: Response;
  try {
    response = await fetchImpl(`${API_BASE_URL}/api/access`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ code }),
    });
  } catch {
    throw new LoginError("Can't reach the server. Check your connection and try again.", 0);
  }
  if (response.ok) return;
  const retry = Number(response.headers.get("Retry-After")) || undefined;
  const message =
    response.status === 401
      ? (await detail(response)) === "Invalid access code."
        ? "That access code isn't right."
        : "Your sign-in has expired. Sign in again."
      : response.status === 429
        ? `Too many attempts. Try again in ${retry ?? 60} seconds.`
        : response.status === 503
          ? "Live runs aren't enabled on this server."
          : "That didn't work. Try again.";
  throw new LoginError(message, response.status, retry);
}

async function detail(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : null;
  } catch {
    return null;
  }
}
