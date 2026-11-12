import type { Route } from "next";
import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import { Breadcrumb } from "~/ui/breadcrumb";

/**
 * Page frames. Every screen is built from these so headers, spacing and entrances are the same
 * everywhere. One screen, one job: if a page needs a second header it is two screens.
 *
 *   <Page>                         the column; width "default" | "reading" | "narrow"
 *     <PageHeader … />             breadcrumb, eyebrow, title, one-line lead, actions
 *     <PageSection title="…">      a titled block inside the page
 *     <Split main={…} aside={…} /> work on the left, context on the right
 */

export interface Crumb {
  label: ReactNode;
  href?: Route;
}

export function Page({
  children,
  width = "default",
  className,
}: {
  children: ReactNode;
  width?: "default" | "reading" | "narrow";
  className?: string;
}) {
  return (
    <div className={cx("page", className)} data-width={width}>
      {children}
    </div>
  );
}

export interface PageHeaderProps {
  /** Trail back up the hierarchy; omit on top-level hubs. */
  breadcrumb?: readonly Crumb[];
  /** Short uppercase label above the title (the area, a count, a date). */
  eyebrow?: ReactNode;
  title: ReactNode;
  /** One sentence that says what this screen is for or what state it is in. */
  lead?: ReactNode;
  /** The primary action first, then at most two others; the rest go in a menu. */
  actions?: ReactNode;
  /** Hubs and heroes speak in the serif display face; working screens use the sans h1. */
  display?: boolean;
  /** Small things beside the title: a status badge, a count. */
  meta?: ReactNode;
  className?: string;
}

export function PageHeader({ breadcrumb, eyebrow, title, lead, actions, display = false, meta, className }: PageHeaderProps) {
  return (
    <header className={cx("page-head rise", className)}>
      {breadcrumb && breadcrumb.length > 0 ? <Breadcrumb items={[...breadcrumb]} /> : null}
      <div className="page-head-row">
        <div className="page-head-text">
          {eyebrow ? <p className="t-overline page-eyebrow">{eyebrow}</p> : null}
          <div className="flex flex-wrap items-center gap-3">
            <h1 className={display ? "t-display-md" : "t-h1"}>{title}</h1>
            {meta}
          </div>
          {lead ? <p className={cx(display ? "t-body-lg" : "t-body", "page-lead")}>{lead}</p> : null}
        </div>
        {actions ? <div className="page-head-actions">{actions}</div> : null}
      </div>
    </header>
  );
}

export function PageSection({
  title,
  description,
  action,
  children,
  className,
  index,
}: {
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Position among sibling sections, for the staggered entrance (0-based). */
  index?: number;
}) {
  return (
    <section className={cx("stack rise", className)} style={index !== undefined ? ({ "--i": Math.min(index + 1, 8) } as React.CSSProperties) : undefined}>
      {title || action ? (
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            {title ? <h2 className="t-h3">{title}</h2> : null}
            {description ? <p className="t-body-sm text-ink-3">{description}</p> : null}
          </div>
          {action}
        </div>
      ) : null}
      {children}
    </section>
  );
}

/** Work on the left, context on the right; a single column below 1024px (aside follows main). */
export function Split({ main, aside, wideAside = false, className }: { main: ReactNode; aside: ReactNode; wideAside?: boolean; className?: string }) {
  return (
    <div className={cx("split", className)} data-aside={wideAside ? "wide" : undefined}>
      <div className="stack">{main}</div>
      <aside className="stack">{aside}</aside>
    </div>
  );
}

/**
 * The header of a single record (a quotation, an order, a customer): who or what it is, its
 * state, the few facts you always need, and the next action. Views of the record sit below as tabs.
 */
export function RecordHeader({
  breadcrumb,
  code,
  title,
  status,
  lead,
  facts,
  actions,
  children,
}: {
  breadcrumb: readonly Crumb[];
  /** The document number or code, set in mono above the title. */
  code?: ReactNode;
  title: ReactNode;
  /** A Badge (or two) describing state. */
  status?: ReactNode;
  lead?: ReactNode;
  /** A FactStrip with the three to five facts that matter at a glance. */
  facts?: ReactNode;
  actions?: ReactNode;
  /** Tabs or a segmented control for the record's views. */
  children?: ReactNode;
}) {
  return (
    <header className="stack rise">
      <Breadcrumb items={[...breadcrumb]} />
      <div className="lk-glass record-head">
        <div className="record-head-top">
          <div className="record-head-id">
            {code ? <p className="t-code-sm lk-mono text-ink-3">{code}</p> : null}
            <div className="record-head-title">
              <h1 className="t-h1">{title}</h1>
              {status}
            </div>
            {lead ? <p className="t-body text-ink-2">{lead}</p> : null}
          </div>
          {actions ? <div className="page-head-actions">{actions}</div> : null}
        </div>
        {facts}
      </div>
      {children}
    </header>
  );
}
