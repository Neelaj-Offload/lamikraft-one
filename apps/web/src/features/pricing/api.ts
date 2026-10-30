/**
 * Pricing API (``/api/v1/pricing``; INTERIM until generated types land): price lists (list, create, update, activate,
 * retire, duplicate), items (add on drafts, edit drafts, supersede from a date, retire, history), FX rates (propose,
 * decide, withdraw) and the FX policy. Prices are `{amount, currency}` strings; nothing is computed on the client.
 */

import { api, requestUntyped, type ApiClient } from "@/lib/api/client";
import { pageFrom, recordFrom } from "@/features/sales/resource-command";
import type { Capability, MoneyWire, TransitionWire } from "@/features/custom-products/api";

export const PRICING_PATH = "/api/v1/pricing";
export const PRICE_LISTS_PAGE_SIZE = 25;
export const ITEMS_PAGE_SIZE = 50;
export const PRICE_LIST_STATUSES = ["draft", "active", "retired"] as const;

export interface PriceListSummary {
  id: string;
  code: string;
  name: string;
  price_type: string;
  scope_kind: string;
  party: { id: string; party_number: string; display_name: string } | null;
  customer_type: string | null;
  currency: string;
  valid_from: string;
  valid_to: string | null;
  status: string;
  priority: number | null;
  item_count: number;
  path: string;
}

export interface PriceListDetail extends PriceListSummary {
  notes: string | null;
  version: number;
  activated_at: string | null;
  retired_at: string | null;
  capabilities: Record<string, Capability>;
  allowed_transitions: TransitionWire[];
}

export interface PriceItem {
  id: string;
  product_id: string;
  product_key: string;
  display_sku: string | null;
  unit_code: string;
  unit_price: MoneyWire;
  moq: { value: string; uom: string } | null;
  notes: string | null;
  valid_from: string;
  valid_to: string | null;
  status: string;
  superseded_by_item_id: string | null;
  version: number;
}

export interface PriceHistoryEntry {
  id: string;
  change_kind: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string | null;
  occurred_at: string;
  actor_name: string | null;
}

export interface FxRate {
  id: string;
  base_currency: string;
  quote_currency: string;
  rate: string;
  rate_date: string;
  source_kind: string;
  source_reference: string;
  status: string;
  proposed_by_name: string | null;
  proposed_at: string;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_reason: string | null;
  is_demo: boolean;
  version: number;
  capabilities: Record<string, Capability>;
}

export interface FxPolicy {
  conversion_enabled: boolean;
  conversion_source_currency: string;
  max_rate_age_days: number;
  version: number;
  capabilities: Record<string, Capability>;
}

const list = (id: string): `/api/v1/${string}` => `${PRICING_PATH}/price-lists/${encodeURIComponent(id)}`;
const item = (id: string): `/api/v1/${string}` => `${PRICING_PATH}/price-list-items/${encodeURIComponent(id)}`;

export async function fetchPriceLists(params: { q?: string | null; status?: string | null; offset?: number | null }, signal?: AbortSignal, client: ApiClient = api) {
  const raw = await requestUntyped<unknown>(client, "get", `${PRICING_PATH}/price-lists`, {
    params: { query: { q: params.q?.trim() || undefined, status: params.status || undefined, offset: params.offset ?? 0, limit: PRICE_LISTS_PAGE_SIZE } },
    signal,
  });
  return pageFrom<PriceListSummary>(raw, "price lists");
}

