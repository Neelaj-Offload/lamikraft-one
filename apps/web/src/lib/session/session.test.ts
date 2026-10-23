import { describe, expect, it, vi } from "vitest";
import { rawBootstrap, testBootstrap } from "@/lib/test-support/session";
import { fetchBootstrap, serverGet } from "./fetch-bootstrap";
import { navRoutesFromBootstrap, routesForMobileTab } from "./nav";
import { BootstrapShapeError, parseBootstrap, parseUiPoll } from "./parse";

describe("parseBootstrap", () => {
  it("reads the §8 payload", () => {
    const session = testBootstrap();
    expect(session.user.display_name).toBe("Meera Iyer");
    expect(session.company).toMatchObject({ display_name: "Crown Decor (Demo)", is_demo: true });
    expect(session.membership.is_demo).toBe(true);
    expect(session.time_zone).toBe("Asia/Kolkata");
    expect(session.permissions).toContainEqual({ key: "sales.quote.read", scope: "own" });
    expect(session.ui.shortcuts_enabled).toBe(true);
    expect(session.nav.map((entry) => entry.key)).toEqual(["today", "inbox", "sales", "products", "settings"]);
    expect(session.inbox_counts).toEqual({ status: "ok", value: { total: 4, tabs: { tasks: 3, approvals: 1 } } });
    expect(session.briefing).toEqual({ status: "ok", value: { version: 1, work_date: "2026-10-12" } });
    expect(session.integrations).toEqual({
      status: "ok",
      value: [{ key: "whatsapp", label: "WhatsApp", mode: "demo" }],
    });
  });

  it("reports every missing required field at once", () => {
    const raw = rawBootstrap({ user: { id: "u" }, time_zone: "Mars/Olympus", server_now: "yesterday" });
    delete raw.permissions;
    let error: unknown;
    try {
      parseBootstrap(raw);
    } catch (caught) {
      error = caught;
    }
    expect(error).toBeInstanceOf(BootstrapShapeError);
    expect((error as BootstrapShapeError).problems).toEqual(
      expect.arrayContaining(["user.display_name", "permissions", "server_now", "time_zone"]),
    );
  });

  it("keeps failed sections explicit instead of inventing zeros", () => {
    const session = testBootstrap({ inbox_counts: { status: "unavailable" }, briefing: undefined, integrations: { items: "x" } });
    expect(session.inbox_counts).toEqual({ status: "unavailable" });
    expect(session.briefing).toEqual({ status: "unavailable" });
    expect(session.integrations).toEqual({ status: "unavailable" });
  });

  it("accepts sections nested under `sections`", () => {
    const raw = rawBootstrap();
    const sections = { inbox_counts: raw.inbox_counts };
    delete raw.inbox_counts;
    expect(parseBootstrap({ ...raw, sections }).inbox_counts.status).toBe("ok");
  });

  it("defaults unknown flags to off and preferences to the documented defaults", () => {
    const session = testBootstrap({ features: undefined, ui_preferences: { theme: "neon", shortcuts_enabled: "yes" } });
    expect(session.features).toEqual({ assistant: false, voice: false });
    expect(session.ui).toMatchObject({ theme: "system", motion: "full", shortcuts_enabled: true, context_rail_open: false });
  });

  it("parses nav entries as keys or objects, dropping disabled and duplicate ones", () => {
    const session = testBootstrap({ nav: ["today", { key: "inbox" }, { key: "finance", enabled: false }, "today", 7] });
    expect(session.nav).toEqual([{ key: "today" }, { key: "inbox" }]);
  });

  it("parses the poll payload", () => {
    expect(parseUiPoll({ briefing: { version: 3, work_date: "2026-10-12" } })).toEqual({
      briefing: { status: "ok", value: { version: 3, work_date: "2026-10-12" } },
      inbox_counts: { status: "unavailable" },
    });
    expect(parseUiPoll(null).briefing.status).toBe("unavailable");
  });
});

describe("navigation from the bootstrap", () => {
  it("lists only areas the bootstrap names, in its order, with manifest paths", () => {
    const session = testBootstrap({ nav: [{ key: "inbox" }, { key: "today" }, { key: "sales" }, { key: "warp-drive" }] });
    const routes = navRoutesFromBootstrap(session.nav, session.permissions.map((p) => p.key));
    expect(routes.map((route) => route.path)).toEqual(["/inbox", "/today", "/sales"]);
  });

  it("double-checks permissions locally", () => {
    const routes = navRoutesFromBootstrap([{ key: "finance" }, { key: "today" }], ["sales.quote.read"]);
    expect(routes.map((route) => route.id)).toEqual(["today"]);
  });

  it("groups areas by phone tab", () => {
    const session = testBootstrap();
    const routes = navRoutesFromBootstrap(session.nav, session.permissions.map((p) => p.key));
    expect(routesForMobileTab(routes, "work").map((r) => r.id)).toEqual(["sales", "products"]);
    expect(routesForMobileTab(routes, "more").map((r) => r.id)).toEqual(["settings"]);
  });
});

describe("server bootstrap fetch", () => {
  const base = { baseUrl: "http://127.0.0.1:8050/", cookieHeader: "lk_session=abc; lk_csrf=def", requestId: "req-1" };

  it("forwards the browser's cookies and request id, uncached", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => Response.json(rawBootstrap()));
    const result = await fetchBootstrap({ ...base, fetchImpl });
    expect(result.status).toBe("ok");
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("http://127.0.0.1:8050/api/v1/session/bootstrap");
    const headers = new Headers(init?.headers);
    expect(headers.get("cookie")).toBe("lk_session=abc; lk_csrf=def");
    expect(headers.get("x-request-id")).toBe("req-1");
    expect(init?.cache).toBe("no-store");
  });

  it("maps 401 and a missing cookie to unauthenticated without guessing", async () => {
    const unauthorised = vi.fn<typeof fetch>(async () =>
      Response.json({ title: "Sign in", status: 401, code: "unauthenticated" }, { status: 401 }),
    );
    expect(await fetchBootstrap({ ...base, fetchImpl: unauthorised })).toEqual({ status: "unauthenticated" });
    const never = vi.fn<typeof fetch>();
    expect(await fetchBootstrap({ ...base, cookieHeader: null, fetchImpl: never })).toEqual({ status: "unauthenticated" });
    expect(never).not.toHaveBeenCalled();
  });

  it("reports server failures, unreachable APIs and unreadable payloads as errors", async () => {
    const failing = vi.fn<typeof fetch>(async () =>
      Response.json({ title: "Unavailable", status: 503, code: "service_unavailable", request_id: "r9" }, { status: 503 }),
    );
    expect(await fetchBootstrap({ ...base, fetchImpl: failing })).toMatchObject({
      status: "error",
      problem: { code: "service_unavailable", request_id: "r9" },
    });

    const down = vi.fn<typeof fetch>(async () => {
      throw new TypeError("fetch failed");
    });
    expect(await fetchBootstrap({ ...base, fetchImpl: down })).toMatchObject({
      status: "error",
      problem: { code: "service_unavailable", status: 503 },
    });

    const odd = vi.fn<typeof fetch>(async () => Response.json({ hello: "world" }));
    expect(await fetchBootstrap({ ...base, fetchImpl: odd })).toMatchObject({
      status: "error",
      problem: { code: "bootstrap_unreadable" },
    });
  });

  it("returns JSON bodies for page prefetches", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => Response.json({ version: 2 }));
    await expect(serverGet("/api/v1/briefings/today", { ...base, fetchImpl })).resolves.toMatchObject({
      ok: true,
      data: { version: 2 },
    });
  });
});
