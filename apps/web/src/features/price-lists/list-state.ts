/**
 * URL search params <-> price-list state. Plain functions so the server pages read their search
 * params with them and the client lists build links with them.
 */

import { CURRENCIES, type CurrencyCode } from "@/lib/format/money";
import { PRICE_LIST_STATUSES, PRICE_SCOPES, PRICE_TYPES, type PriceListStatus, type PriceScope, type PriceType } from "./types";

export const PRICE_LISTS_PAGE_SIZE = 25;

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

function pageOffset(value: string | string[] | undefined, size: number): number {
  const raw = Number.parseInt(first(value) ?? "0", 10);
  return Number.isFinite(raw) && raw > 0 ? raw - (raw % size) : 0;
}

export interface PriceListListState {
  q: string;
  status: PriceListStatus | null;
  price_type: PriceType | null;
  currency: CurrencyCode | null;
  scope_kind: PriceScope | null;
  offset: number;
}

export function priceListListStateFrom(search: Search): PriceListListState {
  return {
    q: (first(search.q) ?? "").trim().slice(0, 200),
    status: PRICE_LIST_STATUSES.find((candidate) => candidate === first(search.status)) ?? null,
    price_type: PRICE_TYPES.find((candidate) => candidate === first(search.price_type)) ?? null,
    currency: CURRENCIES.find((candidate) => candidate === (first(search.currency) ?? "").toUpperCase()) ?? null,
    scope_kind: PRICE_SCOPES.find((candidate) => candidate === first(search.scope_kind)) ?? null,
    offset: pageOffset(search.offset, PRICE_LISTS_PAGE_SIZE),
  };
}

export function priceListListHref(state: Partial<PriceListListState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.status) query.set("status", state.status);
  if (state.price_type) query.set("price_type", state.price_type);
  if (state.currency) query.set("currency", state.currency);
  if (state.scope_kind) query.set("scope_kind", state.scope_kind);
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `/products/price-lists?${search}` : "/products/price-lists";
}

export function priceListListParams(state: PriceListListState): Record<string, string | number | undefined> {
  return {
    q: state.q || undefined,
    status: state.status ?? undefined,
    price_type: state.price_type ?? undefined,
    currency: state.currency ?? undefined,
    scope_kind: state.scope_kind ?? undefined,
    limit: PRICE_LISTS_PAGE_SIZE,
    offset: state.offset,
  };
}

export interface PriceListItemsState {
  q: string;
  include_history: boolean;
  offset: number;
}

export function priceListItemsStateFrom(search: Search): PriceListItemsState {
  const history = first(search.include_history);
  return {
    q: (first(search.q) ?? "").trim().slice(0, 200),
    include_history: history === "true" || history === "1",
    offset: pageOffset(search.offset, PRICE_LISTS_PAGE_SIZE),
  };
}

export function priceListItemsHref(priceListId: string, state: Partial<PriceListItemsState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.include_history) query.set("include_history", "true");
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  const base = `/products/price-lists/${encodeURIComponent(priceListId)}`;
  return search ? `${base}?${search}` : base;
}

export function priceListItemsParams(state: PriceListItemsState): Record<string, string | number | boolean | undefined> {
  return {
    q: state.q || undefined,
    include_history: state.include_history ? true : undefined,
    limit: PRICE_LISTS_PAGE_SIZE,
    offset: state.offset,
  };
}
