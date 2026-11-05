import createClient, { type Client, type Middleware } from "openapi-fetch";
import { matchRoute } from "@/lib/routes";
import { safeAppPath, safeNextPath } from "@/lib/safe-path";
import { NetworkError, ProblemError } from "./errors";
import type { paths } from "./schema";

export {
  NetworkError,
  NON_PROBLEM_CODE,
  ProblemError,
  STALENESS_CONFLICT_CODES,
  conflictFromError,
  isEndpointUnavailable,
  isNetworkError,
  isProblemContentType,
  isProblemError,
  isStalenessConflict,
  type ConflictInfo,
  type KnownProblemCode,
  type ProblemDetails,
} from "./errors";

export const CSRF_COOKIE = "lk_csrf";
export const CSRF_HEADER = "X-CSRF-Token";
export const IDEMPOTENCY_HEADER = "Idempotency-Key";
export const BOOTSTRAP_PATH = "/api/v1/session/bootstrap";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export type ApiClient = Client<paths>;

// ---------------------------------------------------------------------------
// Cookies

export function readCookie(name: string, cookieHeader?: string): string | null {
  const source = cookieHeader ?? (typeof document === "undefined" ? "" : document.cookie);
  for (const part of source.split(";")) {
    const separator = part.indexOf("=");
    if (separator === -1) continue;
    if (part.slice(0, separator).trim() !== name) continue;
    let value = part.slice(separator + 1).trim();
    if (value.length >= 2 && value.startsWith('"') && value.endsWith('"')) value = value.slice(1, -1);
    try {
      return decodeURIComponent(value);
    } catch {
      return value;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Idempotency

function randomBytes(length: number): Uint8Array {
  return globalThis.crypto.getRandomValues(new Uint8Array(length));
}

/**
 * RFC 9562 UUIDv7: 48-bit Unix milliseconds, version 7, 74 random bits. api-conventions §6
 * recommends v7 for Idempotency-Key so keys sort by creation time in the server's table.
 */
export function uuidv7(now: number = Date.now(), random: Uint8Array = randomBytes(10)): string {
  if (!Number.isSafeInteger(now) || now < 0) throw new RangeError("uuidv7 needs a non-negative millisecond timestamp");
  if (random.length < 10) throw new RangeError("uuidv7 needs 10 random bytes");
  const bytes = new Uint8Array(16);
  let ms = now;
  for (let index = 5; index >= 0; index -= 1) {
    bytes[index] = ms % 256;
    ms = Math.floor(ms / 256);
  }
  bytes[6] = 0x70 | (random[0]! & 0x0f);
  bytes[7] = random[1]!;
  bytes[8] = 0x80 | (random[2]! & 0x3f);
  bytes.set(random.subarray(3, 10), 9);
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * A key for one user-initiated command. Create it when the user acts and reuse
 * it for every retry of that same command.
 */
export function createIdempotencyKey(): string {
  return uuidv7();
}

/** Spread into an openapi-fetch call: `api.POST(path, { body, headers: idempotencyHeaders(key) })`. */
export function idempotencyHeaders(key: string): { [IDEMPOTENCY_HEADER]: string } {
  if (!key.trim()) throw new Error("An Idempotency-Key must not be empty");
  if (key.length > 128) throw new Error("An Idempotency-Key must be at most 128 characters");
  return { [IDEMPOTENCY_HEADER]: key };
}

// ---------------------------------------------------------------------------
// Login redirect

export { safeAppPath, safeNextPath };

export function loginUrl(nextPath?: string | null): string {
  const next = safeNextPath(nextPath);
  return next ? `/login?next=${encodeURIComponent(next)}` : "/login";
}

let redirecting = false;

/** Sends the browser to sign-in, unless it is already on a public page such as /login. */
export function redirectToLogin(): void {
  if (typeof window === "undefined" || redirecting) return;
  const { pathname, search } = window.location;
  if (matchRoute(pathname)?.access === "public") return;
  redirecting = true;
  window.location.assign(loginUrl(`${pathname}${search}`));
}

// ---------------------------------------------------------------------------
// Middleware

function isSameOrigin(url: string): boolean {
  if (typeof window === "undefined") return true;
  return new URL(url, window.location.href).origin === window.location.origin;
}

// ---------------------------------------------------------------------------
// CSRF token

let csrfSeed: { token: string; staleCookie: string | null } | null = null;

/**
 * api-conventions §7.1: every bootstrap rotates the CSRF secret. The (app) layout calls the
 * bootstrap on the server, so the rotated `lk_csrf` cookie never reaches the browser, whose
 * cookie is stale from then on; the bootstrap body carries the new value. The SessionProvider
 * seeds it here, and unsafe requests send it until the browser's cookie changes (a sign-in or a
 * browser-side bootstrap sets a newer one). Without the seed, the first command after every
 * full page load would be answered 403 `csrf_token_invalid` and retried.
 */
export function seedCsrfToken(token: string | null): void {
  if (typeof document === "undefined") return;
  csrfSeed = token ? { token, staleCookie: readCookie(CSRF_COOKIE) } : null;
}

/** The value for X-CSRF-Token: the seeded bootstrap value while the cookie is unchanged, else the cookie. */
export function currentCsrfToken(): string | null {
  const cookie = readCookie(CSRF_COOKIE);
  if (csrfSeed) {
    if (cookie === csrfSeed.staleCookie) return csrfSeed.token;
    csrfSeed = null;
  }
  return cookie;
}

export function csrfMiddleware(getToken: () => string | null = currentCsrfToken): Middleware {
  return {
    onRequest({ request }) {
      if (!UNSAFE_METHODS.has(request.method.toUpperCase())) return undefined;
      if (request.headers.has(CSRF_HEADER) || !isSameOrigin(request.url)) return undefined;
      const token = getToken();
      if (token) request.headers.set(CSRF_HEADER, token);
      return request;
    },
  };
}

async function readProblemCode(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.clone().json();
    if (body !== null && typeof body === "object" && typeof (body as { code?: unknown }).code === "string") {
      return (body as { code: string }).code;
    }
  } catch {
    // Not JSON: not a CSRF problem.
  }
  return null;
}

/**
 * api-conventions §3: on 403 `csrf_token_invalid` the client refetches the session
 * bootstrap (which rotates the `lk_csrf` cookie) and retries the command once with
 * the fresh token. The original request, Idempotency-Key included, is replayed as is,
 * so a retry can never create a second effect.
 *
 * Every bootstrap rotates the secret, so refreshes are single-flight: commands rejected at
 * the same time share one refresh, and a command whose token is already older than the
 * current one (another request refreshed it meanwhile) retries without rotating again,
 * which would invalidate the token the other retry carries.
 */
export function csrfRetryMiddleware(getToken: () => string | null = currentCsrfToken): Middleware {
  const pending = new Map<string, Request>();
  let refreshing: Promise<boolean> | null = null;

  const refresh = (fetchImpl: (request: Request) => Promise<Response>, url: string): Promise<boolean> => {
    refreshing ??= fetchImpl(new Request(new URL(BOOTSTRAP_PATH, url), { method: "GET", credentials: "same-origin" }))
      .then(
        (response) => response.ok,
        () => false,
      )
      .finally(() => {
        refreshing = null;
      });
    return refreshing;
  };

  return {
    onRequest({ request, id }) {
      if (UNSAFE_METHODS.has(request.method.toUpperCase()) && isSameOrigin(request.url)) {
        pending.set(id, request.clone());
      }
      return undefined;
    },
    async onResponse({ request, response, id, options }) {
      const original = pending.get(id);
      pending.delete(id);
      if (!original || response.status !== 403) return undefined;
      if ((await readProblemCode(response)) !== "csrf_token_invalid") return undefined;

      const sent = original.headers.get(CSRF_HEADER);
      let token = getToken();
      if (!token || token === sent) {
        if (!(await refresh(options.fetch, request.url))) return undefined;
        token = getToken();
      }
      // No newer token to offer: a retry would be rejected the same way.
      if (!token || token === sent) return undefined;

      const retry = new Request(original);
      retry.headers.set(CSRF_HEADER, token);
      return options.fetch(retry);
    },
    onError({ id }) {
      pending.delete(id);
      return undefined;
    },
  };
}

/** Normalises fetch failures (no HTTP response at all) into NetworkError. */
export const networkErrorMiddleware: Middleware = {
  onError({ error }) {
    if (error instanceof DOMException && error.name === "AbortError") return undefined;
    if (error instanceof NetworkError) return error;
    return new NetworkError(error);
  },
};

export interface UnauthorizedContext {
  request: Request;
  problem: ProblemError;
}

export function unauthorizedMiddleware(
  onUnauthorized: (context: UnauthorizedContext) => void = redirectToLogin,
): Middleware {
  return {
    async onResponse({ request, response }) {
      if (response.status !== 401) return undefined;
      let body: unknown = null;
      try {
        body = await response.clone().json();
      } catch {
        body = null;
      }
      const problem = ProblemError.fromResponse(response, body);
      // Step-up authentication is handled in place by a re-auth dialog, not by leaving the page.
      if (problem.code === "reauth_required" || problem.code === "mfa_required") return undefined;
      // A failed sign-in or demo link is answered on the sign-in page itself.
      if (problem.code === "invalid_credentials" || problem.code === "link_invalid_or_used") return undefined;
      onUnauthorized({ request, problem });
      return undefined;
    },
  };
}

// ---------------------------------------------------------------------------
// Client

export interface ApiClientOptions {
  /** "" keeps requests same-origin; Next rewrites /api/* to FastAPI. */
  baseUrl?: string;
  fetch?: (request: Request) => Promise<Response>;
  getCsrfToken?: () => string | null;
  onUnauthorized?: (context: UnauthorizedContext) => void;
}

export function createApiClient(options: ApiClientOptions = {}): ApiClient {
  const client = createClient<paths>({
    baseUrl: options.baseUrl ?? "",
    credentials: "same-origin",
    ...(options.fetch ? { fetch: options.fetch } : {}),
  });
  // onRequest runs in this order and onResponse in reverse: the CSRF retry sees the
  // response first, so the 401 handler only ever sees the final answer.
  client.use(
    csrfMiddleware(options.getCsrfToken),
    networkErrorMiddleware,
    unauthorizedMiddleware(options.onUnauthorized),
    csrfRetryMiddleware(options.getCsrfToken),
  );
  return client;
}

/** The browser client. Server components must not use it: it relies on same-origin cookies. */
export const api: ApiClient = createApiClient();

type FetchResult = { data?: unknown; error?: unknown; response: Response };
type SuccessData<R> = R extends { data: infer D; error?: never } ? D : never;

/**
 * Resolves to the success body or throws a ProblemError, which suits
 * TanStack Query: `queryFn: () => unwrap(api.GET("/api/v1/..."))`.
 */
export async function unwrap<R extends FetchResult>(pending: Promise<R>): Promise<SuccessData<R>> {
  const result = await pending;
  if (result.response.ok) return result.data as SuccessData<R>;
  throw ProblemError.fromResponse(result.response, result.error);
}

// ---------------------------------------------------------------------------
// Endpoints not yet in the generated schema

export type HttpMethod = "get" | "post" | "put" | "patch" | "delete";

export interface UntypedInit {
  params?: { query?: Record<string, string | number | boolean | undefined | null> };
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

type UntypedRequest = (method: string, url: string, init?: Record<string, unknown>) => Promise<FetchResult>;

/**
 * Calls an endpoint that another lane is building in the same wave and that is therefore
 * not yet in `schema.d.ts`. The response type `T` comes from an interim hand-written type in
 * `src/lib/session/**` or `src/features/<feature>/types.ts`. Replace each call with the typed
 * `api.GET(...)` once the endpoint merges and the schema is regenerated.
 */
export async function requestUntyped<T>(
  client: ApiClient,
  method: HttpMethod,
  path: `/api/v1/${string}`,
  init: UntypedInit = {},
): Promise<T> {
  const query = init.params?.query
    ? Object.fromEntries(Object.entries(init.params.query).filter(([, value]) => value !== undefined && value !== null))
    : undefined;
  const call = (client.request as unknown as UntypedRequest).bind(client);
  const result = await call(method, path, {
    ...(query ? { params: { query } } : {}),
    ...(init.body !== undefined ? { body: init.body } : {}),
    ...(init.headers ? { headers: init.headers } : {}),
    ...(init.signal ? { signal: init.signal } : {}),
  });
  if (result.response.ok) return result.data as T;
  throw ProblemError.fromResponse(result.response, result.error);
}
