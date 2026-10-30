import { describe, expect, it, vi } from "vitest";
import { ProblemError, conflictFromError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { controlsWithoutVisibleFocus, renderWithQueries, seedQueryError, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { fieldErrors, productExportHref } from "./api";
import { CompletenessReport } from "./completeness";
import { createBody, dirtyFields, masterPatch, masterValues, packagingValues, sectionBody, SPEC_FIELDS, specValues } from "./form-model";
import { activeFilterCount, productFilterQuery, productListHref, productListQuery, productListStateFrom } from "./list-state";
import { LookupBrowser, lookupHref, lookupStateFrom } from "./lookups";
import { ProductDetailView } from "./product-detail";
import { NewProductForm, taxonomyOptions } from "./product-form";
import { ProductCatalogue } from "./product-list";
import { deletePlan, moved, TaxonomyManager } from "./taxonomy";
import type { CategoryRead, ProductDetail, ProductSummary } from "./types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/products",
  useSearchParams: () => new URLSearchParams(),
}));

const PRODUCT_ID = "0192a000-0000-7000-8000-0000000000e1";
const CATEGORY_ID = "0192a000-0000-7000-8000-0000000000f1";

const bootstrap = (keys: string[]) =>
  testBootstrap({ permissions: keys.map((key) => ({ key, scope: "company" })) });
const reader = () => bootstrap(["catalogue.product.read", "pricing.price.read"]);
const editor = () =>
  bootstrap([
    "catalogue.product.read",
    "catalogue.product.create",
    "catalogue.product.update",
    "catalogue.product.archive",
    "catalogue.product.export",
    "catalogue.taxonomy.manage",
    "catalogue.media.manage",
    "catalogue.lookup.read",
  ]);

function summary(overrides: Partial<ProductSummary> = {}): ProductSummary {
  return {
    id: PRODUCT_ID,
    product_key: "LK-OT-0450",
    display_sku: "OT-450",
    product_name: "Oak serving tray 450",
    brand: "LK",
    category: { id: CATEGORY_ID, name: "Serveware", is_active: true },
    subcategory: { id: "0192a000-0000-7000-8000-0000000000f2", name: "Trays", is_active: true },
    decor_no: "0120",
    decor_name: "Natural oak",
    finish: "Matte lacquer",
    status: "active",
    thickness_mm: "12",
    size: { length_mm: "450", width_mm: "300", height_mm: null, diameter_mm: null, basis: "master_size" },
    carton_qty: 24,
    primary_image: null,
    archived: false,
    updated_at: "2026-10-12T03:25:00Z",
    path: `/products/${PRODUCT_ID}`,
    redacted_fields: [],
    ...overrides,
  };
}

function detail(overrides: Partial<ProductDetail> = {}): ProductDetail {
  return {
    ...summary(),
    product_type: "Tray",
    variant_group: "Oak serving tray",
    unit_of_sale: "pcs",
    shape: "Rectangular",
    description: null,
    internal_remarks: null,
    decor: { decor_no: "0120", decor_no_source: "0120", decor_name: "Natural oak", decor_primary: null, decor_options: ["0310"], decor_options_text: null },
    stock_attributes: { hsn_sac: null },
    provenance: { origin: "seed", source_sheet: "Master" },
    specification: { length_mm: "450", length_mm_source: "45 cm", width_mm: "300", width_mm_source: "300", height_mm: null, height_mm_source: null, thickness_mm: "12", thickness_mm_source: "12", material_type: "Oak veneer" },
    packaging: { carton_qty: 24, inner_qty: 6, unit_weight_g: "450", packing_type: "Poly bag", summary: "450g · 24/ctn · Poly bag", warnings: [], alias_provenance: null },
    dimensions: [{ kind: "master_size", source_field: "size_mm", source_text: "450 x 300", length_mm: "450", width_mm: "300", height_mm: null, diameter_mm: null, parse_status: "parsed", parse_warnings: [] }],
    completeness: { score_pct: 80, checks_evaluated: 10, checks_passed: 8, missing: [{ code: "no_image", severity: "warning", label: "No stored image" }] },
    primary_image: null,
    media_count: 0,
    sections: [
      { key: "overview", label: "Overview", path: `/products/${PRODUCT_ID}` },
      { key: "specifications", label: "Specifications", path: `/products/${PRODUCT_ID}/specifications` },
      { key: "media", label: "Media", path: `/products/${PRODUCT_ID}/media` },
      { key: "history", label: "History", path: `/products/${PRODUCT_ID}/history` },
    ],
    version: 3,
    created_at: "2026-10-01T03:25:00Z",
    archived_at: null,
    capabilities: {
      update: { allowed: true, reason_code: null },
      archive: { allowed: true, reason_code: null },
      restore: { allowed: false, reason_code: "product_not_archived" },
      manage_media: { allowed: true, reason_code: null },
    },
    prices: [{ currency: "EUR", status: "found", unit_price: { amount: "24.0000", currency: "EUR" } }],
    ...overrides,
  } as ProductDetail;
}

