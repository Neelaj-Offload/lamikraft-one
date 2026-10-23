/**
 * INTERIM hand-written types for `GET /api/v1/tasks/inbox?tab=&cursor=` (keyset page,
 * api-conventions §9 `CursorPage{items,next_cursor,limit}`), derived from
 * docs/design/source/briefing.md §2 (tasks_tasks) and §16 (Tasks and Inbox). Built by the work
 * lane in the same wave.
 *
 * INTERIM(api-generate): replace with the generated schema types when the tasks module merges.
 */

export const INBOX_TABS = ["tasks", "approvals", "exceptions", "snoozed", "done"] as const;
export type InboxTab = (typeof INBOX_TABS)[number];

export type TaskState = "open" | "in_progress" | "done" | "dismissed" | "cancelled" | "expired";
export type DueKind = "hard" | "soft" | "none";

export interface InboxPerson {
  id: string;
  display_name: string;
}

export interface InboxSource {
  type: string;
  id: string;
  /** "Quote LK-QT-2026-0041" */
  label: string;
  href: string | null;
}

export interface InboxItem {
  id: string;
  kind: string;
  family: string;
  title: string;
  summary: string | null;
  state: TaskState;
  due_at: string | null;
  due_kind: DueKind;
  overdue: boolean;
  snoozed_until: string | null;
  source: InboxSource | null;
  /** Canonical screen for the task or its record. */
  href: string | null;
  assignee: InboxPerson | null;
  owner: InboxPerson | null;
  on_behalf_of: InboxPerson | null;
  updated_at: string;
}

export interface InboxPage {
  items: InboxItem[];
  next_cursor: string | null;
  limit: number;
  /** Per-tab counts over the visible set, when the server includes them. */
  counts: Partial<Record<InboxTab, number>> | null;
}
