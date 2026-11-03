/**
 * URL state of the list (server-safe: the page component parses `searchParams` with it, so it must not live in a
 * "use client" module).
 */

import { PRICE_LIST_STATUSES, PRICE_LISTS_PAGE_SIZE } from "./api";

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export interface PriceListState {
  q: string;
  status: string | null;
  offset: number;
}

export function priceListStateFrom(search: Search): PriceListState {
  const q = (first(search.q) ?? "").slice(0, 200);
  const status = PRICE_LIST_STATUSES.find((candidate) => candidate === first(search.status)) ?? null;
  const raw = Number.parseInt(first(search.offset) ?? "0", 10);
  const offset = Number.isFinite(raw) && raw > 0 ? raw - (raw % PRICE_LISTS_PAGE_SIZE) : 0;
  return { q, status, offset };
}

export function priceListHref(state: Partial<PriceListState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.status) query.set("status", state.status);
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `/products/price-lists?${search}` : "/products/price-lists";
}
