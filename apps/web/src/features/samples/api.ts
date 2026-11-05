/**
 * Samples API (``/api/v1/sales/samples``; INTERIM until generated types land): list/status-counts, create, get,
 * update, transitions (dispatch, deliver, record_feedback, close, cancel).
 */

import { api, idempotencyHeaders, requestUntyped, unwrap, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { pageFrom, recordFrom } from "@/features/sales/resource-command";
import type { Capability, PartyWire, TransitionWire, UserWire } from "@/features/custom-products/api";

export const SAMPLES_PATH = "/api/v1/sales/samples";
export const SAMPLES_PAGE_SIZE = 25;
export const SAMPLE_STATUSES = ["requested", "dispatched", "delivered", "feedback_received", "closed", "cancelled"] as const;
export type SampleStatus = (typeof SAMPLE_STATUSES)[number];

export interface Sample {
  id: string;
  sample_number: string;
  party: PartyWire;
  owner: UserWire;
  quote_id: string | null;
  quote_number: string | null;
  custom_product_id: string | null;
  custom_code: string | null;
  product_id: string | null;
  description: string;
  quantity: string;
  unit_code: string;
  status: string;
  requested_on: string;
  dispatched_at: string | null;
  dispatch_reference: string | null;
  challan_id: string | null;
  delivered_at: string | null;
  delivery_evidence_kind: string | null;
  feedback: string | null;
  feedback_outcome: string | null;
  feedback_at: string | null;
  closed_at: string | null;
  close_reason: string | null;
  notes: string | null;
  updated_at: string;
  version: number;
  path: string;
  capabilities: Record<string, Capability>;
  allowed_transitions: TransitionWire[];
}

export interface SampleListParams {
  q?: string | null;
  status?: string | null;
  offset?: number | null;
}

const one = (id: string): `/api/v1/${string}` => `${SAMPLES_PATH}/${encodeURIComponent(id)}`;

export async function fetchSamples(params: SampleListParams, signal?: AbortSignal, client: ApiClient = api) {
  const raw = await requestUntyped<unknown>(client, "get", SAMPLES_PATH, {
    params: { query: { q: params.q?.trim() || undefined, status: params.status || undefined, offset: params.offset ?? 0, limit: SAMPLES_PAGE_SIZE } },
    signal,
  });
  return pageFrom<Sample>(raw, "samples");
}

export async function fetchSample(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<Sample> {
  return recordFrom<Sample>(await requestUntyped<unknown>(client, "get", one(id), { signal }), "sample");
}

export async function createSample(body: Record<string, unknown>, key: string, client: ApiClient = api): Promise<Sample> {
  return recordFrom<Sample>(await requestUntyped<unknown>(client, "post", SAMPLES_PATH, { body, headers: idempotencyHeaders(key) }), "sample");
}

export interface SampleTransitionRequest {
  action: string;
  dispatch_reference?: string | null;
  evidence_kind?: string | null;
  feedback?: string | null;
  feedback_outcome?: string | null;
  reason?: string | null;
}

/** Only filled fields are sent, with the version the person saw. */
export function sampleTransitionBody(sample: Pick<Sample, "version">, request: SampleTransitionRequest): Record<string, unknown> {
  const body: Record<string, unknown> = { action: request.action, expected_version: sample.version };
  for (const key of ["dispatch_reference", "evidence_kind", "feedback", "feedback_outcome", "reason"] as const) {
    const value = request[key]?.trim();
    if (value) body[key] = value;
  }
  return body;
}

// ---- lineage and the delivery challan (Slice 5; typed from the generated schema) -------------------------------------
export type SampleLineage = components["schemas"]["SampleLineage"];
export type LineageNode = components["schemas"]["LineageNode"];
export type ChallanOption = components["schemas"]["ChallanSummaryRow"];

export function fetchSampleLineage(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<SampleLineage> {
  return unwrap(client.GET("/api/v1/sales/samples/{sample_id}/lineage", { params: { path: { sample_id: id } }, signal }));
}

/** Link (or unlink with `null`) the challan that will carry a requested sample; the answer is the sample. */
export async function linkSampleChallan(sample: Pick<Sample, "id" | "version">, challanId: string | null, key: string, client: ApiClient = api): Promise<Sample> {
  return recordFrom<Sample>(
    await requestUntyped<unknown>(client, "post", `${one(sample.id)}/challan`, { body: { expected_version: sample.version, challan_id: challanId }, headers: idempotencyHeaders(key) }),
    "sample",
  );
}

/** Draft or issued sample/outward challans of the sample's customer that the viewer can see. */
export async function fetchChallansForSample(partyId: string, signal?: AbortSignal, client: ApiClient = api): Promise<ChallanOption[]> {
  const page = await unwrap(
    client.GET("/api/v1/challans/challans", {
      params: { query: { party_id: partyId, status: ["draft", "issued"], challan_type: ["sample", "outward"], limit: 50 } },
      signal,
    }),
  );
  return page.items;
}

export async function transitionSample(sample: Pick<Sample, "id" | "version">, request: SampleTransitionRequest, key: string, client: ApiClient = api): Promise<Sample> {
  return recordFrom<Sample>(
    await requestUntyped<unknown>(client, "post", `${one(sample.id)}/transitions`, { body: sampleTransitionBody(sample, request), headers: idempotencyHeaders(key) }),
    "sample",
  );
}
