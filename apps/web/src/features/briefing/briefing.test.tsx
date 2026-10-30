import { describe, expect, it, vi } from "vitest";
import { meeraBriefing, meeraBriefingWire, testItem } from "@/lib/test-support/briefing";
import { countTags, nestedInteractive, render, renderInSession, textOf } from "@/lib/test-support/render";
import { createApiClient } from "@/lib/api/client";
import { acknowledgeBriefing, snoozeItem, runItemAction, snoozeUntil } from "./api";
import { BriefingHeader } from "./briefing-header";
import { BriefingItemRow, dueLabel } from "./briefing-item-row";
import { BriefingSection, FallbackView, FullListToggle, UpdatesBanner } from "./briefing-sections";
import {
  briefingChange,
  hasMoreThanInitial,
  itemStatus,
  primaryAction,
  secondaryActions,
  sectionModels,
  totalItems,
} from "./model";
import { BriefingShapeError, parseBriefingView } from "./parse";
import type { BriefingView } from "./types";

const NOW = new Date("2026-10-12T03:25:00Z");
const IST = { timeZone: "Asia/Kolkata", locale: "en-IN" };
const noop = () => {};

describe("Today view-model", () => {
  it("shows at most the five initial items, sections in canonical order, empty ones omitted", () => {
    const view = meeraBriefing();
    const sections = sectionModels(view, false);
    expect(sections.map((s) => s.code)).toEqual([
      "needs_you_now",
      "plan_for_today",
      "recommendations",
      "changes_since_last_visit",
      "coming_next",
    ]);
    expect(sections.flatMap((s) => s.items).map((i) => i.id)).toEqual(["i1", "i2", "i3", "i4", "i5"]);
    const coming = sections.find((s) => s.code === "coming_next")!;
    expect(coming).toMatchObject({ items: [], hidden: 1, total: 1 });
    expect(sections.find((s) => s.code === "handled_for_you")).toBeUndefined();
    expect(totalItems(view)).toBe(6);
    expect(hasMoreThanInitial(view)).toBe(true);
  });

  it("shows every item with the full list, in server order", () => {
    const sections = sectionModels(meeraBriefing(), true);
    expect(sections.flatMap((s) => s.items).map((i) => i.id)).toEqual(["i1", "i2", "i3", "i4", "i5", "i6"]);
    expect(sections.every((s) => s.hidden === 0)).toBe(true);
  });

  it("counts updates by issue and never re-sorts", () => {
    const displayed = meeraBriefing();
    const latest: BriefingView = {
      ...displayed,
      version: 2,
      items: [
        ...displayed.items.slice(0, 2).map((item) => (item.id === "i2" ? { ...item, fingerprint: "fp-i2-2" } : item)),
        ...displayed.items.slice(3),
        testItem({ id: "i7", section: "needs_you_now", title: "New enquiry from Thornbury" }),
      ],
    };
    // i2 changed, i3 removed, i7 added
    expect(briefingChange(displayed, latest)).toEqual({ kind: "updates", count: 3 });
    expect(briefingChange(displayed, displayed)).toEqual({ kind: "none" });
    // A newer version that moves nothing is applied in place, without a pill.
    expect(briefingChange(displayed, { ...displayed, version: 2 })).toEqual({ kind: "in_place" });
  });

  it("picks one primary control and offers only supported server actions", () => {
    const item = meeraBriefing().items[0]!;
    expect(primaryAction(item)?.action).toBe("open");
    // assign without a task link has nowhere to go, so it is not shown.
    expect(secondaryActions(item).map((a) => a.action)).toEqual(["snooze", "mark_handled", "explain"]);
    const noHref = testItem({
      id: "x",
      section: "needs_you_now",
      allowed_actions: [
        { action: "review", label: null, primary: true, href: null, requires_reason: false, via: "briefings", max_until: null },
        { action: "approve", label: null, primary: false, href: null, requires_reason: false, via: "approvals", max_until: null },
        { action: "mark_handled", label: null, primary: false, href: null, requires_reason: false, via: "briefings", max_until: null },
      ],
    });
    // review without a link and approve (decided on the review page) are never offered.
    expect(primaryAction(noHref)?.action).toBe("mark_handled");
    expect(primaryAction(testItem({ id: "y", section: "coming_next" }))).toBeNull();
  });

  it("labels status by family with urgency colour", () => {
    expect(itemStatus(testItem({ id: "a", section: "needs_you_now", family: "common.approvals", priority_band: "P1" }))).toEqual({
      label: "Decision",
      tone: "danger",
    });
    expect(itemStatus(testItem({ id: "b", section: "coming_next", is_reminder: true, priority_band: "P4" }))).toEqual({
      label: "Reminder",
      tone: "neutral",
    });
    expect(itemStatus(testItem({ id: "c", section: "handled_for_you", family: "x.unknown" }))).toEqual({ label: "Task", tone: "success" });
  });

  it("labels deadlines in the user's zone", () => {
    const item = meeraBriefing().items[0]!;
    expect(dueLabel(item, NOW, IST)).toMatch(/^Due Today, 6:30\spm$/i);
    expect(dueLabel({ ...item, overdue: true }, NOW, IST)).toMatch(/^Overdue · Due Today/);
    expect(dueLabel({ ...item, due_kind: "soft" }, NOW, IST)).toMatch(/^Target Today/);
    expect(dueLabel({ ...item, due_kind: "none" }, NOW, IST)).toBeNull();
    // The server's own text wins when it sends one.
    expect(dueLabel({ ...item, due_label: "Due today, 11:59 pm" }, NOW, IST)).toBe("Due today, 11:59 pm");
  });
});

