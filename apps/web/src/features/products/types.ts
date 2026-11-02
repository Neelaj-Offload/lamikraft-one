/**
 * The catalogue as the web uses it. The shapes mirror backend/app/modules/catalogue/schemas.py
 * (`ProductSummary`, `ProductDetail`, `ProductFacets`, `ProductStats`, `CompletenessSummary`,
 * `CategoryRead`); `parse.ts` is the only place that touches the wire.
 *
 * Measures, money and quantities are DecimalStr strings throughout; the web never does
 * arithmetic on them. Fields the server redacts are absent and named in `redacted_fields`;
 * `prices` is `null` when it was not sent.
 */

export interface Money {
  amount: string;
  currency: string;
}

export interface Quantity {
  value: string;
  uom: string;
}

export interface Capability {
  allowed: boolean;
  reason_code: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export const PRODUCT_STATUSES = ["active", "inactive", "under_development"] as const;
export type ProductStatus = (typeof PRODUCT_STATUSES)[number];

export const PRODUCT_SORTS = ["relevance", "product_key", "product_name", "-updated_at"] as const;
export type ProductSort = (typeof PRODUCT_SORTS)[number];

export const COMPLETENESS_RULES = [
  "no_decor",
  "no_specification",
  "no_thickness",
  "no_size",
  "unparsed_dimensions",
  "no_packaging",
  "no_carton_qty",
  "no_unit_weight",
  "category_inactive",
  "no_hsn_sac",
  "shared_display_sku",
] as const;
export type CompletenessRule = (typeof COMPLETENESS_RULES)[number];

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

export interface OrderValueRecommendation {
  status: string;
  quantity: Quantity | null;
  minimum_order_value: Money | null;
  carton_qty: number | null;
  explanation: string;
  label: string;
}

export type PriceColumnStatus = "found" | "ambiguous" | "not_found" | "unavailable";

/** The standard-tier price of a product in one currency; never converted or relabelled. */
export interface ProductPriceColumn {
  currency: string;
  status: PriceColumnStatus;
  unit_price: Money | null;
  unit_code: string | null;
  price_list_code: string | null;
  item_id: string | null;
  product_moq: Quantity | null;
  recommendation: OrderValueRecommendation | null;
}

export interface ProductSummary {
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
  decor_no: string | null;
  decor_name: string | null;
  finish: string | null;
  shape: string | null;
  status: ProductStatus;
  thickness_mm: string | null;
  size: ProductSize;
  carton_qty: number | null;
  archived: boolean;
  updated_at: string;
  path: string;
  /** Absent (null) without `pricing.price.read`. */
  prices: ProductPriceColumn[] | null;
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
  source_unit: string | null;
  unit_inferred: boolean;
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
  thickness_text: string | null;
  size_label: string | null;
  finish: string | null;
  material_type: string | null;
  groove_count: number | null;
  bowl_count: number | null;
  bowl_type: string | null;
  top_sheet: string | null;
  stand_material: string | null;
  type: string | null;
  no_of_boards: number | null;
  handle_type: string | null;
  special_features: string | null;
  care_instructions: string | null;
  usage_notes: string | null;
}

export interface PackagingRead {
  carton_qty: number | null;
  inner_qty: number | null;
  unit_weight_g: string | null;
  packing_type: string | null;
  carton_length_cm: string | null;
  carton_width_cm: string | null;
  carton_height_cm: string | null;
  net_weight_kg: string | null;
  gross_weight_kg: string | null;
  cbm: string | null;
  packaging_notes: string | null;
  fragile_notes: string | null;
  packaging_status: string | null;
  notes: string | null;
  alias_provenance: Record<string, Record<string, string>> | null;
  summary: string | null;
  warnings: string[];
}

export interface DecorRead {
  decor_no: string | null;
  decor_no_source: string | null;
  decor_name: string | null;
  decor_primary: string | null;
  decor_options: string[];
  decor_options_text: string | null;
}

export interface ProvenanceRead {
  category_source: string | null;
  subcategory_source: string | null;
  source_design_no: string | null;
  source_shape_no: string | null;
  source_sheet: string | null;
  source_row: string | null;
  source_catalog_page: string | null;
  source_notes: string | null;
  origin: string;
  origin_ref: string | null;
}

export interface StockAttributesRead {
  hsn_sac: string | null;
  stock_uom_code: string | null;
  is_stock_tracked: boolean | null;
  track_lots: boolean | null;
  qc_required: boolean | null;
}

export interface CompletenessIssue {
  code: string;
  severity: "warning" | "info";
  label: string;
}

export interface NotEvaluated {
  code: string;
  reason: string;
}

export interface CompletenessRead {
  score_pct: number;
  checks_evaluated: number;
  checks_passed: number;
  missing: CompletenessIssue[];
  not_evaluated: NotEvaluated[];
}

export interface SectionRead {
  key: string;
  label: string;
  path: string;
}

export interface ProductDetail extends ProductSummary {
  description: string | null;
  internal_remarks: string | null;
  decor: DecorRead;
  stock_attributes: StockAttributesRead;
  provenance: ProvenanceRead;
  specification: SpecificationRead | null;
  packaging: PackagingRead | null;
  dimensions: DimensionRead[];
  completeness: CompletenessRead;
  sections: SectionRead[];
  version: number;
  created_at: string;
  archived_at: string | null;
  capabilities: Readonly<Record<string, Capability>>;
}

export interface FacetValue {
  value: string;
  label: string;
  count: number;
}

export const FACET_DIMENSIONS = [
  "categories",
  "subcategories",
  "families",
  "sizes",
  "thicknesses",
  "decors",
  "finishes",
  "statuses",
  "brands",
] as const;
export type FacetDimension = (typeof FACET_DIMENSIONS)[number];

export type ProductFacets = { total: number } & Record<FacetDimension, FacetValue[]>;

export interface CategoryCount {
  category_id: string;
  name: string;
  count: number;
}

export interface ProductStats {
  total: number;
  by_status: Record<string, number>;
  archived: number;
  updated_last_7_days: number;
  by_category: CategoryCount[];
  as_of: string;
}

export interface CompletenessRuleCount {
  code: string;
  label: string;
  severity: "warning" | "info";
  count: number;
  /** In-app list path with the rule's `issue` filter applied; null when the server's path was not in-app. */
  filter_path: string | null;
}

export interface CompletenessSummary {
  total_products: number;
  complete_products: number;
  rules: CompletenessRuleCount[];
  not_evaluated: NotEvaluated[];
}

export interface SubcategoryRead {
  id: string;
  name: string;
  display_order: number;
  is_active: boolean;
  effective_active: boolean;
  description: string | null;
  product_count: number;
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
}
