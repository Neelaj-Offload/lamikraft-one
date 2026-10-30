import { describe, expect, it } from "vitest";
import { countTags, nestedInteractive, renderInSession, textOf } from "@/lib/test-support/render";
import { createApiClient } from "@/lib/api/client";
import { cursorFrom, inboxHref, inboxTabFrom, InboxShapeError, parseInboxCounts, parseInboxPage, parseTaskDetail, taskIdFrom, transitionTask } from "./api";
import { InboxList, inboxStatus, tabCounts } from "./inbox-view";
import { assigneeLabel, itemHref } from "./model";
import { taskCommands } from "./task-drawer";
import type { InboxItem } from "./types";

const NOW = new Date("2026-10-12T03:25:00Z");
const IST = { timeZone: "Asia/Kolkata", locale: "en-IN" };
const ME = "0192a000-0000-7000-8000-00000000000a";
const TASK = "0192a000-0000-7000-8000-0000000000f1";
const PROPOSAL = "0192a000-0000-7000-8000-0000000000a5";
const QUOTE = "0192a000-0000-7000-8000-000000000038";

/** tasks/schemas.py `InboxItem` as the server sends it. */
function rawItem(overrides: Record<string, unknown> = {}) {
  return {
    id: TASK,
    issue_id: "0192a000-0000-7000-8000-0000000000e1",
    kind: "quote_expiry",
    family: "sales.quote_expiry",
    tab: "tasks",
    title: "Berg & Co AB quote expires today",
    state: "open",
    due_at: "2026-10-12T13:00:00Z",
    due_kind: "hard",
    overdue: false,
    blocked: false,
    owner_user_id: ME,
    assignee_user_id: ME,
    queue_code: null,
    snoozed_until: null,
    source_refs: [{ type: "sales.quote", id: QUOTE, version: 3, label: "LK-QT-2026-0006 · Berg & Co AB", path: `/sales/quotes/${QUOTE}` }],
    capabilities: {
      complete: { allowed: true, reason_code: null },
      dismiss: { allowed: true, reason_code: null },
      assign: { allowed: true, reason_code: null },
      snooze: { allowed: true, reason_code: null },
    },
    version: 2,
    ...overrides,
  };
}

describe("Inbox URL state", () => {
  it("reads tabs, cursors and the open task defensively", () => {
    expect(inboxTabFrom("approvals")).toBe("approvals");
    expect(inboxTabFrom(["conversations", "tasks"])).toBe("conversations");
    expect(inboxTabFrom("done")).toBe("tasks");
    expect(inboxTabFrom(undefined)).toBe("tasks");
    expect(cursorFrom("eyJrIjoxfQ")).toBe("eyJrIjoxfQ");
    expect(cursorFrom("<script>")).toBeNull();
    expect(taskIdFrom(TASK)).toBe(TASK);
    expect(taskIdFrom("../etc")).toBeNull();
    expect(inboxHref("tasks")).toBe("/inbox");
    expect(inboxHref("approvals", "abc")).toBe("/inbox/approvals?cursor=abc");
    expect(inboxHref("exceptions", "abc", TASK)).toBe(`/inbox/exceptions?cursor=abc&task=${TASK}`);
  });
});

describe("parseInboxPage (tasks/schemas.py InboxPage)", () => {
  it("reads a keyset page and keeps only in-app links", () => {
    const page = parseInboxPage({
      items: [
        rawItem(),
        rawItem({ id: "t2", source_refs: [{ type: "x", id: "s", label: "Off site", path: "https://evil.example" }] }),
        { id: "bad" },
        // Browsers read "/\host" like "//host": off-site.
        rawItem({ id: "t3", source_refs: [{ type: "x", id: "s", label: "Backslash", path: "/\\evil.example/phish" }] }),
      ],
      next_cursor: "next-1",
      limit: 50,
    });
    expect(page.items.map((item) => item.id)).toEqual([TASK, "t2", "t3"]);
    expect(page.items[0]!.source?.href).toBe(`/sales/quotes/${QUOTE}`);
    expect(page.items[1]!.source?.href).toBeNull();
    expect(page.items[2]!.source?.href).toBeNull();
    expect(page.next_cursor).toBe("next-1");
  });

  it("finds the proposal of an approval task", () => {
    const page = parseInboxPage({
      items: [
        rawItem({
          kind: "approval_decision",
          tab: "approvals",
          source_refs: [{ type: "approvals.proposal", id: PROPOSAL, version: 1, label: "Review LK-QT-2026-0005", path: `/approvals/${PROPOSAL}` }],
        }),
      ],
      next_cursor: null,
      limit: 50,
    });
    expect(page.items[0]!.proposal_id).toBe(PROPOSAL);
    expect(page.items[0]!.source?.href).toBe(`/inbox/approvals/${PROPOSAL}`);
    expect(itemHref(page.items[0]!, "approvals", null)).toBe(`/inbox/approvals/${PROPOSAL}`);
  });

  it("rejects payloads without items", () => {
    expect(() => parseInboxPage({ results: [] })).toThrow(InboxShapeError);
  });

  it("reads counts per tab and drops anything else", () => {
    expect(parseInboxCounts({ tasks: 3, approvals: 1, conversations: 2, exceptions: 1, done: 9, bogus: -1 })).toEqual({
      tasks: 3,
      approvals: 1,
      conversations: 2,
      exceptions: 1,
    });
    expect(tabCounts(undefined, { tasks: 4 }, { tasks: 1 })).toEqual({ tasks: 4 });
    expect(tabCounts({ tasks: 2 }, { tasks: 4 }, null)).toEqual({ tasks: 2 });
  });
});

