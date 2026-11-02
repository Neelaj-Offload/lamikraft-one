import { describe, expect, it } from "vitest";
import {
  pageOf,
  parseCategories,
  parseCompletenessSummary,
  parseProductDetail,
  parseProductFacets,
  parseProductStats,
  parseProductSummary,
  ProductsShapeError,
} from "./parse";

const PRODUCT = "0192b000-0000-7000-8000-000000000001";
const CATEGORY = "0192b000-0000-7000-8000-00000000000c";

function summaryWire(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: PRODUCT,
    product_key: "LK-0120-450",
    display_sku: "LK-0120-450-S",
    product_name: "Natural Oak Serving Board",
    brand: "Lamikraft",
    category: { id: CATEGORY, name: "Boards", is_active: true },
    subcategory: { id: "0192b000-0000-7000-8000-00000000000d", name: "Serving", is_active: true },
    product_type: "board",
    variant_group: "Serving boards",
    unit_of_sale: "pcs",
    decor_no: "0120",
    decor_name: "Natural Oak",
    finish: "Matt",
    shape: "Rectangle",
    status: "active",
    thickness_mm: "0.8",
    size: { length_mm: "450", width_mm: "300", height_mm: null, diameter_mm: null, basis: "master_size" },
    carton_qty: 24,
    archived: false,
    updated_at: "2026-10-30T09:00:00Z",
    path: `/products/${PRODUCT}`,
    ...overrides,
  };
}

const PRICE_COLUMNS = [
  {
    currency: "EUR",
    status: "found",
    unit_price: { amount: "24.0000", currency: "EUR" },
    unit_code: "pcs",
    price_list_code: "EXP-EUR-2026",
    item_id: "0192b000-0000-7000-8000-0000000000aa",
    product_moq: { value: "48", uom: "pcs" },
    recommendation: { status: "AVAILABLE", quantity: { value: "48", uom: "pcs" }, minimum_order_value: { amount: "1500.00", currency: "EUR" }, carton_qty: 24, explanation: "Two cartons", label: "Order 48 pcs" },
  },
  { currency: "INR", status: "ambiguous", unit_price: null, unit_code: null, price_list_code: null, item_id: null, product_moq: null, recommendation: null },
];

describe("parseProductSummary", () => {
  it("reads a row, keeps measures as strings and the path in-app", () => {
    const product = parseProductSummary(summaryWire({ prices: PRICE_COLUMNS, redacted_fields: [] }))!;
    expect(product.product_key).toBe("LK-0120-450");
    expect(product.size.length_mm).toBe("450");
    expect(product.thickness_mm).toBe("0.8");
    expect(product.carton_qty).toBe(24);
    expect(product.status).toBe("active");
    expect(product.path).toBe(`/products/${PRODUCT}`);
    expect(product.prices).toHaveLength(2);
    expect(product.prices![0]).toMatchObject({ status: "found", unit_code: "pcs", unit_price: { amount: "24.0000", currency: "EUR" } });
    expect(product.prices![0]!.recommendation?.label).toBe("Order 48 pcs");
    expect(product.prices![1]).toMatchObject({ currency: "INR", status: "ambiguous", unit_price: null });
  });

  it("leaves prices null when the server redacted them (never an empty list or a mask)", () => {
    const product = parseProductSummary(summaryWire({ redacted_fields: ["prices"] }))!;
    expect(product.prices).toBeNull();
    expect(product.redacted_fields).toEqual(["prices"]);
  });

  it("drops a row without its identity or category, and an off-site path", () => {
    expect(parseProductSummary(summaryWire({ id: undefined }))).toBeNull();
    expect(parseProductSummary(summaryWire({ category: null }))).toBeNull();
    expect(parseProductSummary(summaryWire({ path: "https://evil.example/products" }))!.path).toBe(`/products/${PRODUCT}`);
  });

  it("rejects measures that are not DecimalStr instead of converting them", () => {
    const product = parseProductSummary(summaryWire({ thickness_mm: 0.8, size: { length_mm: "45 cm", width_mm: "300" } }))!;
    expect(product.thickness_mm).toBeNull();
    expect(product.size.length_mm).toBeNull();
    expect(product.size.width_mm).toBe("300");
  });

  it("reads a Page[ProductSummary]", () => {
    const page = pageOf({ items: [summaryWire(), { id: "broken" }], total: 2, limit: 25, offset: 0 }, parseProductSummary);
    expect(page.items).toHaveLength(1);
    expect(page.total).toBe(2);
    expect(() => pageOf({ total: 1 }, parseProductSummary)).toThrow(ProductsShapeError);
  });
});

