/**
 * The catalogue API (backend/app/modules/catalogue/router.py, all `catalogue.product.read`):
 * - GET /api/v1/catalogue/products              Page[ProductSummary] (filters, sort, price_currency)
 * - GET /api/v1/catalogue/products/facets       ProductFacets (same filters)
 * - GET /api/v1/catalogue/products/stats        ProductStats
 * - GET /api/v1/catalogue/products/completeness CompletenessSummary
 * - GET /api/v1/catalogue/products/{id}         ProductDetail
 * - GET /api/v1/catalogue/categories            CategoryRead[] (?include_inactive=)
 * Writes (create, edit, archive, media, taxonomy) live in `features/catalogue/api.ts` (Slice 2).
 */

import { api, requestUntyped, type ApiClient } from "@/lib/api/client";
import { productFilterParams, productListParams, type ProductListState } from "./list-state";
import { pageOf, parseCategories, parseCompletenessSummary, parseProductDetail, parseProductFacets, parseProductStats, parseProductSummary } from "./parse";
import type { CategoryRead, CompletenessSummary, Page, ProductDetail, ProductFacets, ProductStats, ProductSummary } from "./types";

export const PRODUCTS_PATH = "/api/v1/catalogue/products";
export const CATEGORIES_PATH = "/api/v1/catalogue/categories";

export function productPath(productId: string): `/api/v1/${string}` {
  return `${PRODUCTS_PATH}/${encodeURIComponent(productId)}`;
}

/** The list URL the server page prefetches, identical to what the client asks for. */
export function productListQueryString(state: ProductListState): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(productListParams(state))) if (value !== undefined) query.set(key, String(value));
  return query.toString();
}

export async function fetchProducts(state: ProductListState, signal?: AbortSignal, client: ApiClient = api): Promise<Page<ProductSummary>> {
  const raw = await requestUntyped<unknown>(client, "get", PRODUCTS_PATH, { params: { query: productListParams(state) }, signal });
  return pageOf(raw, parseProductSummary);
}

export async function fetchProductFacets(state: ProductListState, signal?: AbortSignal, client: ApiClient = api): Promise<ProductFacets> {
  return parseProductFacets(await requestUntyped<unknown>(client, "get", `${PRODUCTS_PATH}/facets`, { params: { query: productFilterParams(state) }, signal }));
}

export async function fetchProductStats(signal?: AbortSignal, client: ApiClient = api): Promise<ProductStats> {
  return parseProductStats(await requestUntyped<unknown>(client, "get", `${PRODUCTS_PATH}/stats`, { signal }));
}

export async function fetchCompleteness(signal?: AbortSignal, client: ApiClient = api): Promise<CompletenessSummary> {
  return parseCompletenessSummary(await requestUntyped<unknown>(client, "get", `${PRODUCTS_PATH}/completeness`, { signal }));
}

export async function fetchProduct(productId: string, signal?: AbortSignal, client: ApiClient = api): Promise<ProductDetail> {
  return parseProductDetail(await requestUntyped<unknown>(client, "get", productPath(productId), { signal }));
}

export async function fetchCategories(includeInactive: boolean, signal?: AbortSignal, client: ApiClient = api): Promise<CategoryRead[]> {
  return parseCategories(
    await requestUntyped<unknown>(client, "get", CATEGORIES_PATH, { params: { query: { include_inactive: includeInactive ? true : undefined } }, signal }),
  );
}

/** The import-compatible CSV of the current filters (a same-origin download; the server writes it with csv_safe). */
export function productExportHref(state: ProductListState): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(productFilterParams(state))) if (value !== undefined && value !== false) query.set(key, String(value));
  const search = query.toString();
  return `${PRODUCTS_PATH}/export.csv${search ? `?${search}` : ""}`;
}
