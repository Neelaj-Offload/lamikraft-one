"use client";

/**
 * Lookups for the quote screens: customers (parties `PartySummary`, GET /api/v1/parties/parties)
 * and products (catalogue `ProductSummary`, GET /api/v1/catalogue/products). Both lists are
 * filtered on the server; the picker shows at most ten matches. Prices are never read here:
 * `resolve_price` runs on the server when a line is added.
 */

import { useQuery } from "@tanstack/react-query";
import { api, requestUntyped, type ApiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useDebouncedValue } from "@/lib/hooks";

export interface PartyOption {
  id: string;
  party_number: string;
  display_name: string;
  country_code: string;
  default_currency: string;
}

export interface ProductOption {
  id: string;
  product_key: string;
  product_name: string;
  decor: string | null;
  unit_of_sale: string | null;
  carton_qty: number | null;
}

type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => value !== null && typeof value === "object" && !Array.isArray(value);
const str = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);
const items = (raw: unknown): unknown[] => (isObject(raw) && Array.isArray(raw.items) ? raw.items : []);

export function parsePartyOptions(raw: unknown): PartyOption[] {
  return items(raw).flatMap((entry) =>
    isObject(entry) && str(entry.id) && str(entry.display_name)
      ? [
          {
            id: str(entry.id)!,
            party_number: str(entry.party_number) ?? "",
            display_name: str(entry.display_name)!,
            country_code: str(entry.country_code) ?? "",
            default_currency: str(entry.default_currency) ?? "",
          },
        ]
      : [],
  );
}

export function parseProductOptions(raw: unknown): ProductOption[] {
  return items(raw).flatMap((entry) =>
    isObject(entry) && str(entry.id) && str(entry.product_key)
      ? [
          {
            id: str(entry.id)!,
            product_key: str(entry.product_key)!,
            product_name: str(entry.product_name) ?? str(entry.product_key)!,
            decor: str(entry.decor_name) ?? str(entry.decor_no),
            unit_of_sale: str(entry.unit_of_sale),
            carton_qty: typeof entry.carton_qty === "number" ? entry.carton_qty : null,
          },
        ]
      : [],
  );
}

export async function searchParties(q: string, signal?: AbortSignal, client: ApiClient = api): Promise<PartyOption[]> {
  const raw = await requestUntyped<unknown>(client, "get", "/api/v1/parties/parties", {
    params: { query: { q: q.trim() || undefined, role: "customer", limit: 10 } },
    signal,
  });
  return parsePartyOptions(raw);
}

export async function searchProducts(q: string, signal?: AbortSignal, client: ApiClient = api): Promise<ProductOption[]> {
  const raw = await requestUntyped<unknown>(client, "get", "/api/v1/catalogue/products", {
    params: { query: { q: q.trim() || undefined, limit: 10 } },
    signal,
  });
  return parseProductOptions(raw);
}

/** Server-side search as the person types (250 ms debounce, at least 2 characters). */
export function usePartySearch(text: string) {
  const q = useDebouncedValue(text.trim(), 250);
  return useQuery({ queryKey: queryKeys.parties.search(q), queryFn: ({ signal }) => searchParties(q, signal), enabled: q.length >= 2, staleTime: 30_000 });
}

export function useProductSearch(text: string) {
  const q = useDebouncedValue(text.trim(), 250);
  return useQuery({ queryKey: queryKeys.catalogue.productSearch(q), queryFn: ({ signal }) => searchProducts(q, signal), enabled: q.length >= 2, staleTime: 30_000 });
}
