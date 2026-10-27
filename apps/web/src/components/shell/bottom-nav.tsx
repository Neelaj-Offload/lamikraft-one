"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "@/lib/cx";
import { formatCount } from "@/lib/format/money";
import { matchRoute, type MobileTab, type PrimaryRoute } from "@/lib/routes";
import { shellMessages as m } from "@/messages/shell";
import { AreaIcon } from "./nav-icons";

interface PhoneTab {
  id: MobileTab;
  label: string;
  href: "/today" | "/inbox" | "/work" | "/more";
}

/** Today and Inbox appear when the bootstrap lists them; Work and More are hubs of what it lists. */
export function phoneTabs(navRoutes: readonly PrimaryRoute[]): PhoneTab[] {
  const has = (id: string) => navRoutes.some((route) => route.id === id);
  const tabs: PhoneTab[] = [];
  if (has("today")) tabs.push({ id: "today", label: m.phone.today, href: "/today" });
  if (has("inbox")) tabs.push({ id: "inbox", label: m.phone.inbox, href: "/inbox" });
  tabs.push({ id: "work", label: m.phone.work, href: "/work" });
  tabs.push({ id: "more", label: m.phone.more, href: "/more" });
  return tabs;
}

/** Phone navigation below 768 px: Today, Inbox, Work, More (56 px plus the safe-area inset). */
export function BottomNav({ navRoutes, inboxCount, locale }: { navRoutes: readonly PrimaryRoute[]; inboxCount: number | null; locale: string }) {
  const pathname = usePathname();
  const active = matchRoute(pathname)?.mobileTab ?? null;
  const tabs = phoneTabs(navRoutes);

  return (
    <nav
      aria-label={m.primaryNav}
      className="fixed inset-x-0 bottom-0 z-40 border-t bg-surface pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      <ul className={cx("grid", tabs.length === 4 ? "grid-cols-4" : tabs.length === 3 ? "grid-cols-3" : "grid-cols-2")}>
        {tabs.map((tab) => {
          const current = tab.id === active;
          const count = tab.id === "inbox" && inboxCount !== null && inboxCount > 0 ? inboxCount : null;
          return (
            <li key={tab.id}>
              <Link
                href={tab.href}
                aria-current={current ? "page" : undefined}
                className={cx(
                  "flex h-14 flex-col items-center justify-center gap-0.5 text-xs font-medium text-ink-muted",
                  current && "font-bold text-forest",
                )}
              >
                <span className="relative">
                  <AreaIcon id={tab.id} size={22} />
                  {count !== null ? (
                    <span className="absolute -end-2.5 -top-1.5 rounded-sm bg-sand-tint px-1 text-[11px] leading-4 font-bold tabular text-ink">
                      <span aria-hidden="true">{formatCount(count, locale)}</span>
                    </span>
                  ) : null}
                </span>
                <span>
                  {tab.label}
                  {count !== null ? <span className="sr-only">, {m.inboxCount(count)}</span> : null}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
