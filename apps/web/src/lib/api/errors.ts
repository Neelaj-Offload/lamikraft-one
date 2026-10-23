/**
 * Error types for calls to the FastAPI backend.
 *
 * The backend answers failures with RFC 9457 problem+json carrying a snake_case
 * `code` and a `request_id` (docs/architecture/api-conventions.md §3). Non-problem
 * failures (for example a proxy error page while the API is down) are still
 * surfaced as a ProblemError so callers handle one shape.
 */

export const PROBLEM_CONTENT_TYPE = "application/problem+json";

/**
 * Codes the client reacts to (api-conventions §3 and §7.1). The backend may return
 * others; those are handled by HTTP status.
 */
export type KnownProblemCode =
  | "validation_failed"
  | "unauthenticated"
  | "session_expired"
  | "reauth_required"
  | "mfa_required"
  | "invalid_credentials"
  | "account_locked"
  | "link_invalid_or_used"
  | "permission_denied"
  | "cross_site_request"
  | "origin_mismatch"
  | "csrf_token_invalid"
  | "not_found"
  | "version_conflict"
  | "invalid_transition"
  | "proposal_changed"
  | "approval_stale"
  | "item_changed"
  | "recommendation_stale"
  | "not_complete"
  | "not_configured"
  | "pin_ended"
  | "idempotency_key_reused"
  | "snooze_beyond_deadline"
  | "mandatory_control"
  | "rate_limited"
  | "service_unavailable";

/** 409 codes meaning "this changed since you loaded it" (api-conventions §3, never 412). */
export const STALENESS_CONFLICT_CODES: ReadonlySet<string> = new Set([
  "version_conflict",
  "invalid_transition",
  "proposal_changed",
  "approval_stale",
  "item_changed",
  "recommendation_stale",
]);

/** Assigned client-side when the response body is not problem+json. */
export const NON_PROBLEM_CODE = "http_error";

export interface ValidationIssue {
  loc: ReadonlyArray<string | number>;
  msg: string;
  code: string;
}

export interface ProblemDetails {
  type?: string;
  title: string;
  status: number;
  detail?: string | null;
  code: KnownProblemCode | (string & {});
  request_id?: string | null;
  instance?: string;
  /** Extension members such as `errors`, `current_version` or `changed_by`. */
  [extension: string]: unknown;
}

export class ProblemError extends Error {
  override readonly name = "ProblemError";
  readonly code: ProblemDetails["code"];
  readonly title: string;
  readonly detail: string | null;
  readonly status: number;
  readonly request_id: string | null;
  /** Seconds from the Retry-After header (429 and 503), when the server sent one. */
  readonly retryAfterSeconds: number | null;
  /** The full problem document, including extension members. */
  readonly problem: Readonly<ProblemDetails>;

  constructor(problem: ProblemDetails, retryAfterSeconds: number | null = null) {
    super(problem.detail || problem.title);
    this.problem = problem;
    this.code = problem.code;
    this.title = problem.title;
    this.detail = problem.detail ?? null;
    this.status = problem.status;
    this.request_id = problem.request_id ?? null;
    this.retryAfterSeconds = retryAfterSeconds;
  }

  /** Builds an error from a failed response and its already-parsed body. */
  static fromResponse(response: Response, body: unknown): ProblemError {
    const headerRequestId = response.headers.get("x-request-id");
    const retryAfter = parseRetryAfter(response.headers.get("retry-after"));
    if (isProblemBody(body)) {
      return new ProblemError(
        {
          ...body,
          status: typeof body.status === "number" ? body.status : response.status,
          request_id: typeof body.request_id === "string" ? body.request_id : headerRequestId,
        },
        retryAfter,
      );
    }
    const fastApiDetail =
      body !== null && typeof body === "object" && typeof (body as { detail?: unknown }).detail === "string"
        ? (body as { detail: string }).detail
        : null;
    return new ProblemError(
      {
        code: NON_PROBLEM_CODE,
        title: response.statusText || `Request failed with status ${response.status}`,
        status: response.status,
        detail: fastApiDetail,
        request_id: headerRequestId,
      },
      retryAfter,
    );
  }

