/** URL state for this screen: a plain module (no "use client"), so its server page can parse search params. */

import type { UserListParams } from "./api";

export const MEMBER_STATUSES = ["active", "invited", "deactivated"] as const;

export type UserListState = UserListParams;

export function userListStateFrom(params: Record<string, string | string[] | undefined>): UserListState {
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? null;
  const status = one(params.status);
  const offset = Number.parseInt(one(params.offset) ?? "0", 10);
  return {
    q: one(params.q)?.trim().slice(0, 100) || null,
    status: MEMBER_STATUSES.find((s) => s === status) ?? null,
    role: one(params.role)?.match(/^[a-z][a-z0-9_]{1,40}$/) ? one(params.role) : null,
    offset: Number.isFinite(offset) && offset > 0 ? offset : 0,
  };
}

export function userListHref(state: UserListState): string {
  const q = new URLSearchParams();
  if (state.q) q.set("q", state.q);
  if (state.status) q.set("status", state.status);
  if (state.role) q.set("role", state.role);
  if (state.offset) q.set("offset", String(state.offset));
  const s = q.toString();
  return s ? `/settings/users?${s}` : "/settings/users";
}
