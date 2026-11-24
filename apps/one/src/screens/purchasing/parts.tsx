"use client";

import type { Route } from "next";
import type { CSSProperties, ReactNode } from "react";
import { riseIndex } from "~/lib/motion";
import { Page } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Badge, Banner, ButtonLink, PageSummary, Pagination, SegmentedLinks, Skeleton, SkeletonText } from "~/ui";
import type { StatusLook } from "./labels";

/** Small shared parts of the purchasing and quality screens. */

/** Inline style for a staggered entrance: `<div className="rise" style={stagger(i)}>`. */
export const stagger = (index: number) => riseIndex(index) as CSSProperties;

export function StatusBadge({ look, size }: { look: StatusLook; size?: "sm" }) {
  return (
    <Badge tone={look.tone} dot size={size}>
      {look.label}
    </Badge>
  );
}

/**
 * Purchasing is one item in the menu and three lists: what is asked for, what is ordered, what
 * arrived. This switch moves between them and reads in the order the work happens.
 */
export function PurchasingSwitch({ current }: { current: "requisitions" | "orders" | "receipts" }) {
  return (
    <SegmentedLinks
      label="Purchasing lists"
      value={current}
      className="max-w-full self-start"
      options={[
        { value: "requisitions", label: "Requisitions", href: "/operations/purchasing/requisitions" },
        { value: "orders", label: "Purchase orders", href: "/operations/purchasing/orders" },
        { value: "receipts", label: "Goods receipts", href: "/operations/purchasing/receipts" },
      ]}
    />
  );
}

/** The cell that names a line: its number, the product and the product's key. */
export function LineName({ lineNo, name, productKey, note }: { lineNo: number; name: string; productKey: string; note?: ReactNode }) {
  return (
    <span className="flex min-w-0 items-start gap-3">
      <span className="t-caption lk-tnum mt-0.5 w-5 flex-none text-right text-ink-3">{lineNo}</span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="t-label text-ink">{name}</span>
        <span className="t-caption text-ink-3">
          <span className="lk-mono">{productKey}</span>
          {note ? <> · {note}</> : null}
        </span>
      </span>
    </span>
  );
}

/** "1–25 of 132 purchase orders" with page links once there is more than one page. */
export function ListFooter({
  page,
  noun,
  label,
  hrefFor,
  pageSize,
}: {
  page: { items: readonly unknown[]; total: number; limit: number; offset: number } | undefined;
  noun: string;
  label: string;
  hrefFor: (offset: number) => Route;
  pageSize: number;
}) {
  if (!page || page.total === 0) return null;
  const limit = page.limit || pageSize;
  return (
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
      <PageSummary from={page.offset + 1} to={page.offset + page.items.length} total={page.total} noun={noun} />
      {page.total > limit ? (
        <Pagination label={label} page={Math.floor(page.offset / limit) + 1} pages={Math.ceil(page.total / limit)} hrefFor={(n) => hrefFor((n - 1) * limit)} />
      ) : null}
    </div>
  );
}

/** The frame of a record while it loads: a header-shaped skeleton and a body block. */
export function RecordLoading({ label }: { label: string }) {
  return (
    <Page>
      <div className="lk-glass record-head" role="status" aria-label={label}>
        <Skeleton width="160px" height={14} />
        <Skeleton width="45%" height={32} />
        <SkeletonText lines={2} />
      </div>
      <LoadingBlock lines={6} label={label} />
    </Page>
  );
}

/** A record that could not load (missing, outside your scope, or a failed request), with the way back. */
export function RecordFailure({ error, what, retry, backHref, backLabel }: { error: unknown; what: string; retry: () => void; backHref: Route; backLabel: string }) {
  return (
    <Page>
      <ErrorBlock error={error} what={what} onRetry={retry} />
      <div>
        <ButtonLink href={backHref} variant="secondary" iconLeft="arrowLeft">
          {backLabel}
        </ButtonLink>
      </div>
    </Page>
  );
}

export function OfflineBanner({ what }: { what: string }) {
  return (
    <Banner tone="amber" title="You are offline.">
      You can read {what}. Actions work again once the connection is back.
    </Banner>
  );
}

/**
 * For dialogs that hold themselves open while a command runs: the command hooks resolve to null on
 * failure (and raise the toast), so this turns that null into a rejection and the dialog stays open.
 */
export async function must<T>(result: Promise<T | null>): Promise<void> {
  if ((await result) === null) throw new Error("The command did not go through");
}
