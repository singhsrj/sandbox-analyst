import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { setTokenProvider } from "./src/lib/auth";
import { clerk } from "./src/test-utils/clerk-mock";

// Clerk needs a browser session and network; every test gets the controllable stand-in.
vi.mock("@clerk/nextjs", () => import("./src/test-utils/clerk-mock"));

afterEach(() => {
  cleanup();
  clerk.reset();
  setTokenProvider(async () => null);
  window.localStorage.clear();
  window.sessionStorage.clear();
});

// jsdom does not implement these browser APIs that the UI libraries touch.
class NoopObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= NoopObserver as unknown as typeof ResizeObserver;
globalThis.IntersectionObserver ??= NoopObserver as unknown as typeof IntersectionObserver;
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener() {},
  removeEventListener() {},
  addListener() {},
  removeListener() {},
  dispatchEvent: () => false,
})) as typeof window.matchMedia;
Element.prototype.scrollTo ??= () => {};
Element.prototype.scrollIntoView ??= () => {};
