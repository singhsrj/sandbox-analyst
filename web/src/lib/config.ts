/** Public configuration. Only NEXT_PUBLIC_* values exist in the browser; there are no secrets here. */
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

export const THREAD_ID_PATTERN = /^[A-Za-z0-9_-]{8,64}$/;
