"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { CSSProperties } from "react";
import { Icon, type IconName } from "~/ui/icon";
import { phoneTabOf, type PhoneTab } from "./nav";

const TABS: readonly { id: PhoneTab; label: string; href: Route; icon: IconName }[] = [
  { id: "today", label: "Today", href: "/today", icon: "home" },
  { id: "inbox", label: "Inbox", href: "/inbox", icon: "inbox" },
  { id: "work", label: "Work", href: "/work", icon: "grid" },
  { id: "more", label: "More", href: "/more", icon: "menu" },
];

/** Phone navigation: four destinations in a floating dock; the ink bubble slides to the current one. */
export function Dock({ inboxCount }: { inboxCount: number }) {
  const pathname = usePathname();
  const current = phoneTabOf(pathname);
  const index = TABS.findIndex((tab) => tab.id === current);

  return (
    <nav className="dock" aria-label="Primary">
      <span className="dock-bubble" data-hidden={index < 0} style={{ "--dock-index": Math.max(index, 0) } as CSSProperties} aria-hidden />
      {TABS.map((tab) => (
        <Link key={tab.id} href={tab.href} className="dock-item" aria-current={tab.id === current ? "page" : undefined}>
          <Icon name={tab.icon} size={20} />
          <span>{tab.label}</span>
          {tab.id === "inbox" && inboxCount > 0 ? (
            <span className="dock-dot">
              <span className="sr-only">{inboxCount === 1 ? "1 open item" : `${inboxCount} open items`}</span>
            </span>
          ) : null}
        </Link>
      ))}
    </nav>
  );
}