describe("parseBriefingView (briefings/schemas.py BriefingView)", () => {
  it("maps the wire view: issue ids, sections, initial view, sentence and update counts", () => {
    const view = parseBriefingView(meeraBriefingWire());
    expect(view.items.map((i) => i.id)).toEqual(["w1", "w2", "w3"]);
    expect(view.sections).toEqual([
      { code: "needs_you_now", total: 2, item_ids: ["w1", "w2"] },
      { code: "plan_for_today", total: 1, item_ids: ["w3"] },
    ]);
    expect(view.initial_item_ids).toEqual(["w1", "w2", "w3"]);
    expect(view.overview).toMatchObject({ greeting: "Good morning, Meera.", text: "Two customer replies need attention and one quote expires today." });
    expect(view).toMatchObject({ version: 2, latest_version: 3, pending_updates: 1, up_to_date: false, ai_status: "not_used" });
    const first = view.items[0]!;
    expect(first).toMatchObject({ priority_band: "P1", summary_text: "LK-QT-2026-0006 · EUR 5,700.00", due_label: "Due today, 11:59 pm", reasons: ["Expires today"] });
    expect(first.recommendation).toMatchObject({ reason_text: "The quote expires at the end of today.", effect_text: "Keeps the offer open.", alternatives: ["Snooze", "Dismiss with reason"] });
    expect(first.uncertainty_flags).toEqual([{ code: "DEMO_DATA", label: "Demo data" }]);
  });

  it("maps actions: resource paths become app routes, dismiss gets the server's reason codes", () => {
    const view = parseBriefingView(meeraBriefingWire());
    const [first, decision] = view.items;
    const byAction = Object.fromEntries(first!.allowed_actions.map((a) => [a.action, a]));
    expect(byAction.open!.href).toBe("/sales/quotes/0192a000-0000-7000-8000-000000000038");
    expect(byAction.assign!.href).toBe("/inbox?task=0192a000-0000-7000-8000-0000000000f1");
    expect(byAction.snooze!.max_until).toBe("2026-10-12T12:00:00Z");
    expect(byAction.dismiss!.reasons!.map((r) => r.code)).toEqual([
      "handled_outside_system",
      "not_applicable",
      "duplicate",
      "customer_withdrew",
      "no_action_needed",
    ]);
    // Decisions are taken on the review page: approve/reject (via approvals) are not row actions.
    expect(decision!.allowed_actions.map((a) => a.action)).toEqual(["open", "review", "explain"]);
    expect(decision!.allowed_actions[1]!.href).toBe("/inbox/approvals/0192a000-0000-7000-8000-0000000000a5");
    expect(primaryAction(decision!)?.action).toBe("open");
  });

  it("reports missing fields instead of rendering half a briefing", () => {
    const raw = JSON.parse(JSON.stringify(meeraBriefingWire()));
    delete raw.version;
    delete raw.items[1].fingerprint;
    expect(() => parseBriefingView(raw)).toThrow(BriefingShapeError);
    try {
      parseBriefingView(raw);
    } catch (error) {
      expect((error as BriefingShapeError).problems).toEqual(expect.arrayContaining(["version", "items[1].fingerprint"]));
    }
  });

  it("keeps a ready briefing whose overview was withheld (permissions changed)", () => {
    const raw = { ...meeraBriefingWire(), overview: null };
    expect(parseBriefingView(raw).overview).toBeNull();
  });

  it("drops off-site links and caps the initial view at five", () => {
    const raw = JSON.parse(JSON.stringify(meeraBriefingWire()));
    raw.items[0].source_refs[0].path = "https://evil.example/q";
    raw.items[0].allowed_actions[0].path = "//evil.example";
    raw.items[1].source_refs = [{ type: "x", id: "b", label: "Backslash", path: "/\\evil.example/phish" }];
    raw.items[1].allowed_actions = [{ action: "open", via: "briefings", path: "/\t/evil.example" }];
    raw.initial_view = ["w1", "w2", "w3", "w4", "w5", "w6"];
    const view = parseBriefingView(raw);
    expect(view.items[0]!.source_refs[0]!.href).toBeNull();
    expect(view.items[0]!.allowed_actions[0]!.href).toBeNull();
    expect(view.items[1]!.source_refs[0]!.href).toBeNull();
    expect(view.items[1]!.allowed_actions[0]!.href).toBeNull();
    expect(view.initial_item_ids).toHaveLength(5);
  });

  it("requires the fallback block when the status is fallback", () => {
    const raw = { ...meeraBriefingWire(), status: "fallback", fallback_detail: null };
    expect(() => parseBriefingView(raw)).toThrow(BriefingShapeError);
  });

  it("reads an engine-failure fallback without a version or overview (briefing.md §11)", () => {
    const view = parseBriefingView({
      briefing_id: null,
      work_date: "2026-10-12",
      status: "fallback",
      version: null,
      overview: null,
      sections: [],
      items: [],
      fallback_detail: {
        error_code: "engine_failed",
        failed_at: "2026-10-12T03:32:00Z",
        tasks: [{ id: "t1", title: "Reply to Nordhaus", source_refs: [{ type: "sales.customer_message", id: "m1", label: "Message", path: "/sales/customer-messages" }] }],
        last_successful: null,
      },
    });
    expect(view).toMatchObject({ status: "fallback", version: null, overview: null, briefing_id: null });
    expect(view.fallback).toMatchObject({ error_at: "2026-10-12T03:32:00Z", error_code: "engine_failed" });
    expect(view.fallback?.tasks.map((task) => task.title)).toEqual(["Reply to Nordhaus"]);
    expect(view.fallback?.tasks[0]!.source?.href).toBe("/sales/customer-messages");
    // A ready briefing still needs its version.
    expect(() => parseBriefingView({ ...meeraBriefingWire(), version: null })).toThrow(BriefingShapeError);
  });
});

