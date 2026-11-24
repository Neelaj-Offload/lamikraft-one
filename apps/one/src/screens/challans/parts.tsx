"use client";

import type { CSSProperties } from "react";
import { cx } from "@/lib/cx";
import type { QuantityByUnit } from "@/features/challans/types";
import { challanStatus } from "~/data/challans";
import { riseIndex } from "~/lib/motion";
import { Badge, Dash, Qty } from "~/ui";

/** Small shared parts of the challan screens. */

/** Inline style for a staggered entrance: `<li className="rise-plain" style={stagger(i)}>`. */
export const stagger = (index: number) => riseIndex(index) as CSSProperties;

export function StatusBadge({ status, size }: { status: string; size?: "sm" }) {
  const look = challanStatus(status);
  return (
    <Badge tone={look.tone} dot size={size}>
      {look.label}
    </Badge>
  );
}

/**
 * Totals per unit, as the server worked them out ("12 sheets · 2 pcs"). Different units are never
 * added together, here or anywhere in the browser.
 */
export function QuantityList({ value, className }: { value: QuantityByUnit; className?: string }) {
  const entries = Object.entries(value);
  if (entries.length === 0) return <Dash className={className} />;
  return (
    <span className={cx("inline-flex flex-wrap gap-x-1.5", className)}>
      {entries.map(([unit, quantity], index) => (
        <span key={unit} className="inline-flex items-center gap-1.5 whitespace-nowrap">
          {index > 0 ? <span aria-hidden="true">·</span> : null}
          <Qty value={{ value: quantity, uom: unit }} />
        </span>
      ))}
    </span>
  );
}
