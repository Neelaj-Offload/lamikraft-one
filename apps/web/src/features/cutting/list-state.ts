/**
 * URL search params <-> plan list state. Plain functions (no "use client"), so the server page reads its
 * search params with them and the client list builds links with them.
 */

import { PLANS_PAGE_SIZE } from "./api";
import { PLAN_STATUSES, type PlanStatus } from "./types";

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);
const DIGITS = /^\d{1,6}$/;

export interface PlanListState {
  q: string;
  status: PlanStatus | null;
  scope: "mine" | "all";
  offset: number;
}

/** URL → list state; anything unknown falls back to the default, never forwarded raw. */
export function planListStateFrom(search: Search): PlanListState {
  const q = (first(search.q) ?? "").slice(0, 200);
  const status = PLAN_STATUSES.find((candidate) => candidate === first(search.status)) ?? null;
  const scope = first(search.scope) === "mine" ? "mine" : "all";
  const raw = first(search.offset) ?? "0";
  let offset = 0;
  if (DIGITS.test(raw)) {
    for (const digit of raw) offset = offset * 10 + (digit.charCodeAt(0) - 48);
  }
  offset -= offset % PLANS_PAGE_SIZE;
  return { q, status, scope, offset };
}

export function planListHref(state: Partial<PlanListState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.status) query.set("status", state.status);
  if (state.scope === "mine") query.set("scope", "mine");
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `/operations/cutting?${search}` : "/operations/cutting";
}
