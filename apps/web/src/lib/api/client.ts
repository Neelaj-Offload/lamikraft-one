import createClient, { type Client, type Middleware } from "openapi-fetch";
import { matchRoute } from "@/lib/routes";
import { NetworkError, ProblemError } from "./errors";
import type { paths } from "./schema";

export {
  NetworkError,
  NON_PROBLEM_CODE,
  ProblemError,
  isNetworkError,
  isProblemContentType,
  isProblemError,
  type KnownProblemCode,
  type ProblemDetails,
} from "./errors";

export const CSRF_COOKIE = "lk_csrf";
export const CSRF_HEADER = "X-CSRF-Token";
export const IDEMPOTENCY_HEADER = "Idempotency-Key";

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

/**
 * A key for one user-initiated command. Create it when the user acts and reuse
 * it for every retry of that same command.
 */
export function createIdempotencyKey(): string {
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi.randomUUID === "function") return cryptoApi.randomUUID();
  // randomUUID needs a secure context; plain-HTTP LAN deployments still have getRandomValues.
  const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Spread into an openapi-fetch call: `api.POST(path, { body, headers: idempotencyHeaders(key) })`. */
export function idempotencyHeaders(key: string): { [IDEMPOTENCY_HEADER]: string } {
  if (!key.trim()) throw new Error("An Idempotency-Key must not be empty");
  return { [IDEMPOTENCY_HEADER]: key };
}

// ---------------------------------------------------------------------------
// Login redirect

/**
 * Accepts only same-origin relative paths for the `next` login parameter, so a
 * crafted link cannot bounce the user to another site after sign-in.
 */
export function safeNextPath(raw: string | null | undefined): string | null {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return null;
  if (/[\u0000-\u001f\u007f]/.test(raw)) return null;
  const base = "http://lamikraft.invalid";
  let url: URL;
  try {
    url = new URL(raw, base);
  } catch {
    return null;
  }
  if (url.origin !== base) return null;
  const path = `${url.pathname}${url.search}${url.hash}`;
  if (url.pathname === "/login" || url.pathname.startsWith("/login/")) return null;
  return path;
}

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

export function csrfMiddleware(getToken: () => string | null = () => readCookie(CSRF_COOKIE)): Middleware {
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
      if (problem.code === "reauth_required") return undefined;
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
  client.use(
    csrfMiddleware(options.getCsrfToken),
    networkErrorMiddleware,
    unauthorizedMiddleware(options.onUnauthorized),
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
