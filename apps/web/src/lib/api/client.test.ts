import { describe, expect, it, vi } from "vitest";
import {
  CSRF_HEADER,
  IDEMPOTENCY_HEADER,
  NetworkError,
  ProblemError,
  createApiClient,
  createIdempotencyKey,
  currentCsrfToken,
  idempotencyHeaders,
  isProblemContentType,
  loginUrl,
  readCookie,
  redirectToLogin,
  requestUntyped,
  safeNextPath,
  seedCsrfToken,
  unwrap,
  uuidv7,
  type ApiClient,
  type UnauthorizedContext,
} from "./client";
import { conflictFromError, isEndpointUnavailable, isStalenessConflict, parseRetryAfter } from "./errors";

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

const UUID_V7 = /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("Idempotency-Key", () => {
  it("creates distinct RFC 9562 v7 keys", () => {
    const a = createIdempotencyKey();
    const b = createIdempotencyKey();
    expect(a).toMatch(UUID_V7);
    expect(a).not.toBe(b);
  });

  it("encodes the creation time in the first 48 bits", () => {
    const now = Date.UTC(2026, 9, 12, 3, 25, 0, 123);
    const key = uuidv7(now, new Uint8Array(10));
    expect(Number.parseInt(key.replace(/-/g, "").slice(0, 12), 16)).toBe(now);
    expect(key).toBe(`${now.toString(16).padStart(12, "0").slice(0, 8)}-${now.toString(16).padStart(12, "0").slice(8)}-7000-8000-000000000000`);
  });

  it("sorts by creation time", () => {
    const keys = [3, 1, 2].map((offset) => uuidv7(1_760_000_000_000 + offset));
    expect([...keys].sort()).toEqual([keys[1], keys[2], keys[0]]);
  });

  it("only needs getRandomValues, so plain-HTTP LAN deployments work", () => {
    const original = globalThis.crypto;
    vi.stubGlobal("crypto", { getRandomValues: original.getRandomValues.bind(original) });
    expect(createIdempotencyKey()).toMatch(UUID_V7);
  });

  it("rejects invalid inputs", () => {
    expect(() => uuidv7(-1)).toThrow(RangeError);
    expect(() => uuidv7(1, new Uint8Array(4))).toThrow(RangeError);
    expect(() => idempotencyHeaders("x".repeat(129))).toThrow();
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

describe("CSRF retry", () => {
  it("refetches the bootstrap and retries once with the rotated token", async () => {
    let token = "stale";
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: BASE,
      getCsrfToken: () => token,
      onUnauthorized: vi.fn(),
      fetch: async (request) => {
        seen.push(request.clone());
        if (request.url.endsWith("/api/v1/session/bootstrap")) {
          token = "fresh";
          return Response.json({ ok: true });
        }
        if (request.headers.get(CSRF_HEADER) === "stale") {
          return problem(403, { title: "Session check failed", status: 403, code: "csrf_token_invalid" });
        }
        return Response.json({ saved: true, body: await request.json() });
      },
    });
    const call = (client.request as unknown as UntypedRequest).bind(client);
    const key = createIdempotencyKey();
    const result = await call("post", "/api/v1/things", { body: { a: 1 }, headers: idempotencyHeaders(key) });

    expect(result.response.status).toBe(200);
    expect(result.data).toEqual({ saved: true, body: { a: 1 } });
    expect(seen.map((r) => `${r.method} ${new URL(r.url).pathname} ${r.headers.get(CSRF_HEADER)}`)).toEqual([
      "POST /api/v1/things stale",
      "GET /api/v1/session/bootstrap null",
      "POST /api/v1/things fresh",
    ]);
    // The retry is the same command, so it carries the same Idempotency-Key.
    expect(seen[2]!.headers.get(IDEMPOTENCY_HEADER)).toBe(key);
  });

  it("does not retry when the bootstrap refresh fails", async () => {
    let calls = 0;
    const { call } = setup(() => {
      calls += 1;
      return problem(403, { title: "Nope", status: 403, code: "csrf_token_invalid" });
    });
    const result = await call("post", "/api/v1/things");
    expect(result.response.status).toBe(403);
    // the original command and the bootstrap refresh; no second command
    expect(calls).toBe(2);
  });

  it("shares one bootstrap refresh between commands rejected at the same time (single flight)", async () => {
    let token = "stale";
    let bootstraps = 0;
    const seen: string[] = [];
    let releaseBootstrap: () => void = () => {};
    const bootstrapGate = new Promise<void>((resolve) => (releaseBootstrap = resolve));
    const client = createApiClient({
      baseUrl: BASE,
      getCsrfToken: () => token,
      onUnauthorized: vi.fn(),
      fetch: async (request) => {
        if (request.url.endsWith("/api/v1/session/bootstrap")) {
          bootstraps += 1;
          await bootstrapGate;
          token = `fresh-${bootstraps}`;
          return Response.json({ ok: true });
        }
        seen.push(`${new URL(request.url).pathname} ${request.headers.get(CSRF_HEADER)}`);
        if (request.headers.get(CSRF_HEADER) === "stale") {
          return problem(403, { title: "Session check failed", status: 403, code: "csrf_token_invalid" });
        }
        return Response.json({ ok: true });
      },
    });
    const call = (client.request as unknown as UntypedRequest).bind(client);
    const first = call("post", "/api/v1/a");
    const second = call("patch", "/api/v1/b");
    await vi.waitFor(() => expect(bootstraps).toBe(1));
    // Let both 403s arrive before the one refresh resolves.
    await new Promise((resolve) => setTimeout(resolve, 0));
    releaseBootstrap();
    const [a, b] = await Promise.all([first, second]);
    expect(a.response.status).toBe(200);
    expect(b.response.status).toBe(200);
    expect(bootstraps).toBe(1);
    expect(seen.filter((line) => line.endsWith("fresh-1")).sort()).toEqual(["/api/v1/a fresh-1", "/api/v1/b fresh-1"]);
  });

  it("retries without another rotation when the token already changed since the command was sent", async () => {
    let token = "stale";
    let bootstraps = 0;
    const client = createApiClient({
      baseUrl: BASE,
      getCsrfToken: () => token,
      onUnauthorized: vi.fn(),
      fetch: async (request) => {
        if (request.url.endsWith("/api/v1/session/bootstrap")) {
          bootstraps += 1;
          return Response.json({ ok: true });
        }
        if (request.headers.get(CSRF_HEADER) === "stale") {
          token = "fresh"; // another request refreshed meanwhile
          return problem(403, { title: "Session check failed", status: 403, code: "csrf_token_invalid" });
        }
        return Response.json({ ok: true });
      },
    });
    const call = (client.request as unknown as UntypedRequest).bind(client);
    const result = await call("post", "/api/v1/things");
    expect(result.response.status).toBe(200);
    expect(bootstraps).toBe(0);
  });

  it("sends the bootstrap body's token while the browser cookie is still the stale one", () => {
    vi.stubGlobal("document", { cookie: "lk_csrf=old" });
    try {
      seedCsrfToken("from-bootstrap");
      expect(currentCsrfToken()).toBe("from-bootstrap");
      // A sign-in or browser-side bootstrap set a newer cookie: the cookie wins from then on.
      (globalThis.document as { cookie: string }).cookie = "lk_csrf=newer";
      expect(currentCsrfToken()).toBe("newer");
      (globalThis.document as { cookie: string }).cookie = "lk_csrf=old";
      expect(currentCsrfToken()).toBe("old");
    } finally {
      seedCsrfToken(null);
      vi.unstubAllGlobals();
    }
  });

  it("leaves other 403s and safe methods alone", async () => {
    let calls = 0;
    const { call } = setup(() => {
      calls += 1;
      return problem(403, { title: "No", status: 403, code: "permission_denied" });
    });
    await call("post", "/api/v1/things");
    await call("get", "/api/v1/things");
    expect(calls).toBe(2);
  });
});

describe("requestUntyped", () => {
  it("drops empty query values and returns the body", async () => {
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: BASE,
      fetch: async (request) => {
        seen.push(request);
        return Response.json({ ok: 1 });
      },
    });
    await expect(
      requestUntyped<{ ok: number }>(client, "get", "/api/v1/tasks/inbox", {
        params: { query: { tab: "tasks", cursor: undefined, q: null } },
      }),
    ).resolves.toEqual({ ok: 1 });
    expect(new URL(seen[0]!.url).search).toBe("?tab=tasks");
  });

  it("throws ProblemError for failures", async () => {
    const client = createApiClient({
      baseUrl: BASE,
      fetch: async () => problem(404, { title: "Not Found", status: 404, code: "not_found", detail: "Not Found" }),
      onUnauthorized: vi.fn(),
    });
    const error = await requestUntyped(client, "get", "/api/v1/briefings/today").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ProblemError);
    expect(isEndpointUnavailable(error)).toBe(true);
  });
});

