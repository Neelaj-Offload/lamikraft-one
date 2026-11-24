"use client";

import type { ReactNode } from "react";
import {
  DECOR_FIELDS,
  MASTER_FIELDS,
  PACKAGING_FIELDS,
  PROVENANCE_FIELDS,
  SPEC_FIELDS,
  masterValues,
  packagingValues,
  specValues,
} from "@/features/catalogue/form-model";
import type { DimensionRead, PackagingRead, ProductDetail, SpecificationRead } from "@/features/products/types";
import { formatCount, formatDecimal } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import type { LoadedProduct } from "~/data/products";
import { Badge, Banner, Code, DataTable, EmptyState, GlassPanel, KeyValue, type Column, type KeyValueItem, type Tone } from "~/ui";
import { sizeText } from "./format";
import { EditableView } from "./product-editor";

/** The three views of a product's own data: details, specification and packaging. Each reads first and edits in place. */

const SIZE_BASIS: Record<string, string> = {
  master_size: "from the product's own size",
  spec_size: "from the specification size",
  spec_length_width: "from the specification's length and width",
};

function yesNo(value: boolean | null): string | null {
  return value === null ? null : value ? "Yes" : "No";
}

function Prose({ children }: { children: string }) {
  return <p className="t-body m-0 max-w-[68ch] whitespace-pre-line text-ink">{children}</p>;
}

// ---- Details ----

export function ProductDetails({ raw, product }: LoadedProduct) {
  const { locale } = useZone();
  const size = sizeText(product.size, null, locale);
  const basis = product.size.basis ? (SIZE_BASIS[product.size.basis] ?? product.size.basis) : null;
  const identity: KeyValueItem[] = [
    { label: "SKU shown to customers", value: product.display_sku, mono: true },
    { label: "Brand", value: product.brand },
    { label: "Product type", value: product.product_type },
    { label: "Family", value: product.variant_group },
    { label: "Sold by", value: product.unit_of_sale },
    { label: "Shape", value: product.shape },
    { label: "Size", value: size ? `${size} mm${basis ? `, ${basis}` : ""}` : null },
    { label: "Thickness", value: product.thickness_mm ? `${formatDecimal(product.thickness_mm, { locale, maxFractionDigits: 3 }) ?? product.thickness_mm} mm` : null },
    { label: "Finish", value: product.finish },
    { label: "HSN or SAC code", value: product.stock_attributes.hsn_sac, mono: true },
  ];
  const decor: KeyValueItem[] = [
    { label: "Decor number", value: product.decor.decor_no, mono: true },
    { label: "Decor name", value: product.decor.decor_name },
    { label: "Main decor", value: product.decor.decor_primary },
    { label: "Other decors offered", value: product.decor.decor_options.length > 0 ? product.decor.decor_options.join(", ") : product.decor.decor_options_text },
  ];
  const stock: KeyValueItem[] = (
    [
      { label: "Stock unit", value: product.stock_attributes.stock_uom_code },
      { label: "Stock is tracked", value: yesNo(product.stock_attributes.is_stock_tracked) },
      { label: "Lots are tracked", value: yesNo(product.stock_attributes.track_lots) },
      { label: "Needs a quality check", value: yesNo(product.stock_attributes.qc_required) },
    ] satisfies KeyValueItem[]
  ).filter((item) => item.value !== null);
  const source: KeyValueItem[] = (
    [
      { label: "Came from", value: product.provenance.origin },
      { label: "Reference", value: product.provenance.origin_ref, mono: true },
      { label: "Category as entered", value: product.provenance.category_source },
      { label: "Subcategory as entered", value: product.provenance.subcategory_source },
      { label: "Design number", value: product.provenance.source_design_no, mono: true },
      { label: "Shape number", value: product.provenance.source_shape_no, mono: true },
      { label: "Sheet", value: product.provenance.source_sheet },
      { label: "Row", value: product.provenance.source_row, mono: true },
      { label: "Catalogue page", value: product.provenance.source_catalog_page },
      { label: "Notes on the source", value: product.provenance.source_notes },
    ] satisfies KeyValueItem[]
  ).filter((item) => item.value !== null && item.value !== "");

  return (
    <EditableView
      raw={raw}
      mode="master"
      title="Details"
      description="What this product is, which decor it comes in and where its record came from."
      editLabel="Edit details"
      saveLabel="Save details"
      groups={[
        { title: "Identity", description: "The name, size and codes people search and quote by.", fields: MASTER_FIELDS },
        { title: "Decor", description: "A different decor is a different product. Options are the other decors this design is offered in.", fields: DECOR_FIELDS },
        { title: "Source", description: "Where this record came from, for tracing it back to the old catalogue.", fields: PROVENANCE_FIELDS },
      ]}
      initial={masterValues(raw)}
    >
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="stack">
          <GlassPanel title="Identity" titleAs="h3" padding="lg">
            <KeyValue items={identity} columns={2} />
          </GlassPanel>
          {product.description ? (
            <GlassPanel title="Description" titleAs="h3" padding="lg">
              <Prose>{product.description}</Prose>
            </GlassPanel>
          ) : null}
          {product.internal_remarks ? (
            <GlassPanel title="Internal remarks" titleAs="h3" padding="lg" action={<Badge size="sm" icon="lock">Team only</Badge>}>
              <Prose>{product.internal_remarks}</Prose>
            </GlassPanel>
          ) : null}
        </div>
        <div className="stack">
          <GlassPanel title="Decor" titleAs="h3" padding="lg">
            <KeyValue items={decor} />
          </GlassPanel>
          {stock.length > 0 ? (
            <GlassPanel title="Stock keeping" titleAs="h3" padding="lg">
              <KeyValue items={stock} />
            </GlassPanel>
          ) : null}
          {source.length > 0 ? (
            <GlassPanel variant="outline" title="Source" titleAs="h3" padding="lg">
              <KeyValue items={source} />
            </GlassPanel>
          ) : null}
        </div>
      </div>
    </EditableView>
  );
}

