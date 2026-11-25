"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Icon } from "~/ui/icon";
import { areaOf, currentItem, type NavArea } from "./nav";

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
 * The left-side menu. It is flat: every screen is a top-level link with its own icon, and the
 * links are categorised under plain headings (Sales, Products, Operations, Finance). Nothing
 * expands, collapses or nests.
 *
 * Below 1280px, or when collapsed, it becomes an icon rail showing one icon per group (its first
 * screen); the group's other screens are then offered by the pill row above the page.
 */
export function Sidebar({ areas, inboxCount, collapsed, onToggle, companyName, showActivity }: SidebarProps) {
  const pathname = usePathname();
  const search = useSearchParams();
  const activeArea = areaOf(pathname);

  const single = areas.filter((area) => area.items.length === 0 && area.id !== "settings");
  const groups = areas.filter((area) => area.items.length > 0);
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
          <button type="button" className="side-iconbtn side-toggle side-rail-hide max-xl:hidden" onClick={onToggle} aria-label="Collapse the menu">
            <Icon name="panelLeft" size={18} />
          </button>
        </div>

        <nav className="side-scroll" aria-label="Primary">
          <ul className="side-list">
            {single.map((area) => (
              <li key={area.id}>
                <Link href={area.href} className="side-link" data-active={activeArea === area.id} aria-current={pathname === String(area.href) ? "page" : undefined} title={area.label}>
                  <Icon name={area.icon} size={20} />
                  <span className="side-link-text side-text">{area.label}</span>
                  {area.id === "inbox" && inboxCount > 0 ? (
                    <span className="side-count" aria-label={inboxCount === 1 ? "1 open item" : `${inboxCount} open items`}>
                      {inboxCount > 99 ? "99+" : inboxCount}
                    </span>
                  ) : null}
                </Link>
              </li>
            ))}
          </ul>

          {groups.map((area) => {
            const isActive = activeArea === area.id;
            const current = isActive ? currentItem(area, pathname, search) : null;
            const headingId = `side-group-${area.id}`;
            return (
              <section key={area.id} className="side-section" aria-labelledby={headingId}>
                <h2 id={headingId} className="t-overline side-label side-text">
                  {area.label}
                </h2>
                <ul className="side-list">
                  {area.items.map((item, index) => (
                    <li key={item.label} className={index === 0 ? undefined : "side-rail-hide"}>
                      <Link
                        href={item.href}
                        className="side-link"
                        aria-current={current === item ? "page" : undefined}
                        // In rail mode the first screen stands for its whole group.
                        data-rail-active={index === 0 && isActive}
                        title={index === 0 ? area.label : item.label}
                      >
                        <Icon name={item.icon} size={20} />
                        <span className="side-link-text side-text">{item.label}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
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