  /** Field errors of a 422 `validation_failed` response; empty for every other problem. */
  get validationIssues(): ValidationIssue[] {
    const errors = this.problem.errors;
    if (!Array.isArray(errors)) return [];
    return errors.filter(
      (entry): entry is ValidationIssue =>
        entry !== null &&
        typeof entry === "object" &&
        Array.isArray((entry as ValidationIssue).loc) &&
        typeof (entry as ValidationIssue).msg === "string",
    );
  }
}

/** Retry-After is either delta-seconds or an HTTP date; both become whole seconds from now. */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) return Number.parseInt(trimmed, 10);
  const at = Date.parse(trimmed);
  if (Number.isNaN(at)) return null;
  return Math.max(0, Math.ceil((at - now) / 1000));
}

function isProblemBody(body: unknown): body is ProblemDetails {
  if (body === null || typeof body !== "object") return false;
  const candidate = body as Record<string, unknown>;
  return typeof candidate.code === "string" && typeof candidate.title === "string";
}

export function isProblemContentType(contentType: string | null): boolean {
  return contentType?.split(";", 1)[0]?.trim().toLowerCase() === PROBLEM_CONTENT_TYPE;
}

export function isProblemError(error: unknown, code?: ProblemDetails["code"]): error is ProblemError {
  return error instanceof ProblemError && (code === undefined || error.code === code);
}

/** The request never produced an HTTP response (offline, DNS, connection reset). */
export class NetworkError extends Error {
  override readonly name = "NetworkError";

  constructor(cause: unknown) {
    super("The server could not be reached. Check your connection and try again.", { cause });
  }
}

export function isNetworkError(error: unknown): error is NetworkError {
  return error instanceof NetworkError;
}

/**
 * True when the endpoint itself does not exist on this server (yet): a plain 404/405 from
 * the router rather than a `not_found` for a record. Screens use it to show a calm
 * "not available" state instead of an error.
 */
export function isEndpointUnavailable(error: unknown): boolean {
  if (!(error instanceof ProblemError)) return false;
  if (error.status === 405 || error.status === 501) return true;
  if (error.status !== 404) return false;
  // A record outside the actor's scope is a typed `not_found` problem; an unknown route is not.
  return error.code === NON_PROBLEM_CODE || error.problem.detail === "Not Found";
}

// ---------------------------------------------------------------------------
// Conflicts (409)

export interface ConflictInfo {
  code: string;
  title: string;
  detail: string | null;
  request_id: string | null;
  /** version_conflict: the version now stored on the server. */
  currentVersion: number | null;
  /** version_conflict and staleness codes: the fresh (redacted) representation, when sent. */
  current: unknown;
  changedBy: string | null;
  changedAt: string | null;
  /** invalid_transition: the actions still allowed. */
  allowedTransitions: unknown[];
  /** not_complete: what is still missing. */
  remaining: unknown[];
}

/** Extracts the three-way-merge inputs from a 409 problem; null for anything else. */
export function conflictFromError(error: unknown): ConflictInfo | null {
  if (!(error instanceof ProblemError) || error.status !== 409) return null;
  const p = error.problem;
  const changedBy = p.changed_by;
  return {
    code: error.code,
    title: error.title,
    detail: error.detail,
    request_id: error.request_id,
    currentVersion: typeof p.current_version === "number" ? p.current_version : null,
    current: p.current ?? p.item ?? p.proposal ?? null,
    changedBy:
      typeof changedBy === "string"
        ? changedBy
        : changedBy !== null && typeof changedBy === "object" && typeof (changedBy as { display_name?: unknown }).display_name === "string"
          ? (changedBy as { display_name: string }).display_name
          : null,
    changedAt: typeof p.changed_at === "string" ? p.changed_at : null,
    allowedTransitions: Array.isArray(p.allowed_transitions) ? p.allowed_transitions : [],
    remaining: Array.isArray(p.remaining) ? p.remaining : [],
  };
}

export function isStalenessConflict(error: unknown): error is ProblemError {
  return error instanceof ProblemError && error.status === 409 && STALENESS_CONFLICT_CODES.has(error.code);
}
