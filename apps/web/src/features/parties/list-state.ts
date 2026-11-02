/**
 * URL search params <-> list state for the customers list. Plain functions (no "use client"), so
 * the server page can read its search params with them and the client list can build links.
 */

import { queryKeys } from "@/lib/api/query-keys";
import { PARTIES_PAGE_SIZE, type PartyListParams } from "./api";
import { CUSTOMER_TYPES, PARTY_ROLES, PARTY_STATUSES, type CustomerType, type PartyRole, type PartyStatus } from "./types";

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export interface PartyListState {
  q: string;
  role: PartyRole | null;
  status: PartyStatus | null;
  country_code: string | null;
  customer_type: CustomerType | null;
  include_archived: boolean;
  offset: number;
}

/** URL → list state; anything unknown falls back to the default, never forwarded raw. */
export function partyListStateFrom(search: Search): PartyListState {
  const q = (first(search.q) ?? "").slice(0, 200);
  const role = PARTY_ROLES.find((candidate) => candidate === first(search.role)) ?? null;
  const status = PARTY_STATUSES.find((candidate) => candidate === first(search.status)) ?? null;
  const rawCountry = (first(search.country_code) ?? "").trim().toUpperCase();
  const country_code = /^[A-Z]{2}$/.test(rawCountry) ? rawCountry : null;
  const customer_type = CUSTOMER_TYPES.find((candidate) => candidate === first(search.customer_type)) ?? null;
  const include_archived = first(search.include_archived) === "true" || first(search.include_archived) === "1";
  const rawOffset = Number.parseInt(first(search.offset) ?? "0", 10);
  const offset = Number.isFinite(rawOffset) && rawOffset > 0 ? rawOffset - (rawOffset % PARTIES_PAGE_SIZE) : 0;
  return { q, role, status, country_code, customer_type, include_archived, offset };
}

export function partyListHref(state: Partial<PartyListState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.role) query.set("role", state.role);
  if (state.status) query.set("status", state.status);
  if (state.country_code) query.set("country_code", state.country_code);
  if (state.customer_type) query.set("customer_type", state.customer_type);
  if (state.include_archived) query.set("include_archived", "true");
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `/sales/parties?${search}` : "/sales/parties";
}

/** One stable key per list state (the server page keys the client list on it). */
export function partyListKey(state: PartyListState): string {
  return [state.q, state.role, state.status, state.country_code, state.customer_type, state.include_archived, state.offset].join("|");
}

/** The request parameters for one list state. */
export function partyListParams(state: PartyListState): PartyListParams {
  return {
    q: state.q || null,
    role: state.role,
    status: state.status,
    country_code: state.country_code,
    customer_type: state.customer_type,
    include_archived: state.include_archived || null,
    offset: state.offset,
  };
}

/** The query key the server page and the client list share for one list state. */
export function partyListQueryKey(state: PartyListState) {
  const params = partyListParams(state);
  return queryKeys.parties.list({
    q: params.q?.trim() || null,
    role: params.role,
    status: params.status,
    country_code: params.country_code,
    customer_type: params.customer_type,
    include_archived: params.include_archived,
    offset: params.offset,
  });
}
