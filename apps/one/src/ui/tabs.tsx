"use client";

import type { Route } from "next";
import NextLink from "next/link";
import { useRef, useState, type ReactNode } from "react";
import { Tab as RacTab, TabList as RacTabList, TabPanel as RacTabPanel, Tabs as RacTabs } from "react-aria-components";
import { cx } from "@/lib/cx";
import { formatCount } from "@/lib/format/money";
import { useSlidingMark } from "./segmented";

export interface TabItem {
  id: string;
  label: ReactNode;
  /** A real count from the server; left out (not zero) when unknown. */
  count?: number;
  /** Makes the tab a link. Give every tab an href, or none. */
  href?: Route;
}

export interface TabsProps {
  tabs: TabItem[];
  /** The selected tab. Required for link tabs, where the URL decides. */
  selectedKey?: string;
  defaultSelectedKey?: string;
  onSelectionChange?: (id: string) => void;
  variant?: "underline" | "pills";
  /** Names the tab set for assistive technology. */
  label: string;
  className?: string;
  /** In-page tabs: one `TabPanel` per tab. Link tabs: whatever the current route shows. */
  children?: ReactNode;
}

function TabContent({ tab }: { tab: TabItem }) {
  return (
    <>
      {tab.label}
      {tab.count === undefined ? null : <span className="lk-tab-count">{formatCount(tab.count)}</span>}
    </>
  );
}

/**
 * Two kinds of tabs behind one look:
 *  - in-page panels (no `href`): an ARIA tablist; arrow keys move between tabs, each tab shows
 *    its `TabPanel`;
 *  - views that are URLs (`href` on the tabs): a navigation of links with the current one marked,
 *    so every view is deep-linkable and the back button works.
 * The gold ink bar slides to the selected tab; the row scrolls sideways when it does not fit.
 */
export function Tabs({
  tabs,
  selectedKey,
  defaultSelectedKey,
  onSelectionChange,
  variant = "underline",
  label,
  className,
  children,
}: TabsProps) {
  const [internal, setInternal] = useState(defaultSelectedKey ?? tabs[0]?.id);
  const current = selectedKey ?? internal;
  const linkMode = tabs.some((tab) => tab.href !== undefined);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inkRef = useRef<HTMLSpanElement>(null);
  useSlidingMark(
    scrollRef,
    inkRef,
    linkMode ? '[aria-current="page"]' : "[data-selected]",
    `${current}|${tabs.map((tab) => tab.id).join("|")}`,
    true,
  );

  const listClass = cx("lk-tabs", variant === "pills" && "lk-tabs-pills");
  const ink = variant === "underline" ? <span ref={inkRef} className="lk-tabs-ink" aria-hidden="true" /> : null;

  if (linkMode) {
    return (
      <div className={cx("lk-tabs-root", className)}>
        <nav aria-label={label}>
          <div ref={scrollRef} className="lk-tabs-scroll">
            <div className={listClass}>
              {tabs.map((tab) => {
                const selected = tab.id === current;
                return tab.href === undefined ? (
                  <span key={tab.id} className="lk-tab" aria-current={selected ? "page" : undefined} data-disabled={selected ? undefined : true}>
                    <TabContent tab={tab} />
                  </span>
                ) : (
                  <NextLink key={tab.id} href={tab.href} className="lk-tab" aria-current={selected ? "page" : undefined}>
                    <TabContent tab={tab} />
                  </NextLink>
                );
              })}
            </div>
            {ink}
          </div>
        </nav>
        {children}
      </div>
    );
  }

  return (
    <RacTabs
      selectedKey={current}
      onSelectionChange={(key) => {
        const id = String(key);
        setInternal(id);
        onSelectionChange?.(id);
      }}
      className={cx("lk-tabs-root", className)}
    >
      <div ref={scrollRef} className="lk-tabs-scroll">
        <RacTabList aria-label={label} className={listClass}>
          {tabs.map((tab) => (
            <RacTab key={tab.id} id={tab.id} className="lk-tab">
              <TabContent tab={tab} />
            </RacTab>
          ))}
        </RacTabList>
        {ink}
      </div>
      {children}
    </RacTabs>
  );
}

export interface TabPanelProps {
  /** The `id` of the tab this panel belongs to. */
  id: string;
  className?: string;
  children: ReactNode;
}

/** The content of one in-page tab; only the selected panel is rendered. */
export function TabPanel({ id, className, children }: TabPanelProps) {
  return (
    <RacTabPanel id={id} className={cx("lk-tabpanel", className)}>
      {children}
    </RacTabPanel>
  );
}
