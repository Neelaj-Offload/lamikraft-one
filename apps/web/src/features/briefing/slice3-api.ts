/**
 * Slice-3 briefing endpoints, typed from the generated schema (briefings/router.py):
 * - briefings_create_pin            POST  /api/v1/briefings/{briefing_id}/pins        (Listen: pin the version on screen)
 * - briefings_get_pin_script        GET   /api/v1/briefings/pins/{pin_id}/script     (the narration, in the pin's order)
 * - briefings_update_pin            PATCH /api/v1/briefings/pins/{pin_id}            (paused / active / stopped / completed, position)
 * - briefings_get_delta             GET   /api/v1/briefings/delta?since=             (what changed, source-linked)
 * - briefings_get_item              GET   /api/v1/briefings/items/{issue_id}         (one item with its explanation)
 * - briefings_create_summary        POST  /api/v1/briefings/summary                  (send today's WhatsApp summary now)
 */

import { api, idempotencyHeaders, unwrap, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];
export type WirePin = Schemas["PinView"];
export type WireNarration = Schemas["NarrationView"];
export type WireNarrationSegment = Schemas["NarrationSegment"];
export type WireDelta = Schemas["DeltaView"];
export type WireDeltaGroup = Schemas["DeltaGroup"];
export type WireDeltaChange = Schemas["DeltaChange"];
export type WireItemDetail = Schemas["ItemDetailView"];
export type WireSummaryState = Schemas["SummaryStateView"];

export type DeltaSince = "last_ack" | "yesterday" | "last_workday";
export const DELTA_SINCE: readonly DeltaSince[] = ["last_ack", "yesterday", "last_workday"];

/** `?since=` from the URL (a server page reads it; never from a "use client" module). Unknown values → last_ack. */
export function deltaSinceFrom(value: unknown): DeltaSince {
  const raw = Array.isArray(value) ? value[0] : value;
  return DELTA_SINCE.find((since) => since === raw) ?? "last_ack";
}

export function createVoicePin(briefingId: string, idempotencyKey: string, client: ApiClient = api): Promise<WirePin> {
  return unwrap(
    client.POST("/api/v1/briefings/{briefing_id}/pins", {
      params: { path: { briefing_id: briefingId } },
      body: { kind: "voice", detail: "initial" },
      headers: idempotencyHeaders(idempotencyKey),
    }),
  );
}

export function fetchPinScript(pinId: string, signal?: AbortSignal, client: ApiClient = api): Promise<WireNarration> {
  return unwrap(client.GET("/api/v1/briefings/pins/{pin_id}/script", { params: { path: { pin_id: pinId } }, signal }));
}

export function updatePin(
  pinId: string,
  change: { state?: "active" | "paused" | "stopped" | "completed"; position?: number },
  client: ApiClient = api,
): Promise<WirePin> {
  return unwrap(client.PATCH("/api/v1/briefings/pins/{pin_id}", { params: { path: { pin_id: pinId } }, body: change }));
}

export function fetchDelta(since: DeltaSince, cursor: string | null, signal?: AbortSignal, client: ApiClient = api): Promise<WireDelta> {
  return unwrap(
    client.GET("/api/v1/briefings/delta", { params: { query: { since, limit: 100, ...(cursor ? { cursor } : {}) } }, signal }),
  );
}

export function fetchItemDetail(issueId: string, signal?: AbortSignal, client: ApiClient = api): Promise<WireItemDetail> {
  return unwrap(client.GET("/api/v1/briefings/items/{issue_id}", { params: { path: { issue_id: issueId } }, signal }));
}

export function sendSummaryNow(idempotencyKey: string, client: ApiClient = api): Promise<WireSummaryState> {
  return unwrap(client.POST("/api/v1/briefings/summary", { headers: idempotencyHeaders(idempotencyKey) }));
}
