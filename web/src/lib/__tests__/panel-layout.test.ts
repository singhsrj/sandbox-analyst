import { afterEach, describe, expect, it, vi } from "vitest";
import { LAYOUT_KEY, loadLayout, saveLayout } from "../panel-layout";

afterEach(() => vi.restoreAllMocks());

describe("panel layout memory", () => {
  it("keeps one layout with the profile open and one with it closed", () => {
    saveLayout({ sidebar: 20, chat: 80 });
    saveLayout({ sidebar: 18, profile: 40, chat: 42 });
    expect(loadLayout(false, ["sidebar", "chat"])).toEqual({ sidebar: 20, chat: 80 });
    expect(loadLayout(true, ["sidebar", "profile", "chat"])).toEqual({ sidebar: 18, profile: 40, chat: 42 });
  });

  it("ignores a layout for other panels, junk values and broken JSON", () => {
    saveLayout({ sidebar: 20, chat: 80 });
    expect(loadLayout(false, ["sidebar", "chat", "extra"])).toBeUndefined();
    window.localStorage.setItem(LAYOUT_KEY, JSON.stringify({ closed: { sidebar: "x", chat: 500 } }));
    expect(loadLayout(false, ["sidebar", "chat"])).toBeUndefined();
    window.localStorage.setItem(LAYOUT_KEY, "{not json");
    expect(loadLayout(false, ["sidebar", "chat"])).toBeUndefined();
  });

  it("works when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => saveLayout({ sidebar: 20, chat: 80 })).not.toThrow();
    expect(loadLayout(false, ["sidebar", "chat"])).toBeUndefined();
  });
});
