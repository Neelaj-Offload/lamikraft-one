"use client";

import { Badge } from "@/components/ui/badge";
import { Link } from "@/components/ui/link";
import { canAccessRoute, getRoute, type RouteId } from "@/lib/routes";
import { useSession } from "@/lib/session/context";
import { areaMessages } from "@/messages/areas";

/** A delivered part of an area overview: a link when this person may open it, otherwise its label. */
export function DeliveredPart({ label, routeId }: { label: string; routeId: RouteId }) {
  const { permissionKeys } = useSession();
  const route = getRoute(routeId);
  return (
    <>
      {canAccessRoute(route, permissionKeys) ? <Link href={route.path}>{label}</Link> : <span className="text-ink">{label}</span>}
      <Badge tone="success">{areaMessages.available}</Badge>
    </>
  );
}
