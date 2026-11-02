/**
 * URL search params <-> catalogue list state. Plain functions (no "use client"), so the server
 * page can read its search params with them and the client list can build links with them.
 * Every filter, the sort, the price currency and the page offset live in the URL, so every
 * combination is a page and the back button works.
 */

import { CURRENCIES, type CurrencyCode } from "@/lib/format/money";
import { COMPLETENESS_RULES, PRODUCT_SORTS, PRODUCT_STATUSES, type CompletenessRule, type FacetDimension, type ProductSort, type ProductStatus } from "./types";

export const PRODUCTS_PAGE_SIZE = 25;
export const DEFAULT_PRICE_CURRENCY: CurrencyCode = "EUR";

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface ProductListState {
  q: string;
  category_id: string | null;
  subcategory_id: string | null;
  family: string | null;
  size: string | null;
  thickness: string | null;
  decor: string | null;
  finish: string | null;
  status: ProductStatus | null;
  brand: string | null;
  issue: CompletenessRule | null;
  include_archived: boolean;
  /** null means the default: relevance with a search, product key otherwise. */
  sort: ProductSort | null;
  currency: CurrencyCode;
  offset: number;
}

/** The text filters a facet value applies to (`?decor=0120`); each caps the server's max length. */
const TEXT_FILTERS: Record<"family" | "size" | "thickness" | "decor" | "finish" | "brand", number> = {
  family: 200,
  size: 60,
  thickness: 20,
  decor: 40,
  finish: 200,
  brand: 40,
};

const text = (value: string | string[] | undefined, max: number): string | null => {
  const trimmed = (first(value) ?? "").trim().slice(0, max);
  return trimmed === "" ? null : trimmed;
};
const uuid = (value: string | string[] | undefined): string | null => {
  const raw = first(value);
  return raw && UUID.test(raw) ? raw.toLowerCase() : null;
};

/** URL → list state; anything unknown falls back to the default, never forwarded raw. */
export function productListStateFrom(search: Search): ProductListState {
  const rawOffset = Number.parseInt(first(search.offset) ?? "0", 10);
  const offset = Number.isFinite(rawOffset) && rawOffset > 0 ? rawOffset - (rawOffset % PRODUCTS_PAGE_SIZE) : 0;
  return {
    q: (first(search.q) ?? "").trim().slice(0, 200),
    category_id: uuid(search.category_id),
    subcategory_id: uuid(search.subcategory_id),
    family: text(search.family, TEXT_FILTERS.family),
    size: text(search.size, TEXT_FILTERS.size),
    thickness: text(search.thickness, TEXT_FILTERS.thickness),
    decor: text(search.decor, TEXT_FILTERS.decor),
    finish: text(search.finish, TEXT_FILTERS.finish),
    status: PRODUCT_STATUSES.find((candidate) => candidate === first(search.status)) ?? null,
    brand: text(search.brand, TEXT_FILTERS.brand),
    issue: COMPLETENESS_RULES.find((candidate) => candidate === first(search.issue)) ?? null,
    include_archived: first(search.include_archived) === "true" || first(search.include_archived) === "1",
    sort: PRODUCT_SORTS.find((candidate) => candidate === first(search.sort)) ?? null,
    currency: CURRENCIES.find((candidate) => candidate === (first(search.currency) ?? "").toUpperCase()) ?? DEFAULT_PRICE_CURRENCY,
    offset,
  };
}

export function productListHref(state: Partial<ProductListState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  for (const key of ["category_id", "subcategory_id", "family", "size", "thickness", "decor", "finish", "status", "brand", "issue"] as const) {
    const value = state[key];
    if (value) query.set(key, value);
  }
  if (state.include_archived) query.set("include_archived", "true");
  if (state.sort) query.set("sort", state.sort);
  if (state.currency && state.currency !== DEFAULT_PRICE_CURRENCY) query.set("currency", state.currency);
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `/products?${search}` : "/products";
}

/** The sort the server is asked for: relevance only means something with a search. */
export function effectiveSort(state: Pick<ProductListState, "q" | "sort">): ProductSort {
  if (state.sort && state.sort !== "relevance") return state.sort;
  return state.q ? "relevance" : "product_key";
}

export const FACET_FILTER_KEY: Record<FacetDimension, keyof ProductListState> = {
  categories: "category_id",
  subcategories: "subcategory_id",
  families: "family",
  sizes: "size",
  thicknesses: "thickness",
  decors: "decor",
  finishes: "finish",
  statuses: "status",
  brands: "brand",
};

/** The filters a facet dimension's value replaces; a category change also drops the subcategory. */
function facetPatch(dimension: FacetDimension, value: string | null): Partial<ProductListState> {
  const key = FACET_FILTER_KEY[dimension];
  const patch: Partial<ProductListState> = { [key]: value, offset: 0 } as Partial<ProductListState>;
  if (dimension === "categories") patch.subcategory_id = null;
  return patch;
}

/** The list URL with the facet value applied, or removed when it is the selected one (a toggle). */
export function facetToggleHref(state: ProductListState, dimension: FacetDimension, value: string): string {
  const selected = isFacetSelected(state, dimension, value);
  return productListHref({ ...state, ...facetPatch(dimension, selected ? null : value) });
}

export function facetClearHref(state: ProductListState, dimension: FacetDimension): string {
  return productListHref({ ...state, ...facetPatch(dimension, null) });
}

export function isFacetSelected(state: ProductListState, dimension: FacetDimension, value: string): boolean {
  const current = state[FACET_FILTER_KEY[dimension]];
  return typeof current === "string" && current.toLowerCase() === value.toLowerCase();
}

/** Filters that narrow the list (search, facets, issue, archived); sort, currency and offset are not filters. */
export function activeFilterCount(state: ProductListState): number {
  const keys = ["q", "category_id", "subcategory_id", "family", "size", "thickness", "decor", "finish", "status", "brand", "issue"] as const;
  return keys.filter((key) => Boolean(state[key])).length + (state.include_archived ? 1 : 0);
}

export function clearedFiltersHref(state: ProductListState): string {
  return productListHref({ sort: state.sort && state.sort !== "relevance" ? state.sort : null, currency: state.currency });
}

/** Query parameters shared by the list and the facets endpoint (every filter, nothing else). */
export function productFilterParams(state: ProductListState): Record<string, string | boolean | undefined> {
  return {
    q: state.q || undefined,
    category_id: state.category_id ?? undefined,
    subcategory_id: state.subcategory_id ?? undefined,
    family: state.family ?? undefined,
    size: state.size ?? undefined,
    thickness: state.thickness ?? undefined,
    decor: state.decor ?? undefined,
    finish: state.finish ?? undefined,
    status: state.status ?? undefined,
    brand: state.brand ?? undefined,
    issue: state.issue ?? undefined,
    include_archived: state.include_archived ? true : undefined,
  };
}

/** Query parameters of the list page itself (filters plus sort, currency, limit and offset). */
export function productListParams(state: ProductListState): Record<string, string | number | boolean | undefined> {
  return {
    ...productFilterParams(state),
    sort: effectiveSort(state),
    price_currency: state.currency,
    limit: PRODUCTS_PAGE_SIZE,
    offset: state.offset,
  };
}