describe("Inbox list", () => {
  const page = parseInboxPage({
    items: [
      rawItem(),
      rawItem({
        id: "t2",
        title: "Call Maison about finishes",
        overdue: true,
        due_at: "2026-10-11T12:00:00Z",
        assignee_user_id: null,
        owner_user_id: null,
        queue_code: "EXP-SALES",
      }),
    ],
    next_cursor: "c2",
    limit: 2,
  });

  it("is a semantic table with row headers, a phone list and keyset pagination", () => {
    const html = renderInSession(<InboxList tab="tasks" page={page} cursor={null} />);
    expect(html).toContain("<table");
    expect(countTags(html, "th", 'scope="row"')).toBe(2);
    expect(html).toMatch(/<ul aria-label="Tasks in your Inbox"/);
    expect(html).toContain('href="/inbox?cursor=c2"');
    // Titles open the task drawer on the same tab.
    expect(html).toContain(`href="/inbox?task=${TASK}"`);
    expect(textOf(html)).not.toContain("First page");
    expect(textOf(html)).toContain("Overdue");
    expect(textOf(html)).toContain("Queue: EXP-SALES");
    // Linked phone rows render plain cells: no <a> inside <a> (a hydration error otherwise).
    expect(nestedInteractive(html)).toEqual([]);
  });

  it("offers the first page from later pages", () => {
    const html = renderInSession(<InboxList tab="approvals" page={{ ...page, next_cursor: null }} cursor="c2" />);
    expect(html).toContain('href="/inbox/approvals"');
    expect(textOf(html)).toContain("First page");
    expect(textOf(html)).not.toContain("Next page");
  });

  it("explains an empty tab", () => {
    const html = renderInSession(<InboxList tab="conversations" page={{ items: [], next_cursor: null, limit: 50 }} cursor={null} />);
    expect(html).not.toContain("<table");
    expect(textOf(html)).toContain("No customer conversations are waiting for a reply.");
  });

  it("derives status text, not colour alone", () => {
    const base = page.items[0]! as InboxItem;
    expect(inboxStatus(base, NOW, IST)).toEqual({ label: "Open", tone: "info" });
    expect(inboxStatus({ ...base, overdue: true }, NOW, IST)).toEqual({ label: "Overdue", tone: "danger" });
    expect(inboxStatus({ ...base, blocked: true }, NOW, IST)).toEqual({ label: "Waiting on another step", tone: "warning" });
    expect(inboxStatus({ ...base, snoozed_until: "2026-10-12T05:25:00Z" }, NOW, IST).label).toMatch(/^Snoozed · Today, 10:55\sam$/i);
    expect(inboxStatus({ ...base, state: "done", overdue: true }, NOW, IST)).toEqual({ label: "Done", tone: "success" });
  });

  it("names who holds a task from ids only", () => {
    expect(assigneeLabel({ assignee_user_id: ME, owner_user_id: null, queue_code: null }, ME)).toBe("You");
    expect(assigneeLabel({ assignee_user_id: "other", owner_user_id: null, queue_code: null }, ME)).toBe("Another person");
    expect(assigneeLabel({ assignee_user_id: null, owner_user_id: null, queue_code: "OPS" }, ME)).toBe("Queue: OPS");
    expect(assigneeLabel({ assignee_user_id: null, owner_user_id: null, queue_code: null }, ME)).toBe("Unassigned");
  });
});

describe("task drawer commands", () => {
  it("come only from allowed_transitions and allowed capabilities", () => {
    const task = parseTaskDetail({
      ...rawItem({ assignee_user_id: null }),
      facts: {},
      completion_check: "manual",
      completion_evidence: null,
      dismissal_reason_code: null,
      closed_at: null,
      created_at: "2026-10-11T10:00:00Z",
      allowed_transitions: [
        { action: "complete", to_status: "done", requires_reason: false },
        { action: "dismiss", to_status: "dismissed", requires_reason: true },
        { action: "archive", to_status: "archived", requires_reason: false },
      ],
    });
    const commands = taskCommands(task, ME);
    expect(commands.transitions.map((t) => t.action)).toEqual(["complete", "dismiss"]);
    expect(commands).toMatchObject({ assignToMe: true, snooze: true, unsnooze: false, review: null });
    const approval = {
      ...task,
      proposal_id: PROPOSAL,
      allowed_transitions: [],
      capabilities: { assign: { allowed: false, reason_code: "approvals_use_candidates" } },
    };
    expect(taskCommands(approval, ME)).toMatchObject({ transitions: [], assignToMe: false, snooze: false, review: `/inbox/approvals/${PROPOSAL}` });
  });

  it("send expected_version, the reason and an Idempotency-Key", async () => {
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: "http://127.0.0.1:3050",
      getCsrfToken: () => "csrf",
      fetch: async (request) => {
        seen.push(request.clone());
        return Response.json({ ...rawItem({ version: 3, state: "dismissed" }), allowed_transitions: [], facts: {} });
      },
    });
    const result = await transitionTask({ id: TASK, version: 2 }, "dismiss", { reasonCode: "duplicate", note: " same ", idempotencyKey: "k-1" }, client);
    expect(new URL(seen[0]!.url).pathname).toBe(`/api/v1/tasks/tasks/${TASK}/transitions`);
    expect(seen[0]!.headers.get("Idempotency-Key")).toBe("k-1");
    expect(await seen[0]!.json()).toEqual({ action: "dismiss", expected_version: 2, reason_code: "duplicate", note: "same" });
    expect(result).toMatchObject({ version: 3, state: "dismissed" });
  });
});
