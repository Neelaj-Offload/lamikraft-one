/**
 * Today page behaviour beyond the presentational pieces: the on-screen snapshot (never
 * re-sorted until the person applies an update), the daily rollover, the fallback, offline,
 * refetches after the person's own action, and the page's error states.
 */

import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { afterEach, describe, expect, it } from "vitest";
import { createApiClient } from "@/lib/api/client";
import { NetworkError, NON_PROBLEM_CODE, ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { meeraBriefing, testItem } from "@/lib/test-support/briefing";
import { controlsWithoutVisibleFocus, renderInSession, renderWithQueries, seedQueryError, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { fetchExplanation, receiptHref } from "./api";
import { BriefingItemRow } from "./briefing-item-row";
import { UpdatesBanner, updateAnnouncement } from "./briefing-sections";
import { commandBarProps } from "./command-bar";
import { dialogIdentity, reasonToSubmit } from "./item-dialogs";
import {
  briefingChange,
  pendingUpdateFor,
  pollShowsNewerBriefing,
  reconcileDisplayed,
  sectionModels,
} from "./model";
import { BriefingShapeError, parseBriefingView, parseExplanation } from "./parse";
import { refetchBriefing } from "./refresh";
import { TodayView } from "./today-view";
import type { BriefingView } from "./types";

const TODAY = queryKeys.briefings.today();
const NOW = new Date("2026-10-12T03:25:00Z");
const IST = { timeZone: "Asia/Kolkata", locale: "en-IN" };
const noop = () => {};

function version(view: BriefingView, n: number, changes: Partial<BriefingView> = {}): BriefingView {
  return { ...view, version: n, ...changes };
}

const notFound = () =>
  new ProblemError({ code: NON_PROBLEM_CODE, title: "Not Found", status: 404, detail: "Not Found", request_id: null });

describe("Today snapshot: what a fetched briefing does to the list on screen", () => {
  const v1 = meeraBriefing();

  it("applies only the first view and in-place changes; updates wait for Show", () => {
    expect(reconcileDisplayed(null, v1)).toBe(v1);
    expect(reconcileDisplayed(v1, null)).toBe(v1);
    // Same version fetched again (focus refetch): nothing changes on screen.
    expect(reconcileDisplayed(v1, { ...v1 })).toBe(v1);
    // A newer version that moves no item (reworded text) is applied in place.
    const reworded = version(v1, 2, { overview: { ...v1.overview!, text: "Reworded." } });
    expect(reconcileDisplayed(v1, reworded)).toBe(reworded);
    // A newer version that changes an item waits behind the pill.
    const changed = version(v1, 2, { items: v1.items.map((item) => (item.id === "i2" ? { ...item, fingerprint: "fp-i2-2" } : item)) });
    expect(reconcileDisplayed(v1, changed)).toBe(v1);
    expect(briefingChange(v1, changed)).toEqual({ kind: "updates", count: 1 });
  });

  it("compares versions only within one briefing: the rollover is a new briefing, never 'no updates'", () => {
    const yesterday = version(v1, 5);
    const today = version(v1, 1, { briefing_id: "b2", work_date: "2026-10-13" });
    expect(briefingChange(yesterday, today)).toEqual({ kind: "new_briefing", workDate: "2026-10-13" });
    // Same version number on another day is still another briefing.
    expect(briefingChange(yesterday, version(today, 5))).toMatchObject({ kind: "new_briefing" });
    // A different briefing id on the same date (re-created) also counts as new.
    expect(briefingChange(v1, { ...v1, briefing_id: "b9" })).toMatchObject({ kind: "new_briefing" });
    expect(reconcileDisplayed(yesterday, today)).toBe(yesterday);
    expect(pendingUpdateFor(yesterday, today, "en-IN")).toEqual({ kind: "new_briefing", day: expect.stringMatching(/^Tuesday,? 13 October$/) });
  });

  it("handles the fallback: a failed regeneration never replaces a briefing; the real briefing is offered", () => {
    const fallback = parseBriefingView({ status: "fallback", version: null, overview: null, fallback: { error_at: "2026-10-12T03:32:00Z", tasks: [] } });
    expect(briefingChange(v1, { ...fallback, briefing_id: v1.briefing_id, work_date: v1.work_date })).toEqual({ kind: "none" });
    expect(briefingChange(fallback, { ...fallback })).toEqual({ kind: "in_place" });
    expect(briefingChange({ ...fallback, work_date: v1.work_date }, v1)).toMatchObject({ kind: "new_briefing" });
  });

  it("asks for a refetch when the poll reports another work date or a higher version", () => {
    const cached = version(v1, 5);
    expect(pollShowsNewerBriefing({ version: 1, work_date: "2026-10-13" }, cached)).toBe(true);
    expect(pollShowsNewerBriefing({ version: null, work_date: "2026-10-13" }, cached)).toBe(true);
    expect(pollShowsNewerBriefing({ version: 6, work_date: "2026-10-12" }, cached)).toBe(true);
    expect(pollShowsNewerBriefing({ version: 5, work_date: "2026-10-12" }, cached)).toBe(false);
    expect(pollShowsNewerBriefing({ version: 4, work_date: null }, cached)).toBe(false);
    expect(pollShowsNewerBriefing({ version: 1, work_date: "2026-10-12" }, { ...cached, version: null })).toBe(true);
  });

  it("keeps the server's section order (templates may reorder sections)", () => {
    const view = meeraBriefing();
    const reordered = {
      ...view,
      sections: [
        { code: "coming_next" as const, total: 1, item_ids: ["i6"] },
        { code: "needs_you_now" as const, total: 2, item_ids: ["i1", "i2"] },
        { code: "needs_you_now" as const, total: 2, item_ids: ["i1", "i2"] },
        { code: "recommendations" as const, total: 1, item_ids: ["i4"] },
      ],
    };
    expect(sectionModels(reordered, true).map((s) => s.code)).toEqual(["coming_next", "needs_you_now", "recommendations"]);
  });
});

describe("refetchBriefing: after the person's own action, only data fetched after it is applied", () => {
  const clients: QueryClient[] = [];
  afterEach(() => {
    for (const client of clients.splice(0)) client.clear();
  });

  async function setup(first: BriefingView) {
    const responses: Array<() => Promise<BriefingView>> = [async () => first];
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Number.POSITIVE_INFINITY } } });
    clients.push(client);
    const observer = new QueryObserver<BriefingView>(client, { queryKey: TODAY, queryFn: () => responses.shift()!() });
    observer.subscribe(noop);
    await expect.poll(() => observer.getCurrentResult().data).toBe(first);
    return { client, responses };
  }

  it("returns the post-action version, not the version the poll had already cached", async () => {
    const v1 = meeraBriefing();
    const { client, responses } = await setup(v1);
    client.setQueryData(TODAY, version(v1, 2)); // fetched by the poll; the pill offers it
    responses.push(async () => version(v1, 3, { items: v1.items.slice(1) }));
    const fresh = await refetchBriefing(client, TODAY);
    expect(fresh?.version).toBe(3);
    expect(fresh?.items.map((item) => item.id)).not.toContain("i1");
  });

  it("returns null when the refetch fails, leaving nothing pending", async () => {
    const v1 = meeraBriefing();
    const { client, responses } = await setup(v1);
    responses.push(async () => {
      throw new NetworkError(new TypeError("offline"));
    });
    expect(await refetchBriefing(client, TODAY)).toBeNull();
    expect(client.getQueryData<BriefingView>(TODAY)).toBe(v1);
  });

  it("returns the data even when the refetch is deep-equal to what is cached", async () => {
    const v1 = meeraBriefing();
    const { client, responses } = await setup(v1);
    responses.push(async () => JSON.parse(JSON.stringify(v1)) as BriefingView);
    const fresh = await refetchBriefing(client, TODAY);
    expect(fresh).toEqual(v1);
  });

  it("ignores a fetch that was already in flight with pre-action data", async () => {
    const v1 = meeraBriefing();
    const { client, responses } = await setup(v1);
    let releaseStale: (view: BriefingView) => void = noop;
    responses.push(() => new Promise<BriefingView>((resolve) => (releaseStale = resolve)));
    void client.refetchQueries({ queryKey: TODAY });
    await Promise.resolve();
    responses.push(async () => version(v1, 4));
    const pendingFresh = refetchBriefing(client, TODAY);
    releaseStale(version(v1, 2));
    expect((await pendingFresh)?.version).toBe(4);
    expect(client.getQueryData<BriefingView>(TODAY)?.version).toBe(4);
  });
});

