"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { PermissionDenied } from "@/components/ui/states";
import { areaRouteFor, canAccessRoute, matchRoute, type RouteDefinition } from "@/lib/routes";

/** The area a signed-in user may not open at `pathname`, or null when access is fine. */
export function deniedRoute(pathname: string, permissionKeys: Iterable<string>): RouteDefinition | null {
  const route = matchRoute(pathname);
  if (!route || route.access !== "session") return null;
  return canAccessRoute(route, permissionKeys) ? null : route;
}

/**
 * Areas the user's permissions do not cover render a PermissionDenied view instead of the
 * page (frontend_verification §6 "Denied routes"): no data, the missing area named, a path
 * back to Today. Runs on the client so it also guards client-side navigation, which does not
 * re-run the server layout. The API still enforces every read; this only avoids a dead screen.
 */
export function RouteGate({ permissionKeys, children }: { permissionKeys: ReadonlySet<string>; children: ReactNode }) {
  const pathname = usePathname();
  const denied = deniedRoute(pathname, permissionKeys);
  // A sub-route (e.g. the audit log) is named itself; a primary area keeps its area name.
  const area = denied ? (denied.navGroup === "context" ? denied.label : (areaRouteFor(pathname)?.label ?? denied.label)) : null;
  if (denied && area) return <PermissionDenied area={area} />;
  return <>{children}</>;
}