describe("parseProductDetail", () => {
  const detailWire = () =>
    summaryWire({
      description: "A board.",
      internal_remarks: "Check the edge.",
      decor: { decor_no: "0120", decor_no_source: "120", decor_name: "Natural Oak", decor_primary: "Oak", decor_options: ["0120", "0310"], decor_options_text: null },
      stock_attributes: { hsn_sac: "44219990", stock_uom_code: "pcs", is_stock_tracked: true, track_lots: false, qc_required: null },
      provenance: { category_source: "Boards", subcategory_source: null, source_design_no: "D-12", source_shape_no: null, source_sheet: "Sheet1", source_row: "12", source_catalog_page: "4", source_notes: null, source_extra: null, origin: "import", origin_ref: "cat-2026.xlsx" },
      specification: { length_mm: "450", length_mm_source: "45 cm", width_mm: "300", width_mm_source: null, height_mm: null, height_mm_source: null, thickness_mm: "0.8", thickness_mm_source: "0.80", thickness_text: null, size_label: "450x300", finish: "Matt", material_type: "Laminate", groove_count: 2, bowl_count: null, bowl_type: null, top_sheet: null, stand_material: null, type: null, no_of_boards: null, handle_type: null, special_features: null, care_instructions: null, usage_notes: null, source_extra: null },
      packaging: { carton_qty: 24, inner_qty: 6, unit_weight_g: "450", packing_type: "Poly bag", carton_length_cm: null, carton_width_cm: null, carton_height_cm: null, net_weight_kg: null, gross_weight_kg: null, cbm: null, packaging_notes: null, fragile_notes: null, packaging_status: null, notes: null, alias_provenance: { carton_qty: { master_carton_qty: "24" } }, source_extra: null, summary: "450g · 24/ctn · Poly bag", warnings: ["Inner quantity does not divide the carton"] },
      dimensions: [{ kind: "spec_size", source_field: "size_mm", source_text: "45 x 30 cm", length_mm: "450", width_mm: "300", height_mm: null, diameter_mm: null, source_unit: "cm", unit_inferred: false, parse_status: "parsed", parse_warnings: [] }],
      completeness: { score_pct: 78, checks_evaluated: 9, checks_passed: 7, missing: [{ code: "no_hsn_sac", severity: "warning", label: "No HSN/SAC" }, { code: "no_unit_weight", severity: "info", label: "No unit weight" }], not_evaluated: [{ code: "shared_display_sku", reason: "Needs the SKU index" }] },
      sections: [{ key: "specification", label: "Specification", path: `/products/${PRODUCT}?tab=specification` }],
      version: 3,
      created_at: "2026-01-01T00:00:00Z",
      archived_at: null,
      capabilities: { update: { allowed: true, reason_code: null } },
      allowed_transitions: [],
    });

  it("reads every section, keeping entered text next to canonical measures", () => {
    const product = parseProductDetail(detailWire());
    expect(product.version).toBe(3);
    expect(product.decor.decor_options).toEqual(["0120", "0310"]);
    expect(product.specification?.length_mm_source).toBe("45 cm");
    expect(product.packaging?.summary).toBe("450g · 24/ctn · Poly bag");
    expect(product.packaging?.alias_provenance).toEqual({ carton_qty: { master_carton_qty: "24" } });
    expect(product.dimensions[0]).toMatchObject({ kind: "spec_size", parse_status: "parsed", length_mm: "450" });
    expect(product.completeness).toMatchObject({ checks_passed: 7, checks_evaluated: 9 });
    expect(product.completeness.missing.map((issue) => issue.severity)).toEqual(["warning", "info"]);
    expect(product.completeness.not_evaluated[0]?.code).toBe("shared_display_sku");
    expect(product.sections[0]?.path).toBe(`/products/${PRODUCT}?tab=specification`);
    expect(product.capabilities.update?.allowed).toBe(true);
    expect(product.prices).toBeNull();
  });

  it("throws a ProductsShapeError without a version or an identity", () => {
    expect(() => parseProductDetail({ ...detailWire(), version: "3" })).toThrow(ProductsShapeError);
    expect(() => parseProductDetail({ version: 1 })).toThrow(ProductsShapeError);
  });
});

describe("facets, stats, completeness and categories", () => {
  it("reads every facet dimension and defaults a missing one to an empty list", () => {
    const facets = parseProductFacets({
      total: 12,
      categories: [{ value: CATEGORY, label: "Boards", count: 12 }],
      statuses: [{ value: "active", label: "active", count: 10 }],
    });
    expect(facets.total).toBe(12);
    expect(facets.categories[0]).toEqual({ value: CATEGORY, label: "Boards", count: 12 });
    expect(facets.decors).toEqual([]);
    expect(() => parseProductFacets(null)).toThrow(ProductsShapeError);
  });

  it("reads the stats with only the status keys the server returned", () => {
    const stats = parseProductStats({ total: 120, by_status: { active: 100, inactive: 20 }, archived: 3, updated_last_7_days: 8, by_category: [], recently_changed: [], as_of: "2026-11-02T00:00:00Z" });
    expect(stats.by_status).toEqual({ active: 100, inactive: 20 });
    expect("under_development" in stats.by_status).toBe(false);
    expect(stats.archived).toBe(3);
    expect(() => parseProductStats({ by_status: {} })).toThrow(ProductsShapeError);
  });

  it("keeps completeness filter paths in-app and rebuilds a known rule's path when the server's is not", () => {
    const summary = parseCompletenessSummary({
      total_products: 120,
      complete_products: 80,
      rules: [
        { code: "no_decor", label: "No decor", severity: "warning", count: 4, filter_path: "/products?issue=no_decor" },
        { code: "no_size", label: "No size", severity: "info", count: 2, filter_path: "https://evil.example/" },
      ],
      not_evaluated: [{ code: "shared_display_sku", reason: "pending" }],
    });
    expect(summary.rules[0]?.filter_path).toBe("/products?issue=no_decor");
    expect(summary.rules[1]?.filter_path).toBe("/products?issue=no_size");
    expect(summary.not_evaluated).toEqual([{ code: "shared_display_sku", reason: "pending" }]);
  });

  it("reads categories with their subcategories", () => {
    const categories = parseCategories([
      {
        id: CATEGORY,
        name: "Boards",
        display_order: 1,
        is_active: true,
        description: null,
        source_catalog_page_start: "4",
        source_catalog_page_end: "9",
        product_count: 12,
        subcategories: [{ id: "0192b000-0000-7000-8000-00000000000d", name: "Serving", display_order: 1, is_active: false, effective_active: false, description: null, product_count: 3 }],
      },
      { name: "broken" },
    ]);
    expect(categories).toHaveLength(1);
    expect(categories[0]?.subcategories[0]).toMatchObject({ name: "Serving", is_active: false, effective_active: false, product_count: 3 });
    expect(() => parseCategories({})).toThrow(ProductsShapeError);
  });
});
