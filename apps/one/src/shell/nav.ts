/**
 * The information architecture of Lamikraft One.
 *
 * The left-side menu is FLAT: every screen is a top-level link, categorised under a plain group
 * heading (Sales, Products, Operations, Finance). Groups are headings, not parents: nothing
 * expands, collapses or nests (owner's instruction, 2026-11-12).
 *
 * Areas come from the session bootstrap (only authorised, switched-on areas are offered) and each
 * link is checked against the shared route manifest, so navigation never shows a dead or forbidden
 * link. Labels use the team's own vocabulary (docs/meetings): leads, customers, quotations, stock.
 */

import type { Route } from "next";
import { canAccessRoute, matchRoute, type AreaId } from "~/lib/routes";
import type { NavEntry } from "@/lib/session/types";
import type { IconName } from "~/ui/icon";

export interface NavItem {
  label: string;
  icon: IconName;
  href: Route;
  /** Path used for the permission check and for "is this the current page". Defaults to href without its query. */
  path?: string;
  /** Query pairs that must all match for this item to be current (e.g. Leads versus Customers). */
  query?: Readonly<Record<string, string>>;
  /** Extra path prefixes that also belong to this item (detail and child screens). */
  also?: readonly string[];
  /** Current only on exactly this path (a group's overview), never on its child screens. */
  exact?: boolean;
}

export interface NavArea {
  id: Exclude<AreaId, "auth" | "hub">;
  label: string;
  icon: IconName;
  href: Route;
  /** One line that says what the area is for; shown on hubs and the phone Work screen. */
  blurb: string;
  /** The area's screens, all at one level. Where the area has a landing screen it is the first item. */
  items: readonly NavItem[];
}

export const NAV_AREAS: readonly NavArea[] = [
  { id: "today", label: "Today", icon: "home", href: "/today", blurb: "What needs you now, and what changed overnight.", items: [] },
  { id: "inbox", label: "Inbox", icon: "inbox", href: "/inbox", blurb: "Approvals, exceptions and conversations waiting on you.", items: [] },
  {
    id: "sales",
    label: "Sales",
    icon: "handshake",
    href: "/sales",
    blurb: "From first enquiry to confirmed order.",
    items: [
      { label: "Overview", icon: "handshake", href: "/sales", exact: true },
      { label: "Leads", icon: "userPlus", href: "/sales/parties?status=prospect" as Route, path: "/sales/parties", query: { status: "prospect" } },
      { label: "Customers", icon: "users", href: "/sales/parties?status=active" as Route, path: "/sales/parties" },
      { label: "Enquiries", icon: "mail", href: "/sales/enquiries" },
      { label: "Quotations", icon: "fileText", href: "/sales/quotes" },
      { label: "Orders", icon: "cart", href: "/sales/orders" },
      { label: "Samples", icon: "packageOpen", href: "/sales/samples" },
      { label: "Custom products", icon: "shapes", href: "/sales/custom-products" },
      { label: "Messages", icon: "message", href: "/sales/customer-messages" },
    ],
  },
  {
    id: "products",
    label: "Products",
    icon: "box",
    href: "/products",
    blurb: "The catalogue: designs, decors, sizes and prices.",
    items: [
      { label: "Catalogue", icon: "box", href: "/products", also: ["/products/"] },
      { label: "Price lists", icon: "tag", href: "/products/price-lists" },
      { label: "Completeness", icon: "clipboardCheck", href: "/products/completeness" },
      { label: "Taxonomy", icon: "layers", href: "/products/taxonomy" },
    ],
  },
  {
    id: "operations",
    label: "Operations",
    icon: "factory",
    href: "/operations",
    blurb: "Stock, production, purchasing and dispatch.",
    items: [
      { label: "Overview", icon: "factory", href: "/operations", exact: true },
      { label: "Stock", icon: "warehouse", href: "/operations/inventory" },
      { label: "Reservations", icon: "bookmark", href: "/operations/reservations" },
      { label: "Production", icon: "hammer", href: "/operations/production/work-orders", also: ["/operations/production"] },
      { label: "Cut plans", icon: "scissors", href: "/operations/cutting" },
      { label: "Purchasing", icon: "clipboard", href: "/operations/purchasing/orders", also: ["/operations/purchasing"] },
      { label: "Quality", icon: "flask", href: "/operations/quality" },
      { label: "Dispatch", icon: "truck", href: "/operations/dispatch" },
      { label: "Challans", icon: "fileCheck", href: "/operations/challans" },
    ],
  },
  {
    id: "finance",
    label: "Finance",
    icon: "wallet",
    href: "/finance",
    blurb: "Invoices, receipts and what is still owed.",
    items: [
      { label: "Overview", icon: "wallet", href: "/finance", exact: true },
      { label: "Invoices", icon: "receipt", href: "/finance/invoices" },
      { label: "Receipts", icon: "banknote", href: "/finance/receipts" },
      { label: "Credit notes", icon: "undo", href: "/finance/credit-notes" },
      { label: "Ageing", icon: "clock", href: "/finance/ageing" },
      { label: "Exceptions", icon: "alert", href: "/finance/exceptions" },
      { label: "Accounting sync", icon: "refresh", href: "/finance/accounting-sync" },
    ],
  },
  { id: "settings", label: "Settings", icon: "settings", href: "/settings", blurb: "Your profile, your team and how the workspace behaves.", items: [] },
];

