/**
 * Data calls for the entry screens: the signed-out flows (password reset, invitation, two-step
 * sign-in) and the full search results screen. Sign-in, demo sign-in, sign-out and the activity
 * feed already have plain modules in the old app (`@/features/auth/auth-api`,
 * `@/lib/session/sign-out`, `@/features/collab/api`); the calls below lived inside old view files,
 * so they are restated here with the same endpoints, bodies and query keys.
 */

import { api, requestUntyped } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type { SignInStage } from "@/features/auth/auth-api";
import { PAGE_SIZE, type SearchPageState } from "@/features/search/page-state";
import { parseRecent, parseSearchResponse } from "@/features/search/parse";
import type { RecentSearch, SearchResponse } from "@/features/search/types";

const IDENTITY = "/api/v1/identity";

// ---- password reset ----

/** Always answers the same way whether or not the address belongs to someone (no account discovery). */
export function requestPasswordReset(email: string): Promise<unknown> {
  return requestUntyped<unknown>(api, "post", `${IDENTITY}/password-resets`, { body: { email } });
}

/** Sets a new password with a one-time link token. Every session ends; two-step sign-in is kept. */
export function completePasswordReset(token: string, password: string): Promise<unknown> {
  return requestUntyped<unknown>(api, "post", `${IDENTITY}/password-resets/completion`, { body: { token, password } });
}

// ---- invitation ----

export interface InvitationPreview {
  email: string;
  display_name: string;
  company_name: string;
  expires_at: string;
  /** The address already has an account: the password confirms it instead of creating one. */
  has_password: boolean;
}

export function previewInvitation(token: string): Promise<InvitationPreview> {
  return requestUntyped<InvitationPreview>(api, "post", `${IDENTITY}/invitations/preview`, { body: { token } });
}

export async function acceptInvitation(token: string, password: string, displayName: string): Promise<SignInStage> {
  const info = await requestUntyped<{ stage?: SignInStage } | null>(api, "post", `${IDENTITY}/invitations/acceptance`, {
    body: { token, password, display_name: displayName.trim() || null },
  });
  return info?.stage ?? "active";
}

// ---- two-step sign-in ----

export interface TwoStepEnrollment {
  factor_id: string;
  secret: string;
  otpauth_uri: string;
  /** Drawn by the server from the provisioning URI, so no third party ever sees the secret. */
  qr_svg: string;
}

/** An enrolment-only session can read this; a session still waiting for its code cannot (401). */
export function fetchTwoStepStatus(): Promise<{ enrolled: boolean }> {
  return requestUntyped<{ enrolled: boolean }>(api, "get", `${IDENTITY}/me/mfa`);
}

export function verifyTwoStepCode(code: string): Promise<unknown> {
  return requestUntyped<unknown>(api, "post", `${IDENTITY}/session/verification`, { body: { code } });
}

export function startAuthenticatorSetup(): Promise<TwoStepEnrollment> {
  return requestUntyped<TwoStepEnrollment>(api, "post", `${IDENTITY}/me/mfa/totp`);
}

export function confirmAuthenticatorSetup(code: string): Promise<{ recovery_codes: string[] }> {
  return requestUntyped<{ recovery_codes: string[] }>(api, "post", `${IDENTITY}/me/mfa/totp/confirmation`, { body: { code } });
}

// ---- search ----

export const SEARCH_MIN_CHARS = 2;
/** Hits shown per group on the grouped screen; one group on its own pages by PAGE_SIZE. */
export const SEARCH_GROUP_PREVIEW = 5;

export function searchPageKey(state: SearchPageState) {
  return [...queryKeys.search.query(state.q), { type: state.type, offset: state.offset }] as const;
}

export async function fetchSearchPage(state: SearchPageState, signal?: AbortSignal): Promise<SearchResponse> {
  const raw = await requestUntyped<unknown>(api, "get", "/api/v1/search", {
    params: {
      query: {
        q: state.q,
        limit: state.type ? PAGE_SIZE : SEARCH_GROUP_PREVIEW,
        types: state.type ?? undefined,
        offset: state.type ? state.offset : undefined,
      },
    },
    signal,
  });
  return parseSearchResponse(raw, state.q);
}

export async function fetchRecentSearches(signal?: AbortSignal): Promise<RecentSearch[]> {
  return parseRecent(await requestUntyped<unknown>(api, "get", "/api/v1/search/recent", { signal }));
}

/** Remembers a search the person ran (the server keeps the newest ten); a failure never blocks the screen. */
export function rememberSearch(q: string): Promise<void> {
  const query = q.trim();
  if (query.length < SEARCH_MIN_CHARS) return Promise.resolve();
  return requestUntyped<unknown>(api, "post", "/api/v1/search/recent", { body: { query } }).then(
    () => undefined,
    () => undefined,
  );
}
