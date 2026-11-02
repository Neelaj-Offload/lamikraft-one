"use client";

import { usePathname } from "next/navigation";
import { useMemo } from "react";
import { NavTabs } from "@/components/ui/tabs";
import { canAccessRoute, contextRoutesFor, matchRoute, type AreaId } from "@/lib/routes";
import { useSession } from "@/lib/session/context";

/**
 * An area's contextual sub-navigation (frontend_verification §6): the area's `context` routes
 * the person may open, as links with aria-current, under the page title. A detail route marks
 * its list's tab current (`/products/[id]` highlights Products) through `currentId`.
 */
export function AreaNav({
  area,
  label,
  currentId,
  counts,
  leading,
}: {
  area: AreaId;
  label: string;
  currentId?: string;
  counts?: Partial<Record<string, number | null>>;
  /** Tabs placed before the manifest's context routes (the area's own root, e.g. "Products"). */
  leading?: readonly { id: string; label: string; href: string }[];
}) {
  const { permissionKeys, zone } = useSession();
  const pathname = usePathname();
  const tabs = useMemo(
    () => [
      ...(leading ?? []).map((tab) => ({ ...tab, count: counts?.[tab.id] ?? null })),
      ...contextRoutesFor(area)
        .filter((route) => canAccessRoute(route, permissionKeys))
        .map((route) => ({ id: route.id, label: route.label, href: route.path, count: counts?.[route.id] ?? null })),
    ],
    [area, permissionKeys, counts, leading],
  );
  if (tabs.length <= 1) return null;
  const current = currentId ?? matchRoute(pathname ?? "")?.id ?? "";
  return <NavTabs label={label} tabs={tabs} currentId={current} locale={zone.locale} />;
}
