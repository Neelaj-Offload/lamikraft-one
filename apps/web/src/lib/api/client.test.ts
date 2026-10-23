import { describe, expect, it, vi } from "vitest";
import {
  CSRF_HEADER,
  IDEMPOTENCY_HEADER,
  NetworkError,
  ProblemError,
  createApiClient,
  createIdempotencyKey,
  idempotencyHeaders,
  isProblemContentType,
  loginUrl,
  readCookie,
  redirectToLogin,
  safeNextPath,
  unwrap,
  type ApiClient,
  type UnauthorizedContext,
} from "./client";

const BASE = "http://127.0.0.1:3100";

// The generated schema is empty until the backend exports OpenAPI; tests exercise
// the middleware through the untyped request surface.
type UntypedRequest = (method: string, url: string, init?: Record<string, unknown>) => ReturnType<ApiClient["GET"]>;

function setup(responder: (request: Request) => Response | Promise<Response>, csrf: string | null = "tok-123") {
  const seen: Request[] = [];
  const onUnauthorized = vi.fn<(context: UnauthorizedContext) => void>();
  const client = createApiClient({
    baseUrl: BASE,
    fetch: async (request) => {
      seen.push(request);
      return responder(request);
    },
    getCsrfToken: () => csrf,
    onUnauthorized,
  });
  const call = (client.request as unknown as UntypedRequest).bind(client);
  return { call, seen, onUnauthorized };
}

function problem(status: number, body: Record<string, unknown>, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/problem+json", ...headers },
  });
}

describe("CSRF middleware", () => {
  it("adds X-CSRF-Token to unsafe methods only", async () => {
    const { call, seen } = setup(() => Response.json({ ok: true }));
    for (const method of ["get", "head", "options", "post", "put", "patch", "delete"]) {
      await call(method, "/api/v1/things");
    }
    const headerByMethod = Object.fromEntries(seen.map((r) => [r.method, r.headers.get(CSRF_HEADER)]));
    expect(headerByMethod).toEqual({
      GET: null,
      HEAD: null,
      OPTIONS: null,
      POST: "tok-123",
      PUT: "tok-123",
      PATCH: "tok-123",
      DELETE: "tok-123",
    });
  });

  it("sends no header when the cookie is missing", async () => {
    const { call, seen } = setup(() => Response.json({}), null);
    await call("post", "/api/v1/things");
    expect(seen[0]!.headers.has(CSRF_HEADER)).toBe(false);
  });

  it("sends requests same-origin with credentials", async () => {
    const { call, seen } = setup(() => Response.json({}));
    await call("get", "/api/v1/things");
    expect(seen[0]!.credentials).toBe("same-origin");
    expect(seen[0]!.url).toBe(`${BASE}/api/v1/things`);
  });
});

