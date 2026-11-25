"use client";

import type { ReactNode } from "react";
import type { PriceScope } from "@/features/price-lists/types";
import type { ProductPriceColumn, ProductSize } from "@/features/products/types";
import { formatDecimal, formatMoney, type MoneyValue } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { Badge, Dash, type Tone } from "~/ui";

/** Words and small display pieces shared by the Products screens. */

export const PRODUCT_STATUS_LABEL: Record<string, string> = {
  active: "Active",
  inactive: "Inactive",
  under_development: "In development",
};
const PRODUCT_STATUS_TONE: Record<string, Tone> = { active: "leaf", inactive: "neutral", under_development: "amber" };

export function ProductStatusBadge({ status, size }: { status: string; size?: "sm" }) {
  return (
    <Badge tone={PRODUCT_STATUS_TONE[status] ?? "neutral"} dot size={size}>
      {PRODUCT_STATUS_LABEL[status] ?? status}
    </Badge>
  );
}

export const PRICE_LIST_STATUS_LABEL: Record<string, string> = { draft: "Draft", active: "Active", retired: "Retired" };
const PRICE_LIST_STATUS_TONE: Record<string, Tone> = { draft: "amber", active: "leaf", retired: "neutral" };

export function PriceListStatusBadge({ status, size }: { status: string; size?: "sm" }) {
  return (
    <Badge tone={PRICE_LIST_STATUS_TONE[status] ?? "neutral"} dot size={size}>
      {PRICE_LIST_STATUS_LABEL[status] ?? status}
    </Badge>
  );
}

export const PRICE_TYPE_LABEL: Record<string, string> = { domestic: "Domestic", export: "Export", sample: "Sample", distributor: "Distributor" };
export const PRICE_SCOPE_LABEL: Record<string, string> = { standard: "Standard", customer_type: "Customer type", customer: "Customer" };
const CUSTOMER_TYPE_LABEL: Record<string, string> = { standard: "Standard", dealer: "Dealer", distributor: "Distributor" };

/** "Everyone", "Dealers" or the customer's name: who a price list applies to. */
export function scopeText(scope: PriceScope | string, party: { display_name: string } | null, customerType: string | null): string {
  if (scope === "customer") return party?.display_name ?? "One customer";
  if (scope === "customer_type") return customerType ? `${CUSTOMER_TYPE_LABEL[customerType] ?? customerType} customers` : "A customer type";
  return "All customers";
}

/**
 * "450 × 300 × 12" (length × width × thickness, in mm) or "Ø 120". Measures are decimal strings
 * formatted for display, never computed. Null when the product has no size at all.
 */
export function sizeText(size: ProductSize, thicknessMm: string | null, locale: string): string | null {
  const fmt = (value: string | null) => (value ? formatDecimal(value, { locale, maxFractionDigits: 3 }) : null);
  const parts = [fmt(size.length_mm), fmt(size.width_mm), fmt(size.height_mm)].filter((part): part is string => part !== null);
  const diameter = fmt(size.diameter_mm);
  const thickness = fmt(thicknessMm);
  if (parts.length === 0 && !diameter) return thickness ? `${thickness} thick` : null;
  const main = parts.length > 0 ? parts.join(" × ") : `Ø ${diameter}`;
  return thickness && size.height_mm === null ? `${main} × ${thickness}` : main;
}

export function SizeText({ size, thicknessMm, unit = false }: { size: ProductSize; thicknessMm: string | null; unit?: boolean }) {
  const { locale } = useZone();
  const text = sizeText(size, thicknessMm, locale);
  if (!text) return <Dash />;
  return (
    <span className="lk-tnum whitespace-nowrap">
      {text}
      {unit ? " mm" : null}
    </span>
  );
}

/** A unit price keeps up to four decimal places (€9.495), with its unit beside it. */
export function UnitPrice({ value, unit, className }: { value: MoneyValue | null | undefined; unit?: string | null; className?: string }) {
  const { locale } = useZone();
  const text = formatMoney(value, { locale, maxFractionDigits: 4 });
  if (text === null) return <Dash className={className} />;
  return (
    <span className={`lk-tnum whitespace-nowrap ${className ?? ""}`}>
      {text}
      {unit ? <span className="text-ink-3"> / {unit}</span> : null}
    </span>
  );
}

export function priceColumnFor(prices: readonly ProductPriceColumn[] | null, currency: string): ProductPriceColumn | null {
  return prices?.find((column) => column.currency === currency) ?? null;
}

/** Why a product shows no standard price in a currency, in the reader's words. */
export function priceGapText(column: ProductPriceColumn | null): string {
  if (!column || column.status === "not_found") return "Not priced";
  if (column.status === "ambiguous") return "Two lists disagree";
  return "No price on the list";
}

/** The standard list price in one currency: the price, or the reason there is none. */
export function StandardPrice({ column, quiet = false }: { column: ProductPriceColumn | null; quiet?: boolean }) {
  if (column?.status === "found" && column.unit_price) return <UnitPrice value={column.unit_price} unit={column.unit_code} />;
  if (quiet && (!column || column.status === "not_found")) return <Dash />;
  return <span className={column?.status === "ambiguous" ? "text-amber-text" : "text-ink-3"}>{priceGapText(column)}</span>;
}

/** "12 Oct 2026 to 31 Dec 2026" or "From 12 Oct 2026". */
export function validityText(from: ReactNode, to: ReactNode | null): ReactNode {
  return to ? (
    <>
      {from} to {to}
    </>
  ) : (
    <>From {from}</>
  );
}
