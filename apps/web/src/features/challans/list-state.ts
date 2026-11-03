/**
 * URL search params <-> list state for /operations/challans. Plain functions (no "use client"), so the server page
 * reads its search params with them and the client list builds links with them. Unknown values are dropped.
 */

import { queryKeys } from "@/lib/api/query-keys";
import { CHALLANS_PAGE_SIZE, type ChallanListParams } from "./api";
import { CHALLAN_STATUSES, CHALLAN_TYPES, DESTINATION_TYPES, PERIODS, type ChallanStatus, type ChallanType, type DestinationType, type Period } from "./types";

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export const CHALLANS_ROUTE = "/operations/challans";

export interface ChallanListState {
  q: string;
  status: ChallanStatus | null;
  type: ChallanType | null;
  destination: DestinationType | null;
  period: Period | null;
  pending: boolean;
  scope: "mine" | "all";
  offset: number;
}

export const DEFAULT_CHALLAN_LIST: ChallanListState = { q: "", status: null, type: null, destination: null, period: null, pending: false, scope: "all", offset: 0 };

function pick<T extends string>(values: readonly T[], raw: string | undefined): T | null {
  return values.find((candidate) => candidate === raw) ?? null;
}

export function challanListStateFrom(search: Search): ChallanListState {
  const rawOffset = Number.parseInt(first(search.offset) ?? "0", 10);
  return {
    q: (first(search.q) ?? "").slice(0, 200),
    status: pick(CHALLAN_STATUSES, first(search.status)),
    type: pick(CHALLAN_TYPES, first(search.type)),
    destination: pick(DESTINATION_TYPES, first(search.destination)),
    period: pick(PERIODS, first(search.period)),
    pending: first(search.pending) === "1",
    scope: first(search.scope) === "mine" ? "mine" : "all",
    offset: Number.isFinite(rawOffset) && rawOffset > 0 ? rawOffset - (rawOffset % CHALLANS_PAGE_SIZE) : 0,
  };
}

export function challanListHref(state: Partial<ChallanListState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.status) query.set("status", state.status);
  if (state.type) query.set("type", state.type);
  if (state.destination) query.set("destination", state.destination);
  if (state.period) query.set("period", state.period);
  if (state.pending) query.set("pending", "1");
  if (state.scope === "mine") query.set("scope", "mine");
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `${CHALLANS_ROUTE}?${search}` : CHALLANS_ROUTE;
}

export function challanListParams(state: ChallanListState): ChallanListParams {
  return {
    q: state.q || null,
    status: state.status,
    challan_type: state.type,
    destination_type: state.destination,
    period: state.period,
    pending_returnable: state.pending,
    scope: state.scope,
    offset: state.offset,
  };
}

/** The summary ignores the page offset: the cards count the whole filtered set. */
export function challanSummaryParams(state: ChallanListState): ChallanListParams {
  return { ...challanListParams(state), offset: null };
}

export function challanListQueryKey(state: ChallanListState) {
  const { offset, ...filters } = challanListParams(state);
  return queryKeys.challans.list({ ...filters, offset });
}

export function challanSummaryQueryKey(state: ChallanListState) {
  return queryKeys.challans.summary({ ...challanSummaryParams(state), offset: undefined });
}

/** A React key that remounts the list when the URL state changes. */
export function challanListKey(state: ChallanListState): string {
  return challanListHref(state);
}
