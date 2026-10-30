/**
 * Sign-in calls (api-conventions §7.1, frozen 2026-10-23). The `SessionInfo` response body is
 * not needed by the web: the browser receives the `lk_session` and `lk_csrf` cookies and the
 * next page load bootstraps the session.
 */

import { api, requestUntyped, type ApiClient } from "@/lib/api/client";
import { isNetworkError, ProblemError } from "@/lib/api/errors";
import { authMessages as m } from "@/messages/auth";

export const LOGIN_PATH = "/api/v1/identity/session";
export const DEMO_SIGN_IN_PATH = "/api/v1/identity/demo-sign-in";

/** Sign-in stage (platform-2): "active", or a second step still to do on /two-step (enter or set up a code). */
export type SignInStage = "active" | "mfa_pending" | "mfa_enrollment_required";

export async function signIn(email: string, password: string, client: ApiClient = api): Promise<SignInStage> {
  const info = await requestUntyped<{ stage?: SignInStage } | null>(client, "post", LOGIN_PATH, { body: { email, password } });
  return info?.stage ?? "active";
}

/** Where to go after the password: `next`, or the two-step page (which then continues to `next`). */
export function afterSignIn(stage: SignInStage, next: string): string {
  return stage === "active" ? next : `/two-step?next=${encodeURIComponent(next)}`;
}

export async function demoSignIn(token: string, client: ApiClient = api): Promise<void> {
  await requestUntyped<unknown>(client, "post", DEMO_SIGN_IN_PATH, { body: { token } });
}

export interface AuthFailure {
  message: string;
  requestId: string | null;
}

/**
 * Maps a failed sign-in to what the person should read. Wrong credentials get one generic
 * message; rate-limit and lockout messages come from the server's problem+json when it
 * provides them (the server knows the policy), with Retry-After rounded up to minutes.
 */
export function loginFailure(error: unknown): AuthFailure {
  if (isNetworkError(error)) return { message: m.login.network, requestId: null };
  if (!(error instanceof ProblemError)) return { message: m.login.generic, requestId: null };
  const requestId = error.request_id;
  switch (error.code) {
    case "invalid_credentials":
    case "unauthenticated":
      return { message: m.login.invalid, requestId: null };
    case "rate_limited": {
      const minutes = error.retryAfterSeconds ? Math.max(1, Math.ceil(error.retryAfterSeconds / 60)) : null;
      return { message: error.detail ?? m.login.rateLimited(minutes), requestId };
    }
    case "account_locked":
      return { message: error.detail ?? m.login.locked, requestId };
    case "cross_site_request":
    case "origin_mismatch":
    case "csrf_token_invalid":
      return { message: m.login.blocked, requestId };
    case "validation_failed":
      return { message: m.login.invalid, requestId: null };
    default:
      if (error.status === 401) return { message: m.login.invalid, requestId: null };
      if (error.status === 429) return { message: error.detail ?? m.login.rateLimited(null), requestId };
      return { message: m.login.generic, requestId };
  }
}

/** Reads the one-time token from a `#t=<token>` fragment; null when absent or blank. */
export function readFragmentToken(hash: string): string | null {
  const fragment = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!fragment) return null;
  const token = new URLSearchParams(fragment).get("t");
  return token && token.trim() ? token.trim() : null;
}