function pathOf(item: NavItem): string {
  return item.path ?? String(item.href).split("?")[0] ?? String(item.href);
}

function allowed(path: string, permissionKeys: ReadonlySet<string>): boolean {
  const route = matchRoute(path);
  return route !== null && canAccessRoute(route, permissionKeys);
}

/** Areas and items this person may open, in display order. */
export function visibleAreas(nav: readonly NavEntry[], permissionKeys: ReadonlySet<string>): NavArea[] {
  const offered = new Set(nav.map((entry) => entry.key));
  const out: NavArea[] = [];
  for (const area of NAV_AREAS) {
    if (!offered.has(area.id)) continue;
    if (!allowed(String(area.href), permissionKeys)) continue;
    out.push({ ...area, items: area.items.filter((item) => allowed(pathOf(item), permissionKeys)) });
  }
  return out;
}

/** The area a pathname belongs to (from the manifest), or null for hubs and unknown paths. */
export function areaOf(pathname: string): NavArea["id"] | null {
  const area = matchRoute(pathname)?.area;
  if (!area || area === "auth" || area === "hub") return null;
  // Search and Activity sit under Today in the manifest; neither should light up Today.
  if (area === "today" && !(pathname === "/today" || pathname.startsWith("/today/"))) return null;
  return area;
}

/** The single current item of an area: the most specific match, where a query match beats a bare path. */
export function currentItem(area: NavArea, pathname: string, search: URLSearchParams): NavItem | null {
  let best: NavItem | null = null;
  let bestScore = -1;
  for (const item of area.items) {
    const path = pathOf(item);
    let hit: string | undefined;
    if (item.exact) {
      hit = pathname === path ? path : undefined;
    } else {
      hit = [path, ...(item.also ?? [])].find((prefix) => pathname === prefix || pathname.startsWith(prefix.endsWith("/") ? prefix : `${prefix}/`));
    }
    if (!hit) continue;
    const queryOk = !item.query || Object.entries(item.query).every(([key, value]) => search.get(key) === value);
    if (!queryOk) continue;
    // An exact path beats a prefix; a matching query adds weight; longer prefixes beat shorter ones.
    const score = hit.length + (pathname === path ? 1000 : 0) + (item.query ? 500 : 0);
    if (score > bestScore) {
      best = item;
      bestScore = score;
    }
  }
  return best;
}

export type PhoneTab = "today" | "inbox" | "work" | "more";

/** Which phone dock tab is lit for a pathname. */
export function phoneTabOf(pathname: string): PhoneTab | null {
  if (pathname === "/work") return "work";
  if (pathname === "/more") return "more";
  const tab = matchRoute(pathname)?.mobileTab;
  return tab ?? null;
}
