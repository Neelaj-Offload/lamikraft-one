"use client";

import type { Route } from "next";
import type { ReactNode } from "react";
import type { Schemas } from "./types";
import { asRoute } from "~/data/stock";
import { Page } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Banner, ButtonLink, Code, SegmentedLinks, Skeleton, SkeletonText } from "~/ui";
import { locationType } from "./labels";

/** Small shared parts of the Stock screens. */

/**
 * The three ledgers of stock sit side by side: what is on hand, what moved, and the counts that
 * check both. Only "Stock" is in the left menu, so this row is how the other two are reached.
 */
export function StockViews({ current }: { current: "stock" | "categories" | "factory-orders" | "movements" | "stock-takes" }) {
  return (
    <SegmentedLinks
      label="Stock views"
      value={current}
      glass
      className="self-start"
      options={[
        { value: "stock", label: "On hand", href: "/operations/inventory" },
        { value: "categories", label: "By category", href: "/operations/inventory/categories" as Route },
        { value: "factory-orders", label: "Factory orders", href: "/operations/inventory/factory-orders" as Route },
        { value: "movements", label: "Movements", href: "/operations/inventory/movements" },
        { value: "stock-takes", label: "Stock takes", href: "/operations/inventory/stock-takes" },
      ]}
    />
  );
}

/** A product in a table: its key in mono, its name (or another caption) underneath. */
export function ProductCell({ product, caption }: { product: Schemas["ProductRef"]; caption?: ReactNode }) {
  const second = caption === undefined ? product.name : caption;
  return (
    <span className="flex min-w-0 flex-col gap-0.5">
      <Code>{product.product_key}</Code>
      {second ? (
        <span className="t-caption truncate text-ink-3" title={typeof second === "string" ? second : undefined}>
          {second}
        </span>
      ) : null}
    </span>
  );
}

/** A location: its code, and what kind of place it is. */
export function LocationCell({ location }: { location: Schemas["LocationRef"] }) {
  return (
    <span className="flex min-w-0 flex-col gap-0.5">
      <span className="lk-mono text-ink">{location.code}</span>
      <span className="t-caption text-ink-3">{locationType(location.location_type)}</span>
    </span>
  );
}

/** The header-shaped placeholder a record shows while it loads. */
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

/** A record that could not load: what happened, a retry, and the way back. */
export function RecordError({ error, what, onRetry, backHref, backLabel }: { error: unknown; what: string; onRetry: () => void; backHref: string; backLabel: string }) {
  return (
    <Page>
      <ErrorBlock error={error} what={what} onRetry={onRetry} />
      <div>
        <ButtonLink href={asRoute(backHref)} variant="secondary" iconLeft="arrowLeft">
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
