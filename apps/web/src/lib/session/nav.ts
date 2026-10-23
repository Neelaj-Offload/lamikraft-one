/**
 * Navigation comes only from the bootstrap `nav` list (authorised and implemented areas, in
 * order). The route manifest supplies each area's path and label; an area the manifest does
 * not know is ignored rather than linked, so navigation never offers a dead link.
 */

import { canAccessRoute, primaryNavRoutes, type MobileTab, type PrimaryRoute } from "@/lib/routes";
import type { NavEntry } from "./types";

export function navRoutesFromBootstrap(nav: readonly NavEntry[], permissionKeys: Iterable<string>): PrimaryRoute[] {
  const keys = [...permissionKeys];
  const primary = primaryNavRoutes();
  const out: PrimaryRoute[] = [];
  for (const entry of nav) {
    const route = primary.find((candidate) => candidate.id === entry.key || candidate.area === entry.key);
    // The server already filtered by permission; the manifest check is a second, local guard.
    if (route && !out.includes(route) && canAccessRoute(route, keys)) out.push(route);
  }
  return out;
}

/** Areas grouped under a phone tab (Work: Sales, Products, Operations, Finance; More: Settings). */
export function routesForMobileTab(routes: readonly PrimaryRoute[], tab: MobileTab): PrimaryRoute[] {
  return routes.filter((route) => route.mobileTab === tab);
}
