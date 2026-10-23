import { api, requestUntyped, type ApiClient } from "@/lib/api/client";
import { INBOX_TABS, type InboxItem, type InboxPage, type InboxTab, type TaskState } from "./types";

export const INBOX_PATH = "/api/v1/tasks/inbox";

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
  return raw && /^[A-Za-z0-9_\-=.]{1,512}$/.test(raw) ? raw : null;
}

export function inboxHref(tab: InboxTab, cursor: string | null = null): string {
  const params = new URLSearchParams();
  if (tab !== "tasks") params.set("tab", tab);
  if (cursor) params.set("cursor", cursor);
  const query = params.toString();
  return query ? `/inbox?${query}` : "/inbox";
}

const STATES: readonly TaskState[] = ["open", "in_progress", "done", "dismissed", "cancelled", "expired"];
type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => value !== null && typeof value === "object" && !Array.isArray(value);
const str = (value: unknown): string | null => (typeof value === "string" ? value : null);
const appPath = (value: unknown): string | null => {
  const path = str(value);
  return path && path.startsWith("/") && !path.startsWith("//") ? path : null;
};
const person = (value: unknown) =>
  isObject(value) && str(value.display_name) ? { id: str(value.id) ?? "", display_name: str(value.display_name)! } : null;

export function parseInboxPage(raw: unknown): InboxPage {
  if (!isObject(raw) || !Array.isArray(raw.items)) throw new InboxShapeError("The Inbox response could not be read (items).");
  const items: InboxItem[] = raw.items.flatMap((entry) => {
    if (!isObject(entry) || !str(entry.id) || !str(entry.title)) return [];
    const source = isObject(entry.source) && str(entry.source.label) ? entry.source : null;
    return [
      {
        id: str(entry.id)!,
        kind: str(entry.kind) ?? "",
        family: str(entry.family) ?? "",
        title: str(entry.title)!,
        summary: str(entry.summary),
        state: STATES.find((state) => state === entry.state) ?? "open",
        due_at: str(entry.due_at),
        due_kind: entry.due_kind === "hard" || entry.due_kind === "soft" ? entry.due_kind : "none",
        overdue: entry.overdue === true,
        snoozed_until: str(entry.snoozed_until),
        source: source ? { type: str(source.type) ?? "", id: str(source.id) ?? "", label: str(source.label)!, href: appPath(source.href) } : null,
        href: appPath(entry.href),
        assignee: person(entry.assignee),
        owner: person(entry.owner),
        on_behalf_of: person(entry.on_behalf_of),
        updated_at: str(entry.updated_at) ?? "",
      },
    ];
  });
  const counts: Partial<Record<InboxTab, number>> = {};
  if (isObject(raw.counts)) {
    for (const tab of INBOX_TABS) {
      const value = raw.counts[tab];
      if (typeof value === "number" && Number.isInteger(value) && value >= 0) counts[tab] = value;
    }
  }
  return {
    items,
    next_cursor: str(raw.next_cursor),
    limit: typeof raw.limit === "number" ? raw.limit : items.length,
    counts: Object.keys(counts).length > 0 ? counts : null,
  };
}

export async function fetchInbox(tab: InboxTab, cursor: string | null, signal?: AbortSignal, client: ApiClient = api): Promise<InboxPage> {
  const raw = await requestUntyped<unknown>(client, "get", INBOX_PATH, {
    params: { query: { tab, cursor } },
    signal,
  });
  return parseInboxPage(raw);
}
