"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Icon } from "~/ui/icon";
import { areaOf, currentItem, type NavArea } from "./nav";

const OPEN_KEY = "lk-one:nav-open";
/** Sales is open by default: phase one of the rollout is the sales modules (docs/meetings). */
const DEFAULT_OPEN: readonly string[] = ["sales"];

function readOpen(): string[] {
  try {
    const raw = window.localStorage.getItem(OPEN_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === "string") : [...DEFAULT_OPEN];
  } catch {
    return [...DEFAULT_OPEN];
  }
}

function writeOpen(open: readonly string[]): void {
  try {
    window.localStorage.setItem(OPEN_KEY, JSON.stringify(open));
  } catch {
    // Private windows and blocked storage: the menu still works, it just forgets on reload.
  }
}

export interface SidebarProps {
  areas: readonly NavArea[];
  inboxCount: number;
  collapsed: boolean;
  onToggle: () => void;
  companyName: string;
  /** The activity feed needs its own permission. */
  showActivity: boolean;
}

/**
 * The left-side menu: every area, with its screens listed underneath. The group you are in is
 * always open; others open and close with their chevron and remember the choice on this device.
 * Below 1280px (or when collapsed) it becomes an icon rail and the area's screens move to the
 * pill row above the page.
 */
export function Sidebar({ areas, inboxCount, collapsed, onToggle, companyName, showActivity }: SidebarProps) {
  const pathname = usePathname();
  const search = useSearchParams();
  const activeArea = areaOf(pathname);
  const [open, setOpen] = useState<string[]>([...DEFAULT_OPEN]);

  // Stored choices are read after mount so server and client markup agree.
  useEffect(() => {
    const id = window.setTimeout(() => setOpen(readOpen()), 0);
    return () => window.clearTimeout(id);
  }, []);

  const toggleGroup = (id: string) => {
    setOpen((current) => {
      const next = current.includes(id) ? current.filter((value) => value !== id) : [...current, id];
      writeOpen(next);
      return next;
    });
  };

  const main = areas.filter((area) => area.id !== "settings");
  const settings = areas.find((area) => area.id === "settings");

  return (
    <aside className="side">
      <div className="side-panel">
        <div className="side-brand">
          <Link href="/today" className="side-brand-link" aria-label="Lamikraft One, go to Today">
            <Image src="/brand/lamikraft-mark.webp" alt="" width={36} height={36} className="side-mark" priority />
            <span className="side-wordmark side-rail-hide">
              <strong>Lamikraft One</strong>
              <span>{companyName}</span>
            </span>
          </Link>
          <button
            type="button"
            className="side-expander side-toggle side-rail-hide max-xl:hidden"
            onClick={onToggle}
            aria-label="Collapse the menu"
          >
            <Icon name="panelLeft" size={18} />
          </button>
        </div>

        <nav className="side-scroll" aria-label="Primary">
          <ul className="side-list">
            {main.map((area) => {
              const isActive = activeArea === area.id;
              const isOpen = isActive || open.includes(area.id);
              const current = isActive ? currentItem(area, pathname, search) : null;
              const onHub = isActive && pathname === String(area.href);
              return (
                <li key={area.id} className="side-group" data-open={isOpen}>
                  <div className="side-group-head">
                    <Link
                      href={area.href}
                      className="side-link"
                      data-active={isActive && (area.items.length === 0 || current === null)}
                      aria-current={onHub ? "page" : undefined}
                      title={area.label}
                    >
                      <Icon name={area.icon} size={20} />
                      <span className="side-link-text side-text">{area.label}</span>
                      {area.id === "inbox" && inboxCount > 0 ? (
                        <span className="side-count" aria-label={inboxCount === 1 ? "1 open item" : `${inboxCount} open items`}>
                          {inboxCount > 99 ? "99+" : inboxCount}
                        </span>
                      ) : null}
                    </Link>
                    {area.items.length > 0 ? (
                      <button
                        type="button"
                        className="side-expander side-rail-hide"
                        aria-expanded={isOpen}
                        aria-controls={`side-sub-${area.id}`}
                        aria-label={`${isOpen ? "Hide" : "Show"} ${area.label} screens`}
                        disabled={isActive}
                        onClick={() => toggleGroup(area.id)}
                      >
                        <Icon name="chevronRight" size={16} />
                      </button>
                    ) : null}
                  </div>
                  {area.items.length > 0 && isOpen ? (
                    <ul className="side-sub side-rail-hide" id={`side-sub-${area.id}`}>
                      {area.items.map((item) => (
                        <li key={item.label}>
                          <Link href={item.href} className="side-sublink" aria-current={current === item ? "page" : undefined}>
                            {item.label}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="side-foot">
          {showActivity ? (
            <Link href="/activity" className="side-link" aria-current={pathname === "/activity" ? "page" : undefined} title="Activity">
              <Icon name="activity" size={20} />
              <span className="side-link-text side-text">Activity</span>
            </Link>
          ) : null}
          {settings ? (
            <Link href={settings.href} className="side-link" data-active={activeArea === "settings"} title="Settings">
              <Icon name="settings" size={20} />
              <span className="side-link-text side-text">Settings</span>
            </Link>
          ) : null}
          {collapsed ? (
            <button type="button" className="side-link max-xl:hidden" onClick={onToggle} title="Expand the menu">
              <Icon name="panelLeft" size={20} />
              <span className="side-link-text side-text">Expand the menu</span>
            </button>
          ) : null}
        </div>
      </div>
    </aside>
  );
}
