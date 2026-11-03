"use client";

/**
 * The quote configurator (LM-43, API-34, UI-60): a search-first product finder for a quote line.
 * `POST /api/v1/sales/quotes/configurator/resolve` applies the filters before paging, narrows every facet over
 * the whole filtered set, names an `exact_match` when one product remains, and prices each row for the quote's
 * customer (agreement → customer type → standard, approved FX when needed) with its order-value recommendation.
 * Nothing here computes a price: the drawer shows the server's figures and the server re-resolves on add.
 */

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap, type ApiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type { components } from "@/lib/api/schema";
import { compareDecimalStr, isDecimalStr } from "@/lib/format/decimal";
import { useDebouncedValue } from "@/lib/hooks";
import type { CatalogLineRequest, QuoteDetail } from "./types";

type Schemas = components["schemas"];
export type ConfiguratorRequestBody = Schemas["ConfiguratorRequest"];
export type ConfiguratorResult = Schemas["ConfiguratorResult"];
export type ConfiguratorRow = Schemas["ConfiguratorRow"];
export type FacetValue = Schemas["FacetValue"];

export const CONFIGURATOR_PATH = "/api/v1/sales/quotes/configurator/resolve" as const;
export const CONFIGURATOR_PAGE_SIZE = 20;

/** The six cascading filters of the legacy dialog, in its order; each maps to a facet of the response. */
export const CONFIGURATOR_FILTERS = [
  { key: "category_id", facet: "categories" },
  { key: "family", facet: "families" },
  { key: "size", facet: "sizes" },
  { key: "thickness", facet: "thicknesses" },
  { key: "decor", facet: "decors" },
  { key: "finish", facet: "finishes" },
] as const satisfies ReadonlyArray<{ key: keyof ConfiguratorRequestBody; facet: keyof ConfiguratorResult["facets"] }>;

export type FilterKey = (typeof CONFIGURATOR_FILTERS)[number]["key"];
export type ConfiguratorFilters = { q: string } & Record<FilterKey, string | null>;

export const EMPTY_FILTERS: ConfiguratorFilters = {
  q: "",
  category_id: null,
  family: null,
  size: null,
  thickness: null,
  decor: null,
  finish: null,
};

export function activeFilterCount(filters: ConfiguratorFilters): number {
  return CONFIGURATOR_FILTERS.filter(({ key }) => filters[key] !== null).length;
}

/** The request body for one page: empty filters are omitted, the quote's customer, currency and price type apply. */
export function configuratorRequest(
  quote: Pick<QuoteDetail, "party" | "currency" | "price_type">,
  filters: ConfiguratorFilters,
  offset: number,
): ConfiguratorRequestBody {
  const body: ConfiguratorRequestBody = {
    party_id: quote.party.id,
    currency: quote.currency as ConfiguratorRequestBody["currency"],
    price_type: quote.price_type,
    limit: CONFIGURATOR_PAGE_SIZE,
    offset: Math.max(0, offset),
  };
  const q = filters.q.trim();
  if (q) body.q = q;
  for (const { key } of CONFIGURATOR_FILTERS) {
    const value = filters[key];
    if (value !== null) body[key] = value;
  }
  return body;
}

/**
 * The options of one filter: the narrowed facet values with their counts, plus the current selection even when the
 * narrowed set no longer contains it (so a selection never silently disappears), after an "Any" entry.
 */
export function filterOptions(
  values: readonly FacetValue[],
  selected: string | null,
  anyLabel: string,
): { id: string; label: string; detail?: string }[] {
  const options = values.map((value) => ({ id: value.value, label: value.label, detail: String(value.count) }));
  if (selected !== null && !options.some((option) => option.id === selected)) options.unshift({ id: selected, label: selected, detail: "0" });
  return [{ id: ANY, label: anyLabel }, ...options];
}

/** The id of the "Any" option (React Aria keys can't be null). */
export const ANY = "__any__";

export function pageLabel(result: Pick<ConfiguratorResult, "total" | "offset" | "items">): { from: number; to: number; total: number } {
  if (result.total === 0 || result.items.length === 0) return { from: 0, to: 0, total: result.total };
  return { from: result.offset + 1, to: result.offset + result.items.length, total: result.total };
}

export type PickAdvisory = "below_recommendation" | "price_differs" | "unpriced";

/** Amber advisories of the legacy dialog: quantity below the order-value recommendation; price differs from default. */
export function pickAdvisories(row: ConfiguratorRow, quantity: string | null, unitPrice: string | null): PickAdvisory[] {
  const out: PickAdvisory[] = [];
  const recommended = row.recommendation?.status === "AVAILABLE" ? row.recommendation.quantity?.value ?? null : null;
  if (recommended && quantity && isDecimalStr(quantity) && compareDecimalStr(quantity, "0") > 0 && compareDecimalStr(quantity, recommended) < 0) {
    out.push("below_recommendation");
  }
  const listed = row.price?.unit_price?.amount ?? null;
  if (!listed) out.push("unpriced");
  else if (unitPrice && isDecimalStr(unitPrice) && compareDecimalStr(unitPrice, listed) !== 0) out.push("price_differs");
  return out;
}

export type PickError = "quantity" | "price" | "reason";

/** The catalog line to add, or the field that blocks it. The price is sent only when it overrides the default. */
export function pickLine(
  row: ConfiguratorRow,
  input: { quantity: string | null; unitPrice: string | null; reason: string },
): { ok: true; line: CatalogLineRequest } | { ok: false; error: PickError } {
  const { quantity, unitPrice } = input;
  if (!quantity || !isDecimalStr(quantity) || compareDecimalStr(quantity, "0") <= 0) return { ok: false, error: "quantity" };
  if (unitPrice !== null && !isDecimalStr(unitPrice)) return { ok: false, error: "price" };
  const listed = row.price?.unit_price?.amount ?? null;
  const overrides = unitPrice !== null && (listed === null || compareDecimalStr(unitPrice, listed) !== 0);
  const reason = input.reason.trim();
  if (overrides && !reason) return { ok: false, error: "reason" };
  const line: CatalogLineRequest = { line_type: "catalog", product_id: row.product.id, quantity };
  if (row.product.unit_of_sale) line.unit_code = row.product.unit_of_sale;
  if (overrides) {
    line.unit_price = unitPrice;
    line.override_reason = reason;
  }
  return { ok: true, line };
}

export async function resolveConfigurator(body: ConfiguratorRequestBody, signal?: AbortSignal, client: ApiClient = api): Promise<ConfiguratorResult> {
  return unwrap(client.POST(CONFIGURATOR_PATH, { body, signal }));
}

/** One page of the configurator; the search text is debounced, filters and paging apply at once. */
export function useConfigurator(
  quote: Pick<QuoteDetail, "party" | "currency" | "price_type">,
  filters: ConfiguratorFilters,
  offset: number,
  enabled: boolean,
) {
  const q = useDebouncedValue(filters.q, 250);
  const body = configuratorRequest(quote, { ...filters, q }, offset);
  return useQuery({
    queryKey: queryKeys.sales.configurator(body),
    queryFn: ({ signal }) => resolveConfigurator(body, signal),
    enabled,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}
