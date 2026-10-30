import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "@/lib/api/client";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { controlsWithoutVisibleFocus, renderWithQueries, seedQueryError, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { classifyFailure, fieldErrorsOf } from "@/features/sales/resource-command";
import { customExportHref, transitionCustomProduct, type CustomProductDetail } from "./api";
import { CustomProductView } from "./detail";
import { customBody, customFormOf, EMPTY_CUSTOM } from "./form";
import { CustomProductList, customListHref, customListStateFrom } from "./list";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/sales/custom-products",
  useSearchParams: () => new URLSearchParams(),
}));

const ID = "0192a000-0000-7000-8000-0000000000a1";
const perms = (...keys: string[]) => testBootstrap({ permissions: keys.map((key) => ({ key, scope: "own" })) });
const SALES = perms("sales.custom_product.read", "sales.custom_product.create", "sales.custom_product.update", "sales.custom_product.export");

function detail(overrides: Partial<CustomProductDetail> = {}): CustomProductDetail {
  return {
    id: ID,
    custom_code: "CP-0001",
    custom_type: "modified_catalog",
    product_name: "Oak tray 520 with brass handles",
    status: "sample_stage",
    party: { id: "p1", party_number: "P-00001", display_name: "Nordhaus Interiors GmbH", country_code: "DE" },
    legacy_customer_name: null,
    inquiry_reference: "NH-RFQ-2026-118",
    base_product_key: "LK-OT-0450",
    base_product_id: "b1",
    dimensions_text: "520 x 330 x 40 mm",
    decor_no: "0120",
    finish: "Matt lacquer",
    quoted_price: { amount: "31.5000", currency: "EUR" },
    owner: { id: "u1", display_name: "Meera Iyer" },
    promoted_product_id: null,
    archived_at: null,
    updated_at: "2026-10-12T03:00:00Z",
    version: 3,
    path: `/sales/custom-products/${ID}`,
    customer_specific_flag: true,
    description: "Oak serving tray",
    category_id: null,
    subcategory_id: null,
    category_name: null,
    subcategory_name: null,
    length_mm: "520.000",
    width_mm: "330.000",
    height_mm: "40.000",
    thickness_mm: "12.000",
    thickness_text: "12 mm",
    decor_name: "Natural oak",
    shape: "Rectangle",
    groove_count: 2,
    bowl_count: 0,
    handle_type: "Brass bar",
    packaging_notes: "12 per carton",
    packaging: { carton_qty: 12, unit_weight_g: "850" },
    unit_code: "pcs",
    remarks: "Before Diwali",
    status_reason: null,
    dormant_from_status: null,
    created_by: { id: "u1", display_name: "Meera Iyer" },
    spec_revisions: [],
    promotions: [],
    quotes: [],
    capabilities: {
      update: { allowed: true },
      transition: { allowed: true },
      archive: { allowed: false, reason_code: "permission_denied" },
      promote: { allowed: false, reason_code: "permission_denied" },
      duplicate: { allowed: true },
      read_costing: { allowed: false, reason_code: "permission_denied" },
      record_costing: { allowed: false, reason_code: "permission_denied" },
    },
    allowed_transitions: [
      { action: "develop", to_status: "under_development", requires_reason: false },
      { action: "quote", to_status: "quoted", requires_reason: false },
      { action: "reject", to_status: "rejected", requires_reason: true },
    ],
    redacted_fields: ["costing"],
    ...overrides,
  };
}

function renderDetail(product: CustomProductDetail, bootstrap = SALES, costing?: unknown[]) {
  return renderWithQueries(
    <CustomProductView customProductId={ID} />,
    (client) => {
      client.setQueryData(queryKeys.sales.customProduct(ID), product);
      client.setQueryData(queryKeys.sales.customProductHistory(ID), []);
      if (costing) client.setQueryData(queryKeys.sales.customProductCosting(ID), costing);
    },
    bootstrap,
  );
}

describe("custom product list", () => {
  it("keeps filters in the URL and normalises unknown values", () => {
    expect(customListStateFrom({ q: " tray ", status: "bogus", scope: "mine", offset: "30" })).toEqual({ q: " tray ", status: null, scope: "mine", offset: 25 });
    expect(customListHref({ q: "tray", status: "quoted", scope: "all" })).toBe("/sales/custom-products?q=tray&status=quoted");
    expect(customExportHref({ q: "tray", status: "quoted" }, true)).toBe("/api/v1/sales/custom-products/export.csv?q=tray&status=quoted&include_costing=true");
  });

  it("renders rows with the product name, export and New only when permitted", () => {
    const state = { q: "", status: null, scope: "all" as const, offset: 0 };
    const seed = (client: Parameters<Parameters<typeof renderWithQueries>[1]>[0]) =>
      client.setQueryData(queryKeys.sales.customProducts({ q: null, status: null, scope: "all", offset: 0 }), { items: [detail()], total: 1, limit: 25, offset: 0 });
    const text = textOf(renderWithQueries(<CustomProductList state={state} />, seed, SALES));
    expect(text).toContain("CP-0001");
    expect(text).toContain("Oak tray 520 with brass handles");
    expect(text).toContain("Export CSV");
    expect(text).toContain("New custom product");
    const readOnly = textOf(renderWithQueries(<CustomProductList state={state} />, seed, perms("sales.custom_product.read")));
    expect(readOnly).not.toContain("Export CSV");
    expect(readOnly).not.toContain("New custom product");
  });

  it("shows loading, empty, error and forbidden states", () => {
    const state = { q: "", status: null, scope: "all" as const, offset: 0 };
    const key = queryKeys.sales.customProducts({ q: null, status: null, scope: "all", offset: 0 });
    expect(textOf(renderWithQueries(<CustomProductList state={state} />, () => undefined, SALES))).toMatch(/Loading|custom products/i);
    expect(textOf(renderWithQueries(<CustomProductList state={state} />, (c) => c.setQueryData(key, { items: [], total: 0, limit: 25, offset: 0 }), SALES))).toContain(
      "No custom products match these filters.",
    );
    const failed = new ProblemError({ type: "about:blank", title: "Server error", status: 500, code: "internal_error", detail: "boom", request_id: "req-1" });
    expect(textOf(renderWithQueries(<CustomProductList state={state} />, (c) => seedQueryError(c, key, failed), SALES))).toContain("req-1");
    expect(textOf(renderWithQueries(<CustomProductList state={state} />, () => undefined, perms("sales.quote.read")))).toContain("You don't have access to Custom products");
  });
});

