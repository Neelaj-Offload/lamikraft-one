/**
 * Pure view-model for Today: which items show, in which sections, which controls an item
 * offers and how many updates a newer version brings. Order always comes from the server
 * (`display_ordinal`, `initial_item_ids`); nothing here ranks or re-sorts.
 */

import { briefingMessages as m } from "@/messages/briefing";
import type { BriefingAction, BriefingItem, BriefingView, PriorityBand, SectionCode } from "./types";

export const SECTION_ORDER: readonly SectionCode[] = [
  "needs_you_now",
  "plan_for_today",
  "recommendations",
  "changes_since_last_visit",
  "handled_for_you",
  "coming_next",
];

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
 * Sections in canonical order, empty ones omitted (briefing.md §3.4). In the initial view only
 * `initial_item_ids` (at most five) render; other non-empty sections render as a count.
 */
export function sectionModels(view: Pick<BriefingView, "sections" | "items" | "initial_item_ids">, showAll: boolean): SectionModel[] {
  const byId = new Map(view.items.map((item) => [item.id, item]));
  const initial = new Set(view.initial_item_ids);
  const byCode = new Map(view.sections.map((section) => [section.code, section]));
  const out: SectionModel[] = [];
  for (const code of SECTION_ORDER) {
    const section = byCode.get(code);
    if (!section || section.total === 0) continue;
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

/**
 * Updates between the version on screen and a newer one: issues added, removed or whose
 * fingerprint changed. The list on screen is not touched until the person presses Show.
 */
export function countBriefingUpdates(displayed: Pick<BriefingView, "version" | "items">, latest: Pick<BriefingView, "version" | "items">): number {
  if (latest.version === displayed.version) return 0;
  const before = new Map(displayed.items.map((item) => [item.issue_id, item.fingerprint]));
  const after = new Map(latest.items.map((item) => [item.issue_id, item.fingerprint]));
  let count = 0;
  for (const [issue, fingerprint] of after) if (before.get(issue) !== fingerprint) count += 1;
  for (const issue of before.keys()) if (!after.has(issue)) count += 1;
  return count;
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
