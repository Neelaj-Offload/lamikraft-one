"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "@/lib/cx";
import { formatCount } from "@/lib/format/money";
import { areaRouteFor, type PrimaryRoute } from "@/lib/routes";
import { shellMessages as m } from "@/messages/shell";
import { AreaIcon } from "./nav-icons";

/**
 * The sidebar's area list. Items come from the bootstrap `nav` (lib/session/nav.ts): nothing
 * is listed that the server did not authorise and the manifest does not implement.
 */
export function PrimaryNav({ routes, inboxCount, locale }: { routes: readonly PrimaryRoute[]; inboxCount: number | null; locale: string }) {
  const pathname = usePathname();
  const activeId = areaRouteFor(pathname)?.id;

  return (
    <nav aria-label={m.primaryNav}>
      <ul className="flex flex-col gap-0.5">
        {routes.map((route) => {
          const current = route.id === activeId;
          const count = route.id === "inbox" && inboxCount !== null && inboxCount > 0 ? inboxCount : null;
          return (
            <li key={route.id}>
              <Link
                href={route.path}
                aria-current={current ? "page" : undefined}
                className={cx(
                  "flex min-h-11 items-center gap-3 rounded-md px-3 font-medium text-ink-muted transition-colors duration-150 pointer-fine:min-h-9",
                  "hover:bg-surface-sunken hover:text-ink",
                  current && "bg-forest-tint font-semibold text-forest hover:bg-forest-tint hover:text-forest",
                )}
              >
                <AreaIcon id={route.id} size={19} />
                <span className="flex-1">{route.label}</span>
                {count !== null ? (
                  <span className="rounded-sm bg-sand-tint px-1.5 text-xs font-bold tabular text-ink">
                    <span aria-hidden="true">{formatCount(count, locale)}</span>
                    <span className="sr-only">{m.inboxCount(count)}</span>
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
