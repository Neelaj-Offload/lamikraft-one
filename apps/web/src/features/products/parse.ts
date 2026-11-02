/**
 * Runtime readers for the catalogue API (see types.ts). Required fields are checked; links
 * must stay inside the app; DecimalStr values are validated, never converted. Redacted fields
 * (`prices`) stay null when absent, and nothing is masked in their place.
 */

import { isDecimalStr } from "@/lib/format/decimal";
import { safeAppPath } from "@/lib/safe-path";
import {
  COMPLETENESS_RULES,
  PRODUCT_STATUSES,
  type Capability,
  type CategoryRead,
  type CompletenessRead,
  type CompletenessSummary,
  type DecorRead,
  type DimensionRead,
  type FacetDimension,
  type FacetValue,
  type Money,
  type NotEvaluated,
  type PackagingRead,
  type Page,
  type ProductDetail,
  type ProductFacets,
  type ProductPriceColumn,
  type ProductSize,
  type ProductStats,
  type ProductSummary,
  type ProvenanceRead,
  type Quantity,
  type SpecificationRead,
  type StockAttributesRead,
  type SubcategoryRead,
  type TaxonomyRef,
  FACET_DIMENSIONS,
} from "./types";

export class ProductsShapeError extends Error {
  override readonly name = "ProductsShapeError";
}

export type Json = Record<string, unknown>;
export const isObject = (value: unknown): value is Json => value !== null && typeof value === "object" && !Array.isArray(value);
export const str = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);
export const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
export const int = (value: unknown): number | null => (typeof value === "number" && Number.isInteger(value) ? value : null);
export const dec = (value: unknown): string | null => (isDecimalStr(value) ? value : null);
export const bool = (value: unknown): boolean | null => (typeof value === "boolean" ? value : null);
export const strings = (value: unknown): string[] => arr(value).filter((entry): entry is string => typeof entry === "string");

export function need<T>(value: T | null, what: string): T {
  if (value === null) throw new ProductsShapeError(`The catalogue response could not be read (${what}).`);
  return value;
}

export function money(value: unknown): Money | null {
  return isObject(value) && isDecimalStr(value.amount) && str(value.currency) ? { amount: value.amount, currency: str(value.currency)! } : null;
}

export function quantity(value: unknown): Quantity | null {
  return isObject(value) && isDecimalStr(value.value) && str(value.uom) ? { value: value.value, uom: str(value.uom)! } : null;
}

export function capabilities(value: unknown): Record<string, Capability> {
  if (!isObject(value)) return {};
  const out: Record<string, Capability> = {};
  for (const [key, cap] of Object.entries(value)) {
    if (isObject(cap) && typeof cap.allowed === "boolean") out[key] = { allowed: cap.allowed, reason_code: str(cap.reason_code) };
  }
  return out;
}

/** `Page[T]` (`{items,total,limit,offset}`); unreadable rows are dropped, never shown half-filled. */
export function pageOf<T>(raw: unknown, item: (value: unknown) => T | null): Page<T> {
  if (!isObject(raw) || !Array.isArray(raw.items)) throw new ProductsShapeError("The list could not be read (items).");
  const items = raw.items.map(item).filter((entry): entry is T => entry !== null);
  return { items, total: int(raw.total) ?? items.length, limit: int(raw.limit) ?? items.length, offset: int(raw.offset) ?? 0 };
}

function taxonomyRef(value: unknown): TaxonomyRef | null {
  if (!isObject(value) || !str(value.id) || !str(value.name)) return null;
  return { id: str(value.id)!, name: str(value.name)!, is_active: value.is_active !== false };
}

function size(value: unknown): ProductSize {
  const s = isObject(value) ? value : {};
  return { length_mm: dec(s.length_mm), width_mm: dec(s.width_mm), height_mm: dec(s.height_mm), diameter_mm: dec(s.diameter_mm), basis: str(s.basis) };
}

