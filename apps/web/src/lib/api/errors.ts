/**
 * Error types for calls to the FastAPI backend.
 *
 * The backend answers failures with RFC 9457 problem+json carrying a snake_case
 * `code` and a `request_id` (see docs/PLAN.md, API conventions). Non-problem
 * failures (for example a proxy error page while the API is down) are still
 * surfaced as a ProblemError so callers handle one shape.
 */

export const PROBLEM_CONTENT_TYPE = "application/problem+json";

/** Codes the client reacts to; the backend may return others. */
export type KnownProblemCode =
  | "validation_failed"
  | "version_conflict"
  | "permission_denied"
  | "not_found"
  | "session_expired"
  | "reauth_required"
  | "csrf_invalid"
  | "rate_limited"
  | "proposal_stale";

/** Assigned client-side when the response body is not problem+json. */
export const NON_PROBLEM_CODE = "http_error";

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
  /** The full problem document, including extension members. */
  readonly problem: Readonly<ProblemDetails>;

  constructor(problem: ProblemDetails) {
    super(problem.detail || problem.title);
    this.problem = problem;
    this.code = problem.code;
    this.title = problem.title;
    this.detail = problem.detail ?? null;
    this.status = problem.status;
    this.request_id = problem.request_id ?? null;
  }

  /** Builds an error from a failed response and its already-parsed body. */
  static fromResponse(response: Response, body: unknown): ProblemError {
    const headerRequestId = response.headers.get("x-request-id");
    if (isProblemBody(body)) {
      return new ProblemError({
        ...body,
        status: typeof body.status === "number" ? body.status : response.status,
        request_id: typeof body.request_id === "string" ? body.request_id : headerRequestId,
      });
    }
    const fastApiDetail =
      body !== null && typeof body === "object" && typeof (body as { detail?: unknown }).detail === "string"
        ? (body as { detail: string }).detail
        : null;
    return new ProblemError({
      code: NON_PROBLEM_CODE,
      title: response.statusText || `Request failed with status ${response.status}`,
      status: response.status,
      detail: fastApiDetail,
      request_id: headerRequestId,
    });
  }
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
