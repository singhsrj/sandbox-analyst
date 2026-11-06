import { clearSession, getToken } from "./auth";
import { API_BASE_URL } from "./config";
import type { SchemaTable, StoredRun, ThreadSummary } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** The token is missing, expired or was rejected: the UI should ask for the access code again. */
export class AuthRequiredError extends ApiError {
  constructor() {
    super("Your session ended. Enter the access code to continue.", 401);
  }
}

async function request(path: string, init: RequestInit = {}, auth = false): Promise<Response> {
  const headers = new Headers(init.headers);
  if (auth) {
    const token = getToken();
    if (!token) throw new AuthRequiredError();
    headers.set("Authorization", `Bearer ${token}`);
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0);
  }
  if (response.status === 401 && auth) {
    clearSession();
    throw new AuthRequiredError();
  }
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

export async function getSchema(): Promise<SchemaTable[]> {
  const body = (await (await request("/api/schema")).json()) as { tables: SchemaTable[] };
  return body.tables;
}

// --- authenticated --------------------------------------------------------------------
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

/** Artifacts need the bearer token, so images cannot be plain <img src>: fetch, then blob-URL. */
export async function fetchArtifact(url: string): Promise<Blob> {
  return (await request(url, {}, true)).blob();
}
