"use client";

import type { CSSProperties, ReactNode } from "react";
import type { PlanSummary } from "@/features/cutting/types";
import { trimDecimalStr } from "@/lib/format/decimal";
import { formatDecimal } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { planStatus } from "~/data/cutting";
import { riseIndex } from "~/lib/motion";
import { Badge, Dash } from "~/ui";

/** Small shared parts of the cut plan screens. */

/** Inline style for a staggered entrance: `<li className="rise-plain" style={stagger(i)}>`. */
export const stagger = (index: number) => riseIndex(index) as CSSProperties;

export function PlanStatusBadge({ status, size }: { status: string; size?: "sm" }) {
  const look = planStatus(status);
  return (
    <Badge tone={look.tone} dot size={size}>
      {look.label}
    </Badge>
  );
}

/** What still needs a person on this plan: a calculation in flight, changed inputs, boards to measure. */
export function PlanFlags({ plan }: { plan: Pick<PlanSummary, "calc_status" | "stale" | "requires_physical_verification" | "verified"> }) {
  const calculating = plan.calc_status === "queued" || plan.calc_status === "running";
  const failed = plan.calc_status === "failed";
  const verify = plan.requires_physical_verification && !plan.verified;
  if (!calculating && !failed && !plan.stale && !verify) return null;
  return (
    <>
      {calculating ? (
        <Badge tone="cobalt" size="sm" icon="timer">
          Calculating
        </Badge>
      ) : null}
      {failed ? (
        <Badge tone="ember" size="sm" icon="alert">
          Calculation failed
        </Badge>
      ) : null}
      {plan.stale ? (
        <Badge tone="amber" size="sm" icon="refresh">
          Inputs changed
        </Badge>
      ) : null}
      {verify ? (
        <Badge tone="amber" size="sm" icon="ruler">
          Measure boards
        </Badge>
      ) : null}
    </>
  );
}

/** A percentage the server sent as a decimal string ("86.4321" becomes "86.43%"). */
export function Pct({ value, className }: { value: string | null | undefined; className?: string }) {
  const { locale } = useZone();
  const text = formatDecimal(value, { locale, maxFractionDigits: 2 });
  if (text === null) return <Dash className={className} />;
  return <span className={`lk-tnum whitespace-nowrap ${className ?? ""}`}>{text}%</span>;
}

/** A decimal string in the person's locale with a quiet unit after it ("3.482 m²"). */
export function Measure({ value, unit, digits = 3, className }: { value: string | null | undefined; unit: string; digits?: number; className?: string }) {
  const { locale } = useZone();
  const text = formatDecimal(value, { locale, maxFractionDigits: digits });
  if (text === null) return <Dash className={className} />;
  return (
    <span className={`lk-tnum whitespace-nowrap ${className ?? ""}`}>
      {text} {unit}
    </span>
  );
}

/** Millimetres as the saw reads them: no trailing zeros, no grouping ("2440", "18.5"). */
export const mm = (value: string) => trimDecimalStr(value);

/** "2440 × 1220 mm", length first (the grain runs along the length). */
export function Size({ length, width, className }: { length: string; width: string; className?: string }) {
  return (
    <span className={`lk-tnum whitespace-nowrap ${className ?? ""}`}>
      {mm(length)} × {mm(width)} mm
    </span>
  );
}

/** One figure with its label, for a row of results inside a panel. */
export function Figure({ label, children, foot }: { label: string; children: ReactNode; foot?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <dt className="t-caption text-ink-3">{label}</dt>
      <dd className="t-stat-sm text-ink">{children}</dd>
      {foot ? <dd className="t-caption text-ink-3">{foot}</dd> : null}
    </div>
  );
}
