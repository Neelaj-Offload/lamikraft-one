"use client";

import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { formatCount, formatDecimal } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { productsMessages as m } from "@/messages/products";
import type { PackagingRead, ProductDetail } from "./types";

const COUNTS = ["carton_qty", "inner_qty"] as const;
const MEASURES = ["unit_weight_g", "carton_length_cm", "carton_width_cm", "carton_height_cm", "net_weight_kg", "gross_weight_kg", "cbm"] as const;
const TEXTS = ["packing_type", "packaging_status", "packaging_notes", "fragile_notes", "notes"] as const;

export function packagingItems(packaging: PackagingRead, locale: string): KeyValue[] {
  const labels = m.detail.packaging.fields;
  const items: KeyValue[] = [];
  for (const field of COUNTS) {
    const value = packaging[field];
    if (value !== null) items.push({ term: labels[field] ?? field, description: formatCount(value, locale), numeric: true });
  }
  for (const field of MEASURES) {
    const value = packaging[field];
    if (value !== null) items.push({ term: labels[field] ?? field, description: formatDecimal(value, { locale }) ?? value, numeric: true });
  }
  for (const field of TEXTS) {
    const value = packaging[field];
    if (value !== null) items.push({ term: labels[field] ?? field, description: <span className="whitespace-pre-line">{value}</span> });
  }
  return items;
}

export function ProductPackaging({ product }: { product: ProductDetail }) {
  const { locale } = useZone();
  const p = m.detail.packaging;
  const packaging = product.packaging;
  if (!packaging) return <p className="text-ink-muted">{p.none}</p>;
  const items = packagingItems(packaging, locale);
  return (
    <div className="flex flex-col gap-6">
      {packaging.summary ? <p className="text-lg font-[650] text-ink">{packaging.summary}</p> : null}
      {items.length > 0 ? <KeyValueGrid items={items} /> : <p className="text-ink-muted">{p.none}</p>}
      {packaging.warnings.length > 0 ? (
        <section className="flex flex-col gap-1">
          <h2 className="text-sm font-semibold text-warning-text">{p.warnings}</h2>
          <ul className="list-disc ps-5 text-sm text-ink">
            {packaging.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {packaging.alias_provenance ? <p className="text-sm text-ink-muted">{p.aliasNote}</p> : null}
    </div>
  );
}
