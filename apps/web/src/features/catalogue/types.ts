/**
 * Catalogue wire types (INTERIM(api-generate): hand-written from the catalogue lane's Pydantic models until the
 * integrator regenerates `schema.d.ts`). Money and quantities stay strings; never parsed to floats.
 */

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Capability {
  allowed: boolean;
  reason_code: string | null;
}

export interface TaxonomyRef {
  id: string;
  name: string;
  is_active: boolean;
}

export interface ProductSize {
  length_mm: string | null;
  width_mm: string | null;
  height_mm: string | null;
  diameter_mm: string | null;
  basis: string | null;
}

export interface MediaThumb {
  media_id: string;
  file_id: string;
  url: string;
  alt_text: string | null;
}

export interface PriceColumn {
  currency: string;
  status: string;
  unit_price?: { amount: string; currency: string } | null;
  [key: string]: unknown;
}

export const PRODUCT_STATUSES = ["active", "inactive", "under_development"] as const;
export type ProductStatus = (typeof PRODUCT_STATUSES)[number];

export interface ProductSummary {
  id: string;
  product_key: string;
  display_sku: string;
  product_name: string;
  brand: string | null;
  category: TaxonomyRef;
  subcategory: TaxonomyRef | null;
  decor_no: string | null;
  decor_name: string | null;
  finish: string | null;
  status: ProductStatus;
  thickness_mm: string | null;
  size: ProductSize;
  carton_qty: number | null;
  primary_image: MediaThumb | null;
  archived: boolean;
  updated_at: string;
  path: string;
  prices?: PriceColumn[] | null;
  redacted_fields: string[];
}

export interface DimensionRead {
  kind: string;
  source_field: string;
  source_text: string;
  length_mm: string | null;
  width_mm: string | null;
  height_mm: string | null;
  diameter_mm: string | null;
  parse_status: "parsed" | "ambiguous" | "unparsed";
  parse_warnings: string[];
}

export interface SpecificationRead {
  length_mm: string | null;
  length_mm_source: string | null;
  width_mm: string | null;
  width_mm_source: string | null;
  height_mm: string | null;
  height_mm_source: string | null;
  thickness_mm: string | null;
  thickness_mm_source: string | null;
  [field: string]: unknown;
}

export interface PackagingRead {
  carton_qty: number | null;
  inner_qty: number | null;
  unit_weight_g: string | null;
  packing_type: string | null;
  summary: string | null;
  warnings: string[];
  alias_provenance: Record<string, unknown> | null;
  [field: string]: unknown;
}

export interface CompletenessIssue {
  code: string;
  severity: "warning" | "info";
  label: string;
}

export interface ProductDetail {
  id: string;
  product_key: string;
  display_sku: string;
  product_name: string;
  brand: string | null;
  category: TaxonomyRef;
  subcategory: TaxonomyRef | null;
  product_type: string | null;
  variant_group: string | null;
  unit_of_sale: string | null;
  finish: string | null;
  shape: string | null;
  status: ProductStatus;
  description: string | null;
  internal_remarks: string | null;
  decor: {
    decor_no: string | null;
    decor_no_source: string | null;
    decor_name: string | null;
    decor_primary: string | null;
    decor_options: string[];
    decor_options_text: string | null;
  };
  size: ProductSize;
  stock_attributes: Record<string, unknown>;
  provenance: Record<string, unknown>;
  specification: SpecificationRead | null;
  packaging: PackagingRead | null;
  dimensions: DimensionRead[];
  completeness: { score_pct: number; checks_evaluated: number; checks_passed: number; missing: CompletenessIssue[] };
  primary_image: MediaThumb | null;
  media_count: number;
  sections: { key: string; label: string; path: string }[];
  version: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  path: string;
  capabilities: Record<string, Capability>;
  prices?: PriceColumn[] | null;
  redacted_fields: string[];
}

export interface ProductWriteResult {
  product: ProductDetail;
  warnings: string[];
}

export interface FacetValue {
  value: string;
  label: string;
  count: number;
}

export interface ProductFacets {
  total: number;
  categories: FacetValue[];
  subcategories: FacetValue[];
  families: FacetValue[];
  sizes: FacetValue[];
  thicknesses: FacetValue[];
  decors: FacetValue[];
  finishes: FacetValue[];
  statuses: FacetValue[];
  brands: FacetValue[];
}

export interface ProductStats {
  total: number;
  by_status: Record<string, number>;
  archived: number;
  updated_last_7_days: number;
  without_active_price: number | null;
  by_category: { category_id: string; name: string; count: number }[];
}

export interface SubcategoryRead {
  id: string;
  name: string;
  display_order: number;
  is_active: boolean;
  effective_active: boolean;
  description: string | null;
  product_count: number;
  version: number;
}

export interface CategoryRead {
  id: string;
  name: string;
  display_order: number;
  is_active: boolean;
  description: string | null;
  source_catalog_page_start: string | null;
  source_catalog_page_end: string | null;
  product_count: number;
  subcategories: SubcategoryRead[];
  version: number;
}

export interface TaxonomyReferences {
  id: string;
  kind: "category" | "subcategory";
  name: string;
  total: number;
  references: { table: string; label: string; count: number; reassignable: boolean }[];
  aliases: string[];
}

export interface CompletenessSummary {
  total_products: number;
  complete_products: number;
  rules: { code: string; label: string; severity: "warning" | "info"; count: number; filter_path: string }[];
  not_evaluated: { code: string; reason: string }[];
}

export interface MediaRead {
  id: string;
  product_id: string;
  media_type: "image" | "document" | "packaging_photo";
  file_id: string | null;
  file_name: string | null;
  original_filename: string | null;
  content_type: string | null;
  size_bytes: number | null;
  alt_text: string | null;
  is_primary: boolean;
  source_kind: string;
  source_url_key: string | null;
  ingest_status: string;
  uploaded_by_name: string | null;
  uploaded_at: string;
  deleted_at: string | null;
  delete_reason: string | null;
  content_url: string | null;
  previewable: boolean;
  version: number;
  capabilities: Record<string, Capability>;
}

export interface MediaGroups {
  product_id: string;
  image: MediaRead[];
  packaging_photo: MediaRead[];
  document: MediaRead[];
  deleted: MediaRead[];
}

export interface HistoryEntry {
  id: string;
  occurred_at: string;
  action: string;
  actor_name: string | null;
  actor_type: string;
  changed_fields: string[];
  reason: string | null;
}

export interface LookupRead {
  id: string;
  lookup_type: string;
  key_1: string;
  key_2: string;
  value_1: string | null;
  value_2: string | null;
  notes: string | null;
  updated_at: string;
}
