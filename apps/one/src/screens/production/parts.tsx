"use client";

import type { CSSProperties, ReactNode } from "react";
import type { MasterSummary } from "@/features/production/api";
import { trimDecimalStr } from "@/lib/format/decimal";
import { formatDecimal } from "@/lib/format/money";
import { canAccessRoute, matchRoute } from "@/lib/routes";
import { useSession, useZone } from "@/lib/session/context";
import { riseIndex } from "~/lib/motion";
import { asRoute, type StatusLook } from "~/data/production";
import { Page, type Crumb } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Badge, ButtonLink, Code, Dash, Skeleton, SkeletonText, Tabs, type TabItem } from "~/ui";

/** Small shared parts of the Production screens. */

/** Inline style for a staggered entrance: `<li className="rise-plain" style={stagger(i)}>`. */
export const stagger = (index: number) => riseIndex(index) as CSSProperties;

export const OPERATIONS_CRUMB: Crumb = { label: "Operations", href: "/operations" };

export const PATHS = {
  workOrders: "/operations/production/work-orders",
  newWorkOrder: "/operations/production/work-orders/new",
  boms: "/operations/production/boms",
  routings: "/operations/production/routings",
  workCentres: "/operations/production/work-centres",
  capacity: "/operations/production/capacity",
  whatIf: "/operations/production/what-if",
} as const;

/** Whether this person may open an in-app path (checked against the shared route manifest), so links never lead to a refusal. */
export function useCanOpen(): (path: string) => boolean {
  const { permissionKeys } = useSession();
  return (path) => {
    const route = matchRoute(path.split("?")[0] ?? path);
    return route !== null && canAccessRoute(route, permissionKeys);
  };
}

export type ProductionScreen = "workOrders" | "boms" | "routings" | "workCentres" | "capacity" | "whatIf";

/**
 * The production screens side by side, one level, as link tabs under the page header. What-if is
 * offered only to people who may run simulations.
 */
export function ProductionNav({ current }: { current: ProductionScreen }) {
  const { permissionKeys } = useSession();
  const canOpen = useCanOpen();
  const all: { id: ProductionScreen; label: string; path: string; show: boolean }[] = [
    { id: "workOrders", label: "Work orders", path: PATHS.workOrders, show: true },
    { id: "boms", label: "Bills of materials", path: PATHS.boms, show: true },
    { id: "routings", label: "Routings", path: PATHS.routings, show: true },
    { id: "workCentres", label: "Work centres", path: PATHS.workCentres, show: true },
    { id: "capacity", label: "Capacity", path: PATHS.capacity, show: true },
    { id: "whatIf", label: "What-if", path: PATHS.whatIf, show: permissionKeys.has("production.simulation.run") },
  ];
  const tabs: TabItem[] = all.filter((tab) => tab.show && (tab.id === current || canOpen(tab.path))).map((tab) => ({ id: tab.id, label: tab.label, href: asRoute(tab.path) }));
  return <Tabs label="Production screens" tabs={tabs} selectedKey={current} className="rise" />;
}

export function StatusBadge({ look, size }: { look: StatusLook; size?: "sm" }) {
  return (
    <Badge tone={look.tone} dot size={size}>
      {look.label}
    </Badge>
  );
}

/** A work order that is waiting for material. The word carries the meaning; the colour repeats it. */
export function BlockedBadge({ size }: { size?: "sm" }) {
  return (
    <Badge tone="amber" icon="alert" size={size}>
      Waiting for material
    </Badge>
  );
}

/** A product as a cell: its name, with the product key beneath. */
export function ProductCell({ product, note }: { product: MasterSummary["product"]; note?: ReactNode }) {
  return (
    <span className="flex min-w-0 flex-col gap-0.5">
      <span className="t-label text-ink">{product.name}</span>
      <span className="t-caption text-ink-3">
        <Code className="t-code-sm">{product.product_key}</Code>
        {note ? <> · {note}</> : null}
      </span>
    </span>
  );
}

/** Minutes as people read them: "480 min", "22.5 min". */
export function Minutes({ value, className }: { value: string | number | null | undefined; className?: string }) {
  const { locale } = useZone();
  const text = value === null || value === undefined ? null : formatDecimal(trimDecimalStr(String(value)), { locale, maxFractionDigits: 2 });
  if (text === null) return <Dash className={className} />;
  return <span className={`lk-tnum whitespace-nowrap ${className ?? ""}`}>{text} min</span>;
}

/** A percentage the server sent as a decimal string: "85%". */
export function Percent({ value, className }: { value: string | null | undefined; className?: string }) {
  const { locale } = useZone();
  const text = value ? formatDecimal(trimDecimalStr(value), { locale, maxFractionDigits: 2 }) : null;
  if (text === null) return <Dash className={className} />;
  return <span className={`lk-tnum whitespace-nowrap ${className ?? ""}`}>{text}%</span>;
}

export function versionLabel(versionNo: number): string {
  return `Version ${versionNo}`;
}

/** The record header's shape while a record loads. */
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

/** A record that could not load: what happened, a retry, and the way back to its list. */
export function RecordFailed({ error, what, onRetry, backHref, backLabel }: { error: unknown; what: string; onRetry: () => void; backHref: string; backLabel: string }) {
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

/** A titled block inside a record view: heading, one quiet line, then the content. */
export function ViewHeading({ title, text, action }: { title: string; text?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-wrap items-end justify-between gap-3">
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="t-h3">{title}</h2>
        {text ? <p className="t-body-sm text-ink-3">{text}</p> : null}
      </div>
      {action}
    </div>
  );
}