const problem = (status: number, code: string, extra: Record<string, unknown> = {}) =>
  new ProblemError({ type: "about:blank", title: "Problem", status, code, detail: "detail", request_id: "req-1", ...extra });

describe("product list state lives in the URL", () => {
  it("round-trips filters, falls back on bad values and aligns the offset to the page size", () => {
    const state = productListStateFrom({ q: "oak", thickness: "0.8", status: "bogus", limit: "50", offset: "73", has_image: "true", category: "not-a-uuid" });
    expect(state).toMatchObject({ q: "oak", thickness: "0.8", status: null, limit: 50, offset: 50, hasImage: true, category: null });
    expect(productListHref(state)).toBe("/products?q=oak&thickness=0.8&has_image=true&limit=50&offset=50");
    expect(productListStateFrom({ limit: "7" }).limit).toBe(25);
    expect(activeFilterCount(state)).toBe(2);
  });

  it("sends filters to the API and keeps sort and paging out of facets and exports", () => {
    const state = productListStateFrom({ q: "tray", category: CATEGORY_ID, sort: "relevance", offset: "25" });
    expect(productListQuery(state)).toEqual({ q: "tray", category_id: CATEGORY_ID, sort: "relevance", limit: 25, offset: 25 });
    expect(productFilterQuery(state)).toEqual({ q: "tray", category_id: CATEGORY_ID });
    expect(productExportHref(state)).toBe(`/api/v1/catalogue/products/export.csv?q=tray&category_id=${CATEGORY_ID}`);
    expect(productListQuery(productListStateFrom({ sort: "relevance" })).sort).toBe("product_key"); // no query, no relevance
  });
});

describe("product form model", () => {
  it("patches only dirty master fields with the current version and splits decor options", () => {
    const initial = masterValues(detail());
    expect(initial.size_mm).toBe("450 x 300");
    const current = { ...initial, finish: "Oiled", decor_options: "0310, 0415", brand: "" };
    expect(dirtyFields(initial, current).sort()).toEqual(["brand", "decor_options", "finish"]);
    expect(masterPatch(initial, current, 3)).toEqual({ expected_version: 3, finish: "Oiled", decor_options: ["0310", "0415"], brand: null });
  });

  it("keeps entered dimension text and builds full sections for PUT", () => {
    const spec = specValues(detail());
    expect(spec.length_mm).toBe("45 cm"); // the source text, not the canonical millimetres
    expect(sectionBody(SPEC_FIELDS, { ...spec, groove_count: "3" })).toMatchObject({ length_mm: "45 cm", thickness_mm: "12", groove_count: 3 });
    expect(packagingValues(detail()).unit_weight_g).toBe("450");
  });

  it("creates with key, taxonomy and only non-empty sections", () => {
    const body = createBody({ product_key: " LK-NEW ", category_id: CATEGORY_ID, status: "active", product_name: "New", "spec.thickness_mm": "18", "pack.carton_qty": "" });
    expect(body).toEqual({ product_key: "LK-NEW", category_id: CATEGORY_ID, status: "active", product_name: "New", specification: { thickness_mm: "18" } });
  });

  it("maps 422 field errors to dotted paths and recognises 409 conflicts", () => {
    const error = problem(422, "validation_failed", { errors: [{ loc: ["body", "packaging", "carton_qty"], msg: "Alias values disagree", code: "alias_conflict" }] });
    expect(fieldErrors(error)).toEqual({ "packaging.carton_qty": "Alias values disagree" });
    expect(fieldErrors(new Error("x"))).toEqual({});
    expect(conflictFromError(problem(409, "version_conflict"))?.code).toBe("version_conflict");
  });

  it("offers only active taxonomy in pickers", () => {
    const categories: CategoryRead[] = [
      { id: "a", name: "Live", display_order: 1, is_active: true, description: null, source_catalog_page_start: null, source_catalog_page_end: null, product_count: 1, version: 1,
        subcategories: [
          { id: "s1", name: "On", display_order: 1, is_active: true, effective_active: true, description: null, product_count: 0, version: 1 },
          { id: "s2", name: "Off", display_order: 2, is_active: false, effective_active: false, description: null, product_count: 0, version: 1 },
        ] },
      { id: "b", name: "Hidden", display_order: 2, is_active: false, description: null, source_catalog_page_start: null, source_catalog_page_end: null, product_count: 0, version: 1, subcategories: [] },
    ];
    expect(taxonomyOptions(categories, "a")).toEqual({ categories: [{ id: "a", label: "Live" }], subcategories: [{ id: "s1", label: "On" }] });
  });
});

