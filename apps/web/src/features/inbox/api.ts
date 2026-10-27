/**
 * The tasks module's Inbox API (tasks/router.py, prefix `/api/v1/tasks`) and the Inbox URL
 * state. This file is the only reader of the wire shapes in types.ts.
 */

import { api, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import { appLinkFor, UUID_PATTERN } from "@/lib/app-links";
import {
  INBOX_TABS,
  type Capability,
  type InboxCounts,
  type InboxItem,
  type InboxPage,
  type InboxSource,
  type InboxTab,
  type TaskDetail,
  type TaskState,
  type TaskTransitionOption,
  type WireTaskTransition,
} from "./types";

export const INBOX_PATH = "/api/v1/tasks/inbox";
export const INBOX_COUNTS_PATH = "/api/v1/tasks/inbox/counts";
export const INBOX_PAGE_SIZE = 50;

export function taskPath(taskId: string): `/api/v1/${string}` {
  return `/api/v1/tasks/tasks/${encodeURIComponent(taskId)}`;
}

export class InboxShapeError extends Error {
  override readonly name = "InboxShapeError";
}

export function inboxTabFrom(value: string | string[] | null | undefined): InboxTab {
  const raw = Array.isArray(value) ? value[0] : value;
  return INBOX_TABS.find((tab) => tab === raw) ?? "tasks";
}

/** Opaque keyset cursors are base64url; anything else is ignored rather than forwarded. */
export function cursorFrom(value: string | string[] | null | undefined): string | null {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw && /^[A-Za-z0-9_\-=.]{1,400}$/.test(raw) ? raw : null;
}

/** The open task drawer (`?task=`): a task id, or nothing. */
export function taskIdFrom(value: string | string[] | null | undefined): string | null {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw && UUID_PATTERN.test(raw) ? raw : null;
}

/**
 * Each tab is its own route (`/inbox`, `/inbox/approvals`, `/inbox/conversations`,
 * `/inbox/exceptions`), so tabs deep-link and appear in the route manifest. The keyset cursor
 * and the open task stay query parameters.
 */
export function inboxHref(tab: InboxTab, cursor: string | null = null, task: string | null = null): string {
  const path = tab === "tasks" ? "/inbox" : `/inbox/${tab}`;
  const query = new URLSearchParams();
  if (cursor) query.set("cursor", cursor);
  if (task) query.set("task", task);
  const search = query.toString();
  return search ? `${path}?${search}` : path;
}

const STATES: readonly TaskState[] = ["open", "in_progress", "done", "dismissed", "cancelled", "expired"];
type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => value !== null && typeof value === "object" && !Array.isArray(value);
const str = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);
const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const int = (value: unknown): number | null => (typeof value === "number" && Number.isInteger(value) ? value : null);

function source(value: unknown): InboxSource | null {
  if (!isObject(value) || !str(value.id) || !str(value.label)) return null;
  return { type: str(value.type) ?? "", id: str(value.id)!, label: str(value.label)!, href: appLinkFor(value.path) };
}

function capabilities(value: unknown): Record<string, Capability> {
  if (!isObject(value)) return {};
  const out: Record<string, Capability> = {};
  for (const [key, cap] of Object.entries(value)) {
    if (isObject(cap) && typeof cap.allowed === "boolean") out[key] = { allowed: cap.allowed, reason_code: str(cap.reason_code) };
  }
  return out;
}

/** `InboxItem`; null when the row lacks what the list needs (id, title, version). */
export function parseInboxItem(entry: unknown): InboxItem | null {
  if (!isObject(entry) || !str(entry.id) || !str(entry.title) || int(entry.version) === null) return null;
  const sources = arr(entry.source_refs).map(source).filter((ref): ref is InboxSource => ref !== null);
  const primary = sources[0] ?? null;
  const proposal = arr(entry.source_refs).find((ref) => isObject(ref) && ref.type === "approvals.proposal");
  return {
    id: str(entry.id)!,
    issue_id: str(entry.issue_id) ?? "",
    kind: str(entry.kind) ?? "",
    family: str(entry.family) ?? "",
    tab: INBOX_TABS.find((tab) => tab === entry.tab) ?? "tasks",
    title: str(entry.title)!,
    state: STATES.find((state) => state === entry.state) ?? "open",
    due_at: str(entry.due_at),
    due_kind: entry.due_kind === "hard" || entry.due_kind === "soft" ? entry.due_kind : "none",
    overdue: entry.overdue === true,
    blocked: entry.blocked === true,
    owner_user_id: str(entry.owner_user_id),
    assignee_user_id: str(entry.assignee_user_id),
    queue_code: str(entry.queue_code),
    snoozed_until: str(entry.snoozed_until),
    source: primary,
    proposal_id: isObject(proposal) ? str(proposal.id) : null,
    capabilities: capabilities(entry.capabilities),
    version: int(entry.version)!,
  };
}

