"use client";

import type { ReactNode } from "react";
import {
  Link as RacLink,
  Tab as RacTab,
  TabList as RacTabList,
  TabPanel as RacTabPanel,
  Tabs as RacTabs,
  type TabsProps as RacTabsProps,
} from "react-aria-components";
import { cx } from "@/lib/cx";
import { formatCount } from "@/lib/format/money";

/**
 * Two kinds of tabs:
 * - `NavTabs` for views that are URLs (Inbox tabs, detail-screen sections): a <nav> of links
 *   with aria-current (frontend_verification §4 "Tabs are links"), so each view is
 *   deep-linkable and works with the back button;
 * - `Tabs` for in-page panels that are not separate URLs (an ARIA tablist).
 */

const tabClasses =
  "relative inline-flex min-h-11 items-center gap-2 px-3 text-[15px] font-medium whitespace-nowrap text-ink-muted outline-hidden focus-visible:focus-ring-inset data-[focus-visible]:focus-ring-inset " +
  "hover:text-ink pointer-fine:min-h-10 " +
  "after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-transparent";

export interface NavTab {
  id: string;
  label: string;
  href: string;
  /** A real count from the server; omitted (not zero) when unknown. */
  count?: number | null;
}

export function NavTabs({ label, tabs, currentId, locale }: { label: string; tabs: readonly NavTab[]; currentId: string; locale?: string }) {
  return (
    <nav aria-label={label} className="-mx-4 overflow-x-auto border-b px-4 md:mx-0 md:px-0">
      <ul className="flex gap-1">
        {tabs.map((tab) => {
          const current = tab.id === currentId;
          return (
            <li key={tab.id} className="shrink-0">
              <RacLink
                href={tab.href}
                aria-current={current ? "page" : undefined}
                className={cx(tabClasses, current && "font-semibold text-ink after:bg-forest")}
              >
                {tab.label}
                {typeof tab.count === "number" ? (
                  <span className="rounded-sm bg-surface-sunken px-1.5 text-xs font-semibold tabular text-ink-muted">
                    {formatCount(tab.count, locale)}
                  </span>
                ) : null}
              </RacLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export interface PanelTab {
  id: string;
  label: string;
  content: ReactNode;
}

export type TabsProps = Omit<RacTabsProps, "className" | "children"> & {
  label: string;
  tabs: readonly PanelTab[];
  className?: string;
};

export function Tabs({ label, tabs, className, ...props }: TabsProps) {
  return (
    <RacTabs {...props} className={cx("flex flex-col gap-4", className)}>
      <RacTabList aria-label={label} items={tabs} className="flex gap-1 overflow-x-auto border-b">
        {(tab) => (
          <RacTab id={tab.id} className={cx(tabClasses, "cursor-default selected:font-semibold selected:text-ink selected:after:bg-forest")}>
            {tab.label}
          </RacTab>
        )}
      </RacTabList>
      {tabs.map((tab) => (
        <RacTabPanel key={tab.id} id={tab.id} className="rounded-md outline-hidden focus-visible:focus-ring data-[focus-visible]:focus-ring">
          {tab.content}
        </RacTabPanel>
      ))}
    </RacTabs>
  );
}
