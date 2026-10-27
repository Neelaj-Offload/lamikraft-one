/**
 * Pure view-model for Today: which items show, in which sections, which controls an item
 * offers and what a newer briefing brings. Order always comes from the server (section order,
 * `display_ordinal`, `initial_item_ids`); nothing here ranks or re-sorts.
 */

import { formatBusinessDate } from "@/lib/format/time";
import { briefingMessages as m } from "@/messages/briefing";
import { SECTION_CODES } from "./parse";
import type { BriefingAction, BriefingItem, BriefingView, PriorityBand, SectionCode } from "./types";

/** The six section codes (briefing.md §5); templates may order them differently (§15). */
export const SECTION_ORDER: readonly SectionCode[] = SECTION_CODES;

/** Two columns from wide screens up: work to do on the left, context on the right. */
export const MAIN_SECTIONS: ReadonlySet<SectionCode> = new Set(["needs_you_now", "plan_for_today", "recommendations"]);

export interface SectionModel {
  code: SectionCode;
  title: string;
  /** Items shown now, in server order. */
  items: BriefingItem[];
  /** Items of this section the server listed (may be fewer than `total` if it pages). */
  listed: number;
  total: number;
  /** Listed items hidden until the full list is shown. */
  hidden: number;
}

/**
 * Sections in the order the server sent them (a template may set `section_order`, briefing.md
 * §15), empty ones omitted (§3.4); unknown codes and repeats are skipped. In the initial view
 * only `initial_item_ids` (at most five) render; other non-empty sections render as a count.
 */
export function sectionModels(view: Pick<BriefingView, "sections" | "items" | "initial_item_ids">, showAll: boolean): SectionModel[] {
  const byId = new Map(view.items.map((item) => [item.id, item]));
  const initial = new Set(view.initial_item_ids);
  const seen = new Set<SectionCode>();
  const out: SectionModel[] = [];
  for (const section of view.sections) {
    const code = section.code;
    if (!SECTION_ORDER.includes(code) || seen.has(code)) continue;
    seen.add(code);
    if (section.total === 0) continue;
    const listed = section.item_ids.map((id) => byId.get(id)).filter((item): item is BriefingItem => Boolean(item));
    const items = showAll ? listed : listed.filter((item) => initial.has(item.id));
    out.push({
      code,
      title: m.sections[code],
      items,
      listed: listed.length,
      total: section.total,
      hidden: listed.length - items.length,
    });
  }
  return out;
}

/** Whether the full list holds more than the initial view. */
export function hasMoreThanInitial(view: Pick<BriefingView, "sections" | "initial_item_ids">): boolean {
  return totalItems(view) > view.initial_item_ids.length;
}

export function totalItems(view: Pick<BriefingView, "sections">): number {
  return view.sections.reduce((sum, section) => sum + section.total, 0);
}

type BriefingIdentity = Pick<BriefingView, "briefing_id" | "work_date">;
export type BriefingSnapshot = Pick<BriefingView, "briefing_id" | "work_date" | "version" | "status" | "items">;

/**
 * Whether two views belong to the same briefing. A briefing is per (user, work_date) and its
 * version numbers restart every day (briefing.md §2), so a version is only comparable within
 * one briefing: after the daily rollover "version 1" is newer than yesterday’s "version 5".
 */
export function isSameBriefing(a: BriefingIdentity, b: BriefingIdentity): boolean {
  if (a.work_date && b.work_date && a.work_date !== b.work_date) return false;
  if (a.briefing_id && b.briefing_id && a.briefing_id !== b.briefing_id) return false;
  return true;
}

/**
 * What a newly fetched briefing means for the one on screen (briefing.md §7: the list never
 * re-sorts until the person applies it):
 * - `none`: nothing to show (same version, or a failed regeneration while a briefing is shown);
 * - `in_place`: a newer version of the same briefing that moves no item (reworded text),
 *   or a refreshed fallback: applied without asking;
 * - `updates`: issues added, removed or changed: "N updates · Show";
 * - `new_briefing`: another day’s briefing (rollover), or the real briefing replacing the
 *   fallback: "Your briefing for … is ready · Show".
 */
export type BriefingChange =
  | { kind: "none" }
  | { kind: "in_place" }
  | { kind: "updates"; count: number }
  | { kind: "new_briefing"; workDate: string };

export function briefingChange(displayed: BriefingSnapshot, latest: BriefingSnapshot): BriefingChange {
  if (displayed === latest) return { kind: "none" };
  if (!isSameBriefing(displayed, latest)) return { kind: "new_briefing", workDate: latest.work_date };
  if (latest.status === "fallback") return displayed.status === "fallback" ? { kind: "in_place" } : { kind: "none" };
  if (displayed.status === "fallback") return { kind: "new_briefing", workDate: latest.work_date };
  if (latest.version === displayed.version) return { kind: "none" };
  const count = countChangedIssues(displayed.items, latest.items);
  return count === 0 ? { kind: "in_place" } : { kind: "updates", count };
}