describe("401 on sign-in pages", () => {
  it("does not redirect for invalid credentials or a used demo link", async () => {
    for (const code of ["invalid_credentials", "link_invalid_or_used"]) {
      const { call, onUnauthorized } = setup(() => problem(401, { title: "No", status: 401, code }));
      await call("post", "/api/v1/identity/session");
      expect(onUnauthorized).not.toHaveBeenCalled();
    }
  });
});

describe("problem helpers", () => {
  it("parses Retry-After seconds and dates", () => {
    expect(parseRetryAfter("120")).toBe(120);
    expect(parseRetryAfter("Mon, 12 Oct 2026 03:30:00 GMT", Date.UTC(2026, 9, 12, 3, 25))).toBe(300);
    expect(parseRetryAfter("soon")).toBeNull();
    expect(parseRetryAfter(null)).toBeNull();
  });

  it("exposes Retry-After and validation issues on the error", async () => {
    const { call } = setup(() =>
      problem(429, { title: "Too many attempts", status: 429, code: "rate_limited" }, { "Retry-After": "600" }),
    );
    const error = (await unwrap(call("post", "/api/v1/identity/session")).catch((e: unknown) => e)) as ProblemError;
    expect(error.retryAfterSeconds).toBe(600);

    const invalid = new ProblemError({
      code: "validation_failed",
      title: "Some values are not valid",
      status: 422,
      errors: [{ loc: ["body", "email"], msg: "Enter an email", code: "value_error" }, "junk"],
    });
    expect(invalid.validationIssues).toEqual([{ loc: ["body", "email"], msg: "Enter an email", code: "value_error" }]);
  });

  it("extracts three-way conflict data from a 409", () => {
    const error = new ProblemError({
      code: "version_conflict",
      title: "This record changed since you opened it",
      status: 409,
      current_version: 5,
      current: { remarks: "theirs" },
      changed_by: { display_name: "Meera Iyer" },
      changed_at: "2026-10-12T05:12:00Z",
    });
    expect(isStalenessConflict(error)).toBe(true);
    expect(conflictFromError(error)).toMatchObject({
      currentVersion: 5,
      current: { remarks: "theirs" },
      changedBy: "Meera Iyer",
      changedAt: "2026-10-12T05:12:00Z",
    });
    expect(conflictFromError(new ProblemError({ code: "x", title: "x", status: 422 }))).toBeNull();
  });

  it("tells a missing endpoint from a record outside scope", () => {
    const route = new ProblemError({ code: "not_found", title: "Not Found", status: 404, detail: "Not Found" });
    const record = new ProblemError({
      code: "not_found",
      title: "Not found or not available to you",
      status: 404,
      detail: "The quote does not exist or is outside your scope.",
    });
    expect(isEndpointUnavailable(route)).toBe(true);
    expect(isEndpointUnavailable(record)).toBe(false);
    expect(isEndpointUnavailable(new ProblemError({ code: "method_not_allowed", title: "x", status: 405 }))).toBe(true);
    expect(isEndpointUnavailable(new Error("x"))).toBe(false);
  });
});