function priceColumn(value: unknown): ProductPriceColumn | null {
  if (!isObject(value) || !str(value.currency)) return null;
  const status = value.status === "found" || value.status === "ambiguous" || value.status === "unavailable" ? value.status : "not_found";
  const rec = isObject(value.recommendation) ? value.recommendation : null;
  return {
    currency: str(value.currency)!,
    status,
    unit_price: money(value.unit_price),
    unit_code: str(value.unit_code),
    price_list_code: str(value.price_list_code),
    item_id: str(value.item_id),
    product_moq: quantity(value.product_moq),
    recommendation:
      rec && str(rec.label)
        ? {
            status: str(rec.status) ?? "NOT_EVALUATED",
            quantity: quantity(rec.quantity),
            minimum_order_value: money(rec.minimum_order_value),
            carton_qty: int(rec.carton_qty),
            explanation: str(rec.explanation) ?? "",
            label: str(rec.label)!,
          }
        : null,
  };
}

/** `prices` is null when the server did not send it (redacted) — never an empty list in its place. */
function prices(value: unknown): ProductPriceColumn[] | null {
  if (!Array.isArray(value)) return null;
  return value.map(priceColumn).filter((entry): entry is ProductPriceColumn => entry !== null);
}

export function parseProductSummary(raw: unknown): ProductSummary | null {
  if (!isObject(raw) || !str(raw.id) || !str(raw.product_key) || !str(raw.product_name)) return null;
  const category = taxonomyRef(raw.category);
  if (!category) return null;
  const id = str(raw.id)!;
  return {
    id,
    product_key: str(raw.product_key)!,
    display_sku: str(raw.display_sku) ?? str(raw.product_key)!,
    product_name: str(raw.product_name)!,
    brand: str(raw.brand),
    category,
    subcategory: taxonomyRef(raw.subcategory),
    product_type: str(raw.product_type),
    variant_group: str(raw.variant_group),
    unit_of_sale: str(raw.unit_of_sale),
    decor_no: str(raw.decor_no),
    decor_name: str(raw.decor_name),
    finish: str(raw.finish),
    shape: str(raw.shape),
    status: PRODUCT_STATUSES.find((status) => status === raw.status) ?? "inactive",
    thickness_mm: dec(raw.thickness_mm),
    size: size(raw.size),
    carton_qty: int(raw.carton_qty),
    archived: raw.archived === true || str(raw.archived_at) !== null,
    updated_at: str(raw.updated_at) ?? "",
    path: safeAppPath(raw.path) ?? `/products/${encodeURIComponent(id)}`,
    prices: prices(raw.prices),
    redacted_fields: strings(raw.redacted_fields),
  };
}

function dimension(value: unknown): DimensionRead | null {
  if (!isObject(value) || !str(value.kind) || typeof value.source_text !== "string") return null;
  return {
    kind: str(value.kind)!,
    source_field: str(value.source_field) ?? "",
    source_text: value.source_text,
    length_mm: dec(value.length_mm),
    width_mm: dec(value.width_mm),
    height_mm: dec(value.height_mm),
    diameter_mm: dec(value.diameter_mm),
    source_unit: str(value.source_unit),
    unit_inferred: value.unit_inferred === true,
    parse_status: value.parse_status === "parsed" || value.parse_status === "ambiguous" ? value.parse_status : "unparsed",
    parse_warnings: strings(value.parse_warnings),
  };
}

function specification(value: unknown): SpecificationRead | null {
  if (!isObject(value)) return null;
  return {
    length_mm: dec(value.length_mm),
    length_mm_source: str(value.length_mm_source),
    width_mm: dec(value.width_mm),
    width_mm_source: str(value.width_mm_source),
    height_mm: dec(value.height_mm),
    height_mm_source: str(value.height_mm_source),
    thickness_mm: dec(value.thickness_mm),
    thickness_mm_source: str(value.thickness_mm_source),
    thickness_text: str(value.thickness_text),
    size_label: str(value.size_label),
    finish: str(value.finish),
    material_type: str(value.material_type),
    groove_count: int(value.groove_count),
    bowl_count: int(value.bowl_count),
    bowl_type: str(value.bowl_type),
    top_sheet: str(value.top_sheet),
    stand_material: str(value.stand_material),
    type: str(value.type),
    no_of_boards: int(value.no_of_boards),
    handle_type: str(value.handle_type),
    special_features: str(value.special_features),
    care_instructions: str(value.care_instructions),
    usage_notes: str(value.usage_notes),
  };
}

function aliasProvenance(value: unknown): Record<string, Record<string, string>> | null {
  if (!isObject(value)) return null;
  const out: Record<string, Record<string, string>> = {};
  for (const [field, detail] of Object.entries(value)) {
    if (!isObject(detail)) continue;
    const inner: Record<string, string> = {};
    for (const [key, text] of Object.entries(detail)) if (typeof text === "string") inner[key] = text;
    out[field] = inner;
  }
  return Object.keys(out).length > 0 ? out : null;
}