/** Issues added, removed or whose fingerprint changed between two versions. */
export function countChangedIssues(before: readonly Pick<BriefingItem, "issue_id" | "fingerprint">[], after: readonly Pick<BriefingItem, "issue_id" | "fingerprint">[]): number {
  const was = new Map(before.map((item) => [item.issue_id, item.fingerprint]));
  const now = new Map(after.map((item) => [item.issue_id, item.fingerprint]));
  let count = 0;
  for (const [issue, fingerprint] of now) if (was.get(issue) !== fingerprint) count += 1;
  for (const issue of was.keys()) if (!now.has(issue)) count += 1;
  return count;
}

/**
 * The view to show after a background fetch: the first view as soon as one exists, an
 * `in_place` change applied at once, anything else left for the person to apply.
 */
export function reconcileDisplayed<T extends BriefingSnapshot>(displayed: T | null, latest: T | null): T | null {
  if (latest === null) return displayed;
  if (displayed === null) return latest;
  return briefingChange(displayed, latest).kind === "in_place" ? latest : displayed;
}

/** What the "… · Show" pill offers: N updates to the briefing on screen, or another briefing. */
export type PendingUpdate = { kind: "updates"; count: number } | { kind: "new_briefing"; day: string | null };

/** The pill for a fetched briefing, or null when there is nothing for the person to apply. */
export function pendingUpdateFor(displayed: BriefingSnapshot, latest: BriefingSnapshot, locale: string): PendingUpdate | null {
  const change = briefingChange(displayed, latest);
  if (change.kind === "updates") return { kind: "updates", count: change.count };
  if (change.kind === "new_briefing") {
    return { kind: "new_briefing", day: change.workDate ? formatBusinessDate(change.workDate, locale, "long") : null };
  }
  return null;
}

/**
 * Whether the UI poll reports a briefing the cached one is older than: another work date
 * (rollover), a higher version of the same day, or a version where only a fallback exists.
 */
export function pollShowsNewerBriefing(
  polled: { version: number | null; work_date: string | null },
  cached: Pick<BriefingView, "version" | "work_date">,
): boolean {
  if (polled.work_date && cached.work_date && polled.work_date !== cached.work_date) return true;
  if (polled.version === null) return false;
  return cached.version === null || polled.version > cached.version;
}

/** Actions the web can carry out today. Others the server offers are not shown (no dead controls). */
export const SUPPORTED_ACTIONS: ReadonlySet<string> = new Set([
  "open",
  "review",
  "prepare",
  "approve",
  "reject",
  "snooze",
  "mark_handled",
  "dismiss",
  "explain",
]);

/** Navigation actions need an href; command actions are POSTed. */
export function isNavigationAction(action: BriefingAction): boolean {
  return action.action === "open" || action.action === "review" || (action.action === "prepare" && Boolean(action.href));
}

function usable(action: BriefingAction): boolean {
  if (!SUPPORTED_ACTIONS.has(action.action)) return false;
  if ((action.action === "open" || action.action === "review") && !action.href) return false;
  return true;
}

/** The one primary control: the server's `primary` action, else its first usable action. */
export function primaryAction(item: Pick<BriefingItem, "allowed_actions">): BriefingAction | null {
  const candidates = item.allowed_actions.filter(usable);
  return candidates.find((action) => action.primary) ?? candidates.find((action) => action.action !== "explain") ?? null;
}

/** Everything else the server allows, filtered to what the web supports, in server order. */
export function secondaryActions(item: Pick<BriefingItem, "allowed_actions">): BriefingAction[] {
  const primary = primaryAction(item);
  return item.allowed_actions.filter((action) => usable(action) && action !== primary);
}

export function actionLabel(action: BriefingAction): string {
  return action.label ?? m.actions[action.action] ?? action.action;
}

export type StatusTone = "danger" | "warning" | "info" | "neutral" | "success";

/** Small status: what kind of thing this is, coloured by urgency (text always present). */
export function itemStatus(item: Pick<BriefingItem, "family" | "is_reminder" | "priority_band" | "overdue" | "section">): {
  label: string;
  tone: StatusTone;
} {
  const label = item.is_reminder ? m.status.reminder! : (m.status[item.family] ?? m.status.fallback!);
  if (item.section === "handled_for_you") return { label, tone: "success" };
  const band: Record<PriorityBand, StatusTone> = { P1: "danger", P2: "warning", P3: "info", P4: "neutral" };
  return { label, tone: item.overdue ? "danger" : band[item.priority_band] };
}
