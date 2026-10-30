/**
 * Custom products API (``/api/v1/sales/custom-products``; INTERIM until `npm run api:generate` types land):
 * list/status-counts/export.csv, create, get, update, transitions, duplicate, archive/unarchive, history, protected
 * costing, spec revisions with outcomes, promotion request and execution. Money is `{amount, currency}` strings.
 */

import { api, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import { pageFrom, recordFrom } from "@/features/sales/resource-command";

export const CUSTOM_PATH = "/api/v1/sales/custom-products";
export const CUSTOM_PAGE_SIZE = 25;

export const CUSTOM_STATUSES = [
  "inquiry",
  "under_development",
  "sample_stage",
  "quoted",
  "approved",
  "rejected",
  "dormant",
  "converted_to_standard",
] as const;
export type CustomStatus = (typeof CUSTOM_STATUSES)[number];
export const CUSTOM_TYPES = ["modified_catalog", "fully_new", "quote_only"] as const;

export interface MoneyWire {
  amount: string;
  currency: string;
}
export interface Capability {
  allowed: boolean;
  reason_code?: string | null;
}
export interface TransitionWire {
  action: string;
  to_status: string;
  requires_reason: boolean;
}
export interface UserWire {
  id: string;
  display_name: string | null;
}
export interface PartyWire {
  id: string;
  party_number: string;
  display_name: string;
  country_code: string;
}

export interface CustomProductSummary {
  id: string;
  custom_code: string;
  custom_type: string;
  product_name: string;
  status: string;
  party: PartyWire | null;
  legacy_customer_name: string | null;
  inquiry_reference: string | null;
  base_product_key: string | null;
  dimensions_text: string | null;
  decor_no: string | null;
  finish: string | null;
  quoted_price: MoneyWire | null;
  owner: UserWire;
  promoted_product_id: string | null;
  archived_at: string | null;
  updated_at: string;
  version: number;
  path: string;
}

export interface CustomPackagingWire {
  carton_qty?: number | null;
  inner_qty?: number | null;
  packing_type?: string | null;
  unit_weight_g?: string | null;
  cbm?: string | null;
}

export interface SpecRevisionWire {
  id: string;
  revision_no: number;
  spec_snapshot: Record<string, unknown>;
  sample_id: string | null;
  sample_number: string | null;
  sample_reference: string | null;
  sample_sent_on: string | null;
  feedback: string | null;
  outcome: string;
  decided_at: string | null;
  decided_by: UserWire | null;
  created_at: string;
  version: number;
}

export interface PromotionWire {
  id: string;
  status: string;
  payload: Record<string, unknown>;
  proposal_id: string | null;
  requested_by: UserWire | null;
  executed_product_id: string | null;
  executed_at: string | null;
  failure_reason: string | null;
  decision_reason: string | null;
  created_at: string;
}

export interface CustomProductDetail extends CustomProductSummary {
  base_product_id: string | null;
  customer_specific_flag: boolean;
  description: string | null;
  category_id: string | null;
  subcategory_id: string | null;
  category_name: string | null;
  subcategory_name: string | null;
  length_mm: string | null;
  width_mm: string | null;
  height_mm: string | null;
  thickness_mm: string | null;
  thickness_text: string | null;
  decor_name: string | null;
  shape: string | null;
  groove_count: number | null;
  bowl_count: number | null;
  handle_type: string | null;
  packaging_notes: string | null;
  packaging: CustomPackagingWire | null;
  unit_code: string;
  remarks: string | null;
  status_reason: string | null;
  dormant_from_status: string | null;
  created_by: UserWire | null;
  spec_revisions: SpecRevisionWire[];
  promotions: PromotionWire[];
  quotes: { quote_id: string; quote_number: string; status: string; line_no: number }[];
  capabilities: Record<string, Capability>;
  allowed_transitions: TransitionWire[];
  redacted_fields: string[];
}

export interface CostingWire {
  id: string;
  cost_version: number;
  cost: MoneyWire;
  basis_note: string | null;
  recorded_at: string;
  recorded_by: UserWire | null;
}

export interface CustomHistoryWire {
  id: string;
  action: string;
  from_status: string;
  to_status: string;
  reason: string | null;
  actor: UserWire | null;
  quote_id: string | null;
  occurred_at: string;
}

export interface CustomListParams {
  q?: string | null;
  status?: string | null;
  scope?: "mine" | "all" | null;
  offset?: number | null;
}

const one = (id: string): `/api/v1/${string}` => `${CUSTOM_PATH}/${encodeURIComponent(id)}`;

function listQuery(params: CustomListParams) {
  return { q: params.q?.trim() || undefined, status: params.status || undefined, scope: params.scope ?? undefined };
}

export async function fetchCustomProducts(params: CustomListParams, signal?: AbortSignal, client: ApiClient = api) {
  const raw = await requestUntyped<unknown>(client, "get", CUSTOM_PATH, {
    params: { query: { ...listQuery(params), offset: params.offset ?? 0, limit: CUSTOM_PAGE_SIZE } },
    signal,
  });
  return pageFrom<CustomProductSummary>(raw, "custom products");
}

/** The export link for the current filters (a real download; costing columns only on request and permission). */
export function customExportHref(params: CustomListParams, includeCosting = false): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(listQuery(params))) if (value) query.set(key, value);
  if (includeCosting) query.set("include_costing", "true");
  const search = query.toString();
  return search ? `${CUSTOM_PATH}/export.csv?${search}` : `${CUSTOM_PATH}/export.csv`;
}

