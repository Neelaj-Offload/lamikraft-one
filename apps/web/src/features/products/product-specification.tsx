"use client";

import { StatusPill, type Tone } from "@/components/ui/badge";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { EmptyState } from "@/components/ui/states";
import { formatCount, formatDecimal } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { productsMessages as m } from "@/messages/products";
import type { DimensionRead, ProductDetail, SpecificationRead } from "./types";

const PARSE_TONE: Record<string, Tone> = { parsed: "success", ambiguous: "warning", unparsed: "danger" };

type MeasureField = "length_mm" | "width_mm" | "height_mm" | "thickness_mm";
const MEASURES: MeasureField[] = ["length_mm", "width_mm", "height_mm", "thickness_mm"];
const TEXTS = [
  "thickness_text",
  "size_label",
  "finish",
  "material_type",
  "bowl_type",
  "top_sheet",
  "stand_material",
  "type",
  "handle_type",
  "special_features",
  "care_instructions",
  "usage_notes",
] as const;
const COUNTS = ["groove_count", "bowl_count", "no_of_boards"] as const;

function EnteredAs({ value, source }: { value: string; source: string | null }) {
  return (
    <span className="flex flex-col">
      <span>{value}</span>
      {source && source !== value ? <span className="text-sm text-ink-muted">{m.detail.specification.enteredAs(source)}</span> : null}
    </span>
  );
}

/** Every non-null specification field, with the entered text under canonical measures. */
export function specificationItems(spec: SpecificationRead, locale: string): KeyValue[] {
  const labels = m.detail.specification.fields;
  const items: KeyValue[] = [];
  for (const field of MEASURES) {
    const value = spec[field];
    if (value === null) continue;
    items.push({ term: labels[field] ?? field, description: <EnteredAs value={formatDecimal(value, { locale, maxFractionDigits: 3 }) ?? value} source={spec[`${field}_source`]} />, numeric: true });
  }
  for (const field of TEXTS) {
    const value = spec[field];
    if (value !== null) items.push({ term: labels[field] ?? field, description: <span className="whitespace-pre-line">{value}</span> });
  }
  for (const field of COUNTS) {
    const value = spec[field];
    if (value !== null) items.push({ term: labels[field] ?? field, description: formatCount(value, locale), numeric: true });
  }
  return items;
}

function parsedText(dimension: DimensionRead, locale: string): string | null {
  const fmt = (value: string | null) => (value ? formatDecimal(value, { locale, maxFractionDigits: 3 }) : null);
  const parts = [fmt(dimension.length_mm), fmt(dimension.width_mm), fmt(dimension.height_mm)].filter((part): part is string => part !== null);
  if (parts.length > 0) return parts.join(" × ");
  const diameter = fmt(dimension.diameter_mm);
  return diameter ? `Ø ${diameter}` : null;
}

function dimensionColumns(locale: string): DataTableColumn<DimensionRead>[] {
  const s = m.detail.specification;
  return [
    { id: "kind", header: s.columns.kind, isRowHeader: true, mobile: "title", cell: (row) => s.kinds[row.kind] ?? row.kind },
    { id: "source", header: s.columns.source, mobile: "key", cell: (row) => <span className="font-mono text-sm">{row.source_text}</span> },
    {
      id: "parsed",
      header: s.columns.parsed,
      numeric: true,
      mobile: "amount",
      cell: (row) => {
        const text = parsedText(row, locale);
        return text ? (
          <span className="tabular whitespace-nowrap">
            {text}
            {row.unit_inferred ? <span className="text-ink-muted"> ({s.unitInferred})</span> : null}
          </span>
        ) : (
          <span className="text-ink-muted">—</span>
        );
      },
    },
    {
      id: "status",
      header: s.columns.status,
      mobile: "status",
      cell: (row) => <StatusPill tone={PARSE_TONE[row.parse_status] ?? "neutral"}>{s.parse[row.parse_status] ?? row.parse_status}</StatusPill>,
    },
    {
      id: "warnings",
      header: s.columns.warnings,
      cell: (row) => (row.parse_warnings.length > 0 ? <span className="text-sm text-ink-muted">{row.parse_warnings.join("; ")}</span> : <span className="text-ink-muted">—</span>),
    },
  ];
}

export function ProductSpecification({ product }: { product: ProductDetail }) {
  const { locale } = useZone();
  const s = m.detail.specification;
  const items = product.specification ? specificationItems(product.specification, locale) : [];
  return (
    <div className="flex flex-col gap-8">
      {items.length > 0 ? <KeyValueGrid items={items} /> : <p className="text-ink-muted">{s.none}</p>}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-[650] text-ink">{s.dimensions}</h2>
        <DataTable
          caption={s.dimensionsCaption}
          hideCaption
          columns={dimensionColumns(locale)}
          rows={product.dimensions}
          rowId={(row) => `${row.kind}:${row.source_field}`}
          empty={<EmptyState title={s.dimensions} headingLevel={3}>{s.noDimensions}</EmptyState>}
        />
      </section>
    </div>
  );
}
