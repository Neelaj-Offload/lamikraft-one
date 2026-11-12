import type { Route } from "next";
import NextLink from "next/link";
import { cx } from "@/lib/cx";
import { formatCount } from "@/lib/format/money";
import { Icon } from "./icon";

type PageItem = number | "gap-before" | "gap-after";

/** 1 … 4 5 6 … 20: first, last, the current page and its neighbours; every page up to seven. */
function pageItems(page: number, pages: number): PageItem[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, index) => index + 1);
  const items: PageItem[] = [1];
  if (page > 3) items.push("gap-before");
  for (let p = Math.max(2, page - 1); p <= Math.min(pages - 1, page + 1); p++) items.push(p);
  if (page < pages - 2) items.push("gap-after");
  items.push(pages);
  return items;
}

interface PaginationBase {
  /** The current page, starting at 1. */
  page: number;
  /** How many pages there are. */
  pages: number;
  /** Names the navigation when a screen has more than one ("Quotations pages"). */
  label?: string;
  className?: string;
}

export type PaginationProps = PaginationBase &
  (
    | { /** Link mode: each page is a URL (works in a server component). */ hrefFor: (page: number) => Route; onChange?: undefined }
    | { /** Button mode: the caller holds the page in state. */ onChange: (page: number) => void; hrefFor?: undefined }
  );

/**
 * Page navigation. No directive on purpose: with `hrefFor` it renders on the server; with
 * `onChange` it is rendered by a client component.
 */
export function Pagination({ page, pages, hrefFor, onChange, label = "Pagination", className }: PaginationProps) {
  if (pages < 1) return null;
  const current = Math.min(Math.max(1, Math.trunc(page)), pages);
  const items = pageItems(current, pages);
  const edges = [
    { key: "previous", target: current - 1, name: "Previous page", icon: "chevronLeft", rel: "prev", enabled: current > 1 },
    { key: "next", target: current + 1, name: "Next page", icon: "chevronRight", rel: "next", enabled: current < pages },
  ] as const;

  const edge = (which: (typeof edges)[number]) => {
    const glyph = <Icon name={which.icon} size={16} />;
    if (hrefFor) {
      return which.enabled ? (
        <NextLink key={which.key} href={hrefFor(which.target)} rel={which.rel} className="lk-pager-btn" aria-label={which.name}>
          {glyph}
        </NextLink>
      ) : (
        <span key={which.key} role="link" aria-disabled="true" aria-label={which.name} className="lk-pager-btn">
          {glyph}
        </span>
      );
    }
    return (
      <button
        key={which.key}
        type="button"
        className="lk-pager-btn"
        aria-label={which.name}
        disabled={!which.enabled}
        onClick={() => onChange?.(which.target)}
      >
        {glyph}
      </button>
    );
  };

  return (
    <nav className={cx("lk-pager", className)} aria-label={label}>
      {edge(edges[0])}
      {items.map((item) => {
        if (typeof item !== "number") {
          return (
            <span key={item} className="lk-pager-ellipsis" aria-hidden="true">
              …
            </span>
          );
        }
        const selected = item === current;
        const name = `Page ${formatCount(item)}`;
        return hrefFor ? (
          <NextLink key={item} href={hrefFor(item)} className="lk-pager-btn" aria-label={name} aria-current={selected ? "page" : undefined}>
            {formatCount(item)}
          </NextLink>
        ) : (
          <button
            key={item}
            type="button"
            className="lk-pager-btn"
            aria-label={name}
            aria-current={selected ? "page" : undefined}
            onClick={() => onChange?.(item)}
          >
            {formatCount(item)}
          </button>
        );
      })}
      {edge(edges[1])}
    </nav>
  );
}

export interface PageSummaryProps {
  /** Position of the first row shown, starting at 1. */
  from: number;
  to: number;
  total: number;
  /** The plural noun for what is listed: "quotations". */
  noun: string;
  className?: string;
}

/** "1–25 of 132 quotations", in tabular numerals so it does not jitter between pages. */
export function PageSummary({ from, to, total, noun, className }: PageSummaryProps) {
  return (
    <p className={cx("lk-page-summary", className)}>
      {total === 0 ? `No ${noun}` : `${formatCount(from)}–${formatCount(to)} of ${formatCount(total)} ${noun}`}
    </p>
  );
}
