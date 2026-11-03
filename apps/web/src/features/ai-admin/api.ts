/** Calls for Settings → AI and the trace view (see types.ts for the operations). */

import { api, createIdempotencyKey, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import { parseAiStatus, parseAiUsage, parseTrace } from "./parse";
import type { AiStatus, AiUsage, Trace } from "./types";

export const AI_ADMIN_PATH = "/api/v1/admin/ai";
export const AI_ROUTING_SETTING = "ai_routing";

export async function fetchAiStatus(signal?: AbortSignal, client: ApiClient = api): Promise<AiStatus> {
  return parseAiStatus(await requestUntyped<unknown>(client, "get", `${AI_ADMIN_PATH}/status`, { signal }));
}

export async function fetchAiUsage(days: number, signal?: AbortSignal, client: ApiClient = api): Promise<AiUsage> {
  return parseAiUsage(await requestUntyped<unknown>(client, "get", `${AI_ADMIN_PATH}/usage`, { params: { query: { days } }, signal }));
}

export async function verifyAi(client: ApiClient = api): Promise<void> {
  await requestUntyped<unknown>(client, "post", `${AI_ADMIN_PATH}/verify`, { headers: idempotencyHeaders(createIdempotencyKey()) });
}

export async function fetchTrace(correlationId: string, signal?: AbortSignal, client: ApiClient = api): Promise<Trace> {
  return parseTrace(await requestUntyped<unknown>(client, "get", `/api/v1/traces/${encodeURIComponent(correlationId)}`, { signal }));
}
