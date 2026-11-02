/**
 * The pricing API (backend/app/modules/pricing/router.py, `pricing.price.read` unless noted):
 * - GET /api/v1/pricing/price-lists                   Page[PriceListSummary]
 * - GET /api/v1/pricing/price-lists/{id}              PriceListDetail
 * - GET /api/v1/pricing/price-lists/{id}/items        Page[PriceListItemRead]
 * - GET /api/v1/pricing/products/{id}/prices          ProductPrices (cost of record only with pricing.cost.read)
 * - GET /api/v1/pricing/products/{id}/costs           Page[ProductCostRead] (pricing.cost.read)
 * No write endpoints exist in this slice.
 */

import { api, requestUntyped, type ApiClient } from "@/lib/api/client";
import { priceListItemsParams, priceListListParams, type PriceListItemsState, type PriceListListState } from "./list-state";
import { parsePriceListDetail, parsePriceListItemPage, parsePriceListPage, parseProductCostPage, parseProductPrices } from "./parse";
import type { Page, PriceListDetail, PriceListItem, PriceListSummary, ProductCost, ProductPrices } from "./types";

export const PRICE_LISTS_PATH = "/api/v1/pricing/price-lists";
export const PRICING_PRODUCTS_PATH = "/api/v1/pricing/products";

export function priceListPath(priceListId: string): `/api/v1/${string}` {
  return `${PRICE_LISTS_PATH}/${encodeURIComponent(priceListId)}`;
}

export async function fetchPriceLists(state: PriceListListState, signal?: AbortSignal, client: ApiClient = api): Promise<Page<PriceListSummary>> {
  return parsePriceListPage(await requestUntyped<unknown>(client, "get", PRICE_LISTS_PATH, { params: { query: priceListListParams(state) }, signal }));
}

export async function fetchPriceList(priceListId: string, signal?: AbortSignal, client: ApiClient = api): Promise<PriceListDetail> {
  return parsePriceListDetail(await requestUntyped<unknown>(client, "get", priceListPath(priceListId), { signal }));
}

export async function fetchPriceListItems(
  priceListId: string,
  state: PriceListItemsState,
  signal?: AbortSignal,
  client: ApiClient = api,
): Promise<Page<PriceListItem>> {
  return parsePriceListItemPage(
    await requestUntyped<unknown>(client, "get", `${priceListPath(priceListId)}/items`, { params: { query: priceListItemsParams(state) }, signal }),
  );
}

export async function fetchProductPrices(productId: string, signal?: AbortSignal, client: ApiClient = api): Promise<ProductPrices> {
  return parseProductPrices(await requestUntyped<unknown>(client, "get", `${PRICING_PRODUCTS_PATH}/${encodeURIComponent(productId)}/prices`, { signal }));
}

/** Cost history; call only when the person holds `pricing.cost.read` (the server audits every read). */
export async function fetchProductCosts(productId: string, signal?: AbortSignal, client: ApiClient = api): Promise<Page<ProductCost>> {
  return parseProductCostPage(
    await requestUntyped<unknown>(client, "get", `${PRICING_PRODUCTS_PATH}/${encodeURIComponent(productId)}/costs`, { params: { query: { limit: 10, offset: 0 } }, signal }),
  );
}