describe("item commands (POST briefings/items/{issue_id}/actions)", () => {
  it("send the action, Idempotency-Key, briefing version and item fingerprint; nothing else", async () => {
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: "http://127.0.0.1:3050",
      getCsrfToken: () => "csrf",
      fetch: async (request) => {
        seen.push(request.clone());
        return Response.json({ action: "mark_handled", issue_id: "issue-i1", outcome: "completed" });
      },
    });
    const item = meeraBriefing().items[0]!;
    await runItemAction({ item, action: "mark_handled", briefingVersion: 3, idempotencyKey: "key-1" }, client);
    await snoozeItem({ item, until: "2026-10-12T04:25:00Z", briefingVersion: 3, idempotencyKey: "key-2" }, client);
    await runItemAction({ item, action: "dismiss", reasonCode: "duplicate", note: "  same as 0005 ", briefingVersion: 3, idempotencyKey: "key-3" }, client);
    await runItemAction({ item, action: "dismiss", reasonCode: "price_too_high", briefingVersion: 3, idempotencyKey: "key-4" }, client);

    for (const request of seen) expect(new URL(request.url).pathname).toBe("/api/v1/briefings/items/issue-i1/actions");
    expect(seen[0]!.headers.get("Idempotency-Key")).toBe("key-1");
    expect(seen[0]!.headers.get("X-CSRF-Token")).toBe("csrf");
    expect(await seen[0]!.json()).toEqual({ action: "mark_handled", briefing_version: 3, item_fingerprint: "fp-i1-1" });
    expect(await seen[1]!.json()).toEqual({ action: "snooze", until: "2026-10-12T04:25:00Z", briefing_version: 3, item_fingerprint: "fp-i1-1" });
    expect(await seen[2]!.json()).toEqual({ action: "dismiss", reason_code: "duplicate", note: "same as 0005", briefing_version: 3, item_fingerprint: "fp-i1-1" });
    // A code outside the server's enum is never sent.
    expect(await seen[3]!.json()).toEqual({ action: "dismiss", briefing_version: 3, item_fingerprint: "fp-i1-1" });
  });

  it("acknowledges the version on screen explicitly", async () => {
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: "http://127.0.0.1:3050",
      getCsrfToken: () => "csrf",
      fetch: async (request) => {
        seen.push(request.clone());
        return Response.json({ accepted: true });
      },
    });
    await acknowledgeBriefing("b-1", 2, "key-ack", client);
    expect(new URL(seen[0]!.url).pathname).toBe("/api/v1/briefings/b-1/acknowledge");
    expect(seen[0]!.headers.get("Idempotency-Key")).toBe("key-ack");
    expect(await seen[0]!.json()).toEqual({ version: 2, method: "explicit" });
  });

  it("computes snooze instants in UTC, capped at the server's max_until", () => {
    expect(snoozeUntil("1h", NOW)).toBe("2026-10-12T04:25:00Z");
    expect(snoozeUntil("24h", NOW)).toBe("2026-10-13T03:25:00Z");
    expect(snoozeUntil("24h", NOW, "2026-10-12T12:00:00Z")).toBe("2026-10-12T12:00:00Z");
    expect(snoozeUntil("1h", NOW, "2026-10-12T12:00:00Z")).toBe("2026-10-12T04:25:00Z");
  });
});