export function parseInboxPage(raw: unknown): InboxPage {
  if (!isObject(raw) || !Array.isArray(raw.items)) throw new InboxShapeError("The Inbox response could not be read (items).");
  const items = raw.items.map(parseInboxItem).filter((item): item is InboxItem => item !== null);
  return { items, next_cursor: str(raw.next_cursor), limit: int(raw.limit) ?? items.length };
}

/** `InboxCounts{tasks, approvals, conversations, exceptions}`; unknown keys and bad values dropped. */
export function parseInboxCounts(raw: unknown): InboxCounts {
  const counts: InboxCounts = {};
  if (!isObject(raw)) return counts;
  for (const tab of INBOX_TABS) {
    const value = raw[tab];
    if (typeof value === "number" && Number.isInteger(value) && value >= 0) counts[tab] = value;
  }
  return counts;
}

const TRANSITIONS: readonly TaskTransitionOption["action"][] = ["start", "complete", "dismiss"];

export function parseTaskDetail(raw: unknown): TaskDetail {
  const base = parseInboxItem(raw);
  if (!base || !isObject(raw)) throw new InboxShapeError("The task could not be read.");
  return {
    ...base,
    facts: isObject(raw.facts) ? raw.facts : {},
    completion_check: str(raw.completion_check) ?? "",
    dismissal_reason_code: str(raw.dismissal_reason_code),
    closed_at: str(raw.closed_at),
    created_at: str(raw.created_at) ?? "",
    allowed_transitions: arr(raw.allowed_transitions).flatMap((entry) => {
      if (!isObject(entry)) return [];
      const action = TRANSITIONS.find((candidate) => candidate === entry.action);
      return action ? [{ action, to_status: str(entry.to_status) ?? "", requires_reason: entry.requires_reason === true }] : [];
    }),
  };
}

export async function fetchInbox(tab: InboxTab, cursor: string | null, signal?: AbortSignal, client: ApiClient = api): Promise<InboxPage> {
  const raw = await requestUntyped<unknown>(client, "get", INBOX_PATH, {
    params: { query: { tab, cursor, limit: INBOX_PAGE_SIZE } },
    signal,
  });
  return parseInboxPage(raw);
}

export async function fetchInboxCounts(signal?: AbortSignal, client: ApiClient = api): Promise<InboxCounts> {
  return parseInboxCounts(await requestUntyped<unknown>(client, "get", INBOX_COUNTS_PATH, { signal }));
}

export async function fetchTask(taskId: string, signal?: AbortSignal, client: ApiClient = api): Promise<TaskDetail> {
  return parseTaskDetail(await requestUntyped<unknown>(client, "get", taskPath(taskId), { signal }));
}

export async function transitionTask(
  task: Pick<TaskDetail, "id" | "version">,
  action: TaskTransitionOption["action"],
  options: { reasonCode?: string | null; note?: string | null; idempotencyKey: string },
  client: ApiClient = api,
): Promise<TaskDetail> {
  const body: WireTaskTransition = { action, expected_version: task.version };
  if (options.reasonCode) body.reason_code = options.reasonCode;
  const note = options.note?.trim();
  if (note) body.note = note;
  const raw = await requestUntyped<unknown>(client, "post", `${taskPath(task.id)}/transitions`, {
    body,
    headers: idempotencyHeaders(options.idempotencyKey),
  });
  return parseTaskDetail(raw);
}

export async function assignTask(
  task: Pick<TaskDetail, "id" | "version">,
  assigneeUserId: string,
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<TaskDetail> {
  const raw = await requestUntyped<unknown>(client, "put", `${taskPath(task.id)}/assignee`, {
    body: { assignee_user_id: assigneeUserId, expected_version: task.version },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return parseTaskDetail(raw);
}

export function snoozeTask(taskId: string, until: string, idempotencyKey: string, client: ApiClient = api): Promise<unknown> {
  return requestUntyped(client, "put", `${taskPath(taskId)}/snooze`, { body: { until }, headers: idempotencyHeaders(idempotencyKey) });
}

export function unsnoozeTask(taskId: string, client: ApiClient = api): Promise<unknown> {
  return requestUntyped(client, "delete", `${taskPath(taskId)}/snooze`);
}
