"use client";

/**
 * Data hooks for Settings → people and access (users, roles, the access check, access requests,
 * delegation, leave, security, profile). The old app kept these queries inside its view files
 * (`apps/web/src/app/(app)/settings/_lib/*.tsx`); the calls themselves live in the plain module
 * `_lib/api.ts`, which is used as it is.
 *
 * Every hook reuses the old query keys under `["identity", …]`, and every mutation in these screens
 * ends with `useRefreshIdentity()`, the same `identity.all()` invalidation the old screens ran.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import {
  fetchAbsences,
  fetchAccessCheck,
  fetchAccessRequests,
  fetchCatalogue,
  fetchDelegations,
  fetchEffective,
  fetchMfa,
  fetchMySessions,
  fetchRole,
  fetchRoles,
  fetchUser,
  fetchUsers,
  type UserListParams,
} from "@/app/(app)/settings/_lib/api";
import type { Scope } from "@/app/(app)/settings/_lib/types";
import { fetchMe } from "@/features/settings/api";
import { api, requestUntyped } from "@/lib/api/client";
import { isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { useDebouncedValue } from "@/lib/hooks";

/** Re-reads everything under `["identity"]` after a change, as every old settings command did. */
export function useRefreshIdentity(): () => Promise<void> {
  const client = useQueryClient();
  return useCallback(() => client.invalidateQueries({ queryKey: queryKeys.identity.all() }), [client]);
}

// ---- users ---------------------------------------------------------------------------------------

export function useUsers(state: UserListParams) {
  return useQuery({ queryKey: queryKeys.identity.users(state), queryFn: ({ signal }) => fetchUsers(state, signal) });
}

/** The first page of active people, for the access check's person picker (the old simulator's query and key). */
export function useActiveUsers() {
  return useQuery({
    queryKey: queryKeys.identity.users({}),
    queryFn: ({ signal }) => fetchUsers({ q: null, status: "active", role: null, offset: 0 }, signal),
  });
}

export function useUser(userId: string) {
  return useQuery({ queryKey: queryKeys.identity.user(userId), queryFn: ({ signal }) => fetchUser(userId, signal) });
}

// ---- roles and permissions -----------------------------------------------------------------------

export function useRoles() {
  return useQuery({ queryKey: queryKeys.identity.roles(), queryFn: ({ signal }) => fetchRoles(signal) });
}

/** One role; `roleId` null (a new role) keeps the query idle. */
export function useRole(roleId: string | null) {
  return useQuery({
    queryKey: queryKeys.identity.role(roleId ?? "new"),
    queryFn: ({ signal }) => fetchRole(roleId!, signal),
    enabled: roleId !== null,
  });
}

/**
 * The permission catalogue. Only people who may read roles can load it, so the access-request form
 * asks without retrying (`retry: false`) and falls back to a typed key when it is refused.
 */
export function usePermissionCatalogue(options: { enabled?: boolean; retry?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.identity.catalogue(),
    queryFn: ({ signal }) => fetchCatalogue(signal),
    enabled: options.enabled ?? true,
    ...(options.retry === false ? { retry: false } : {}),
  });
}

export function useEffectiveAccess(subject: { userId: string | null; roleId: string | null }) {
  return useQuery({
    queryKey: queryKeys.identity.effective(subject),
    queryFn: ({ signal }) => fetchEffective(subject, signal),
    enabled: Boolean(subject.userId || subject.roleId),
  });
}

export function useAccessCheck(userId: string | null, key: string | null, scope: Scope) {
  return useQuery({
    queryKey: queryKeys.identity.check({ userId: userId ?? "", key: key ?? "", scope }),
    queryFn: ({ signal }) => fetchAccessCheck(userId!, key!, scope, signal),
    enabled: Boolean(userId) && Boolean(key),
  });
}

// ---- your own security ---------------------------------------------------------------------------

export function useMfaStatus() {
  return useQuery({ queryKey: queryKeys.identity.mfa(), queryFn: ({ signal }) => fetchMfa(signal) });
}

export function useMySessions() {
  return useQuery({ queryKey: queryKeys.identity.sessions(), queryFn: ({ signal }) => fetchMySessions(signal) });
}

export function useMe() {
  return useQuery({ queryKey: queryKeys.identity.me(), queryFn: ({ signal }) => fetchMe(signal) });
}

// ---- delegation, leave, access requests ----------------------------------------------------------

export function useDelegations(scope: "mine" | "all") {
  return useQuery({ queryKey: queryKeys.identity.delegations(scope), queryFn: ({ signal }) => fetchDelegations(scope, signal) });
}

export function useAbsences(scope: "mine" | "team") {
  return useQuery({ queryKey: queryKeys.identity.absences(scope), queryFn: ({ signal }) => fetchAbsences(scope, signal) });
}

export function useAccessRequests(scope: "mine" | "all", enabled = true) {
  return useQuery({
    queryKey: queryKeys.identity.accessRequests(scope),
    queryFn: ({ signal }) => fetchAccessRequests(scope, signal),
    enabled,
  });
}

// ---- colleague search ----------------------------------------------------------------------------

export interface PersonHit {
  id: string;
  name: string;
  /** Job title or team, as the directory search returns it. Never contact details. */
  detail: string | null;
}

interface PeopleSearchResult {
  groups: { resource_type: string; hits: { resource_id: string; title: string; subtitle: string | null }[] }[];
}

export const PEOPLE_SEARCH_MIN_CHARS = 2;

/** Colleagues by name over the people directory (`GET /search?types=org.person`), once two letters are typed. */
export function usePeopleSearch(text: string) {
  const q = useDebouncedValue(text.trim(), 250);
  const query = useQuery({
    queryKey: [...queryKeys.search.query(q), "people"],
    queryFn: async ({ signal }): Promise<PersonHit[]> => {
      const result = await requestUntyped<PeopleSearchResult>(api, "get", "/api/v1/search", {
        params: { query: { q, types: "org.person", limit: 10 } },
        signal,
      });
      return result.groups.flatMap((group) => group.hits).map((hit) => ({ id: hit.resource_id, name: hit.title, detail: hit.subtitle }));
    },
    enabled: q.length >= PEOPLE_SEARCH_MIN_CHARS,
  });
  return { hits: query.data ?? [], isSearching: query.isFetching, ready: q.length >= PEOPLE_SEARCH_MIN_CHARS };
}

// ---- step-up -------------------------------------------------------------------------------------

/** The problem codes that ask the person to confirm it is them before a sensitive change (permissions.md §6). */
export const STEP_UP_CODES: ReadonlySet<string> = new Set(["reauth_required", "mfa_required"]);

/** Which proof a refused command asks for: the password again, or an authenticator code. */
export function needsStepUp(error: unknown): "password" | "code" | null {
  if (!isProblemError(error) || !STEP_UP_CODES.has(error.code)) return null;
  return error.code === "mfa_required" ? "code" : "password";
}
