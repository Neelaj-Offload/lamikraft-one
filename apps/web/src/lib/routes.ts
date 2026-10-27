/**
 * Route manifest: the single source for navigation, breadcrumbs, the axe sweep,
 * the dead-control crawl and screenshot capture. Every `page.tsx` under
 * src/app must have an entry (enforced by routes.test.ts).
 *
 * Paths use the App Router segment syntax for dynamic parts, e.g.
 * `/sales/quotes/[quoteId]`; route groups such as `(app)` are omitted.
 */

export type AreaId =
  | "auth"
  | "today"
  | "inbox"
  | "sales"
  | "products"
  | "operations"
  | "finance"
  | "settings"
  /** Phone hubs (/work, /more) that group areas; never a sidebar entry. */
  | "hub";

/** primary: sidebar / area entry points. context: an area's sub-navigation. null: never listed. */
export type NavGroup = "primary" | "context";

/** Which phone bottom-navigation tab is active while the route is shown. */
export type MobileTab = "today" | "inbox" | "work" | "more";

/** A permission module prefix, e.g. "sales." matches sales.quote.read. */
export type PermissionPrefix = `${string}.`;

/** public: reachable signed out. session: requires a signed-in session. */
export type RouteAccess = "public" | "session";

export interface RouteDefinition {
  readonly id: string;
  readonly path: `/${string}` | "/";
  readonly label: string;
  readonly area: AreaId;
  readonly navGroup: NavGroup | null;
  readonly mobileTab: MobileTab | null;
  /**
   * null: any signed-in user. A prefix or a list of prefixes: the user needs at
   * least one permission key starting with one of them (areas such as
   * Operations span several backend modules).
   */
  readonly requiredPermission: PermissionPrefix | readonly PermissionPrefix[] | null;
  readonly access: RouteAccess;
}

export const routes = [
  {
    id: "home",
    path: "/",
    label: "Lamikraft One",
    area: "today",
    navGroup: null,
    mobileTab: "today",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "login",
    path: "/login",
    label: "Sign in",
    area: "auth",
    navGroup: null,
    mobileTab: null,
    requiredPermission: null,
    access: "public",
  },
  {
    id: "today",
    path: "/today",
    label: "Today",
    area: "today",
    navGroup: "primary",
    mobileTab: "today",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "inbox",
    path: "/inbox",
    label: "Inbox",
    area: "inbox",
    navGroup: "primary",
    mobileTab: "inbox",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "sales",
    path: "/sales",
    label: "Sales",
    area: "sales",
    navGroup: "primary",
    mobileTab: "work",
    requiredPermission: "sales.",
    access: "session",
  },
  {
    id: "products",
    path: "/products",
    label: "Products",
    area: "products",
    navGroup: "primary",
    mobileTab: "work",
    requiredPermission: "catalogue.",
    access: "session",
  },
  {
    id: "operations",
    path: "/operations",
    label: "Operations",
    area: "operations",
    navGroup: "primary",
    mobileTab: "work",
    requiredPermission: [
      "challans.",
      "cutting.",
      "inventory.",
      "procurement.",
      "production.",
      "logistics.",
    ],
    access: "session",
  },
  {
    id: "finance",
    path: "/finance",
    label: "Finance",
    area: "finance",
    navGroup: "primary",
    mobileTab: "work",
    requiredPermission: "finance.",
    access: "session",
  },
  {
    id: "settings",
    path: "/settings",
    label: "Settings",
    area: "settings",
    navGroup: "primary",
    mobileTab: "more",
    requiredPermission: null,
    access: "session",
  },
  // --- web lane, Slice 1 wave 1: auth flows and phone hubs -------------------------------
  {
    id: "demo-sign-in",
    path: "/demo-sign-in",
    label: "Demo sign-in",
    area: "auth",
    navGroup: null,
    mobileTab: null,
    requiredPermission: null,
    access: "public",
  },
  {
    id: "sign-out",
    path: "/sign-out",
    label: "Sign out",
    area: "auth",
    navGroup: null,
    mobileTab: null,
    requiredPermission: null,
    access: "public",
  },
  {
    id: "work",
    path: "/work",
    label: "Work",
    area: "hub",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "more",
    path: "/more",
    label: "More",
    area: "hub",
    navGroup: null,
    mobileTab: "more",
    requiredPermission: null,
    access: "session",
  },
  // --- web lane, Slice 1 wave 1 review fixes: Inbox tabs are routes (frontend_verification §4) -
  {
    id: "inbox-approvals",
    path: "/inbox/approvals",
    label: "Approvals",
    area: "inbox",
    navGroup: "context",
    mobileTab: "inbox",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "inbox-exceptions",
    path: "/inbox/exceptions",
    label: "Exceptions",
    area: "inbox",
    navGroup: "context",
    mobileTab: "inbox",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "inbox-snoozed",
    path: "/inbox/snoozed",
    label: "Snoozed",
    area: "inbox",
    navGroup: "context",
    mobileTab: "inbox",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "inbox-done",
    path: "/inbox/done",
    label: "Done",
    area: "inbox",
    navGroup: "context",
    mobileTab: "inbox",
    requiredPermission: null,
    access: "session",
  },
] as const satisfies readonly RouteDefinition[];

