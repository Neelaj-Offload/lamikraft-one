/**
 * Calls to the briefings module (briefings/router.py). Every item command goes to
 * `POST /api/v1/briefings/items/{issue_id}/actions` with an Idempotency-Key minted when the
 * person acts (reused on retry), the briefing version on screen and the item's fingerprint, so
 * a stale screen gets 409 `item_changed` instead of acting on something that moved. Snooze and
 * Explain are actions of that same endpoint (`ItemActionRequest.action`).
 */

import { api, createIdempotencyKey, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import { safeAppPath } from "@/lib/safe-path";
import { parseBriefingView, parseExplanation } from "./parse";
import type {
  BriefingExplanation,
  BriefingItem,
  BriefingView,
  DismissalReasonCode,
  WireAcknowledgeRequest,
  WireItemActionRequest,
} from "./types";
import { DISMISSAL_REASON_CODES } from "./types";

export const TODAY_PATH = "/api/v1/briefings/today";

export async function fetchToday(signal?: AbortSignal, client: ApiClient = api): Promise<BriefingView> {
  return parseBriefingView(await requestUntyped<unknown>(client, "get", TODAY_PATH, { signal }));
}

export interface ItemCommand {
  item: Pick<BriefingItem, "issue_id" | "fingerprint">;
  briefingVersion: number;
  idempotencyKey: string;
}

function actionsPath(issueId: string): `/api/v1/${string}` {
  return `/api/v1/briefings/items/${encodeURIComponent(issueId)}/actions`;
}

function isDismissalReason(code: string | null | undefined): code is DismissalReasonCode {
  return typeof code === "string" && (DISMISSAL_REASON_CODES as readonly string[]).includes(code);
}

/** The request body for one item action; only fields the server accepts (extra="forbid"). */
export function itemActionBody(
  command: Pick<ItemCommand, "item" | "briefingVersion"> & {
    action: WireItemActionRequest["action"];
    until?: string | null;
    reasonCode?: string | null;
    note?: string | null;
  },
): WireItemActionRequest {
  const body: WireItemActionRequest = {
    action: command.action,
    briefing_version: command.briefingVersion,
    item_fingerprint: command.item.fingerprint,
  };
  if (command.until) body.until = command.until;
  if (isDismissalReason(command.reasonCode)) body.reason_code = command.reasonCode;
  const note = command.note?.trim();
  if (note) body.note = note;
  return body;
}

/** POST briefings/items/{issue_id}/actions for mark_handled, dismiss (reason) and unsnooze. */
export function runItemAction(
  command: ItemCommand & { action: string; reasonCode?: string | null; note?: string | null },
  client: ApiClient = api,
): Promise<unknown> {
  const action = command.action as WireItemActionRequest["action"];
  return requestUntyped(client, "post", actionsPath(command.item.issue_id), {
    body: itemActionBody({ ...command, action }),
    headers: idempotencyHeaders(command.idempotencyKey),
  });
}

/** The snooze action. The server bounds `until` by the deadline (422 with `max_until`). */
export function snoozeItem(command: ItemCommand & { until: string }, client: ApiClient = api): Promise<unknown> {
  return requestUntyped(client, "post", actionsPath(command.item.issue_id), {
    body: itemActionBody({ ...command, action: "snooze" }),
    headers: idempotencyHeaders(command.idempotencyKey),
  });
}

/**
 * The explain action: read-only, so each request is its own command with a fresh key. It
 * carries no version or fingerprint (an explanation of the current state is always valid).
 */
export async function fetchExplanation(issueId: string, signal?: AbortSignal, client: ApiClient = api): Promise<BriefingExplanation> {
  const result = await requestUntyped<unknown>(client, "post", actionsPath(issueId), {
    body: { action: "explain" } satisfies WireItemActionRequest,
    headers: idempotencyHeaders(createIdempotencyKey()),
    signal,
  });
  return parseExplanation(result);
}

/** POST briefings/{briefing_id}/acknowledge: "Mark as seen" for the version on screen. */
export function acknowledgeBriefing(
  briefingId: string,
  version: number,
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<unknown> {
  return requestUntyped(client, "post", `/api/v1/briefings/${encodeURIComponent(briefingId)}/acknowledge`, {
    body: { version, method: "explicit" } satisfies WireAcknowledgeRequest,
    headers: idempotencyHeaders(idempotencyKey),
  });
}

/** A receipt link from an action response (`{href}`), only when it stays in the app. */
export function receiptHref(result: unknown): string | null {
  return result !== null && typeof result === "object" ? safeAppPath((result as { href?: unknown }).href) : null;
}

/**
 * Snooze choices as instants (UTC), capped at the server's `max_until` for the item so the
 * request is never refused for a limit the screen already knew.
 */
export function snoozeUntil(choice: "1h" | "3h" | "24h", now: Date, maxUntil: string | null = null): string {
  const hours = choice === "1h" ? 1 : choice === "3h" ? 3 : 24;
  let at = now.getTime() + hours * 3_600_000;
  const cap = maxUntil ? Date.parse(maxUntil) : Number.NaN;
  if (Number.isFinite(cap) && cap < at) at = cap;
  return new Date(at).toISOString().replace(/\.\d{3}Z$/, "Z");
}