describe("Today components", () => {
  it("BriefingHeader: one h1 greeting and one factual sentence from the server", () => {
    const html = render(
      <BriefingHeader
        greeting="Good morning, Meera."
        overview="Two customer replies need attention."
        meta="Monday, 12 October · Updated 8:55 am"
        wording={{ label: "Standard wording", hint: "Template text." }}
      />,
    );
    expect(countTags(html, "h1")).toBe(1);
    expect(html).toMatch(/<h1[^>]*>Good morning, Meera\.<\/h1>/);
    expect(textOf(html)).toContain("Two customer replies need attention.");
    expect(textOf(html)).toContain("Standard wording");
  });

  it("BriefingItemRow: status, problem, recommendation, evidence and one primary control", () => {
    const item = meeraBriefing().items[0]!;
    const html = renderInSession(<BriefingItemRow item={item} now={NOW} zone={IST} onCommand={noop} />);
    const text = textOf(html);
    expect(text).toContain("Quote expiry");
    expect(html).toMatch(/<h3[^>]*>Berg &amp; Co AB quote expires today<\/h3>/);
    expect(text).toContain("Suggested: Extend the validity or confirm the order today.");
    expect(html).toContain('href="/sales/quotes/q38"');
    expect(text).toContain("Quote LK-QT-2026-0038");
    expect(text).toMatch(/Updated 8:45\sam/i);
    // exactly one primary control (the Open quote link) plus the More actions menu button
    expect(countTags(html, "a", "bg-forest")).toBe(1);
    expect(html).toContain('aria-label="More actions for Berg &amp; Co AB quote expires today"');
    expect(text).toContain("Why is this here?");
    expect(nestedInteractive(html)).toEqual([]);
  });

  it("BriefingItemRow: no controls when the server allows none, or read-only", () => {
    const bare = renderInSession(<BriefingItemRow item={testItem({ id: "z", section: "coming_next" })} now={NOW} zone={IST} onCommand={noop} />);
    expect(countTags(bare, "button")).toBe(0);
    const readOnly = renderInSession(<BriefingItemRow item={meeraBriefing().items[0]!} now={NOW} zone={IST} onCommand={noop} readOnly />);
    expect(readOnly).not.toContain("More actions");
    expect(countTags(readOnly, "a", "bg-forest")).toBe(0);
  });

  it("BriefingSection: labelled list; hidden items offer the full list", () => {
    const section = sectionModels(meeraBriefing(), false).find((s) => s.code === "coming_next")!;
    const html = renderInSession(<BriefingSection section={section} now={NOW} zone={IST} onCommand={noop} pending={null} onShowAll={noop} />);
    expect(html).toMatch(/<section aria-labelledby="([^"]+)"[^>]*><h2 id="\1"/);
    expect(textOf(html)).toContain("Coming next");
    expect(textOf(html)).toContain("1 more item in the full list");
  });

  it("UpdatesBanner renders nothing until there are updates", () => {
    expect(render(<UpdatesBanner update={{ kind: "updates", count: 0 }} onShow={noop} />)).toBe("");
    const html = render(<UpdatesBanner update={{ kind: "updates", count: 3 }} onShow={noop} />);
    expect(textOf(html)).toBe("3 updates Show");
  });

  it("FullListToggle reports its state", () => {
    expect(render(<FullListToggle expanded={false} total={6} controls="list" onToggle={noop} />)).toContain('aria-expanded="false"');
    expect(textOf(render(<FullListToggle expanded={false} total={6} controls="list" onToggle={noop} />))).toBe(
      "See all work for today (6)",
    );
  });

  it("FallbackView: timestamped banner, current tasks and the last briefing", () => {
    const last = meeraBriefing();
    const html = renderInSession(
      <FallbackView
        fallback={{
          error_at: "2026-10-12T03:32:00Z",
          error_code: "engine_failed",
          tasks: [
            {
              id: "t1",
              title: "Reply to Berg & Co AB",
              due_at: "2026-10-12T13:00:00Z",
              due_kind: "hard",
              overdue: false,
              source: { type: "sales.message", id: "m2", label: "Message from Berg", href: "/sales/messages/m2", updated_at: null },
            },
          ],
          last_successful: { version: 3, generated_at: "2026-10-09T03:30:00Z", data_as_of: "2026-10-09T03:30:00Z", overview: last.overview, items: last.items.slice(0, 1) },
        }}
        now={NOW}
        zone={IST}
        onRetry={vi.fn()}
        isRetrying={false}
      />,
    );
    const text = textOf(html);
    expect(html).toContain('role="alert"');
    expect(text).toMatch(/Today's briefing couldn't be prepared/);
    expect(text).toMatch(/Prepared at Today, 9:02\sam without success\. Showing your current tasks and the last briefing from Fri/i);
    expect(text).toContain("Try again");
    expect(html).toContain('href="/sales/messages/m2"');
    expect(text).toContain("Berg & Co AB quote expires today");
    // the last briefing is read-only: no item controls
    expect(html).not.toContain("More actions");
  });
});
