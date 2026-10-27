/**
 * The Inbox (tasks module, backend/app/modules/tasks/{router,schemas}.py).
 *
 * `Wire*` types mirror the Pydantic models exactly (`InboxItem`, `InboxPage`, `InboxCounts`,
 * `TaskDetail`, `TaskTransition`, `TaskAssignment`, `SnoozeRequest`, `SnoozeOut`).
 * INTERIM(api-generate): replace them with `components["schemas"][...]` once the tasks module
 * merges; `api.ts` is the only reader of the wire shapes.
 */

/** tasks/schemas.py `InboxTab`. */
export const INBOX_TABS = ["tasks", "approvals", "conversations", "exceptions"] as const;
export type InboxTab = (typeof INBOX_TABS)[number];

export type TaskState = "open" | "in_progress" | "done" | "dismissed" | "cancelled" | "expired";
export type DueKind = "hard" | "soft" | "none";

// ---------------------------------------------------------------------------------------------
// Wire

export interface WireCapability {
  allowed: boolean;
  reason_code: string | null;
}

export interface WireSourceRef {
  type: string;
  id: string;
  version: number | null;
  label: string;
  path: string | null;
}

export interface WireInboxItem {
  id: string;
  issue_id: string;
  kind: string;
  family: string;
  tab: InboxTab;
  title: string;
  state: string;
  due_at: string | null;
  due_kind: string;
  overdue: boolean;
  blocked: boolean;
  owner_user_id: string | null;
  assignee_user_id: string | null;
  queue_code: string | null;
  snoozed_until: string | null;
  source_refs: WireSourceRef[];
  capabilities: Record<string, WireCapability>;
  version: number;
}

export interface WireInboxPage {
  items: WireInboxItem[];
  next_cursor: string | null;
  limit: number;
}

export type WireInboxCounts = Record<InboxTab, number>;

export interface WireAllowedTransition {
  action: string;
  to_status: string;
  requires_reason: boolean;
}

export interface WireTaskDetail extends WireInboxItem {
  facts: Record<string, unknown>;
  completion_check: string;
  completion_evidence: Record<string, unknown> | null;
  dismissal_reason_code: string | null;
  closed_at: string | null;
  created_at: string;
  allowed_transitions: WireAllowedTransition[];
}

/** `POST /api/v1/tasks/tasks/{task_id}/transitions` (`TaskTransition`, extra="forbid"). */
export interface WireTaskTransition {
  action: "complete" | "dismiss" | "start";
  expected_version: number;
  reason_code?: string;
  note?: string;
}

// ---------------------------------------------------------------------------------------------
// View model

export interface InboxSource {
  type: string;
  id: string;
  /** "LK-QT-2026-0005 · Maison Atelier SARL" */
  label: string;
  href: string | null;
}

export interface Capability {
  allowed: boolean;
  reason_code: string | null;
}

export interface InboxItem {
  id: string;
  issue_id: string;
  kind: string;
  family: string;
  tab: InboxTab;
  title: string;
  state: TaskState;
  due_at: string | null;
  due_kind: DueKind;
  overdue: boolean;
  blocked: boolean;
  owner_user_id: string | null;
  assignee_user_id: string | null;
  queue_code: string | null;
  snoozed_until: string | null;
  source: InboxSource | null;
  /** The approval proposal this task asks to decide, when it is one (approvals tab). */
  proposal_id: string | null;
  capabilities: Readonly<Record<string, Capability>>;
  version: number;
}

export interface InboxPage {
  items: InboxItem[];
  next_cursor: string | null;
  limit: number;
}

export type InboxCounts = Partial<Record<InboxTab, number>>;

export interface TaskTransitionOption {
  action: "complete" | "dismiss" | "start";
  to_status: string;
  requires_reason: boolean;
}

export interface TaskDetail extends InboxItem {
  facts: Readonly<Record<string, unknown>>;
  completion_check: string;
  dismissal_reason_code: string | null;
  closed_at: string | null;
  created_at: string;
  allowed_transitions: TaskTransitionOption[];
}