export async function fetchCustomProduct(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<CustomProductDetail> {
  return recordFrom<CustomProductDetail>(await requestUntyped<unknown>(client, "get", one(id), { signal }), "custom product");
}

export async function createCustomProduct(body: Record<string, unknown>, key: string, client: ApiClient = api): Promise<CustomProductDetail> {
  return recordFrom(await requestUntyped<unknown>(client, "post", CUSTOM_PATH, { body, headers: idempotencyHeaders(key) }), "custom product");
}

export async function updateCustomProduct(
  product: Pick<CustomProductDetail, "id" | "version">,
  changes: Record<string, unknown>,
  client: ApiClient = api,
): Promise<CustomProductDetail> {
  return recordFrom(
    await requestUntyped<unknown>(client, "patch", one(product.id), { body: { expected_version: product.version, ...changes } }),
    "custom product",
  );
}

export async function transitionCustomProduct(
  product: Pick<CustomProductDetail, "id" | "version">,
  action: string,
  reason: string | null,
  client: ApiClient = api,
): Promise<CustomProductDetail> {
  const body: Record<string, unknown> = { action, expected_version: product.version };
  if (reason?.trim()) body.reason = reason.trim();
  return recordFrom(await requestUntyped<unknown>(client, "post", `${one(product.id)}/transitions`, { body }), "custom product");
}

export async function duplicateCustomProduct(id: string, key: string, client: ApiClient = api): Promise<CustomProductDetail> {
  return recordFrom(await requestUntyped<unknown>(client, "post", `${one(id)}/duplicate`, { headers: idempotencyHeaders(key) }), "custom product");
}

export async function archiveCustomProduct(
  product: Pick<CustomProductDetail, "id" | "version">,
  archive: boolean,
  reason: string | null,
  client: ApiClient = api,
): Promise<CustomProductDetail> {
  return recordFrom(
    await requestUntyped<unknown>(client, "post", `${one(product.id)}/${archive ? "archive" : "unarchive"}`, {
      body: { expected_version: product.version, ...(reason?.trim() ? { reason: reason.trim() } : {}) },
    }),
    "custom product",
  );
}

export async function fetchCustomHistory(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<CustomHistoryWire[]> {
  const raw = await requestUntyped<unknown>(client, "get", `${one(id)}/history`, { signal });
  return Array.isArray(raw) ? (raw as CustomHistoryWire[]) : [];
}

export async function fetchCosting(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<CostingWire[]> {
  const raw = await requestUntyped<unknown>(client, "get", `${one(id)}/costing`, { signal });
  return Array.isArray(raw) ? (raw as CostingWire[]) : [];
}

export async function recordCosting(id: string, body: { cost_amount: string; cost_currency: string; basis_note?: string | null }, client: ApiClient = api) {
  return requestUntyped<CostingWire>(client, "post", `${one(id)}/costing`, { body });
}

export async function recordSpecRevision(id: string, body: { sample_reference?: string | null; feedback?: string | null }, client: ApiClient = api) {
  return requestUntyped<SpecRevisionWire>(client, "post", `${one(id)}/spec-revisions`, { body });
}

export async function decideSpecRevision(id: string, revision: Pick<SpecRevisionWire, "id" | "version">, outcome: "approved" | "rejected", client: ApiClient = api) {
  return recordFrom<CustomProductDetail>(
    await requestUntyped<unknown>(client, "post", `${one(id)}/spec-revisions/${encodeURIComponent(revision.id)}/outcome`, {
      body: { outcome, expected_version: revision.version },
    }),
    "custom product",
  );
}

export async function requestPromotion(id: string, body: { product_key: string; display_sku?: string | null }, client: ApiClient = api) {
  return requestUntyped<PromotionWire>(client, "post", `${one(id)}/promotion`, { body });
}

export async function executePromotion(id: string, promotionId: string, client: ApiClient = api) {
  return requestUntyped<PromotionWire>(client, "post", `${one(id)}/promotions/${encodeURIComponent(promotionId)}/execute`, {});
}