describe("TodayView (server render)", () => {
  it("shows a calm 'not available yet' with Retry, and no link back to the page itself", () => {
    const html = renderWithQueries(<TodayView />, (client) => seedQueryError(client, TODAY, notFound()));
    const text = textOf(html);
    expect(text).toContain("Your briefing isn't available yet");
    expect(text).toContain("Try again");
    expect(html).not.toContain('href="/today"');
    expect(html).toMatch(/<h1[^>]*>Today<\/h1>/);
  });

  it("shows Offline when the first load could not reach the server", () => {
    const html = renderWithQueries(<TodayView />, (client) => seedQueryError(client, TODAY, new NetworkError(new TypeError("down"))));
    expect(textOf(html)).toContain("You're offline");
  });

  it("dates the briefing by its work date, not the browser's clock (00:10 belongs to the previous day)", () => {
    // 2026-10-12T18:40Z is 00:10 on Tuesday 13 October in Kolkata; the rollover is 04:00.
    const bootstrap = testBootstrap({ server_now: "2026-10-12T18:40:00Z" });
    const html = renderWithQueries(<TodayView />, (client) => client.setQueryData(TODAY, meeraBriefing()), bootstrap);
    const text = textOf(html);
    expect(text).toMatch(/Monday,? 12 October/);
    expect(text).not.toMatch(/Tuesday/);
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("renders an engine-failure fallback that has no version or overview", () => {
    const fallback = parseBriefingView({
      status: "fallback",
      version: null,
      overview: null,
      sections: [],
      items: [],
      fallback: { error_at: "2026-10-12T03:32:00Z", tasks: [{ id: "t1", title: "Reply to Nordhaus" }], last_successful: null },
    });
    expect(fallback.version).toBeNull();
    const html = renderWithQueries(<TodayView />, (client) => client.setQueryData(TODAY, fallback));
    const text = textOf(html);
    expect(html).toMatch(/<h1[^>]*>Today<\/h1>/);
    expect(html).toContain('role="alert"');
    expect(text).toContain("Today's briefing couldn't be prepared");
    expect(text).toContain("Reply to Nordhaus");
    expect(text).not.toContain("See all work for today");
  });

  it("labels the cached briefing 'Offline · as of' and disables commands after a network failure", () => {
    const view = meeraBriefing();
    view.items[1] = testItem({
      id: "i2",
      section: "needs_you_now",
      title: "Reply to Berg & Co AB",
      allowed_actions: [{ action: "mark_handled", label: null, primary: true, href: null, requires_reason: false }],
    });
    const html = renderWithQueries(<TodayView />, (client) => {
      client.setQueryData(TODAY, view);
      client.getQueryCache().find({ queryKey: TODAY })!.setState({ status: "error", error: new NetworkError(new TypeError("down")) });
    });
    const text = textOf(html);
    expect(text).toMatch(/Offline · as of Today, 8:55\sam/i);
    expect(text).not.toContain("This may be out of date");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>(?:(?!<\/button>).)*Mark handled/);
    expect(text).toContain("Actions are disabled until the connection is back.");
    // Links to records stay available.
    expect(html).toContain('href="/sales/quotes/q38"');
  });

  it("keeps push-to-talk away while no recorder is wired, even with the voice capability", () => {
    const bootstrap = testBootstrap({ capabilities: { assistant: false, voice: true } });
    const html = renderWithQueries(<TodayView />, (client) => client.setQueryData(TODAY, meeraBriefing()), bootstrap);
    expect(html).not.toContain("Hold to talk");
  });
});

describe("command bar capabilities", () => {
  const recorder = { onPressStart: noop, onPressEnd: noop, isRecording: false };
  const submit = async () => {};

  it("renders push-to-talk only with the voice flag and a recorder", () => {
    expect(commandBarProps({ assistant: false, voice: true }, { recorder, submit: null }).voice).toBe(recorder);
    expect(commandBarProps({ assistant: false, voice: false }, { recorder, submit: null }).voice).toBeNull();
    expect(commandBarProps({ assistant: false, voice: true }, { recorder: null, submit: null }).voice).toBeNull();
  });

  it("enables typed commands only with the assistant flag and a sender, and otherwise says why", () => {
    expect(commandBarProps({ assistant: true, voice: false }, { recorder: null, submit }).onSubmit).toBe(submit);
    expect(commandBarProps({ assistant: false, voice: false }, { recorder: null, submit }).onSubmit).toBeUndefined();
    const notWired = commandBarProps({ assistant: true, voice: false }, { recorder: null, submit: null });
    expect(notWired.onSubmit).toBeUndefined();
    expect(notWired.unavailableReason).toMatch(/can't be sent from Today yet/);
    expect(commandBarProps({ assistant: false, voice: false }, { recorder: null, submit: null }).unavailableReason).toMatch(/isn't switched on/);
  });
});

describe("updates pill", () => {
  it("is not a live region of its own (the page announces once) and renders nothing without an update", () => {
    expect(renderInSession(<UpdatesBanner update={null} onShow={noop} />)).toBe("");
    expect(renderInSession(<UpdatesBanner update={{ kind: "updates", count: 0 }} onShow={noop} />)).toBe("");
    const html = renderInSession(<UpdatesBanner update={{ kind: "updates", count: 3 }} onShow={noop} />);
    expect(html).not.toContain("aria-live");
    expect(textOf(html)).toBe("3 updates Show");
    expect(textOf(renderInSession(<UpdatesBanner update={{ kind: "new_briefing", day: "Tuesday, 13 October" }} onShow={noop} />))).toBe(
      "Your briefing for Tuesday, 13 October is ready Show",
    );
    expect(updateAnnouncement({ kind: "updates", count: 1 })).toBe("1 update to your briefing is ready. Press Show to see it.");
  });
});

describe("item dialogs", () => {
  const reasons = [
    { code: "duplicate", label: "Duplicate" },
    { code: "not_relevant", label: "Not relevant" },
  ];

  it("never submits a reason the current action does not offer", () => {
    expect(reasonToSubmit("duplicate", reasons)).toBe("duplicate");
    expect(reasonToSubmit("price_too_high", reasons)).toBeNull();
    expect(reasonToSubmit(null, reasons)).toBeNull();
  });

  it("resets when the dialog opens for another item or action", () => {
    const item = meeraBriefing().items[0]!;
    expect(dialogIdentity(false, item, { action: "dismiss" })).toBeNull();
    expect(dialogIdentity(true, item, { action: "dismiss" })).toBe("issue-i1:dismiss");
    expect(dialogIdentity(true, item, { action: "reject" })).not.toBe(dialogIdentity(true, item, { action: "dismiss" }));
    expect(dialogIdentity(true, meeraBriefing().items[1]!, { action: "dismiss" })).not.toBe("issue-i1:dismiss");
  });
});

describe("offline item row", () => {
  it("disables command controls with the reason and keeps navigation", () => {
    const item = testItem({
      id: "c",
      section: "needs_you_now",
      title: "Approve the price change",
      allowed_actions: [
        { action: "approve", label: null, primary: true, href: null, requires_reason: false },
        { action: "open", label: "Open quote", primary: false, href: "/sales/quotes/q1", requires_reason: false },
      ],
    });
    const html = renderInSession(<BriefingItemRow item={item} now={NOW} zone={IST} onCommand={noop} commandsDisabledReason="You're offline." />);
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>(?:(?!<\/button>).)*Approve/);
    expect(textOf(html)).toContain("You're offline.");
    const online = renderInSession(<BriefingItemRow item={item} now={NOW} zone={IST} onCommand={noop} />);
    expect(online).not.toMatch(/<button[^>]*disabled=""[^>]*>(?:(?!<\/button>).)*Approve/);
  });
});

describe("Explain and receipts", () => {
  it("reads reasons given as objects and drops sources that leave the app", () => {
    const explanation = parseExplanation({
      text: "Due today and not confirmed.",
      reasons: [{ code: "DUE_TODAY", text: "The quote expires today." }, "No reply since Friday.", { code: "STALE" }, 7],
      sources: [
        { type: "sales.quote", id: "q1", label: "Quote 1", href: "/sales/quotes/q1" },
        { type: "x", id: "evil", label: "Evil", href: "/\\evil.example/phish" },
        { type: "x", id: "abs", label: "Absolute", href: "https://evil.example" },
      ],
      rule_version: "r3",
    });
    expect(explanation.reasons).toEqual(["The quote expires today.", "No reply since Friday.", "STALE"]);
    expect(explanation.sources.map((source) => source.href)).toEqual(["/sales/quotes/q1", null, null]);
    expect(() => parseExplanation({ reasons: [] })).toThrow(BriefingShapeError);
    expect(() => parseExplanation("nope")).toThrow(BriefingShapeError);
  });

  it("fetches Explain through the parser, so a bad shape is an error state, not a crash", async () => {
    const client = createApiClient({ baseUrl: "http://127.0.0.1:3050", fetch: async () => Response.json({ reasons: [{ code: "X" }] }) });
    await expect(fetchExplanation("issue-1", undefined, client)).rejects.toBeInstanceOf(BriefingShapeError);
  });

  it("links a receipt only when it stays in the app", () => {
    expect(receiptHref({ href: "/sales/quotes/q1" })).toBe("/sales/quotes/q1");
    expect(receiptHref({ href: "/\\evil.example" })).toBeNull();
    expect(receiptHref({ href: "https://evil.example" })).toBeNull();
    expect(receiptHref(null)).toBeNull();
  });
});
