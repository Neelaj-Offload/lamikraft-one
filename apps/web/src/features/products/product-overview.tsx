"use client";

import { Badge, type Tone } from "@/components/ui/badge";
import { Money, Quantity } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { SectionCard } from "@/components/ui/section-card";
import { formatDecimal } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { productsMessages as m } from "@/messages/products";
import { sizeText } from "./product-format";
import type { ProductDetail, ProductPriceColumn } from "./types";

const SEVERITY_TONE: Record<string, Tone> = { warning: "warning", info: "info" };

function yesNo(value: boolean | null): string | null {
  return value === null ? null : value ? m.detail.yes : m.detail.no;
}

/** The master facts worth a row; empty values are dropped before rendering. */
export function masterFacts(product: ProductDetail, locale: string): KeyValue[] {
  const f = m.detail.fields;
  const size = sizeText(product.size, null, locale);
  const basis = product.size.basis ? m.detail.sizeBasis[product.size.basis] ?? product.size.basis : null;
  const candidates: (KeyValue & { description: KeyValue["description"] | null })[] = [
    { term: f.display_sku, description: product.display_sku, mono: true },
    { term: f.decor_no, description: product.decor.decor_no, mono: true },
    { term: f.decor_name, description: product.decor.decor_name },
    { term: f.decor_primary, description: product.decor.decor_primary },
    { term: f.decor_options, description: product.decor.decor_options.length > 0 ? product.decor.decor_options.join(", ") : product.decor.decor_options_text },
    { term: f.finish, description: product.finish },
    { term: f.shape, description: product.shape },
    { term: f.size, description: size ? `${size} mm${basis ? ` (${basis})` : ""}` : null, numeric: true },
    { term: f.thickness, description: product.thickness_mm ? `${formatDecimal(product.thickness_mm, { locale, maxFractionDigits: 3 }) ?? product.thickness_mm} mm` : null, numeric: true },
    { term: f.product_type, description: product.product_type },
    { term: f.variant_group, description: product.variant_group },
    { term: f.unit_of_sale, description: product.unit_of_sale },
    { term: f.brand, description: product.brand },
    { term: f.hsn_sac, description: product.stock_attributes.hsn_sac, mono: true },
    { term: f.stock_uom, description: product.stock_attributes.stock_uom_code },
    { term: f.is_stock_tracked, description: yesNo(product.stock_attributes.is_stock_tracked) },
    { term: f.track_lots, description: yesNo(product.stock_attributes.track_lots) },
    { term: f.qc_required, description: yesNo(product.stock_attributes.qc_required) },
  ];
  return candidates.filter((item): item is KeyValue => item.description !== null && item.description !== "");
}

