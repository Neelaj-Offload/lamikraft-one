/**
 * Runtime readers for the pricing API (see types.ts). Money stays `{amount, currency}` and is
 * validated as DecimalStr, never converted; guarded fields that are absent read as null.
 */

import { safeAppPath } from "@/lib/safe-path";
import { arr, capabilities, int, isDecimalStr, isObject, money, pageOf, quantity, str, strings, type Json } from "./parse-helpers";
import {
  PRICE_LIST_STATUSES,
  PRICE_SCOPES,
  PRICE_TYPES,
  type Page,
  type PartyMini,
  type PriceListDetail,
  type PriceListItem,
  type PriceListSummary,
  type ProductCost,
  type ProductPrice,
  type ProductPrices,
} from "./types";

export class PriceListsShapeError extends Error {
  override readonly name = "PriceListsShapeError";
}

function fail(what: string): never {
  throw new PriceListsShapeError(`The pricing response could not be read (${what}).`);
}

function party(value: unknown): PartyMini | null {
  if (!isObject(value) || !str(value.id)) return null;
  return { id: str(value.id)!, party_number: str(value.party_number) ?? "", display_name: str(value.display_name) ?? str(value.party_number) ?? "" };
}

export function parsePriceListSummary(raw: unknown): PriceListSummary | null {
  if (!isObject(raw) || !str(raw.id) || !str(raw.code) || !str(raw.valid_from)) return null;
  const id = str(raw.id)!;
  return {
    id,
    code: str(raw.code)!,
    name: str(raw.name) ?? str(raw.code)!,
    price_type: PRICE_TYPES.find((type) => type === raw.price_type) ?? "export",
    scope_kind: PRICE_SCOPES.find((scope) => scope === raw.scope_kind) ?? "standard",
    party: party(raw.party),
    customer_type: str(raw.customer_type),
    currency: str(raw.currency) ?? "",
    default_unit_code: str(raw.default_unit_code),
    valid_from: str(raw.valid_from)!,
    valid_to: str(raw.valid_to),
    status: PRICE_LIST_STATUSES.find((status) => status === raw.status) ?? "draft",
    priority: int(raw.priority),
    item_count: int(raw.item_count) ?? 0,
    path: safeAppPath(raw.path) ?? `/products/price-lists/${encodeURIComponent(id)}`,
  };
}

export function parsePriceListDetail(raw: unknown): PriceListDetail {
  const summary = parsePriceListSummary(raw) ?? fail("price list");
  const body = raw as Json;
  if (int(body.version) === null) fail("version");
  return {
    ...summary,
    price_basis: str(body.price_basis),
    notes: str(body.notes),
    source_kind: str(body.source_kind),
    source_ref: str(body.source_ref),
    activated_at: str(body.activated_at),
    retired_at: str(body.retired_at),
    version: int(body.version)!,
    capabilities: capabilities(body.capabilities),
    redacted_fields: strings(body.redacted_fields),
  };
}

export function parsePriceListItem(raw: unknown): PriceListItem | null {
  if (!isObject(raw) || !str(raw.id) || !str(raw.product_id) || !str(raw.product_key) || !str(raw.valid_from)) return null;
  const unitPrice = money(raw.unit_price);
  if (!unitPrice) return null;
  return {
    id: str(raw.id)!,
    price_list_id: str(raw.price_list_id) ?? "",
    price_list_code: str(raw.price_list_code) ?? "",
    product_id: str(raw.product_id)!,
    product_key: str(raw.product_key)!,
    display_sku: str(raw.display_sku),
    unit_code: str(raw.unit_code) ?? "",
    unit_price: unitPrice,
    final_price: money(raw.final_price),
    base_price: money(raw.base_price),
    base_price_label: str(raw.base_price_label),
    addon_price: money(raw.addon_price),
    addon_price_label: str(raw.addon_price_label),
    price_basis: str(raw.price_basis),
    yield_qty_per_board: isDecimalStr(raw.yield_qty_per_board) ? raw.yield_qty_per_board : null,
    thickness_mm: isDecimalStr(raw.thickness_mm) ? raw.thickness_mm : null,
    source_kind: str(raw.source_kind),
    source_ref: str(raw.source_ref),
    moq: quantity(raw.moq),
    notes: str(raw.notes),
    valid_from: str(raw.valid_from)!,
    valid_to: str(raw.valid_to),
    status: raw.status === "retired" ? "retired" : "active",
    superseded_by_item_id: str(raw.superseded_by_item_id),
    version: int(raw.version) ?? 0,
    redacted_fields: strings(raw.redacted_fields),
  };
}

export function parseProductPrice(raw: unknown): ProductPrice | null {
  const item = parsePriceListItem(raw);
  if (!item || !isObject(raw)) return null;
  return {
    ...item,
    price_list_name: str(raw.price_list_name) ?? item.price_list_code,
    price_type: PRICE_TYPES.find((type) => type === raw.price_type) ?? "export",
    scope_kind: PRICE_SCOPES.find((scope) => scope === raw.scope_kind) ?? "standard",
    party: party(raw.party),
    customer_type: str(raw.customer_type),
  };
}

export function parseProductCost(raw: unknown): ProductCost | null {
  if (!isObject(raw) || !str(raw.id) || !str(raw.effective_from)) return null;
  const components = Array.isArray(raw.cost_components)
    ? raw.cost_components.flatMap((entry) => (isObject(entry) && str(entry.label) && isDecimalStr(entry.amount) ? [{ label: str(entry.label)!, amount: entry.amount }] : []))
    : null;
  return {
    id: str(raw.id)!,
    product_id: str(raw.product_id) ?? "",
    cost_version: int(raw.cost_version) ?? 0,
    unit_cost: money(raw.unit_cost),
    unit_code: str(raw.unit_code) ?? "",
    cost_components: components,
    source_kind: str(raw.source_kind) ?? "manual",
    effective_from: str(raw.effective_from)!,
    recorded_at: str(raw.recorded_at) ?? "",
    redacted_fields: strings(raw.redacted_fields),
  };
}

export function parseProductPrices(raw: unknown): ProductPrices {
  if (!isObject(raw) || !str(raw.product_id)) fail("product prices");
  const body = raw as Json;
  return {
    product_id: str(body.product_id)!,
    product_key: str(body.product_key) ?? "",
    on_date: str(body.on_date) ?? "",
    prices: arr(body.prices).map(parseProductPrice).filter((entry): entry is ProductPrice => entry !== null),
    current_cost: isObject(body.current_cost) ? parseProductCost(body.current_cost) : null,
    redacted_fields: strings(body.redacted_fields),
  };
}

export function parsePriceListPage(raw: unknown): Page<PriceListSummary> {
  return pageOf(raw, parsePriceListSummary);
}

export function parsePriceListItemPage(raw: unknown): Page<PriceListItem> {
  return pageOf(raw, parsePriceListItem);
}

export function parseProductCostPage(raw: unknown): Page<ProductCost> {
  return pageOf(raw, parseProductCost);
}
