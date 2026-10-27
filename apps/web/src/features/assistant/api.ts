/**
 * Calls to the agents module (INTERIM(api-generate): see types.ts). A turn returns 202 with a
 * run id; the run is then read every 500 ms with `after_seq` so only new steps travel.
 */

import { api, createIdempotencyKey, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import { parseConversationId, parseRun, parseTurnAccepted } from "./parse";
import type { AgentRun, ScreenContext } from "./types";

export const CONVERSATIONS_PATH = "/api/v1/agents/conversations";

export async function createConversation(client: ApiClient = api): Promise<string> {
  const raw = await requestUntyped<unknown>(client, "post", CONVERSATIONS_PATH, {
    body: { channel: "web" },
    headers: idempotencyHeaders(createIdempotencyKey()),
  });
  return parseConversationId(raw);
}

export interface TurnInput {
  text: string;
  context: ScreenContext;
  /** A ClarificationCard option, posted back exactly as the server sent it. */
  selectedOption?: unknown;
}

export async function postTurn(conversationId: string, turn: TurnInput, idempotencyKey: string, client: ApiClient = api): Promise<string> {
  const body: Record<string, unknown> = { text: turn.text, context: turn.context };
  if (turn.selectedOption !== undefined) body.selected_option = turn.selectedOption;
  const raw = await requestUntyped<unknown>(client, "post", `${CONVERSATIONS_PATH}/${encodeURIComponent(conversationId)}/turns`, {
    body,
    headers: idempotencyHeaders(idempotencyKey),
  });
  return parseTurnAccepted(raw);
}

export async function fetchRun(runId: string, afterSeq: number, signal?: AbortSignal, client: ApiClient = api): Promise<AgentRun> {
  const raw = await requestUntyped<unknown>(client, "get", `/api/v1/agents/runs/${encodeURIComponent(runId)}`, {
    params: { query: { after_seq: afterSeq } },
    signal,
  });
  return parseRun(raw);
}

export async function cancelRun(runId: string, client: ApiClient = api): Promise<AgentRun | null> {
  const raw = await requestUntyped<unknown>(client, "post", `/api/v1/agents/runs/${encodeURIComponent(runId)}/cancel`, {
    headers: idempotencyHeaders(createIdempotencyKey()),
  });
  try {
    return parseRun(raw);
  } catch {
    return null;
  }
}