export type ManifestRoute = (typeof routes)[number];
export type RouteId = ManifestRoute["id"];
/** Primary entries keep their literal paths, so typed `<Link href>` checks them against real pages. */
export type PrimaryRoute = Extract<ManifestRoute, { navGroup: "primary" }>;

const byId = new Map<string, RouteDefinition>(routes.map((route) => [route.id, route]));

export function getRoute(id: RouteId): RouteDefinition {
  const route = byId.get(id);
  if (!route) throw new Error(`Unknown route id: ${id}`);
  return route;
}

export function primaryNavRoutes(): PrimaryRoute[] {
  return routes.filter((route): route is PrimaryRoute => route.navGroup === "primary");
}

export function permissionPrefixes(route: RouteDefinition): readonly PermissionPrefix[] {
  const required = route.requiredPermission;
  if (required === null) return [];
  return typeof required === "string" ? [required] : required;
}

/** Whether a user holding `permissionKeys` may see the route in navigation. */
export function canAccessRoute(route: RouteDefinition, permissionKeys: Iterable<string>): boolean {
  const prefixes = permissionPrefixes(route);
  if (prefixes.length === 0) return true;
  for (const key of permissionKeys) {
    if (prefixes.some((prefix) => key.startsWith(prefix))) return true;
  }
  return false;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Compiles a manifest path pattern into an anchored RegExp. */
export function compileRoutePattern(pattern: string): RegExp {
  if (pattern === "/") return /^\/$/;
  let source = "";
  for (const segment of pattern.split("/").filter(Boolean)) {
    if (/^\[\[\.\.\.[^\]]+\]\]$/.test(segment)) source += "(?:/[^/]+)*";
    else if (/^\[\.\.\.[^\]]+\]$/.test(segment)) source += "(?:/[^/]+)+";
    else if (/^\[[^\]]+\]$/.test(segment)) source += "/[^/]+";
    else source += `/${escapeRegExp(segment)}`;
  }
  return new RegExp(`^${source}/?$`);
}

function specificity(path: string): number {
  // Static segments outrank dynamic ones; catch-alls rank last.
  return path
    .split("/")
    .filter(Boolean)
    .reduce((score, segment) => {
      if (segment.startsWith("[[...")) return score;
      if (segment.startsWith("[...")) return score + 1;
      if (segment.startsWith("[")) return score + 2;
      return score + 3;
    }, 0);
}

const compiled = [...routes]
  .sort((a, b) => specificity(b.path) - specificity(a.path))
  .map((route) => ({ route: route as RouteDefinition, pattern: compileRoutePattern(route.path) }));

/** Finds the manifest entry for a concrete pathname such as `/sales/quotes/7f3…`. */
export function matchRoute(pathname: string): RouteDefinition | null {
  const clean = pathname.split(/[?#]/, 1)[0] || "/";
  for (const { route, pattern } of compiled) {
    if (pattern.test(clean)) return route;
  }
  return null;
}

/** The primary-area route that owns a pathname (used for aria-current in navigation). */
export function areaRouteFor(pathname: string): RouteDefinition | null {
  const match = matchRoute(pathname);
  if (!match) return null;
  return routes.find((route) => route.navGroup === "primary" && route.area === match.area) ?? null;
}
