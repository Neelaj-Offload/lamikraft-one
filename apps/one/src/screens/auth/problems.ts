import { isNetworkError, isProblemError, ProblemError } from "@/lib/api/errors";

/**
 * What a failed sign-in or one-time link says to the person. Wrong credentials always get the same
 * sentence (no account discovery); rate-limit and lockout wording comes from the server when it
 * sends some, because the server knows the policy.
 */

export interface AuthFailure {
  message: string;
  /** Shown as "Reference …" when the cause is on our side or a security check, never for a wrong password. */
  requestId: string | null;
}

const WRONG = "That email and password do not match an active account. Check both and try again.";
const UNREACHABLE = "Lamikraft One cannot be reached. Check your connection and try again.";
const OUR_SIDE = "Something went wrong on our side. Try again in a moment.";

function waitText(seconds: number | null): string {
  if (!seconds) return "Too many attempts. Wait a few minutes, then try again.";
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  return `Too many attempts. Try again in ${minutes} ${minutes === 1 ? "minute" : "minutes"}.`;
}

/** Email and password sign-in, and the demo link when it fails for a reason other than the link itself. */
export function signInFailure(error: unknown): AuthFailure {
  if (isNetworkError(error)) return { message: UNREACHABLE, requestId: null };
  if (!(error instanceof ProblemError)) return { message: OUR_SIDE, requestId: null };
  const requestId = error.request_id;
  switch (error.code) {
    case "invalid_credentials":
    case "unauthenticated":
    case "validation_failed":
      return { message: WRONG, requestId: null };
    case "rate_limited":
      return { message: error.detail ?? waitText(error.retryAfterSeconds), requestId };
    case "account_locked":
      return {
        message: error.detail ?? "This account is locked for a while after repeated failed attempts. Try again later, or ask a workspace admin.",
        requestId,
      };
    case "cross_site_request":
    case "origin_mismatch":
    case "csrf_token_invalid":
      return { message: "A security check stopped this sign-in. Reload the page and try again.", requestId };
    default:
      if (error.status === 401) return { message: WRONG, requestId: null };
      if (error.status === 429) return { message: error.detail ?? waitText(error.retryAfterSeconds), requestId };
      return { message: OUR_SIDE, requestId };
  }
}

/** One-time links: an invitation or a password reset. */
export function linkFailure(error: unknown): string {
  if (isNetworkError(error)) return UNREACHABLE;
  if (isProblemError(error, "link_invalid_or_used")) return "This link has expired or was already used. Ask for a new one.";
  if (isProblemError(error) && error.status === 429) return waitText(error.retryAfterSeconds);
  if (isProblemError(error)) return error.detail ?? error.title;
  return "Something went wrong. Try again.";
}

/** What the server said about one field of a rejected form (422); undefined when it had no complaint about it. */
export function fieldIssue(error: unknown, field: string): string | undefined {
  if (!isProblemError(error) || error.status !== 422) return undefined;
  return error.validationIssues.find((issue) => issue.loc.includes(field))?.msg;
}

/** The password rule the server rejected (422), to show under the field; undefined for any other failure. */
export function passwordRuleFailure(error: unknown): string | undefined {
  if (!isProblemError(error) || error.status !== 422) return undefined;
  // A malformed token or another field is not a password problem.
  if (fieldIssue(error, "token") || fieldIssue(error, "display_name")) return undefined;
  return fieldIssue(error, "password") ?? error.validationIssues[0]?.msg ?? error.detail ?? undefined;
}

/** The link is spent, expired, or was cut short on the way here (a token the server will not even read). */
export function isSpentLink(error: unknown): boolean {
  return isProblemError(error, "link_invalid_or_used") || fieldIssue(error, "token") !== undefined;
}