describe("product catalogue screen", () => {
  const state = productListStateFrom({});
  const seed = (client: import("@tanstack/react-query").QueryClient, items: ProductSummary[]) => {
    client.setQueryData(queryKeys.catalogue.products(productListQuery(state)), { items, total: items.length, limit: 25, offset: 0 });
    client.setQueryData(queryKeys.catalogue.stats(), { total: 4, by_status: { active: 4 }, archived: 1, updated_last_7_days: 2, without_active_price: 1, by_category: [{ category_id: CATEGORY_ID, name: "Serveware", count: 3 }] });
  };

  it("renders rows, summary figures and category chips; create and export only with their permissions", () => {
    const html = renderWithQueries(<ProductCatalogue state={state} />, (c) => seed(c, [summary()]), editor());
    const text = textOf(html);
    expect(text).toContain("LK-OT-0450");
    expect(text).toContain("450 × 300 mm");
    expect(text).toContain("4 live products · 4 active · 2 updated in 7 days · 1 without a current price · 1 archived");
    expect(text).toContain("Add product");
    expect(text).toContain("Export CSV");
    expect(html).toContain('aria-label="Categories"');
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
    const readOnly = textOf(renderWithQueries(<ProductCatalogue state={state} />, (c) => seed(c, [summary()]), reader()));
    expect(readOnly).not.toContain("Add product");
    expect(readOnly).not.toContain("Export CSV");
  });

  it("shows an empty state and an error state", () => {
    expect(textOf(renderWithQueries(<ProductCatalogue state={state} />, (c) => seed(c, []), reader()))).toContain("No products match");
    const failed = renderWithQueries(
      <ProductCatalogue state={state} />,
      (c) => seedQueryError(c, queryKeys.catalogue.products(productListQuery(state)), problem(500, "internal_error")),
      reader(),
    );
    expect(textOf(failed)).not.toContain("LK-OT-0450");
    expect(failed).toContain("role=");
  });

  it("is a loading region before data arrives", () => {
    expect(renderWithQueries(<ProductCatalogue state={state} />, () => undefined, reader())).toContain("aria-busy");
  });
});

