import { describe, expect, it } from "vitest";
import { isEditableTarget, isSearchShortcut, type ShortcutEvent } from "@/lib/shortcuts";
import { parseSearchResponse } from "./parse";
import { SEARCH_DEBOUNCE_MS, SEARCH_MIN_CHARS, searchStatus } from "./search-dialog";

function key(partial: Partial<ShortcutEvent> & { key: string }): ShortcutEvent {
  return { ctrlKey: false, metaKey: false, altKey: false, target: null, ...partial };
}

describe("search shortcut", () => {
  it("opens on / outside text fields when shortcuts are on", () => {
    expect(isSearchShortcut(key({ key: "/", target: { tagName: "BODY" } as unknown as EventTarget }), { shortcutsEnabled: true })).toBe(true);
    expect(isSearchShortcut(key({ key: "/" }), { shortcutsEnabled: false })).toBe(false);
  });

  it("never steals / from fields being typed in", () => {
    for (const target of [
      { tagName: "INPUT", type: "text" },
      { tagName: "INPUT", type: "search" },
      { tagName: "TEXTAREA" },
      { tagName: "SELECT" },
      { tagName: "DIV", isContentEditable: true },
      { tagName: "DIV", getAttribute: (name: string) => (name === "role" ? "spinbutton" : null) },
    ]) {
      expect(isEditableTarget(target as unknown as EventTarget), JSON.stringify(target)).toBe(true);
      expect(isSearchShortcut(key({ key: "/", target: target as unknown as EventTarget }), { shortcutsEnabled: true })).toBe(false);
    }
    expect(isEditableTarget({ tagName: "INPUT", type: "checkbox" } as unknown as EventTarget)).toBe(false);
  });

  it("opens on Ctrl/Cmd+K everywhere, even with single-key shortcuts off (WCAG 2.1.4)", () => {
    const field = { tagName: "INPUT", type: "text" } as unknown as EventTarget;
    expect(isSearchShortcut(key({ key: "k", ctrlKey: true, target: field }), { shortcutsEnabled: false })).toBe(true);
    expect(isSearchShortcut(key({ key: "K", metaKey: true }), { shortcutsEnabled: false })).toBe(true);
    expect(isSearchShortcut(key({ key: "k", ctrlKey: true, altKey: true }), { shortcutsEnabled: true })).toBe(false);
    expect(isSearchShortcut(key({ key: "/", ctrlKey: true }), { shortcutsEnabled: true })).toBe(false);
    expect(isSearchShortcut(key({ key: "/", isComposing: true }), { shortcutsEnabled: true })).toBe(false);
    expect(isSearchShortcut(key({ key: "/", defaultPrevented: true }), { shortcutsEnabled: true })).toBe(false);
  });
});

describe("search results", () => {
  it("follow the platform provider contract and keep only in-app paths", () => {
    const response = parseSearchResponse(
      {
        q: "oak",
        groups: [
          {
            group: "Products",
            resource_type: "catalogue.product",
            total: 7,
            items: [
              { resource_type: "catalogue.product", resource_id: "p1", title: "LK-OT-0450 · Oak serving tray 450", subtitle: "Trays", path: "/products/p1" },
              { resource_type: "catalogue.product", resource_id: "p2", title: "Evil", subtitle: null, path: "https://evil.example" },
              { title: "No path" },
            ],
          },
          { group: "Parties", resource_type: "parties.party", total: 0, items: [] },
          "junk",
        ],
      },
      "oak",
    );
    expect(response.groups).toHaveLength(1);
    expect(response.groups[0]).toMatchObject({ group: "Products", total: 7 });
    expect(response.groups[0]!.items.map((hit) => hit.path)).toEqual(["/products/p1"]);
    expect(parseSearchResponse(null, "x")).toEqual({ q: "x", groups: [] });
  });

  it("describe their state in the live status line", () => {
    expect(SEARCH_MIN_CHARS).toBe(2);
    expect(SEARCH_DEBOUNCE_MS).toBe(250);
    expect(searchStatus("o", { isFetching: false, data: undefined, isError: false })).toBe("Type at least 2 characters to search.");
    expect(searchStatus("oak", { isFetching: true, data: undefined, isError: false })).toBe("Searching…");
    expect(searchStatus("oak", { isFetching: false, data: { q: "oak", groups: [] }, isError: false })).toBe(
      "Nothing matches “oak” that you can open.",
    );
    const data = {
      q: "oak",
      groups: [{ group: "Products", resource_type: "p", total: 2, items: [{ resource_type: "p", resource_id: "1", title: "a", subtitle: null, path: "/a" }] }],
    };
    expect(searchStatus("oak", { isFetching: false, data, isError: false })).toBe("1 result");
  });
});
