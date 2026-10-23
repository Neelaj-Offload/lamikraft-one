import { describe, expect, it } from "vitest";
import { countTags, nestedInteractive, renderInSession, textOf } from "@/lib/test-support/render";
import { cursorFrom, inboxHref, inboxTabFrom, InboxShapeError, parseInboxPage } from "./api";
import { InboxList, inboxStatus } from "./inbox-view";
import type { InboxItem } from "./types";

const NOW = new Date("2026-10-12T03:25:00Z");
const IST = { timeZone: "Asia/Kolkata", locale: "en-IN" };

function rawItem(overrides: Record<string, unknown> = {}) {
  return {
    id: "t1",
    kind: "quote_expiry",
    family: "sales.quote_expiry",
    title: "Berg & Co AB quote expires today",
    summary: "LK-QT-2026-0038",
    state: "open",
    due_at: "2026-10-12T13:00:00Z",
    due_kind: "hard",
    overdue: false,
    snoozed_until: null,
    source: { type: "sales.quote", id: "q38", label: "Quote LK-QT-2026-0038", href: "/sales/quotes/q38" },
    href: "/sales/quotes/q38",
    assignee: { id: "u1", display_name: "Meera Iyer" },
    owner: { id: "u1", display_name: "Meera Iyer" },
    on_behalf_of: null,
    updated_at: "2026-10-12T03:15:00Z",
    ...overrides,
  };
}

describe("Inbox URL state", () => {
  it("reads tabs and cursors defensively", () => {
    expect(inboxTabFrom("approvals")).toBe("approvals");
    expect(inboxTabFrom(["done", "tasks"])).toBe("done");
    expect(inboxTabFrom("company")).toBe("tasks");
    expect(inboxTabFrom(undefined)).toBe("tasks");
    expect(cursorFrom("eyJrIjoxfQ")).toBe("eyJrIjoxfQ");
    expect(cursorFrom("<script>")).toBeNull();
    expect(inboxHref("tasks")).toBe("/inbox");
    expect(inboxHref("approvals", "abc")).toBe("/inbox?tab=approvals&cursor=abc");
  });
});

describe("parseInboxPage", () => {
  it("reads a keyset page and keeps only in-app links", () => {
    const page = parseInboxPage({
      items: [rawItem(), rawItem({ id: "t2", href: "https://evil.example", source: null }), { id: "bad" }],
      next_cursor: "next-1",
      limit: 50,
      counts: { tasks: 3, approvals: 1, bogus: 9, done: -1 },
    });
    expect(page.items.map((item) => item.id)).toEqual(["t1", "t2"]);
    expect(page.items[1]!.href).toBeNull();
    expect(page.next_cursor).toBe("next-1");
    expect(page.counts).toEqual({ tasks: 3, approvals: 1 });
  });

  it("rejects payloads without items", () => {
    expect(() => parseInboxPage({ results: [] })).toThrow(InboxShapeError);
  });
});

describe("Inbox list", () => {
  const page = parseInboxPage({
    items: [rawItem(), rawItem({ id: "t2", title: "Approve price override", overdue: true, due_at: "2026-10-11T12:00:00Z" })],
    next_cursor: "c2",
    limit: 2,
  });

  it("is a semantic table with row headers, a phone list and keyset pagination", () => {
    const html = renderInSession(<InboxList tab="tasks" page={page} cursor={null} />);
    expect(html).toContain("<table");
    expect(countTags(html, "th", 'scope="row"')).toBe(2);
    expect(html).toMatch(/<ul aria-label="Tasks in your Inbox"/);
    expect(html).toContain('href="/inbox?cursor=c2"');
    expect(textOf(html)).not.toContain("First page");
    expect(textOf(html)).toContain("Overdue");
    expect(textOf(html)).toContain("Meera Iyer");
    // Linked phone rows render plain cells: no <a> inside <a> (a hydration error otherwise).
    expect(nestedInteractive(html)).toEqual([]);
  });

  it("offers the first page from later pages", () => {
    const html = renderInSession(<InboxList tab="approvals" page={{ ...page, next_cursor: null }} cursor="c2" />);
    expect(html).toContain('href="/inbox?tab=approvals"');
    expect(textOf(html)).toContain("First page");
    expect(textOf(html)).not.toContain("Next page");
  });

  it("explains an empty tab", () => {
    const html = renderInSession(<InboxList tab="approvals" page={{ items: [], next_cursor: null, limit: 50, counts: null }} cursor={null} />);
    expect(html).not.toContain("<table");
    expect(textOf(html)).toContain("No approvals are waiting on you.");
  });

  it("derives status text, not colour alone", () => {
    const base = page.items[0]! as InboxItem;
    expect(inboxStatus(base, NOW, IST)).toEqual({ label: "Open", tone: "info" });
    expect(inboxStatus({ ...base, overdue: true }, NOW, IST)).toEqual({ label: "Overdue", tone: "danger" });
    expect(inboxStatus({ ...base, snoozed_until: "2026-10-12T05:25:00Z" }, NOW, IST).label).toMatch(/^Snoozed · Today, 10:55\sam$/i);
    expect(inboxStatus({ ...base, state: "done", overdue: true }, NOW, IST)).toEqual({ label: "Done", tone: "success" });
  });
});