describe("Idempotency-Key", () => {
  it("creates distinct RFC 4122 v4 keys", () => {
    const a = createIdempotencyKey();
    const b = createIdempotencyKey();
    expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(a).not.toBe(b);
  });

  it("falls back to getRandomValues outside secure contexts", () => {
    const original = globalThis.crypto;
    vi.stubGlobal("crypto", { getRandomValues: original.getRandomValues.bind(original) });
    expect(createIdempotencyKey()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it("is sent as a header and reused verbatim", async () => {
    const { call, seen } = setup(() => Response.json({}));
    const key = createIdempotencyKey();
    await call("post", "/api/v1/things", { headers: idempotencyHeaders(key) });
    await call("post", "/api/v1/things", { headers: idempotencyHeaders(key) });
    expect(seen.map((r) => r.headers.get(IDEMPOTENCY_HEADER))).toEqual([key, key]);
  });

  it("rejects empty keys", () => {
    expect(() => idempotencyHeaders("  ")).toThrow();
  });
});

describe("ProblemError", () => {
  it("is thrown by unwrap for problem+json responses", async () => {
    const { call } = setup(() =>
      problem(409, {
        type: "about:blank",
        title: "Version conflict",
        status: 409,
        detail: "Quote changed since you opened it",
        code: "version_conflict",
        request_id: "req-1",
        current_version: 4,
      }),
    );
    const error = await unwrap(call("patch", "/api/v1/sales/quotes/1")).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ProblemError);
    const problemError = error as ProblemError;
    expect(problemError).toMatchObject({
      code: "version_conflict",
      title: "Version conflict",
      detail: "Quote changed since you opened it",
      status: 409,
      request_id: "req-1",
    });
    expect(problemError.problem.current_version).toBe(4);
    expect(problemError.message).toBe("Quote changed since you opened it");
  });

  it("takes request_id from the header when the body lacks it", async () => {
    const { call } = setup(() =>
      problem(403, { title: "Forbidden", status: 403, code: "permission_denied" }, { "X-Request-ID": "req-h" }),
    );
    const error = (await unwrap(call("get", "/api/v1/x")).catch((e: unknown) => e)) as ProblemError;
    expect(error.request_id).toBe("req-h");
    expect(error.detail).toBeNull();
  });

  it("wraps non-problem failures without inventing details", async () => {
    const { call } = setup(() => new Response("<html>Bad gateway</html>", { status: 502, statusText: "Bad Gateway" }));
    const error = (await unwrap(call("get", "/api/v1/x")).catch((e: unknown) => e)) as ProblemError;
    expect(error).toMatchObject({ code: "http_error", status: 502, title: "Bad Gateway", detail: null });
  });

  it("returns data for successful responses", async () => {
    const { call } = setup(() => Response.json({ items: [1, 2] }));
    await expect(unwrap(call("get", "/api/v1/x"))).resolves.toEqual({ items: [1, 2] });
  });

  it("recognises the problem media type", () => {
    expect(isProblemContentType("application/problem+json; charset=utf-8")).toBe(true);
    expect(isProblemContentType("application/json")).toBe(false);
    expect(isProblemContentType(null)).toBe(false);
  });
});

describe("network failures", () => {
  it("surface as NetworkError", async () => {
    const { call } = setup(() => {
      throw new TypeError("Failed to fetch");
    });
    await expect(call("get", "/api/v1/x")).rejects.toBeInstanceOf(NetworkError);
  });

  it("leave aborts untouched", async () => {
    const { call } = setup(() => {
      throw new DOMException("The operation was aborted.", "AbortError");
    });
    await expect(call("get", "/api/v1/x")).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("401 handling", () => {
  it("calls onUnauthorized for an expired session", async () => {
    const { call, onUnauthorized } = setup(() =>
      problem(401, { title: "Session expired", status: 401, code: "session_expired" }),
    );
    await call("get", "/api/v1/session/bootstrap");
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(onUnauthorized.mock.calls[0]![0].problem.code).toBe("session_expired");
  });

  it("does not leave the page for step-up re-authentication", async () => {
    const { call, onUnauthorized } = setup(() =>
      problem(401, { title: "Confirm it's you", status: 401, code: "reauth_required" }),
    );
    await call("post", "/api/v1/approvals/1/decide");
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("ignores other statuses", async () => {
    const { call, onUnauthorized } = setup(() => problem(403, { title: "No", status: 403, code: "permission_denied" }));
    await call("get", "/api/v1/x");
    expect(onUnauthorized).not.toHaveBeenCalled();
  });
});

describe("login redirect", () => {
  function stubLocation(pathname: string, search = "") {
    const assign = vi.fn<(url: string) => void>();
    vi.stubGlobal("window", { location: { pathname, search, assign, href: `${BASE}${pathname}${search}` } });
    return assign;
  }

  it("redirects protected pages with a next parameter", () => {
    const assign = stubLocation("/sales", "?tab=open");
    redirectToLogin();
    expect(assign).toHaveBeenCalledWith("/login?next=%2Fsales%3Ftab%3Dopen");
  });

  it("stays put on public pages", async () => {
    vi.resetModules();
    const fresh = await import("./client");
    const assign = stubLocation("/login");
    fresh.redirectToLogin();
    expect(assign).not.toHaveBeenCalled();
  });
});

describe("safeNextPath", () => {
  it.each([
    ["/today", "/today"],
    ["/sales/quotes/1?panel=line:2#notes", "/sales/quotes/1?panel=line:2#notes"],
  ])("accepts %s", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });

  it.each([
    null,
    "",
    "today",
    "//evil.example",
    "/\\evil.example",
    "https://evil.example/today",
    "/\t/evil.example",
    "/login",
    "/login?next=/today",
  ])("rejects %s", (input) => {
    expect(safeNextPath(input)).toBeNull();
  });

  it("builds login URLs", () => {
    expect(loginUrl("/inbox")).toBe("/login?next=%2Finbox");
    expect(loginUrl("//evil.example")).toBe("/login");
  });
});

describe("readCookie", () => {
  it("reads, unquotes and decodes values", () => {
    const header = 'lk_ui="theme=dark"; lk_csrf=abc%2Edef; other=1';
    expect(readCookie("lk_csrf", header)).toBe("abc.def");
    expect(readCookie("lk_ui", header)).toBe("theme=dark");
    expect(readCookie("missing", header)).toBeNull();
  });
});
