import { globSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  areaRouteFor,
  canAccessRoute,
  compileRoutePattern,
  matchRoute,
  primaryNavRoutes,
  routes,
  type RouteDefinition,
} from "./routes";

const appDir = fileURLToPath(new URL("../app", import.meta.url));

/** Converts `(app)/sales/quotes/[quoteId]/page.tsx` into `/sales/quotes/[quoteId]`. */
function fileToRoutePath(file: string): string {
  const segments = file.split(/[\\/]/).slice(0, -1);
  const routeSegments = segments.filter(
    (segment) => !(segment.startsWith("(") && segment.endsWith(")")) && !segment.startsWith("@"),
  );
  return `/${routeSegments.join("/")}`;
}

/** Dynamic segment names are irrelevant to coverage: `[quoteId]` and `[id]` are the same route. */
function normalise(routePath: string): string {
  return routePath
    .replace(/\[\[\.\.\.[^\]]+\]\]/g, "[[...]]")
    .replace(/\[\.\.\.[^\]]+\]/g, "[...]")
    .replace(/\[(?!\.\.\.|\[)[^\]]+\]/g, "[]");
}

function isRoutable(file: string): boolean {
  // Next excludes private folders (`_name`) from routing.
  return !file.split(/[\\/]/).some((segment) => segment.startsWith("_"));
}

const pageFiles = globSync("**/page.{ts,tsx,js,jsx,mdx}", { cwd: appDir }).filter(isRoutable);
const filePaths = pageFiles.map((file) => normalise(fileToRoutePath(file)));
const manifestPaths = routes.map((route) => normalise(route.path));

describe("route manifest coverage", () => {
  it("finds the app's pages", () => {
    expect(pageFiles.length).toBeGreaterThan(0);
  });

  it("registers every page.tsx under src/app", () => {
    const unregistered = pageFiles.filter((_, index) => !manifestPaths.includes(filePaths[index]!));
    expect(unregistered, "add these pages to src/lib/routes.ts").toEqual([]);
  });

  it("has no manifest entries without a page", () => {
    const orphaned = routes.filter((route) => !filePaths.includes(normalise(route.path))).map((r) => r.path);
    expect(orphaned, "remove these entries or add their page.tsx").toEqual([]);
  });

  it("does not map two pages to the same URL", () => {
    expect(new Set(filePaths).size).toBe(filePaths.length);
  });
});

describe("route manifest integrity", () => {
  it("has unique ids and paths", () => {
    expect(new Set(routes.map((r) => r.id)).size).toBe(routes.length);
    expect(new Set(manifestPaths).size).toBe(routes.length);
  });

  it("uses well-formed permission prefixes", () => {
    for (const route of routes as readonly RouteDefinition[]) {
      const required = route.requiredPermission;
      const prefixes = required === null ? [] : typeof required === "string" ? [required] : required;
      for (const prefix of prefixes) expect(prefix).toMatch(/^[a-z][a-z_]*\.$/);
    }
  });

  it("keeps the seven primary areas in sidebar order", () => {
    expect(primaryNavRoutes().map((r) => r.path)).toEqual([
      "/today",
      "/inbox",
      "/sales",
      "/products",
      "/operations",
      "/finance",
      "/settings",
    ]);
  });

  it("gives every signed-in route a phone tab", () => {
    for (const route of routes as readonly RouteDefinition[]) {
      if (route.access === "session") expect(route.mobileTab, route.path).not.toBeNull();
    }
  });
});

describe("matchRoute", () => {
  it("matches static paths with or without a trailing slash and query", () => {
    expect(matchRoute("/sales")?.id).toBe("sales");
    expect(matchRoute("/sales/")?.id).toBe("sales");
    expect(matchRoute("/today?panel=item:1")?.id).toBe("today");
    expect(matchRoute("/")?.id).toBe("home");
  });

  it("returns null for unknown paths", () => {
    expect(matchRoute("/nope")).toBeNull();
    expect(matchRoute("/sales/quotes")).toBeNull();
  });

  it("compiles dynamic, catch-all and optional catch-all segments", () => {
    expect(compileRoutePattern("/sales/quotes/[quoteId]").test("/sales/quotes/0192-abc")).toBe(true);
    expect(compileRoutePattern("/sales/quotes/[quoteId]").test("/sales/quotes/a/b")).toBe(false);
    expect(compileRoutePattern("/docs/[...slug]").test("/docs/a/b")).toBe(true);
    expect(compileRoutePattern("/docs/[...slug]").test("/docs")).toBe(false);
    expect(compileRoutePattern("/docs/[[...slug]]").test("/docs")).toBe(true);
    expect(compileRoutePattern("/a.b").test("/aXb")).toBe(false);
  });

  it("resolves the owning primary area", () => {
    expect(areaRouteFor("/finance")?.id).toBe("finance");
    expect(areaRouteFor("/login")).toBeNull();
  });
});

describe("canAccessRoute", () => {
  const byId = (id: string) => (routes as readonly RouteDefinition[]).find((r) => r.id === id)!;

  it("allows routes without a requirement", () => {
    expect(canAccessRoute(byId("today"), [])).toBe(true);
  });

  it("requires a key under the module prefix", () => {
    expect(canAccessRoute(byId("sales"), ["sales.quote.read"])).toBe(true);
    expect(canAccessRoute(byId("sales"), ["salesforce.x.read", "finance.invoice.read"])).toBe(false);
  });

  it("accepts any listed module for multi-module areas", () => {
    expect(canAccessRoute(byId("operations"), ["cutting.plan.read"])).toBe(true);
    expect(canAccessRoute(byId("operations"), ["sales.quote.read"])).toBe(false);
  });
});

describe("fileToRoutePath", () => {
  it("drops route groups and parallel slots", () => {
    expect(fileToRoutePath(path.join("(app)", "sales", "page.tsx"))).toBe("/sales");
    expect(fileToRoutePath("(app)/@rail/inbox/page.tsx")).toBe("/inbox");
    expect(fileToRoutePath("page.tsx")).toBe("/");
    expect(normalise("/sales/quotes/[quoteId]/review")).toBe("/sales/quotes/[]/review");
  });
});
