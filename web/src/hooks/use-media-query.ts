"use client";

import { useSyncExternalStore } from "react";

/**
 * Whether a CSS media query matches, kept in sync as the window changes.
 * `fallback` is used on the server and where `matchMedia` is missing (tests, old browsers).
 */
export function useMediaQuery(query: string, fallback = true): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => undefined;
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : fallback),
    () => fallback,
  );
}
