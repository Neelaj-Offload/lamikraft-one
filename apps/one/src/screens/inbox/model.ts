/**
 * The Inbox in words. Plain module (no hooks, no JSX): route files and client screens both use it.
 *
 * The API files work by `tab` (tasks, approvals, conversations, exceptions). The screen has four
 * views: All is everything waiting on the person (the three kinds, each counted once), then one
 * view per kind that needs its own attention. Exceptions overlap the others: an overdue approval
 * is both an approval and an exception.
 */

import type { Route } from "next";
import type { CSSProperties } from "react";
import { inboxHref } from "@/features/inbox/api";
import type { InboxCounts, InboxItem, InboxTab } from "@/features/inbox/types";
import { reviewHref } from "@/lib/app-links";
import { formatDayTime, type ZoneOptions } from "@/lib/format/time";
import { riseIndex } from "~/lib/motion";
import type { Tone } from "~/ui/badge";
import type { IconName } from "~/ui/icon";

export const INBOX_VIEWS = ["all", "approvals", "exceptions", "conversations"] as const;
export type InboxView = (typeof INBOX_VIEWS)[number];

/** The API tab whose keyset cursor a view pages through. All pages through its tasks. */
export const VIEW_TAB: Record<InboxView, InboxTab> = { all: "tasks", approvals: "approvals", exceptions: "exceptions", conversations: "conversations" };

export const VIEW_LABEL: Record<InboxView, string> = { all: "All", approvals: "Approvals", exceptions: "Exceptions", conversations: "Conversations" };

export const VIEW_LEAD: Record<InboxView, string> = {
  all: "Everything waiting on you: decisions first, then customers, then the rest.",
  approvals: "Requests that need your yes or no before the work can move.",
  exceptions: "Work that is past its deadline, and work nobody has picked up.",
  conversations: "Customers who are waiting for an answer from you.",
};

export function viewHref(view: InboxView, cursor: string | null = null, task: string | null = null): Route {
  return inboxHref(VIEW_TAB[view], cursor, task) as Route;
}

/** All counts each open item once, so exceptions (which sit in another kind too) are left out. */
export function viewCount(view: InboxView, counts: InboxCounts): number | undefined {
  if (view !== "all") return counts[VIEW_TAB[view]];
  const { tasks, approvals, conversations } = counts;
  return tasks === undefined || approvals === undefined || conversations === undefined ? undefined : tasks + approvals + conversations;
}

export type ItemKind = "approval" | "conversation" | "task";

/** What kind of work a row is, whichever view lists it. */
export function kindOf(item: Pick<InboxItem, "tab" | "proposal_id">): ItemKind {
  if (item.proposal_id || item.tab === "approvals") return "approval";
  if (item.tab === "conversations") return "conversation";
  return "task";
}

export const KIND_LOOK: Record<ItemKind, { icon: IconName; action: string; noun: string }> = {
  approval: { icon: "badgeCheck", action: "Review", noun: "Approval" },
  conversation: { icon: "message", action: "Reply", noun: "Conversation" },
  task: { icon: "clipboardCheck", action: "Open", noun: "Task" },
};

/** An approval opens its review screen; everything else opens in place, on the same view and page. */
export function itemHref(item: InboxItem, view: InboxView, cursor: string | null): Route {
  if (item.proposal_id) return reviewHref(item.proposal_id) as Route;
  return viewHref(view, cursor, item.id);
}

type Holding = Pick<InboxItem, "assignee_user_id" | "owner_user_id" | "queue_code">;

/** Of whom it is asked, from ids only: you, a teammate, a team queue, or nobody yet. */
export function holderText(item: Holding, userId: string): string {
  const holder = item.assignee_user_id ?? item.owner_user_id;
  if (holder === userId) return "Yours";
  if (holder) return "With a teammate";
  if (item.queue_code) return `In the ${item.queue_code.replace(/[_-]+/g, " ")} queue`;
  return "Nobody has picked this up";
}

type Timing = Pick<InboxItem, "state" | "snoozed_until" | "overdue" | "blocked" | "due_at" | "due_kind">;

const isOpen = (item: Pick<InboxItem, "state">) => item.state === "open" || item.state === "in_progress";

/** The deadline in plain words, or null when the item has none. */
export function dueText(item: Timing, now: Date | null, zone: ZoneOptions): string | null {
  if (!item.due_at || item.due_kind === "none" || !now) return null;
  const when = formatDayTime(item.due_at, now, zone);
  if (!when) return null;
  return item.overdue && isOpen(item) ? `Was due ${lowerFirst(when)}` : `Due ${lowerFirst(when)}`;
}

/** "Today, 5:00 PM" reads as "today, 5:00 PM" mid-sentence; weekday and month names keep their capital. */
function lowerFirst(text: string): string {
  return /^(Today|Tomorrow|Yesterday)\b/.test(text) ? text.charAt(0).toLowerCase() + text.slice(1) : text;
}

/** The one state worth a badge on a row. Open with nothing unusual shows no badge at all. */
export function itemBadge(item: Timing, now: Date | null, zone: ZoneOptions): { label: string; tone: Tone } | null {
  if (item.snoozed_until && isOpen(item)) {
    const until = now ? formatDayTime(item.snoozed_until, now, zone) : null;
    return { label: until ? `Snoozed until ${lowerFirst(until)}` : "Snoozed", tone: "neutral" };
  }
  if (item.overdue && isOpen(item)) return { label: "Overdue", tone: "ember" };
  if (item.blocked && isOpen(item)) return { label: "Waiting on another step", tone: "amber" };
  switch (item.state) {
    case "in_progress":
      return { label: "In progress", tone: "cobalt" };
    case "done":
      return { label: "Done", tone: "leaf" };
    case "dismissed":
      return { label: "Dismissed", tone: "neutral" };
    case "cancelled":
      return { label: "Cancelled", tone: "neutral" };
    case "expired":
      return { label: "Expired", tone: "amber" };
    default:
      return null;
  }
}

/** The same, for the task's own panel, where an open task says so. */
export function taskBadge(item: Timing, now: Date | null, zone: ZoneOptions): { label: string; tone: Tone } {
  return itemBadge(item, now, zone) ?? { label: "Open", tone: "cobalt" };
}

export const EMPTY: Record<InboxView, { icon: IconName; title: string; text: string }> = {
  all: {
    icon: "inbox",
    title: "Nothing is waiting on you",
    text: "Approvals, customer replies and tasks land here the moment they need you.",
  },
  approvals: {
    icon: "badgeCheck",
    title: "No decisions waiting",
    text: "When someone needs your yes on a price, a discount or a small order, the request lands here.",
  },
  exceptions: {
    icon: "checkCircle",
    title: "Nothing overdue, nothing unclaimed",
    text: "Work that slips past its deadline, or that nobody picks up, shows here before it becomes a problem.",
  },
  conversations: {
    icon: "message",
    title: "Every customer has an answer",
    text: "A message that needs a reply from you lands here, with the customer's own words.",
  },
};

/** `riseIndex` as a style object React accepts (it sets the `--i` custom property for the stagger). */
export function staggered(index: number): CSSProperties {
  return riseIndex(index) as CSSProperties;
}
