import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { setTokenProvider } from "./src/lib/auth";
import { clerk } from "./src/test-utils/clerk-mock";

// Clerk needs a browser session and network; every test gets the controllable stand-in.
vi.mock("@clerk/nextjs", () => import("./src/test-utils/clerk-mock"));
// jsdom has no layout, so the resizable panels are plain boxes in tests (see the mock).
vi.mock("react-resizable-panels", () => import("./src/test-utils/resizable-mock"));

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
// "(min-width: Npx)" answers from jsdom's window (1024px wide), so tests get the desktop layout.
window.matchMedia ??= ((query: string) => ({
  matches: Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? Infinity) <= window.innerWidth,
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
