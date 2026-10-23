"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { areaRouteFor, primaryNavRoutes } from "@/lib/routes";

const items = primaryNavRoutes();

export function PrimaryNav() {
  const pathname = usePathname();
  const activeId = areaRouteFor(pathname)?.id;

  return (
    <nav aria-label="Primary" className="-mx-4 overflow-x-auto px-4 lg:mx-0 lg:overflow-visible lg:px-0">
      <ul className="flex gap-1 lg:flex-col">
        {items.map((route) => (
          <li key={route.id} className="shrink-0">
            <Link
              href={route.path}
              aria-current={route.id === activeId ? "page" : undefined}
              className="flex min-h-11 items-center rounded-md px-3 font-medium text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink aria-[current=page]:bg-forest-tint aria-[current=page]:font-semibold aria-[current=page]:text-forest lg:pointer-fine:min-h-9"
            >
              {route.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