function PriceColumnRow({ column }: { column: ProductPriceColumn }) {
  const p = m.detail.prices;
  return (
    <li className="flex flex-col gap-1 border-b pb-3 last:border-b-0 last:pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="font-mono text-sm text-ink-muted">{column.currency}</span>
        {column.status === "found" && column.unit_price ? (
          <span className="text-ink">
            <Money value={column.unit_price} maxFractionDigits={4} className="font-semibold" />
            {column.unit_code ? <span className="text-ink-muted"> {p.perUnit(column.unit_code)}</span> : null}
          </span>
        ) : (
          <span className="text-ink-muted">{column.status === "ambiguous" ? p.ambiguous : column.status === "unavailable" ? p.unavailable : p.notFound}</span>
        )}
      </div>
      {column.status === "found" ? (
        <dl className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-muted">
          {column.price_list_code ? (
            <div className="flex gap-1">
              <dt>{p.list}:</dt>
              <dd className="font-mono text-ink">{column.price_list_code}</dd>
            </div>
          ) : null}
          {column.product_moq ? (
            <div className="flex gap-1">
              <dt>{p.moq}:</dt>
              <dd className="text-ink">
                <Quantity value={column.product_moq} />
              </dd>
            </div>
          ) : null}
          {column.recommendation ? (
            <div className="flex gap-1">
              <dt>{p.recommendation}:</dt>
              <dd className="text-ink">{column.recommendation.label}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </li>
  );
}

export function ProductOverview({ product }: { product: ProductDetail }) {
  const { locale } = useZone();
  const c = m.detail.completeness;
  const pv = m.detail.provenance;
  const provenanceItems: KeyValue[] = (
    [
      { term: pv.origin, description: product.provenance.origin },
      { term: pv.originRef, description: product.provenance.origin_ref, mono: true },
      { term: pv.categorySource, description: product.provenance.category_source },
      { term: pv.subcategorySource, description: product.provenance.subcategory_source },
      { term: pv.designNo, description: product.provenance.source_design_no, mono: true },
      { term: pv.shapeNo, description: product.provenance.source_shape_no, mono: true },
      { term: pv.sheet, description: product.provenance.source_sheet },
      { term: pv.row, description: product.provenance.source_row, mono: true },
      { term: pv.catalogPage, description: product.provenance.source_catalog_page },
      { term: pv.notes, description: product.provenance.source_notes },
    ] as (KeyValue & { description: string | null })[]
  ).filter((item): item is KeyValue & { description: string } => item.description !== null);

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div className="flex flex-col gap-8">
        <section aria-label={m.detail.masterFacts} className="flex flex-col gap-4">
          <KeyValueGrid items={masterFacts(product, locale)} columns={2} />
        </section>
        {product.description ? (
          <section className="flex flex-col gap-1">
            <h2 className="text-sm text-ink-muted">{m.detail.description}</h2>
            <p className="whitespace-pre-line text-ink">{product.description}</p>
          </section>
        ) : null}
        {product.internal_remarks ? (
          <section className="flex flex-col gap-1">
            <h2 className="flex items-center gap-2 text-sm text-ink-muted">
              {m.detail.internalRemarks}
              <Badge tone="neutral">{m.detail.internal}</Badge>
            </h2>
            <p className="whitespace-pre-line text-ink">{product.internal_remarks}</p>
          </section>
        ) : null}
      </div>
      <div className="flex flex-col gap-6">
        <SectionCard title={c.title} description={c.score(product.completeness.checks_passed, product.completeness.checks_evaluated)}>
          {product.completeness.missing.length === 0 ? (
            <p className="text-sm text-ink-muted">{c.missingNone}</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {product.completeness.missing.map((issue) => (
                <li key={issue.code} className="flex items-start gap-2 text-sm">
                  <Badge tone={SEVERITY_TONE[issue.severity] ?? "neutral"}>{c.severity[issue.severity] ?? issue.severity}</Badge>
                  <span className="text-ink">{issue.label}</span>
                </li>
              ))}
            </ul>
          )}
          {product.completeness.not_evaluated.length > 0 ? (
            <div className="flex flex-col gap-1 text-sm text-ink-muted">
              <p className="font-semibold">{c.notEvaluated}</p>
              <ul className="flex flex-col gap-0.5">
                {product.completeness.not_evaluated.map((entry) => (
                  <li key={entry.code}>
                    <span className="font-mono">{entry.code}</span>
                    {entry.reason ? ` — ${entry.reason}` : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </SectionCard>
        {product.prices !== null ? (
          <SectionCard title={m.detail.prices.title} description={m.detail.prices.description}>
            {product.prices.length === 0 ? (
              <p className="text-sm text-ink-muted">{m.detail.prices.notFound}</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {product.prices.map((column) => (
                  <PriceColumnRow key={column.currency} column={column} />
                ))}
              </ul>
            )}
          </SectionCard>
        ) : null}
        <SectionCard title={pv.title}>
          <KeyValueGrid items={provenanceItems} columns={2} />
        </SectionCard>
      </div>
    </div>
  );
}