describe("custom product detail", () => {
  it("offers only the server's transitions, editable fields and no costing without cost access", () => {
    const html = renderDetail(detail());
    const text = textOf(html);
    expect(text).toContain("Start development");
    expect(text).toContain("Mark as quoted");
    expect(text).toContain("Reject");
    expect(text).not.toContain("Approve");
    expect(text).toContain("Duplicate");
    expect(text).not.toContain("Archive");
    expect(html).toMatch(/value="Oak tray 520 with brass handles"/);
    expect(text).toContain("Costing is restricted");
    expect(text).not.toContain("Record costing");
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("is a read-only record when the server does not allow edits, and shows costing to cost readers", () => {
    const product = detail({
      status: "converted_to_standard",
      promoted_product_id: "prod-1",
      allowed_transitions: [],
      capabilities: { update: { allowed: false, reason_code: "custom_product_converted" }, read_costing: { allowed: true }, record_costing: { allowed: true } },
      redacted_fields: [],
    });
    const html = renderDetail(product, perms("sales.custom_product.read", "pricing.cost.read"), [
      { id: "c1", cost_version: 1, cost: { amount: "17.2500", currency: "EUR" }, basis_note: "veneer", recorded_at: "2026-10-12T03:00:00Z", recorded_by: { id: "u2", display_name: "Priya Nair" } },
    ]);
    const text = textOf(html);
    expect(text).toContain("Converted to a catalogue product");
    expect(text).toContain("No status changes are available to you.");
    expect(html).not.toMatch(/<input[^>]*value="Oak tray 520/);
    expect(text).toContain("€17.25");
    expect(text).toContain("Record costing");
    expect(html).toContain('data-restricted="true"');
  });

  it("shows forbidden and error states", () => {
    const forbidden = new ProblemError({ type: "about:blank", title: "Forbidden", status: 403, code: "permission_denied", detail: null, request_id: "r" });
    const html = renderWithQueries(<CustomProductView customProductId={ID} />, (c) => seedQueryError(c, queryKeys.sales.customProduct(ID), forbidden), SALES);
    expect(textOf(html)).toContain("You don't have access to Custom products");
  });
});

describe("custom product form and commands", () => {
  it("sends every filled field on create and only changed fields (with nulls to clear) on update", () => {
    const body = customBody({ ...EMPTY_CUSTOM, product_name: " Teak tray ", length_mm: "600", carton_qty: "12", quoted_price: "38", quoted_currency: "EUR" }, null);
    expect(body).toEqual({
      custom_type: "fully_new",
      customer_specific_flag: false,
      unit_code: "pcs",
      quoted_currency: "EUR",
      packaging: { carton_qty: 12 },
      product_name: "Teak tray",
      length_mm: "600",
      quoted_price: "38",
    });
    const base = customFormOf(detail());
    expect(customBody(base, base)).toEqual({});
    expect(customBody({ ...base, finish: "", groove_count: "3" }, base)).toEqual({ finish: null, groove_count: 3 });
    expect(customBody({ ...base, quoted_price: "33" }, base)).toEqual({ quoted_price: "33", quoted_currency: "EUR" });
  });

  it("posts transitions with the version the person saw and maps 422 fields", async () => {
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: "http://127.0.0.1:3060",
      getCsrfToken: () => "csrf",
      fetch: async (request) => {
        seen.push(request.clone());
        return Response.json(detail({ status: "rejected", version: 4 }));
      },
    });
    const result = await transitionCustomProduct({ id: ID, version: 3 }, "reject", "  Too costly  ", client);
    expect(await seen[0]!.json()).toEqual({ action: "reject", expected_version: 3, reason: "Too costly" });
    expect(new URL(seen[0]!.url).pathname).toBe(`/api/v1/sales/custom-products/${ID}/transitions`);
    expect(result.status).toBe("rejected");
    const invalid = new ProblemError({
      type: "about:blank", title: "Invalid", status: 422, code: "validation_failed", detail: null, request_id: "r",
      errors: [{ loc: ["body", "base_product_id"], msg: "A modified catalogue product needs its base product", code: "base_product_required" }],
    } as never);
    expect(fieldErrorsOf(invalid)).toEqual({ base_product_id: "A modified catalogue product needs its base product" });
    const stale = new ProblemError({ type: "about:blank", title: "Conflict", status: 409, code: "version_conflict", detail: "changed", request_id: "r", current_version: 5 } as never);
    expect(classifyFailure(stale)).toEqual({ conflict: true, fieldErrors: {} });
    expect(classifyFailure(invalid).conflict).toBe(false);
  });
});
