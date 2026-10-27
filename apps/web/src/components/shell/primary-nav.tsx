"use client";

import { usePathname } from "next/navigation";
import { Link as RacLink } from "react-aria-components";
import { Tooltip } from "@/components/ui/tooltip";
import { cx } from "@/lib/cx";
import { formatCount } from "@/lib/format/money";
import { areaRouteFor, type PrimaryRoute } from "@/lib/routes";
import { shellMessages as m } from "@/messages/shell";
import { AreaIcon } from "./nav-icons";

/**
 * How the sidebar is drawn (frontend_verification §6, PARITY UI-07):
 * - `auto`: 208 px with labels from 1280 px, the 64 px icon rail on tablets (768-1279 px);
 * - `rail`: the 64 px icon rail at every width from 768 px (the person collapsed it).
 * Both are pure CSS, so the server render already matches the screen.
 */
export type SidebarMode = "auto" | "rail";

/** Class recipes per mode; whole literal strings so Tailwind sees every class. */
export const sidebarClasses = {
  auto: {
    label: "md:max-xl:sr-only",
    link: "md:max-xl:justify-center md:max-xl:px-0",
    count: "md:max-xl:absolute md:max-xl:end-1 md:max-xl:top-1",
    wide: "md:max-xl:hidden",
  },
  rail: {
    label: "sr-only",
    link: "justify-center px-0",
    count: "absolute end-1 top-1",
    wide: "hidden",
  },
} as const satisfies Record<SidebarMode, Record<string, string>>;

/**
 * The sidebar's area list. Items come from the bootstrap `nav` (lib/session/nav.ts): nothing
 * is listed that the server did not authorise and the manifest does not implement. In the icon
 * rail each link keeps its name (visually hidden) and shows it as a tooltip on hover and focus.
 */
export function PrimaryNav({
  routes,
  inboxCount,
  locale,
  mode = "auto",
  showTooltips = false,
  id,
}: {
  routes: readonly PrimaryRoute[];
  inboxCount: number | null;
  locale: string;
  mode?: SidebarMode;
  /** True while the icon rail is what the person sees (tablet width, or collapsed). */
  showTooltips?: boolean;
  id?: string;
}) {
  const pathname = usePathname();
  const activeId = areaRouteFor(pathname ?? "")?.id;
  const classes = sidebarClasses[mode];

  return (
    <nav id={id} aria-label={m.primaryNav}>
      <ul className="flex flex-col gap-0.5">
        {routes.map((route) => {
          const current = route.id === activeId;
          const count = route.id === "inbox" && inboxCount !== null && inboxCount > 0 ? inboxCount : null;
          return (
            <li key={route.id}>
              <Tooltip content={route.label} placement="end" delay={300} isDisabled={!showTooltips}>
                <RacLink
                  href={route.path}
                  aria-current={current ? "page" : undefined}
                  className={cx(
                    "relative flex min-h-11 items-center gap-3 rounded-md px-3 font-medium text-ink-muted transition-colors duration-150 pointer-fine:min-h-9",
                    "hover:bg-surface-sunken hover:text-ink",
                    classes.link,
                    current && "bg-forest-tint font-semibold text-forest hover:bg-forest-tint hover:text-forest",
                  )}
                >
                  <AreaIcon id={route.id} size={19} />
                  <span className={cx("flex-1", classes.label)}>{route.label}</span>
                  {count !== null ? (
                    <span className={cx("rounded-sm bg-sand-tint px-1.5 text-xs font-bold tabular text-ink", classes.count)}>
                      <span aria-hidden="true">{formatCount(count, locale)}</span>
                      <span className="sr-only">{m.inboxCount(count)}</span>
                    </span>
                  ) : null}
                </RacLink>
              </Tooltip>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
