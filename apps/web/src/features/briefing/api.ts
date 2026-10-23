/**
 * Calls to the briefings module (briefing.md §9, §16). Every command carries an
 * Idempotency-Key minted when the person acts (reused on retry), the briefing version on
 * screen and the item's fingerprint, so a stale screen gets 409 `item_changed` instead of
 * acting on something that moved.
 */

import { api, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import { parseBriefingView } from "./parse";
import type { BriefingExplanation, BriefingItem, BriefingView } from "./types";

export const TODAY_PATH = "/api/v1/briefings/today";

export async function fetchToday(signal?: AbortSignal, client: ApiClient = api): Promise<BriefingView> {
  return parseBriefingView(await requestUntyped<unknown>(client, "get", TODAY_PATH, { signal }));
}

export interface ItemCommand {
  item: Pick<BriefingItem, "issue_id" | "fingerprint" | "proposal_ref">;
  briefingVersion: number;
  idempotencyKey: string;
}

function itemPath(issueId: string, suffix: string): `/api/v1/${string}` {
  return `/api/v1/briefings/items/${encodeURIComponent(issueId)}/${suffix}`;
}

/** POST briefings/items/{issue_id}/actions/{action} with optional reason and note. */
export function runItemAction(
  command: ItemCommand & { action: string; reasonCode?: string | null; note?: string | null },
  client: ApiClient = api,
): Promise<unknown> {
  const body: Record<string, unknown> = {
    briefing_version: command.briefingVersion,
    item_fingerprint: command.item.fingerprint,
  };
  if (command.reasonCode) body.reason_code = command.reasonCode;
  if (command.note) body.note = command.note;
  if (command.item.proposal_ref) body.proposal = { id: command.item.proposal_ref.id, version: command.item.proposal_ref.version };
  return requestUntyped(client, "post", itemPath(command.item.issue_id, `actions/${encodeURIComponent(command.action)}`), {
    body,
    headers: idempotencyHeaders(command.idempotencyKey),
  });
}

/** POST briefings/items/{issue_id}/snooze {until}. The server bounds it by the deadline (422 with max_until). */
export function snoozeItem(command: ItemCommand & { until: string }, client: ApiClient = api): Promise<unknown> {
  return requestUntyped(client, "post", itemPath(command.item.issue_id, "snooze"), {
    body: { until: command.until, briefing_version: command.briefingVersion, item_fingerprint: command.item.fingerprint },
    headers: idempotencyHeaders(command.idempotencyKey),
  });
}

export function fetchExplanation(issueId: string, signal?: AbortSignal, client: ApiClient = api): Promise<BriefingExplanation> {
  return requestUntyped<BriefingExplanation>(client, "get", itemPath(issueId, "explain"), { signal });
}

/** Snooze choices as instants (UTC); the server enforces deadline and policy bounds. */
export function snoozeUntil(choice: "1h" | "3h" | "24h", now: Date): string {
  const hours = choice === "1h" ? 1 : choice === "3h" ? 3 : 24;
  return new Date(now.getTime() + hours * 3_600_000).toISOString().replace(/\.\d{3}Z$/, "Z");
}
