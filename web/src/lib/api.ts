import { getToken, type Me } from "./auth";
import { API_BASE_URL } from "./config";
import type { DataProfile, ReplayDetail, ReplaySummary, StoredRun, ThreadSummary } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** The token is missing, expired or was rejected: the UI should ask the person to sign in. */
export class AuthRequiredError extends ApiError {
  constructor() {
    super("Sign in to continue.", 401);
  }
}

async function request(path: string, init: RequestInit = {}, auth = false): Promise<Response> {
  const headers = new Headers(init.headers);
  if (auth) {
    const token = await getToken();
    if (!token) throw new AuthRequiredError();
    headers.set("Authorization", `Bearer ${token}`);
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0);
  }
  if (response.status === 401 && auth) throw new AuthRequiredError();
  if (!response.ok) {
    let detail = `Request failed (${response.status}).`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(detail, response.status);
  }
  return response;
}

// --- public ---------------------------------------------------------------------------
export async function getExamples(): Promise<string[]> {
  const body = (await (await request("/api/examples")).json()) as { questions: string[] };
  return body.questions;
}

/** The statistical profile of a dataset (tables, distributions, outliers, ER diagram). Public. */
export async function getProfile(dataset: string): Promise<DataProfile> {
  return (await (await request(`/api/profiles/${encodeURIComponent(dataset)}`)).json()) as DataProfile;
}

/** Recorded, checked runs anyone can watch (replay mode). */
export async function listReplays(): Promise<ReplaySummary[]> {
  const body = (await (await request("/api/replays")).json()) as { replays: ReplaySummary[] };
  return body.replays;
}

export async function getReplay(id: string): Promise<ReplayDetail> {
  return (await (await request(`/api/replays/${encodeURIComponent(id)}`)).json()) as ReplayDetail;
}

/** "What else should there be?" Anyone may send one; `website` is the hidden honeypot field. */
export async function sendSuggestion(text: string, website = ""): Promise<void> {
  await request("/api/suggestions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, website }),
  });
}

// --- authenticated --------------------------------------------------------------------
export async function getMe(): Promise<Me> {
  return (await (await request("/api/me", {}, true)).json()) as Me;
}

export async function listThreads(): Promise<ThreadSummary[]> {
  const body = (await (await request("/api/threads", {}, true)).json()) as {
    threads: ThreadSummary[];
  };
  return body.threads;
}

export async function getThread(
  threadId: string,
): Promise<{ thread: ThreadSummary; runs: StoredRun[] }> {
  const response = await request(`/api/threads/${encodeURIComponent(threadId)}`, {}, true);
  return (await response.json()) as { thread: ThreadSummary; runs: StoredRun[] };
}

export async function deleteThread(threadId: string): Promise<void> {
  await request(`/api/threads/${encodeURIComponent(threadId)}`, { method: "DELETE" }, true);
}

/**
 * A visitor's own files need the bearer token, so images cannot be plain <img src>: fetch, then
 * blob-URL. Files of recorded runs (replays) are public and are fetched without it.
 */
export async function fetchArtifact(url: string): Promise<Blob> {
  return (await request(url, {}, !url.startsWith("/api/replays/"))).blob();
}
