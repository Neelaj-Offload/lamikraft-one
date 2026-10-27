import type { Tone } from "@/components/ui/badge";
import { reviewHref } from "@/lib/app-links";
import { formatDayTime, type ZoneOptions } from "@/lib/format/time";
import { inboxMessages as m } from "@/messages/inbox";
import { inboxHref } from "./api";
import type { InboxItem, InboxTab } from "./types";

export function inboxStatus(item: Pick<InboxItem, "state" | "snoozed_until" | "overdue" | "blocked">, now: Date | null, zone: ZoneOptions): { label: string; tone: Tone } {
  const open = item.state === "open" || item.state === "in_progress";
  if (item.snoozed_until && open) {
    const until = now ? formatDayTime(item.snoozed_until, now, zone) : null;
    return { label: until ? `${m.state.snoozed} · ${until}` : m.state.snoozed, tone: "neutral" };
  }
  if (item.overdue && open) return { label: m.state.overdue, tone: "danger" };
  if (item.blocked && open) return { label: m.state.blocked, tone: "warning" };
  const tones: Record<InboxItem["state"], Tone> = {
    open: "info",
    in_progress: "forest",
    done: "success",
    dismissed: "neutral",
    cancelled: "neutral",
    expired: "warning",
  };
  return { label: m.state[item.state], tone: tones[item.state] };
}

/** Who holds the task, from ids only: you, another person, a queue, or nobody yet. */
export function assigneeLabel(item: Pick<InboxItem, "assignee_user_id" | "owner_user_id" | "queue_code">, userId: string): string {
  const holder = item.assignee_user_id ?? item.owner_user_id;
  if (holder === userId) return m.you;
  if (holder) return m.someoneElse;
  if (item.queue_code) return m.queue(item.queue_code);
  return m.unassigned;
}

/**
 * Where a row's title goes: an approval opens its review page; every other task opens the
 * task drawer on the same tab and page.
 */
export function itemHref(item: InboxItem, tab: InboxTab, cursor: string | null): string {
  if (item.proposal_id) return reviewHref(item.proposal_id);
  return inboxHref(tab, cursor, item.id);
}

