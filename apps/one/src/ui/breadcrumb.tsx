import type { Route } from "next";
import NextLink from "next/link";
import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import { Icon } from "./icon";

export interface BreadcrumbItem {
  label: ReactNode;
  /** Where the ancestor lives. The last item is the current page and never links. */
  href?: Route;
}

export interface BreadcrumbProps {
  /** From the top of the hierarchy down to the current page. */
  items: BreadcrumbItem[];
  className?: string;
}

/**
 * The path to the current page. On phones the trail collapses to one "back to parent" link
 * (the nearest ancestor that has an href), which is what a thumb actually needs there.
 */
export function Breadcrumb({ items, className }: BreadcrumbProps) {
  const parent = items.slice(0, -1).findLast((item) => item.href !== undefined);
  return (
    <nav aria-label="Breadcrumb" className={cx("lk-crumbs-nav", parent && "lk-crumbs-collapsible", className)}>
      {parent?.href ? (
        <NextLink href={parent.href} className="lk-crumbs-back">
          <Icon name="chevronLeft" size={16} />
          <span className="lk-crumbs-back-label">
            <span className="lk-sr-only">Back to </span>
            {parent.label}
          </span>
        </NextLink>
      ) : null}
      <ol className="lk-crumbs">
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <li key={index} className="lk-crumbs-item">
              {last ? (
                <span className="lk-crumbs-current" aria-current="page">
                  {item.label}
                </span>
              ) : item.href ? (
                <NextLink href={item.href}>{item.label}</NextLink>
              ) : (
                <span>{item.label}</span>
              )}
              {last ? null : <Icon name="chevronRight" className="lk-crumbs-sep" size={14} />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