export async function fetchPriceList(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<PriceListDetail> {
  return recordFrom<PriceListDetail>(await requestUntyped<unknown>(client, "get", list(id), { signal }), "price list");
}

export async function fetchPriceItems(id: string, params: { q?: string | null; offset?: number | null; history?: boolean | null }, signal?: AbortSignal, client: ApiClient = api) {
  const raw = await requestUntyped<unknown>(client, "get", `${list(id)}/items`, {
    params: { query: { q: params.q?.trim() || undefined, include_history: params.history ? true : undefined, offset: params.offset ?? 0, limit: ITEMS_PAGE_SIZE } },
    signal,
  });
  return pageFrom<PriceItem>(raw, "prices");
}

export async function createPriceList(body: Record<string, unknown>, client: ApiClient = api): Promise<PriceListDetail> {
  return recordFrom(await requestUntyped<unknown>(client, "post", `${PRICING_PATH}/price-lists`, { body }), "price list");
}

export async function priceListCommand(
  priceList: Pick<PriceListDetail, "id" | "version">,
  command: "activate" | "retire",
  reason: string | null,
  client: ApiClient = api,
): Promise<PriceListDetail> {
  return recordFrom(
    await requestUntyped<unknown>(client, "post", `${list(priceList.id)}/${command}`, {
      body: { expected_version: priceList.version, ...(reason?.trim() ? { reason: reason.trim() } : {}) },
    }),
    "price list",
  );
}

export async function duplicatePriceList(id: string, body: { code: string; name: string; valid_from: string; valid_to?: string | null }, client: ApiClient = api) {
  return recordFrom<PriceListDetail>(await requestUntyped<unknown>(client, "post", `${list(id)}/duplicate`, { body }), "price list");
}

export async function addPriceItem(id: string, body: Record<string, unknown>, client: ApiClient = api): Promise<PriceItem> {
  return recordFrom(await requestUntyped<unknown>(client, "post", `${list(id)}/items`, { body }), "price");
}

export async function updatePriceItem(entry: Pick<PriceItem, "id" | "version">, changes: Record<string, unknown>, client: ApiClient = api): Promise<PriceItem> {
  return recordFrom(await requestUntyped<unknown>(client, "patch", item(entry.id), { body: { expected_version: entry.version, ...changes } }), "price");
}

export async function supersedePriceItem(entry: Pick<PriceItem, "id" | "version">, body: { unit_price: string; valid_from: string; reason?: string | null }, client: ApiClient = api) {
  return recordFrom<PriceItem>(
    await requestUntyped<unknown>(client, "post", `${item(entry.id)}/supersede`, { body: { ...body, expected_version: entry.version } }),
    "price",
  );
}

export async function retirePriceItem(entry: Pick<PriceItem, "id" | "version">, body: { reason: string; retire_from?: string | null }, client: ApiClient = api) {
  return recordFrom<PriceItem>(
    await requestUntyped<unknown>(client, "post", `${item(entry.id)}/retire`, { body: { ...body, expected_version: entry.version } }),
    "price",
  );
}

export async function fetchItemHistory(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<PriceHistoryEntry[]> {
  const raw = await requestUntyped<unknown>(client, "get", `${item(id)}/history`, { signal });
  return Array.isArray(raw) ? (raw as PriceHistoryEntry[]) : [];
}

export async function fetchFxRates(params: { status?: string | null; offset?: number | null }, signal?: AbortSignal, client: ApiClient = api) {
  const raw = await requestUntyped<unknown>(client, "get", `${PRICING_PATH}/fx-rates`, {
    params: { query: { status: params.status || undefined, offset: params.offset ?? 0, limit: 50 } },
    signal,
  });
  return pageFrom<FxRate>(raw, "FX rates");
}

export async function proposeFxRate(body: Record<string, unknown>, client: ApiClient = api): Promise<FxRate> {
  return recordFrom(await requestUntyped<unknown>(client, "post", `${PRICING_PATH}/fx-rates`, { body }), "FX rate");
}

export async function decideFxRate(id: string, decision: "approve" | "reject", reason: string | null, client: ApiClient = api): Promise<FxRate> {
  return recordFrom(
    await requestUntyped<unknown>(client, "post", `${PRICING_PATH}/fx-rates/${encodeURIComponent(id)}/decision`, {
      body: { decision, ...(reason?.trim() ? { reason: reason.trim() } : {}) },
    }),
    "FX rate",
  );
}

export async function withdrawFxRate(id: string, client: ApiClient = api): Promise<FxRate> {
  return recordFrom(await requestUntyped<unknown>(client, "post", `${PRICING_PATH}/fx-rates/${encodeURIComponent(id)}/withdraw`, {}), "FX rate");
}

export async function fetchFxPolicy(signal?: AbortSignal, client: ApiClient = api): Promise<FxPolicy> {
  return requestUntyped<FxPolicy>(client, "get", `${PRICING_PATH}/fx-policy`, { signal });
}

export async function updateFxPolicy(policy: Pick<FxPolicy, "version">, changes: Partial<Omit<FxPolicy, "version" | "capabilities">>, client: ApiClient = api): Promise<FxPolicy> {
  return requestUntyped<FxPolicy>(client, "put", `${PRICING_PATH}/fx-policy`, { body: { expected_version: policy.version, ...changes } });
}
