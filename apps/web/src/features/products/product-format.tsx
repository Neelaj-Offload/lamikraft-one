"use client";

import { StatusPill, type Tone } from "@/components/ui/badge";
import { Money } from "@/components/ui/format";
import { formatDecimal } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { productsMessages as m } from "@/messages/products";
import type { ProductPriceColumn, ProductSize } from "./types";

export const PRODUCT_STATUS_TONE: Record<string, Tone> = {
  active: "success",
  inactive: "neutral",
  under_development: "warning",
};

export function ProductStatusPill({ status }: { status: string }) {
  return <StatusPill tone={PRODUCT_STATUS_TONE[status] ?? "neutral"}>{m.status[status] ?? status}</StatusPill>;
}

/**
 * "450 × 300 × 0.8" (length × width × thickness, mm) or "Ø 120" — DecimalStr measures formatted
 * for display, never computed. Null when the product has no size at all.
 */
export function sizeText(size: ProductSize, thicknessMm: string | null, locale: string): string | null {
  const fmt = (value: string | null) => (value ? formatDecimal(value, { locale, maxFractionDigits: 3 }) : null);
  const parts = [fmt(size.length_mm), fmt(size.width_mm), fmt(size.height_mm)].filter((part): part is string => part !== null);
  const diameter = fmt(size.diameter_mm);
  const thickness = fmt(thicknessMm);
  if (parts.length === 0 && !diameter) return thickness ? `T ${thickness}` : null;
  const main = parts.length > 0 ? parts.join(" × ") : `Ø ${diameter}`;
  return thickness && size.height_mm === null ? `${main} × ${thickness}` : main;
}

export function SizeCell({ size, thicknessMm }: { size: ProductSize; thicknessMm: string | null }) {
  const { locale } = useZone();
  const text = sizeText(size, thicknessMm, locale);
  return text ? <span className="tabular whitespace-nowrap">{text}</span> : <span className="text-ink-muted">—</span>;
}

/** The standard-list price column for one currency: a real price, or why there is none. */
export function PriceColumnCell({ column }: { column: ProductPriceColumn | null }) {
  if (!column || column.status === "not_found") return <span className="text-ink-muted">{m.list.price.notFound}</span>;
  if (column.status === "ambiguous") return <span className="text-warning-text">{m.list.price.ambiguous}</span>;
  if (column.status === "unavailable" || !column.unit_price) return <span className="text-ink-muted">{m.list.price.unavailable}</span>;
  return (
    <span className="whitespace-nowrap">
      <Money value={column.unit_price} maxFractionDigits={4} />
      {column.unit_code ? <span className="text-ink-muted"> / {column.unit_code}</span> : null}
    </span>
  );
}

export function priceColumnFor(prices: readonly ProductPriceColumn[] | null, currency: string): ProductPriceColumn | null {
  return prices?.find((column) => column.currency === currency) ?? null;
}
