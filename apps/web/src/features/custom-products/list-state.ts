/** URL state for this screen: a plain module (no "use client"), so its server page can parse search params. */

import { CUSTOM_PAGE_SIZE, CUSTOM_STATUSES, type CustomStatus } from "./api";

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export interface CustomListState {
  q: string;
  status: CustomStatus | null;
  scope: "mine" | "all";
  offset: number;
}

/** URL -> list state; unknown values fall back to the defaults, never forwarded raw. */
export function customListStateFrom(search: Search): CustomListState {
  const q = (first(search.q) ?? "").slice(0, 200);
  const status = CUSTOM_STATUSES.find((candidate) => candidate === first(search.status)) ?? null;
  const scope = first(search.scope) === "mine" ? "mine" : "all";
  const raw = Number.parseInt(first(search.offset) ?? "0", 10);
  const offset = Number.isFinite(raw) && raw > 0 ? raw - (raw % CUSTOM_PAGE_SIZE) : 0;
  return { q, status, scope, offset };
}

export function customListHref(state: Partial<CustomListState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.status) query.set("status", state.status);
  if (state.scope === "mine") query.set("scope", "mine");
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `/sales/custom-products?${search}` : "/sales/custom-products";
}