function packaging(value: unknown): PackagingRead | null {
  if (!isObject(value)) return null;
  return {
    carton_qty: int(value.carton_qty),
    inner_qty: int(value.inner_qty),
    unit_weight_g: dec(value.unit_weight_g),
    packing_type: str(value.packing_type),
    carton_length_cm: dec(value.carton_length_cm),
    carton_width_cm: dec(value.carton_width_cm),
    carton_height_cm: dec(value.carton_height_cm),
    net_weight_kg: dec(value.net_weight_kg),
    gross_weight_kg: dec(value.gross_weight_kg),
    cbm: dec(value.cbm),
    packaging_notes: str(value.packaging_notes),
    fragile_notes: str(value.fragile_notes),
    packaging_status: str(value.packaging_status),
    notes: str(value.notes),
    alias_provenance: aliasProvenance(value.alias_provenance),
    summary: str(value.summary),
    warnings: strings(value.warnings),
  };
}

function decor(value: unknown): DecorRead {
  const d = isObject(value) ? value : {};
  return {
    decor_no: str(d.decor_no),
    decor_no_source: str(d.decor_no_source),
    decor_name: str(d.decor_name),
    decor_primary: str(d.decor_primary),
    decor_options: strings(d.decor_options),
    decor_options_text: str(d.decor_options_text),
  };
}

function provenance(value: unknown): ProvenanceRead {
  const p = isObject(value) ? value : {};
  return {
    category_source: str(p.category_source),
    subcategory_source: str(p.subcategory_source),
    source_design_no: str(p.source_design_no),
    source_shape_no: str(p.source_shape_no),
    source_sheet: str(p.source_sheet),
    source_row: str(p.source_row),
    source_catalog_page: str(p.source_catalog_page),
    source_notes: str(p.source_notes),
    origin: str(p.origin) ?? "ui",
    origin_ref: str(p.origin_ref),
  };
}

function stockAttributes(value: unknown): StockAttributesRead {
  const s = isObject(value) ? value : {};
  return {
    hsn_sac: str(s.hsn_sac),
    stock_uom_code: str(s.stock_uom_code),
    is_stock_tracked: bool(s.is_stock_tracked),
    track_lots: bool(s.track_lots),
    qc_required: bool(s.qc_required),
  };
}

function notEvaluated(value: unknown): NotEvaluated[] {
  return arr(value).flatMap((entry) => (isObject(entry) && str(entry.code) ? [{ code: str(entry.code)!, reason: str(entry.reason) ?? "" }] : []));
}

function completeness(value: unknown): CompletenessRead {
  const c = isObject(value) ? value : {};
  return {
    score_pct: int(c.score_pct) ?? 0,
    checks_evaluated: int(c.checks_evaluated) ?? 0,
    checks_passed: int(c.checks_passed) ?? 0,
    missing: arr(c.missing).flatMap((entry) =>
      isObject(entry) && str(entry.code)
        ? [{ code: str(entry.code)!, severity: entry.severity === "info" ? ("info" as const) : ("warning" as const), label: str(entry.label) ?? str(entry.code)! }]
        : [],
    ),
    not_evaluated: notEvaluated(c.not_evaluated),
  };
}

export function parseProductDetail(raw: unknown): ProductDetail {
  const summary = need(parseProductSummary(raw), "product");
  const body = raw as Json;
  if (int(body.version) === null) throw new ProductsShapeError("The catalogue response could not be read (version).");
  return {
    ...summary,
    description: str(body.description),
    internal_remarks: str(body.internal_remarks),
    decor: decor(body.decor),
    stock_attributes: stockAttributes(body.stock_attributes),
    provenance: provenance(body.provenance),
    specification: specification(body.specification),
    packaging: packaging(body.packaging),
    dimensions: arr(body.dimensions).map(dimension).filter((entry): entry is DimensionRead => entry !== null),
    completeness: completeness(body.completeness),
    sections: arr(body.sections).flatMap((entry) => {
      const path = isObject(entry) ? safeAppPath(entry.path) : null;
      return isObject(entry) && str(entry.key) && path ? [{ key: str(entry.key)!, label: str(entry.label) ?? str(entry.key)!, path }] : [];
    }),
    version: int(body.version)!,
    created_at: str(body.created_at) ?? "",
    archived_at: str(body.archived_at),
    capabilities: capabilities(body.capabilities),
  };
}