describe("product detail screen", () => {
  it("shows capability-driven actions, tabs with deep links and the overview", () => {
    const html = renderWithQueries(<ProductDetailView productId={PRODUCT_ID} section="overview" />, (c) => c.setQueryData(queryKeys.catalogue.product(PRODUCT_ID), detail()), editor());
    const text = textOf(html);
    expect(text).toContain("Oak serving tray 450");
    expect(text).toContain("Archive");
    expect(text).not.toContain("Restore");
    expect(text).toContain("EUR: 24.0000");
    expect(text).toContain("No stored image");
    expect(html).toContain(`href="/products/${PRODUCT_ID}/specifications"`);
    expect(html).toContain('aria-current="page"');
  });

  it("disables editing with the reason for archived products and offers Restore", () => {
    const archived = detail({
      archived_at: "2026-10-11T03:25:00Z",
      capabilities: {
        update: { allowed: false, reason_code: "product_archived" },
        archive: { allowed: false, reason_code: "product_archived" },
        restore: { allowed: true, reason_code: null },
        manage_media: { allowed: false, reason_code: "product_archived" },
      },
    });
    const html = renderWithQueries(<ProductDetailView productId={PRODUCT_ID} section="overview" />, (c) => c.setQueryData(queryKeys.catalogue.product(PRODUCT_ID), archived), editor());
    expect(textOf(html)).toContain("Restore the product to edit it");
    expect(textOf(html)).toContain("Archived");
    expect(textOf(html)).not.toContain("Archive product");
  });

  it("shows a calm state when the product is forbidden or missing", () => {
    const html = renderWithQueries(
      <ProductDetailView productId={PRODUCT_ID} section="overview" />,
      (c) => seedQueryError(c, queryKeys.catalogue.product(PRODUCT_ID), problem(404, "not_found")),
      reader(),
    );
    expect(textOf(html)).not.toContain("Oak serving tray 450");
  });

  it("renders the specifications tab from the entered text", () => {
    const html = renderWithQueries(<ProductDetailView productId={PRODUCT_ID} section="specifications" />, (c) => c.setQueryData(queryKeys.catalogue.product(PRODUCT_ID), detail()), editor());
    expect(textOf(html)).toContain("45 cm");
    expect(textOf(html)).toContain("Oak veneer");
  });
});

describe("taxonomy, completeness, lookups and the create form", () => {
  it("plans deletes: reassign when referenced, blocked when a table cannot be moved", () => {
    const refs = { id: "x", kind: "category" as const, name: "Serveware", total: 5, aliases: [], references: [{ table: "catalogue_product", label: "Products", count: 5, reassignable: true }] };
    expect(deletePlan(refs)).toEqual({ blocked: false, needsTarget: true, counts: { catalogue_product: 5 } });
    expect(deletePlan({ ...refs, references: [...refs.references, { table: "catalogue_subcategory", label: "Subcategories", count: 2, reassignable: false }] }).blocked).toBe(true);
    expect(moved(["a", "b", "c"], "b", -1)).toEqual(["b", "a", "c"]);
    expect(moved(["a", "b"], "a", -1)).toEqual(["a", "b"]);
  });

  it("taxonomy, the create form and lookups are refused without their permissions", () => {
    expect(textOf(renderWithQueries(<TaxonomyManager />, () => undefined, reader()))).not.toContain("New category");
    expect(textOf(renderWithQueries(<NewProductForm />, () => undefined, reader()))).not.toContain("Create product");
    expect(textOf(renderWithQueries(<LookupBrowser state={lookupStateFrom({})} />, () => undefined, reader()))).not.toContain("Export CSV");
  });

  it("renders the create form sections for creators", () => {
    const html = renderWithQueries(<NewProductForm />, (c) => c.setQueryData(queryKeys.catalogue.categories(false), []), editor());
    const text = textOf(html);
    for (const label of ["Product key", "Master data", "Decor", "Specifications", "Packaging", "Unit weight (kg)", "Plate 3 size"]) expect(text).toContain(label);
  });

  it("links every completeness count to its list filter", () => {
    const html = renderWithQueries(
      <CompletenessReport />,
      (c) => c.setQueryData(queryKeys.catalogue.completeness(), { total_products: 4, complete_products: 1, rules: [{ code: "no_image", label: "No stored image", severity: "warning", count: 3, filter_path: "/products?issue=no_image" }], not_evaluated: [] }),
      reader(),
    );
    expect(html).toContain('href="/products?issue=no_image"');
    expect(textOf(html)).toContain("1 of 4 live products pass every check.");
  });

  it("keeps lookup filters in the URL", () => {
    expect(lookupHref(lookupStateFrom({ type: "finish", q: " mt ", offset: "60" }))).toBe("/settings/lookups?type=finish&q=mt&offset=50");
  });
});