// ---- Specification ----

const SPEC_MEASURES = ["length_mm", "width_mm", "height_mm", "thickness_mm"] as const;
const SPEC_TEXTS = [
  "thickness_text",
  "size_label",
  "finish",
  "material_type",
  "type",
  "top_sheet",
  "bowl_type",
  "handle_type",
  "stand_material",
  "special_features",
  "care_instructions",
  "usage_notes",
] as const;
const SPEC_COUNTS = ["groove_count", "bowl_count", "no_of_boards"] as const;

const SPEC_LABEL: Record<string, string> = {
  length_mm: "Length",
  width_mm: "Width",
  height_mm: "Height",
  thickness_mm: "Thickness",
  thickness_text: "Thickness as described",
  size_label: "Size name",
  finish: "Finish",
  material_type: "Material",
  type: "Type",
  top_sheet: "Top sheet",
  bowl_type: "Bowl type",
  handle_type: "Handle type",
  stand_material: "Stand material",
  special_features: "Special features",
  care_instructions: "Care instructions",
  usage_notes: "Usage notes",
  groove_count: "Grooves",
  bowl_count: "Bowls",
  no_of_boards: "Boards",
};

function specItems(spec: SpecificationRead, locale: string): { measures: KeyValueItem[]; build: KeyValueItem[]; notes: { label: string; text: string }[] } {
  const measures: KeyValueItem[] = [];
  for (const field of SPEC_MEASURES) {
    const value = spec[field];
    if (value === null) continue;
    const source = spec[`${field}_source`];
    const shown = `${formatDecimal(value, { locale, maxFractionDigits: 3 }) ?? value} mm`;
    measures.push({
      label: SPEC_LABEL[field],
      value: (
        <span className="flex flex-col">
          <span className="lk-tnum">{shown}</span>
          {source && source !== value ? <span className="t-caption text-ink-3">Entered as {source}</span> : null}
        </span>
      ),
    });
  }
  const build: KeyValueItem[] = [];
  const notes: { label: string; text: string }[] = [];
  for (const field of SPEC_TEXTS) {
    const value = spec[field];
    if (value === null) continue;
    if (field === "special_features" || field === "care_instructions" || field === "usage_notes") notes.push({ label: SPEC_LABEL[field] ?? field, text: value });
    else build.push({ label: SPEC_LABEL[field], value });
  }
  for (const field of SPEC_COUNTS) {
    const value = spec[field];
    if (value !== null) build.push({ label: SPEC_LABEL[field], value: <span className="lk-tnum">{formatCount(value, locale)}</span> });
  }
  return { measures, build, notes };
}

const DIMENSION_KIND: Record<string, string> = {
  master_size: "Product size",
  spec_size: "Specification size",
  board_size: "Board size",
  working_size: "Working size",
  stand_size: "Stand size",
  plate_1_size: "Plate 1 size",
  plate_2_size: "Plate 2 size",
  plate_3_size: "Plate 3 size",
};
const PARSE: Record<string, { tone: Tone; label: string }> = {
  parsed: { tone: "leaf", label: "Understood" },
  ambiguous: { tone: "amber", label: "Unclear" },
  unparsed: { tone: "ember", label: "Not understood" },
};

