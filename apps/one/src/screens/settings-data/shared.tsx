import type { Route } from "next";
import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import { formatCount } from "@/lib/format/money";
import type { Crumb } from "~/shell/page";
import { Badge, Icon, PageSummary, Pagination, type IconName, type Tone } from "~/ui";

/** Small parts the settings data screens share. No directive: usable from server and client files. */

export const SETTINGS_CRUMBS: readonly Crumb[] = [{ label: "Settings", href: "/settings" }];

export const asRoute = (href: string) => href as Route;

/** An identifier people compare or copy: wraps anywhere instead of pushing the layout wide. */
export function Mono({ children, title, className }: { children: ReactNode; title?: string; className?: string }) {
  return (
    <span title={title} className={cx("t-code-sm lk-mono [overflow-wrap:anywhere]", className)}>
      {children}
    </span>
  );
}

export function Quiet({ children }: { children: ReactNode }) {
  return <span className="text-ink-3">{children}</span>;
}

/** The first twelve characters of a checksum; the full value goes in the element's title. */
export function shortSha(sha: string | null | undefined): string | null {
  return sha ? `${sha.slice(0, 12)}…` : null;
}

/** "products_master" becomes "Products master": names from the legacy export are shown, not translated. */
export function entityLabel(entity: string): string {
  const text = entity.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function bytesText(bytes: number | null | undefined, locale: string): string | null {
  if (bytes === null || bytes === undefined) return null;
  if (bytes < 1024) return `${formatCount(bytes, locale)} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toLocaleString(locale, { maximumFractionDigits: 1 })} KB`;
  return `${(kb / 1024).toLocaleString(locale, { maximumFractionDigits: 1 })} MB`;
}

export interface StatusLook {
  label: string;
  tone: Tone;
  icon?: IconName;
}

/** A status as a word with a dot; the colour only reinforces the word. */
export function StatusBadge({ look, size }: { look: StatusLook; size?: "sm" }) {
  return (
    <Badge tone={look.tone} size={size} dot={!look.icon} icon={look.icon}>
      {look.label}
    </Badge>
  );
}

export function lookOf(map: Record<string, StatusLook>, status: string): StatusLook {
  return map[status] ?? { label: entityLabel(status), tone: "neutral" };
}

interface PageLike {
  total: number;
  limit: number;
  offset: number;
  items: readonly unknown[];
}

type PagerProps = { data: PageLike; noun: string; label: string; fallbackLimit: number } & (
  | { hrefFor: (offset: number) => Route; onOffset?: undefined }
  | { onOffset: (offset: number) => void; hrefFor?: undefined }
);

/** "1–25 of 132 imports" with page links (URL state) or page buttons (state held by the screen). */
export function OffsetPager({ data, noun, label, fallbackLimit, hrefFor, onOffset }: PagerProps) {
  if (data.total === 0) return null;
  const limit = data.limit || fallbackLimit;
  const page = Math.floor(data.offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(data.total / limit));
  return (
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
      <PageSummary from={data.offset + 1} to={data.offset + data.items.length} total={data.total} noun={noun} />
      {pages <= 1 ? null : hrefFor ? (
        <Pagination label={label} page={page} pages={pages} hrefFor={(target) => hrefFor((target - 1) * limit)} />
      ) : (
        <Pagination label={label} page={page} pages={pages} onChange={(target) => onOffset((target - 1) * limit)} />
      )}
    </div>
  );
}

/** A command the person runs on the server, set apart so it can be read and copied exactly. */
export function ServerCommand({ children }: { children: string }) {
  return (
    <code className="t-code-sm lk-mono inline-flex max-w-full items-center gap-2 rounded-sm border border-line bg-surface px-2 py-1 select-all [overflow-wrap:anywhere]">
      <Icon name="command" size={14} className="flex-none text-ink-3" />
      {children}
    </code>
  );
}

/** A labelled group inside a panel: an overline, then its content. */
export function Block({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <div role="group" aria-label={title} className={cx("flex min-w-0 flex-col gap-3", className)}>
      <p className="t-overline text-ink-3">{title}</p>
      {children}
    </div>
  );
}

/** UI copy says "quotation"; labels that come from the old settings model still say "quote". */
export function sayQuotation(text: string): string {
  return text.replace(/\bQuotes\b/g, "Quotations").replace(/\bquotes\b/g, "quotations").replace(/\bQuote\b/g, "Quotation").replace(/\bquote\b/g, "quotation");
}
