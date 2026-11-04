"use client";

import { Link as RacLink } from "react-aria-components";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { Money, Quantity } from "@/components/ui/format";
import { ErrorState, NotAvailable, PermissionDenied } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { ProblemError } from "@/lib/api/errors";
import { compareDecimalStr, isDecimalStr } from "@/lib/format/decimal";
import { procurementMessages as m } from "@/messages/procurement";

/** A DecimalStr above zero (string comparison, never a float). */
export function positive(value: string | null | undefined): boolean {
  return value != null && isDecimalStr(value) && compareDecimalStr(value, "0") > 0;
}

export const dash = <span className="text-ink-muted">—</span>;

export function qty(value: string | null | undefined, uom: string | null | undefined) {
  return value != null && uom ? <Quantity value={{ value, uom }} /> : dash;
}

export function money(amount: string | null | undefined, currency: string) {
  return amount != null ? <Money value={{ amount, currency }} /> : dash;
}

/** 404 and out-of-scope records are the same "not available" state on purpose; 403 names the area. */
export function failure(error: unknown, area: string, what: string, retry: () => void) {
  if (error instanceof ProblemError && error.status === 404) return <NotAvailable />;
  if (error instanceof ProblemError && error.status === 403) return <PermissionDenied area={area} />;
  return <ErrorState error={error} what={what} onRetry={retry} />;
}

const PO_TONES: Record<string, Tone> = {
  draft: "neutral",
  pending_approval: "warning",
  approved: "info",
  issued: "info",
  partially_received: "info",
  received: "success",
  closed: "neutral",
  cancelled: "neutral",
};
const REQ_TONES: Record<string, Tone> = { draft: "neutral", submitted: "warning", approved: "info", rejected: "danger", closed: "success", cancelled: "neutral" };
const MATCH_TONES: Record<string, Tone> = { matched: "success", pending: "warning", qty_mismatch: "danger", price_variance: "danger", amount_mismatch: "danger" };

export function PoStatusPill({ status }: { status: string }) {
  return <StatusPill tone={PO_TONES[status] ?? "neutral"}>{m.poStatus[status] ?? status}</StatusPill>;
}

export function RequisitionStatusPill({ status }: { status: string }) {
  return <StatusPill tone={REQ_TONES[status] ?? "neutral"}>{m.requisitionStatus[status] ?? status}</StatusPill>;
}

export function MatchStatusPill({ status }: { status: string }) {
  return <StatusPill tone={MATCH_TONES[status] ?? "neutral"}>{m.matchStatus[status] ?? status}</StatusPill>;
}

export const OPERATIONS_LEADING = [{ id: "operations", label: "Overview", href: "/operations" }] as const;

/** The purchasing sub-navigation (requisitions, purchase orders, goods receipts). */
export function PurchasingTabs({ current }: { current: "requisitions" | "orders" | "receipts" }) {
  const tabs = [
    { id: "requisitions", href: "/operations/purchasing/requisitions", label: m.tabs.requisitions },
    { id: "orders", href: "/operations/purchasing/orders", label: m.tabs.orders },
    { id: "receipts", href: "/operations/purchasing/receipts", label: m.tabs.receipts },
  ] as const;
  return (
    <nav aria-label={m.tabs.label} className="flex flex-wrap gap-4 text-sm">
      {tabs.map((t) => (
        <RacLink key={t.id} href={t.href} aria-current={t.id === current ? "page" : undefined} className={`${linkClasses} ${t.id === current ? "font-semibold" : ""}`}>
          {t.label}
        </RacLink>
      ))}
    </nav>
  );
}
