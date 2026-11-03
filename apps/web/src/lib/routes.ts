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
    id: "operations-challans",
    path: "/operations/challans",
    label: "Challans",
    area: "operations",
    navGroup: "context",
    mobileTab: "work",
    requiredPermission: "challans.",
    access: "session",
  },
  {
    id: "operations-challan-new",
    path: "/operations/challans/new",
    label: "New challan",
    area: "operations",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "challans.",
    access: "session",
  },
  {
    id: "operations-challan",
    path: "/operations/challans/[challanId]",
    label: "Challan",
    area: "operations",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "challans.",
    access: "session",
  },
  {
    id: "print-challan",
    path: "/print/challans/[challanId]",
    label: "Challan print view",
    area: "operations",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "challans.",
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
    id: "inbox-conversations",
    path: "/inbox/conversations",
    label: "Conversations",
    area: "inbox",
    navGroup: "context",
    mobileTab: "inbox",
    requiredPermission: null,
    access: "session",
  },
  // --- web lane, Slice 1 wave 2: review page and sales area (the snoozed/done Inbox tabs were
  // removed: the tasks API has no such tabs; snoozed items keep their tab with a Snoozed status) -
  {
    id: "inbox-approval-review",
    path: "/inbox/approvals/[proposalId]",
    label: "Review request",
    area: "inbox",
    navGroup: null,
    mobileTab: "inbox",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "approval-alias",
    path: "/approvals/[proposalId]",
    label: "Review request",
    area: "inbox",
    navGroup: null,
    mobileTab: "inbox",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "sales-quotes",
    path: "/sales/quotes",
    label: "Quotes",
    area: "sales",
    navGroup: "context",
    mobileTab: "work",
    requiredPermission: "sales.",
    access: "session",
  },
  {
    id: "sales-quote-new",
    path: "/sales/quotes/new",
    label: "New quote",
    area: "sales",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "sales.",
    access: "session",
  },
  {
    id: "sales-quote",
    path: "/sales/quotes/[quoteId]",
    label: "Quote",
    area: "sales",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "sales.",
    access: "session",
  },
  {
    id: "sales-enquiries",
    path: "/sales/enquiries",
    label: "Enquiries",
    area: "sales",
    navGroup: "context",
    mobileTab: "work",
    requiredPermission: "sales.",
    access: "session",
  },
  {
    id: "sales-enquiry",
    path: "/sales/enquiries/[enquiryId]",
    label: "Enquiry",
    area: "sales",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "sales.",
    access: "session",
  },
  {
    id: "sales-customer-messages",
    path: "/sales/customer-messages",
    label: "Customer messages",
    area: "sales",
    navGroup: "context",
    mobileTab: "work",
    requiredPermission: "sales.",
    access: "session",
  },
  // --- checkpoint 2: parties, products, settings sections (docs/superpowers/specs/2026-11-02-*) ----
  {
    id: "sales-parties",
    path: "/sales/parties",
    label: "Customers",
    area: "sales",
    navGroup: "context",
    mobileTab: "work",
    requiredPermission: "parties.",
    access: "session",
  },
  {
    id: "sales-party-new",
    path: "/sales/parties/new",
    label: "New customer",
    area: "sales",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "parties.",
    access: "session",
  },
  {
    id: "sales-party",
    path: "/sales/parties/[partyId]",
    label: "Customer",
    area: "sales",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "parties.",
    access: "session",
  },
  {
    id: "products-completeness",
    path: "/products/completeness",
    label: "Completeness",
    area: "products",
    navGroup: "context",
    mobileTab: "work",
    requiredPermission: "catalogue.",
    access: "session",
  },
  {
    id: "products-taxonomy",
    path: "/products/taxonomy",
    label: "Taxonomy",
    area: "products",
    navGroup: "context",
    mobileTab: "work",
    requiredPermission: "catalogue.",
    access: "session",
  },
  {
    id: "products-price-lists",
    path: "/products/price-lists",
    label: "Price lists",
    area: "products",
    navGroup: "context",
    mobileTab: "work",
    requiredPermission: "pricing.",
    access: "session",
  },
  {
    id: "products-price-list",
    path: "/products/price-lists/[priceListId]",
    label: "Price list",
    area: "products",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "pricing.",
    access: "session",
  },
  {
    id: "products-product",
    path: "/products/[productId]",
    label: "Product",
    area: "products",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "catalogue.",
    access: "session",
  },
  {
    id: "settings-profile",
    path: "/settings/profile",
    label: "Profile",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "settings-company",
    path: "/settings/company",
    label: "Company",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: "org.",
    access: "session",
  },
  {
    id: "settings-reference",
    path: "/settings/reference",
    label: "Reference data",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "settings-integrations",
    path: "/settings/integrations",
    label: "Integrations",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "settings-ai",
    path: "/settings/ai",
    label: "AI",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: "agents.",
    access: "session",
  },
  {
    id: "settings-ai-trace",
    path: "/settings/ai/traces/[correlationId]",
    label: "Trace",
    area: "settings",
    navGroup: null,
    mobileTab: "more",
    requiredPermission: "agents.",
    access: "session",
  },
  {
    id: "settings-audit",
    path: "/settings/audit",
    label: "Audit log",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: "audit.",
    access: "session",
  },
  // platform-2 (Slice 2): settings, account security, auth links, global search, activity --------
  {
    id: "auth-two-step",
    path: "/two-step",
    label: "Two-step sign-in",
    area: "auth",
    navGroup: null,
    mobileTab: null,
    requiredPermission: null,
    access: "public",
  },
  {
    id: "auth-invite",
    path: "/invite",
    label: "Accept invitation",
    area: "auth",
    navGroup: null,
    mobileTab: null,
    requiredPermission: null,
    access: "public",
  },
  {
    id: "auth-reset-password",
    path: "/reset-password",
    label: "Choose a new password",
    area: "auth",
    navGroup: null,
    mobileTab: null,
    requiredPermission: null,
    access: "public",
  },
  {
    id: "auth-forgot-password",
    path: "/forgot-password",
    label: "Forgot password",
    area: "auth",
    navGroup: null,
    mobileTab: null,
    requiredPermission: null,
    access: "public",
  },
  {
    id: "settings-security",
    path: "/settings/security",
    label: "Security",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "settings-delegation",
    path: "/settings/delegation",
    label: "Delegation",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "settings-leave",
    path: "/settings/leave",
    label: "Leave",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "settings-access-requests",
    path: "/settings/access-requests",
    label: "Access requests",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "settings-users",
    path: "/settings/users",
    label: "Users",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: "identity.",
    access: "session",
  },
  {
    id: "settings-user-invite",
    path: "/settings/users/invite",
    label: "Invite someone",
    area: "settings",
    navGroup: null,
    mobileTab: "more",
    requiredPermission: "identity.",
    access: "session",
  },
  {
    id: "settings-user",
    path: "/settings/users/[userId]",
    label: "Member",
    area: "settings",
    navGroup: null,
    mobileTab: "more",
    requiredPermission: "identity.",
    access: "session",
  },
  {
    id: "settings-roles",
    path: "/settings/roles",
    label: "Roles",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: "identity.",
    access: "session",
  },
  {
    id: "settings-role-new",
    path: "/settings/roles/new",
    label: "New role",
    area: "settings",
    navGroup: null,
    mobileTab: "more",
    requiredPermission: "identity.",
    access: "session",
  },
  {
    id: "settings-role",
    path: "/settings/roles/[roleId]",
    label: "Role",
    area: "settings",
    navGroup: null,
    mobileTab: "more",
    requiredPermission: "identity.",
    access: "session",
  },
  {
    id: "settings-role-edit",
    path: "/settings/roles/[roleId]/edit",
    label: "Edit role",
    area: "settings",
    navGroup: null,
    mobileTab: "more",
    requiredPermission: "identity.",
    access: "session",
  },
  {
    id: "settings-role-simulate",
    path: "/settings/roles/simulate",
    label: "Role simulator",
    area: "settings",
    navGroup: null,
    mobileTab: "more",
    requiredPermission: "identity.",
    access: "session",
  },
  {
    id: "search",
    path: "/search",
    label: "Search",
    area: "today",
    navGroup: null,
    mobileTab: "more",
    requiredPermission: "search.",
    access: "session",
  },
  {
    id: "activity",
    path: "/activity",
    label: "Activity",
    area: "today",
    navGroup: null,
    mobileTab: "more",
    requiredPermission: "collab.",
    access: "session",
  },
  // catalogue lane (Slice 2 wave 1): new product, section deep links, imports, lookups, customer types
  { id: "products-new", path: "/products/new", label: "New product", area: "products", navGroup: null, mobileTab: "work", requiredPermission: "catalogue.", access: "session" },
  { id: "product-section", path: "/products/[productId]/[section]", label: "Product", area: "products", navGroup: null, mobileTab: "work", requiredPermission: "catalogue.", access: "session" },
  { id: "settings-imports", path: "/settings/imports", label: "Imports", area: "settings", navGroup: "context", mobileTab: "more", requiredPermission: "imports.", access: "session" },
  { id: "settings-import-new", path: "/settings/imports/new", label: "New import", area: "settings", navGroup: null, mobileTab: "more", requiredPermission: "imports.", access: "session" },
  { id: "settings-import", path: "/settings/imports/[jobId]", label: "Import", area: "settings", navGroup: null, mobileTab: "more", requiredPermission: "imports.", access: "session" },
  { id: "settings-lookups", path: "/settings/lookups", label: "Lookup reference", area: "settings", navGroup: "context", mobileTab: "more", requiredPermission: "catalogue.", access: "session" },
  { id: "settings-customer-types", path: "/settings/customer-types", label: "Customer types", area: "settings", navGroup: "context", mobileTab: "more", requiredPermission: "parties.", access: "session" },
  // commercial-2 lane (Slice 2): custom products, samples, quote settings, FX rates
  {
    id: "sales-custom-products",
    path: "/sales/custom-products",
    label: "Custom products",
    area: "sales",
    navGroup: "context",
    mobileTab: "work",
    requiredPermission: "sales.",
    access: "session",
  },
  {
    id: "sales-custom-product-new",
    path: "/sales/custom-products/new",
    label: "New custom product",
    area: "sales",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "sales.",
    access: "session",
  },
  {
    id: "sales-custom-product",
    path: "/sales/custom-products/[customProductId]",
    label: "Custom product",
    area: "sales",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "sales.",
    access: "session",
  },
  {
    id: "sales-samples",
    path: "/sales/samples",
    label: "Samples",
    area: "sales",
    navGroup: "context",
    mobileTab: "work",
    requiredPermission: "sales.",
    access: "session",
  },
  {
    id: "sales-sample",
    path: "/sales/samples/[sampleId]",
    label: "Sample",
    area: "sales",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "sales.",
    access: "session",
  },
  {
    id: "settings-quotes",
    path: "/settings/quotes",
    label: "Quote settings",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: "sales.",
    access: "session",
  },
  {
    id: "settings-fx-rates",
    path: "/settings/fx-rates",
    label: "FX rates",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: "pricing.",
    access: "session",
  },
  // cutting (Slice 2 wave 2): saved cut plans, plan editor, grain locks
  {
    id: "operations-cutting",
    path: "/operations/cutting",
    label: "Cut plans",
    area: "operations",
    navGroup: "context",
    mobileTab: "work",
    requiredPermission: "cutting.",
    access: "session",
  },
  {
    id: "operations-cutting-new",
    path: "/operations/cutting/new",
    label: "New cut plan",
    area: "operations",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "cutting.",
    access: "session",
  },
  {
    id: "operations-cutting-grain-locks",
    path: "/operations/cutting/grain-locks",
    label: "Grain locks",
    area: "operations",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "cutting.",
    access: "session",
  },
  {
    id: "operations-cutting-plan",
    path: "/operations/cutting/[planId]",
    label: "Cut plan",
    area: "operations",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "cutting.",
    access: "session",
  },
  // --- Slice 3 WhatsApp lane: Settings › WhatsApp and the review-link landing page --------------
  {
    id: "settings-whatsapp",
    path: "/settings/whatsapp",
    label: "WhatsApp",
    area: "settings",
    navGroup: "context",
    mobileTab: "more",
    requiredPermission: null,
    access: "session",
  },
  {
    id: "review-link",
    path: "/r/[token]",
    label: "Review link",
    area: "inbox",
    navGroup: null,
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

/** The area's sub-navigation entries, in manifest order (`AreaNav`). */
export function contextRoutesFor(area: AreaId): RouteDefinition[] {
  return routes.filter((route) => route.navGroup === "context" && route.area === area);
}
