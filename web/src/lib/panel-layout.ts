/**
 * Remembered widths of the workspace panels, one layout with the data profile open and one with it
 * closed. A per-browser convenience: storage may be blocked (private mode), so every access is
 * guarded and a missing or malformed value just means "use the default widths".
 */

export type PanelLayout = Record<string, number>;
type Saved = { open?: PanelLayout; closed?: PanelLayout };

export const LAYOUT_KEY = "workspace-layout:v1";
const PANEL_ID = /^[a-z]{1,20}$/;

function read(): Saved {
  try {
    const raw = window.localStorage.getItem(LAYOUT_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (!parsed || typeof parsed !== "object") return {};
    const out: Saved = {};
    for (const which of ["open", "closed"] as const) {
      const layout = valid((parsed as Saved)[which]);
      if (layout) out[which] = layout;
    }
    return out;
  } catch {
    return {};
  }
}

function valid(value: unknown): PanelLayout | undefined {
  if (!value || typeof value !== "object") return undefined;
  const entries = Object.entries(value as Record<string, unknown>);
  const ok =
    entries.length >= 2 &&
    entries.every(([k, v]) => PANEL_ID.test(k) && typeof v === "number" && v >= 0 && v <= 100);
  return ok ? (Object.fromEntries(entries) as PanelLayout) : undefined;
}

/** The saved layout for the profile open or closed, if it matches the panels on screen. */
export function loadLayout(profileOpen: boolean, panelIds: string[]): PanelLayout | undefined {
  const layout = read()[profileOpen ? "open" : "closed"];
  if (!layout) return undefined;
  const keys = Object.keys(layout).sort().join();
  return keys === [...panelIds].sort().join() ? layout : undefined;
}

export function saveLayout(layout: PanelLayout): void {
  const saved = read();
  saved["profile" in layout ? "open" : "closed"] = layout;
  try {
    window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(saved));
  } catch {
    /* not remembered; fine */
  }
}