function parsedText(dimension: DimensionRead, locale: string): string | null {
  const fmt = (value: string | null) => (value ? formatDecimal(value, { locale, maxFractionDigits: 3 }) : null);
  const parts = [fmt(dimension.length_mm), fmt(dimension.width_mm), fmt(dimension.height_mm)].filter((part): part is string => part !== null);
  if (parts.length > 0) return parts.join(" × ");
  const diameter = fmt(dimension.diameter_mm);
  return diameter ? `Ø ${diameter}` : null;
}

function dimensionColumns(locale: string): Column<DimensionRead>[] {
  return [
    { key: "kind", header: "Measure", primary: true, cell: (row) => DIMENSION_KIND[row.kind] ?? row.kind },
    { key: "source", header: "As entered", mobileLabel: "As entered", cell: (row) => <Code>{row.source_text}</Code> },
    {
      key: "parsed",
      header: "Read as, mm",
      mobileLabel: "Read as, mm",
      numeric: true,
      cell: (row) => {
        const text = parsedText(row, locale);
        return text ? (
          <span className="lk-tnum whitespace-nowrap">
            {text}
            {row.unit_inferred ? <span className="text-ink-3"> (unit assumed)</span> : null}
          </span>
        ) : (
          <span className="text-ink-3">Nothing</span>
        );
      },
    },
    {
      key: "status",
      header: "Reading",
      cell: (row) => {
        const parse = PARSE[row.parse_status] ?? { tone: "neutral" as Tone, label: row.parse_status };
        return (
          <Badge tone={parse.tone} size="sm" dot>
            {parse.label}
          </Badge>
        );
      },
    },
    {
      key: "warnings",
      header: "Notes",
      hideOnMobile: true,
      cell: (row) => (row.parse_warnings.length > 0 ? <span className="t-body-sm text-ink-2">{row.parse_warnings.join(" ")}</span> : null),
    },
  ];
}

function NotesPanels({ notes }: { notes: { label: string; text: string }[] }): ReactNode {
  if (notes.length === 0) return null;
  return (
    <div className="tiles" data-min="lg">
      {notes.map((note) => (
        <GlassPanel key={note.label} variant="outline" title={note.label} titleAs="h3" padding="lg">
          <Prose>{note.text}</Prose>
        </GlassPanel>
      ))}
    </div>
  );
}

export function ProductSpecification({ raw, product }: LoadedProduct) {
  const { locale } = useZone();
  const items = product.specification ? specItems(product.specification, locale) : null;
  const hasSpec = items !== null && items.measures.length + items.build.length + items.notes.length > 0;
  return (
    <EditableView
      raw={raw}
      mode="specification"
      title="Specification"
      description="How big it is and what it is made of. Sizes are read into millimetres as you type them."
      editLabel={hasSpec ? "Edit specification" : "Add the specification"}
      saveLabel="Save specification"
      groups={[{ title: "Specification", description: "Leave a field empty to clear it. Lengths are millimetres unless you add a unit.", fields: SPEC_FIELDS }]}
      initial={specValues(raw)}
    >
      {hasSpec && items ? (
        <>
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <GlassPanel title="Measurements" titleAs="h3" padding="lg">
              {items.measures.length > 0 ? <KeyValue items={items.measures} columns={2} /> : <p className="t-body-sm m-0 text-ink-3">No measurements yet.</p>}
            </GlassPanel>
            <GlassPanel title="Build" titleAs="h3" padding="lg">
              {items.build.length > 0 ? <KeyValue items={items.build} columns={2} /> : <p className="t-body-sm m-0 text-ink-3">Nothing about material or finish yet.</p>}
            </GlassPanel>
          </div>
          <NotesPanels notes={items.notes} />
        </>
      ) : (
        <GlassPanel>
          <EmptyState icon="ruler" title="Add the specification" text="Without a size and thickness this product cannot be cut, packed or quoted with confidence." compact />
        </GlassPanel>
      )}
      {product.dimensions.length > 0 ? (
        <section className="stack" aria-label="Sizes as entered">
          <div className="flex flex-col gap-1">
            <h3 className="t-h4">Sizes as entered</h3>
            <p className="t-body-sm m-0 text-ink-3">Every size is kept as it was typed, beside what Lamikraft One read it as.</p>
          </div>
          <GlassPanel padding="none">
            <DataTable
              label="Sizes as entered"
              columns={dimensionColumns(locale)}
              rows={product.dimensions}
              rowKey={(row) => `${row.kind}:${row.source_field}`}
            />
          </GlassPanel>
        </section>
      ) : null}
    </EditableView>
  );
}

// ---- Packaging ----

