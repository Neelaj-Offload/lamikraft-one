"use client";

import type { Route } from "next";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { Button as RacButton } from "react-aria-components";
import { isSearchShortcut } from "@/lib/shortcuts";
import { Avatar } from "~/ui/avatar";
import { Badge } from "~/ui/badge";
import { IconButtonLink } from "~/ui/button";
import { Menu, type MenuItem } from "~/ui/menu";
import { SearchField } from "~/ui/search-field";
import { ThemeToggle } from "~/ui/theme-toggle";
import { Tooltip } from "~/ui/tooltip";

export interface TopBarProps {
  userName: string;
  userEmail: string | null;
  roleLine: string;
  isDemo: boolean;
  inboxCount: number;
  canSearch: boolean;
  shortcutsEnabled: boolean;
}

const DEMO_NOTE =
  "Demo workspace. The people, customers and documents are fictional, and nothing is sent outside Lamikraft One.";

/**
 * The floating bar above every signed-in screen: search first, then the few things that are
 * global (workspace mode, inbox, theme, account). Page titles and actions belong to the page.
 */
export function TopBar({ userName, userEmail, roleLine, isDemo, inboxCount, canSearch, shortcutsEnabled }: TopBarProps) {
  const router = useRouter();
  const searchRef = useRef<HTMLDivElement>(null);

  // "/" (or Ctrl/Cmd K) jumps to search from anywhere outside a text field.
  useEffect(() => {
    if (!canSearch) return;
    const onKey = (event: KeyboardEvent) => {
      if (!isSearchShortcut(event, { shortcutsEnabled })) return;
      const input = searchRef.current?.querySelector<HTMLInputElement>("input");
      if (!input) return;
      event.preventDefault();
      input.focus();
      input.select();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canSearch, shortcutsEnabled]);

  const accountItems: MenuItem[] = [
    { id: "profile", label: "Your profile", icon: "user", href: "/settings/profile" },
    { id: "security", label: "Sign-in and security", icon: "shield", href: "/settings/security" },
    { id: "settings", label: "Workspace settings", icon: "settings", href: "/settings" },
    { separator: true, id: "sep" },
    { id: "sign-out", label: "Sign out", icon: "logOut", href: "/sign-out" },
  ];

  return (
    <header className="top">
      <Link href="/today" className="top-brand" aria-label="Lamikraft One, go to Today">
        <Image src="/brand/lamikraft-mark.webp" alt="" width={30} height={30} />
      </Link>

      {canSearch ? (
        <div className="top-search" ref={searchRef} role="search">
          <SearchField
            label="Search customers, quotations, products and more"
            placeholder="Search customers, quotations, products"
            shortcut={shortcutsEnabled ? "/" : false}
            onSubmit={(value) => {
              const q = value.trim();
              if (q.length > 0) router.push(`/search?q=${encodeURIComponent(q)}` as Route);
            }}
          />
        </div>
      ) : (
        <div className="top-spacer" />
      )}

      <div className="top-spacer top-hide-sm" />

      <div className="top-actions">
        {isDemo ? (
          <Tooltip text={DEMO_NOTE}>
            <RacButton className="rounded-pill" aria-label={`Demo. ${DEMO_NOTE}`}>
              <Badge tone="gold" dot>
                Demo
              </Badge>
            </RacButton>
          </Tooltip>
        ) : null}
        <span className="top-hide-sm">
          <IconButtonLink
            icon="inbox"
            label={inboxCount > 0 ? `Inbox, ${inboxCount} open` : "Inbox"}
            href="/inbox"
            variant="ghost"
            badge={inboxCount > 0}
          />
        </span>
        <span className="top-hide-sm">
          <ThemeToggle variant="icon" />
        </span>
        <Menu
          label={`Account menu for ${userName}`}
          placement="bottom end"
          items={accountItems}
          trigger={
            <RacButton className="press rounded-pill" aria-label={`Account menu for ${userName}. ${roleLine}${userEmail ? `, ${userEmail}` : ""}`}>
              <Avatar name={userName} size="md" />
            </RacButton>
          }
        />
      </div>
    </header>
  );
}
