/**
 * The route manifest for this app: the shared manifest (`@/lib/routes`, which also drives the old app and its tests)
 * plus the screens that exist only here, the CRM programme's new modules. Import routing helpers from this module,
 * never from `@/lib/routes` directly, so the new screens are matched, permission-checked and shown in navigation.
 */

import {
  canAccessRoute,
  compileRoutePattern,
  contextRoutesFor as baseContextRoutesFor,
  matchRoute as baseMatchRoute,
  routes as baseRoutes,
  type AreaId,
  type RouteDefinition,
} from "@/lib/routes";

export { canAccessRoute, type AreaId, type RouteDefinition };

/** Screens added by the CRM programme (docs/superpowers/specs/2026-11-25-*.md). */
export const extraRoutes: readonly RouteDefinition[] = [
  {
    id: "sales-proforma-invoices",
    path: "/sales/proforma-invoices",
    label: "Proforma invoices",
    area: "sales",
    navGroup: "context",
    mobileTab: "work",
    requiredPermission: "sales.",
    access: "session",
  },
  {
    id: "sales-proforma-invoice",
    path: "/sales/proforma-invoices/[proformaId]",
    label: "Proforma invoice",
    area: "sales",
    navGroup: null,
    mobileTab: "work",
    requiredPermission: "sales.",
    access: "session",
  },
];

const compiledExtra = extraRoutes.map((route) => ({ route, pattern: compileRoutePattern(route.path) }));

/** The route definition for a pathname: this app's own screens first, then the shared manifest. */
export function matchRoute(pathname: string): RouteDefinition | null {
  const clean = pathname.split(/[?#]/, 1)[0] || "/";
  for (const { route, pattern } of compiledExtra) {
    if (pattern.test(clean)) return route;
  }
  return baseMatchRoute(pathname);
}

/** The area's sub-navigation entries: the shared ones, then this app's own. */
export function contextRoutesFor(area: AreaId): RouteDefinition[] {
  return [...baseContextRoutesFor(area), ...extraRoutes.filter((route) => route.navGroup === "context" && route.area === area)];
}

/** Every route this app knows: the shared manifest plus its own screens. */
export const routes: readonly RouteDefinition[] = [...baseRoutes, ...extraRoutes];