const PACK_COUNTS = ["carton_qty", "inner_qty"] as const;
const PACK_MEASURES = ["unit_weight_g", "net_weight_kg", "gross_weight_kg", "cbm"] as const;
const PACK_NOTES = ["packaging_notes", "fragile_notes", "notes"] as const;
const PACK_LABEL: Record<string, string> = {
  carton_qty: "Units per carton",
  inner_qty: "Units per inner pack",
  unit_weight_g: "Unit weight",
  net_weight_kg: "Net weight",
  gross_weight_kg: "Gross weight",
  cbm: "Carton volume",
  packing_type: "Packing type",
  packaging_status: "Packaging status",
  packaging_notes: "Packing notes",
  fragile_notes: "Handling notes for fragile goods",
  notes: "Other notes",
};
const PACK_UNIT: Record<string, string> = { unit_weight_g: "g", net_weight_kg: "kg", gross_weight_kg: "kg", cbm: "CBM" };

function packagingItems(packaging: PackagingRead, locale: string): { carton: KeyValueItem[]; notes: { label: string; text: string }[] } {
  const carton: KeyValueItem[] = [];
  for (const field of PACK_COUNTS) {
    const value = packaging[field];
    carton.push({ label: PACK_LABEL[field], value: value === null ? null : <span className="lk-tnum">{formatCount(value, locale)}</span> });
  }
  const dims = [packaging.carton_length_cm, packaging.carton_width_cm, packaging.carton_height_cm];
  if (dims.some((value) => value !== null)) {
    carton.push({
      label: "Carton size",
      value: <span className="lk-tnum">{dims.map((value) => (value ? (formatDecimal(value, { locale }) ?? value) : "?")).join(" × ")} cm</span>,
    });
  }
  for (const field of PACK_MEASURES) {
    const value = packaging[field];
    if (value === null && field !== "unit_weight_g") continue;
    carton.push({ label: PACK_LABEL[field], value: value === null ? null : <span className="lk-tnum">{`${formatDecimal(value, { locale }) ?? value} ${PACK_UNIT[field]}`}</span> });
  }
  if (packaging.packing_type) carton.push({ label: PACK_LABEL.packing_type, value: packaging.packing_type });
  if (packaging.packaging_status) carton.push({ label: PACK_LABEL.packaging_status, value: packaging.packaging_status });
  const notes: { label: string; text: string }[] = [];
  for (const field of PACK_NOTES) {
    const value = packaging[field];
    if (value !== null) notes.push({ label: PACK_LABEL[field] ?? field, text: value });
  }
  return { carton, notes };
}

export function ProductPackaging({ raw, product }: LoadedProduct) {
  const { locale } = useZone();
  const packaging = product.packaging;
  const items = packaging ? packagingItems(packaging, locale) : null;
  return (
    <EditableView
      raw={raw}
      mode="packaging"
      title="Packaging"
      description="How it is packed: what goes in a carton, what the carton weighs and how to handle it."
      editLabel={packaging ? "Edit packaging" : "Add packaging"}
      saveLabel="Save packaging"
      groups={[{ title: "Packaging", description: "Leave a field empty to clear it.", fields: PACKAGING_FIELDS }]}
      initial={packagingValues(raw)}
    >
      {packaging && items ? (
        <>
          {packaging.warnings.length > 0 ? (
            <Banner tone="amber" title={packaging.warnings.length === 1 ? "One thing to check in this packaging." : `${packaging.warnings.length} things to check in this packaging.`}>
              {packaging.warnings.map((warning) => (
                <span key={warning} className="block">
                  {warning}
                </span>
              ))}
            </Banner>
          ) : null}
          <GlassPanel padding="lg" className="flex flex-col gap-5">
            {packaging.summary ? <p className="t-h3 m-0 text-ink">{packaging.summary}</p> : null}
            <KeyValue items={items.carton} columns={2} />
            {packaging.alias_provenance ? (
              <p className="t-caption m-0 text-ink-3">Some of these values were entered under older field names and have been matched to the fields shown here.</p>
            ) : null}
          </GlassPanel>
          <NotesPanels notes={items.notes} />
        </>
      ) : (
        <GlassPanel>
          <EmptyState icon="packageOpen" title="Add packaging" text="Carton quantity and unit weight are what dispatch and freight quotes are worked out from." compact />
        </GlassPanel>
      )}
    </EditableView>
  );
}

/** For the summary: the handful of facts that describe the product at a glance. */
export function glanceItems(product: ProductDetail, locale: string): KeyValueItem[] {
  const size = sizeText(product.size, product.thickness_mm, locale);
  return [
    { label: "Category", value: product.subcategory ? `${product.category.name}, ${product.subcategory.name}` : product.category.name },
    { label: "Decor", value: [product.decor.decor_no, product.decor.decor_name].filter(Boolean).join(" ") || null },
    { label: "Size", value: size ? `${size} mm` : null },
    { label: "Sold by", value: product.unit_of_sale },
    { label: "Per carton", value: product.carton_qty === null ? null : formatCount(product.carton_qty, locale) },
  ];
}