function facetValues(value: unknown): FacetValue[] {
  return arr(value).flatMap((entry) =>
    isObject(entry) && typeof entry.value === "string" ? [{ value: entry.value, label: str(entry.label) ?? entry.value, count: int(entry.count) ?? 0 }] : [],
  );
}

export function parseProductFacets(raw: unknown): ProductFacets {
  if (!isObject(raw)) throw new ProductsShapeError("The catalogue response could not be read (facets).");
  const out = { total: int(raw.total) ?? 0 } as ProductFacets;
  for (const dimension of FACET_DIMENSIONS) out[dimension as FacetDimension] = facetValues(raw[dimension]);
  return out;
}

export function parseProductStats(raw: unknown): ProductStats {
  if (!isObject(raw) || int(raw.total) === null) throw new ProductsShapeError("The catalogue response could not be read (stats).");
  const byStatus: Record<string, number> = {};
  if (isObject(raw.by_status)) for (const [key, count] of Object.entries(raw.by_status)) if (int(count) !== null) byStatus[key] = int(count)!;
  return {
    total: int(raw.total)!,
    by_status: byStatus,
    archived: int(raw.archived) ?? 0,
    updated_last_7_days: int(raw.updated_last_7_days) ?? 0,
    by_category: arr(raw.by_category).flatMap((entry) =>
      isObject(entry) && str(entry.category_id) ? [{ category_id: str(entry.category_id)!, name: str(entry.name) ?? "", count: int(entry.count) ?? 0 }] : [],
    ),
    as_of: str(raw.as_of) ?? "",
  };
}

export function parseCompletenessSummary(raw: unknown): CompletenessSummary {
  if (!isObject(raw) || int(raw.total_products) === null) throw new ProductsShapeError("The catalogue response could not be read (completeness).");
  return {
    total_products: int(raw.total_products)!,
    complete_products: int(raw.complete_products) ?? 0,
    rules: arr(raw.rules).flatMap((entry) => {
      if (!isObject(entry) || !str(entry.code)) return [];
      const code = str(entry.code)!;
      return [
        {
          code,
          label: str(entry.label) ?? code,
          severity: entry.severity === "info" ? ("info" as const) : ("warning" as const),
          count: int(entry.count) ?? 0,
          filter_path:
            safeAppPath(entry.filter_path) ??
            (COMPLETENESS_RULES.some((rule) => rule === code) ? `/products?${new URLSearchParams({ issue: code }).toString()}` : null),
        },
      ];
    }),
    not_evaluated: notEvaluated(raw.not_evaluated),
  };
}

function subcategory(value: unknown): SubcategoryRead | null {
  if (!isObject(value) || !str(value.id) || !str(value.name)) return null;
  const isActive = value.is_active !== false;
  return {
    id: str(value.id)!,
    name: str(value.name)!,
    display_order: int(value.display_order) ?? 0,
    is_active: isActive,
    effective_active: bool(value.effective_active) ?? isActive,
    description: str(value.description),
    product_count: int(value.product_count) ?? 0,
  };
}

export function parseCategory(raw: unknown): CategoryRead | null {
  if (!isObject(raw) || !str(raw.id) || !str(raw.name)) return null;
  return {
    id: str(raw.id)!,
    name: str(raw.name)!,
    display_order: int(raw.display_order) ?? 0,
    is_active: raw.is_active !== false,
    description: str(raw.description),
    source_catalog_page_start: str(raw.source_catalog_page_start),
    source_catalog_page_end: str(raw.source_catalog_page_end),
    product_count: int(raw.product_count) ?? 0,
    subcategories: arr(raw.subcategories).map(subcategory).filter((entry): entry is SubcategoryRead => entry !== null),
  };
}

export function parseCategories(raw: unknown): CategoryRead[] {
  const list = isObject(raw) && Array.isArray(raw.items) ? raw.items : raw;
  if (!Array.isArray(list)) throw new ProductsShapeError("The catalogue response could not be read (categories).");
  return list.map(parseCategory).filter((entry): entry is CategoryRead => entry !== null);
}
