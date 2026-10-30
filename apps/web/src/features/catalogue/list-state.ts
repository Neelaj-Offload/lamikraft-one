/**
 * URL search params <-> product list state (UI-34): every filter, the sort, the page size and the offset live in the
 * URL, so a filtered page survives reload and can be shared. Plain functions (no "use client").
 */

import { PRODUCT_STATUSES, type ProductStatus } from "./types";

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export const PAGE_SIZES = [25, 50, 100] as const;
export type PageSize = (typeof PAGE_SIZES)[number];
export const PRODUCT_SORTS = ["product_key", "product_name", "-updated_at", "relevance"] as const;
export type ProductSort = (typeof PRODUCT_SORTS)[number];

export const TEXT_FILTERS = ["q", "family", "size", "thickness", "decor", "finish", "brand", "issue"] as const;
type TextFilter = (typeof TEXT_FILTERS)[number];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface ProductListState extends Record<TextFilter, string> {
  category: string | null;
  subcategory: string | null;
  status: ProductStatus | null;
  hasImage: boolean | null;
  hasPrice: boolean | null;
  archived: boolean;
  sort: ProductSort;
  limit: PageSize;
  offset: number;
}

function tri(value: string | undefined): boolean | null {
  return value === "true" ? true : value === "false" ? false : null;
}

export function productListStateFrom(search: Search): ProductListState {
  const text = Object.fromEntries(TEXT_FILTERS.map((name) => [name, (first(search[name]) ?? "").slice(0, 200)])) as Record<
    TextFilter,
    string
  >;
  const rawLimit = Number.parseInt(first(search.limit) ?? "25", 10);
  const limit = (PAGE_SIZES as readonly number[]).includes(rawLimit) ? (rawLimit as PageSize) : 25;
  const rawOffset = Number.parseInt(first(search.offset) ?? "0", 10);
  const offset = Number.isFinite(rawOffset) && rawOffset > 0 ? rawOffset - (rawOffset % limit) : 0;
  const category = first(search.category) ?? "";
  const subcategory = first(search.subcategory) ?? "";
  return {
    ...text,
    category: UUID.test(category) ? category : null,
    subcategory: UUID.test(subcategory) ? subcategory : null,
    status: PRODUCT_STATUSES.find((s) => s === first(search.status)) ?? null,
    hasImage: tri(first(search.has_image)),
    hasPrice: tri(first(search.has_price)),
    archived: first(search.archived) === "true",
    sort: PRODUCT_SORTS.find((s) => s === first(search.sort)) ?? "product_key",
    limit,
    offset,
  };
}

export const EMPTY_LIST_STATE: ProductListState = productListStateFrom({});

/** State -> query parameters of `GET /api/v1/catalogue/products` (only what is set). */
export function productListQuery(state: ProductListState): Record<string, string | number | boolean> {
  const query: Record<string, string | number | boolean> = {};
  for (const name of TEXT_FILTERS) if (state[name].trim()) query[name] = state[name].trim();
  if (state.category) query.category_id = state.category;
  if (state.subcategory) query.subcategory_id = state.subcategory;
  if (state.status) query.status = state.status;
  if (state.hasImage !== null) query.has_image = state.hasImage;
  if (state.hasPrice !== null) query.has_price = state.hasPrice;
  if (state.archived) query.include_archived = true;
  query.sort = state.sort === "relevance" && !state.q.trim() ? "product_key" : state.sort;
  query.limit = state.limit;
  query.offset = state.offset;
  return query;
}

/** The filters alone (no sort or paging): facets and the export use the same WHERE as the list. */
export function productFilterQuery(state: ProductListState): Record<string, string | number | boolean> {
  const query = productListQuery(state);
  delete query.sort;
  delete query.limit;
  delete query.offset;
  return query;
}

export function productListHref(state: Partial<ProductListState>): string {
  const full = { ...EMPTY_LIST_STATE, ...state };
  const query = new URLSearchParams();
  for (const name of TEXT_FILTERS) if (full[name].trim()) query.set(name, full[name].trim());
  if (full.category) query.set("category", full.category);
  if (full.subcategory) query.set("subcategory", full.subcategory);
  if (full.status) query.set("status", full.status);
  if (full.hasImage !== null) query.set("has_image", String(full.hasImage));
  if (full.hasPrice !== null) query.set("has_price", String(full.hasPrice));
  if (full.archived) query.set("archived", "true");
  if (full.sort !== "product_key") query.set("sort", full.sort);
  if (full.limit !== 25) query.set("limit", String(full.limit));
  if (full.offset) query.set("offset", String(full.offset));
  const search = query.toString();
  return search ? `/products?${search}` : "/products";
}

/** How many filters are active (shown on the phone "Filters" button). */
export function activeFilterCount(state: ProductListState): number {
  let n = TEXT_FILTERS.filter((name) => name !== "q" && state[name].trim()).length;
  for (const value of [state.category, state.subcategory, state.status]) if (value) n += 1;
  for (const value of [state.hasImage, state.hasPrice]) if (value !== null) n += 1;
  return n + (state.archived ? 1 : 0);
}
