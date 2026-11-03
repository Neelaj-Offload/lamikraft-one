import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { renderWithQueries, textOf } from "@/lib/test-support/render";
import { testQuoteWire } from "@/lib/test-support/sales";
import { testBootstrap } from "@/lib/test-support/session";
import { ConfiguratorPanel } from "./configurator-drawer";
import {
  ANY,
  CONFIGURATOR_PATH,
  EMPTY_FILTERS,
  configuratorRequest,
  filterOptions,
  pageLabel,
  pickAdvisories,
  pickLine,
  resolveConfigurator,
  type ConfiguratorResult,
  type ConfiguratorRow,
} from "./configurator";
import { parseQuoteDetail } from "./parse";
import type { useQuoteCommand } from "./use-quote-command";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/sales/quotes/0192a000-0000-7000-8000-000000000009",
  useSearchParams: () => new URLSearchParams(),
}));

const quote = parseQuoteDetail(testQuoteWire());
const commands = { run: vi.fn(), pending: null, offline: null, reload: vi.fn() } as unknown as ReturnType<typeof useQuoteCommand>;

function row(overrides: Partial<ConfiguratorRow> = {}): ConfiguratorRow {
  return {
    product: {
      id: "0192a000-0000-7000-8000-0000000000t1",
      product_key: "LK-OT-0450",
      display_sku: "LK-OT-0450",
      product_name: "Oak serving tray",
      brand: "LK",
      category: { id: "0192a000-0000-7000-8000-0000000000c1", name: "Serveware" },
      subcategory: null,
      product_type: null,
      variant_group: "Trays",
      unit_of_sale: "pcs",
      decor_no: "D-104",
      decor_name: "Natural oak",
      finish: "Matt",
      shape: null,
      status: "active",
      thickness_mm: "12",
      size: { length_mm: "450", width_mm: "300", height_mm: null, diameter_mm: null },
      carton_qty: 24,
      archived: false,
      updated_at: "2026-10-12T03:26:00Z",
      path: "/products/0192a000-0000-7000-8000-0000000000t1",
      redacted_fields: [],
    } as unknown as ConfiguratorRow["product"],
    packaging_summary: "450g · 24/ctn · Poly bag",
    price: {
      status: "found",
      unit_price: { amount: "24.0000", currency: "EUR" },
      unit_code: "pcs",
      price_list_code: "STD-EXPORT-EUR",
      tier: "standard",
      reason_code: null,
      explanation: "Standard export list",
      product_moq: null,
      converted_with_fx: false,
    },
    recommendation: {
      status: "AVAILABLE",
      quantity: { value: "216", uom: "pcs" },
      minimum_order_value: { amount: "5000.00", currency: "EUR" },
      carton_qty: 24,
      explanation: "EUR 5,000 at EUR 24.00, rounded up to full cartons of 24",
      label: "Order-value recommendation: 216 pcs",
    },
    ...overrides,
  };
}

function result(items: ConfiguratorRow[], extra: Partial<ConfiguratorResult> = {}): ConfiguratorResult {
  const facet = (value: string, label: string, count: number) => ({ value, label, count });
  return {
    items,
    total: items.length,
    limit: 20,
    offset: 0,
    exact_match: items.length === 1 ? items[0]!.product.id : null,
    currency: "EUR",
    facets: {
      total: items.length,
      categories: [facet("0192a000-0000-7000-8000-0000000000c1", "Serveware", items.length)],
      subcategories: [],
      families: [facet("Trays", "Trays", items.length)],
      sizes: [facet("450x300", "450 × 300 mm", items.length)],
      thicknesses: [facet("12", "12 mm", items.length)],
      decors: [facet("D-104", "D-104 Natural oak", items.length)],
      finishes: [facet("Matt", "Matt", items.length)],
      statuses: [],
      brands: [],
    },
    ...extra,
  };
}

describe("configurator model", () => {
  it("builds the request from the quote and omits empty filters", () => {
    expect(configuratorRequest(quote, EMPTY_FILTERS, 0)).toEqual({
      party_id: quote.party.id,
      currency: "EUR",
      price_type: quote.price_type,
      limit: 20,
      offset: 0,
    });
    const body = configuratorRequest(quote, { ...EMPTY_FILTERS, q: "  oak ", thickness: "12", finish: "Matt" }, -5);
    expect(body).toMatchObject({ q: "oak", thickness: "12", finish: "Matt", offset: 0 });
    expect(body).not.toHaveProperty("decor");
  });

  it("lists narrowed facet options with counts and keeps a selection that dropped out", () => {
    const values = [{ value: "Matt", label: "Matt", count: 3 }];
    expect(filterOptions(values, null, "Any")).toEqual([
      { id: ANY, label: "Any" },
      { id: "Matt", label: "Matt", detail: "3" },
    ]);
    expect(filterOptions(values, "Gloss", "Any").map((o) => o.id)).toEqual([ANY, "Gloss", "Matt"]);
  });

  it("labels the page range", () => {
    expect(pageLabel({ total: 45, offset: 20, items: Array.from({ length: 20 }, () => row()) })).toEqual({ from: 21, to: 40, total: 45 });
    expect(pageLabel({ total: 0, offset: 0, items: [] })).toEqual({ from: 0, to: 0, total: 0 });
  });

  it("raises the amber advisories of the legacy dialog", () => {
    expect(pickAdvisories(row(), "100", "24.0000")).toEqual(["below_recommendation"]);
    expect(pickAdvisories(row(), "216", "24")).toEqual([]);
    expect(pickAdvisories(row(), "240", "22.00")).toEqual(["price_differs"]);
    expect(pickAdvisories(row({ price: { ...row().price!, unit_price: null } }), "240", null)).toEqual(["unpriced"]);
    // an unavailable recommendation never warns about quantity (and is never called MOQ)
    expect(pickAdvisories(row({ recommendation: { ...row().recommendation!, status: "NOT_EVALUATED", quantity: null } }), "1", "24")).toEqual([]);
  });

  it("sends the price only when it overrides the default, and then needs a reason", () => {
    expect(pickLine(row(), { quantity: "240", unitPrice: "24.0000", reason: "" })).toEqual({
      ok: true,
      line: { line_type: "catalog", product_id: row().product.id, quantity: "240", unit_code: "pcs" },
    });
    expect(pickLine(row(), { quantity: "0", unitPrice: null, reason: "" })).toEqual({ ok: false, error: "quantity" });
    expect(pickLine(row(), { quantity: "240", unitPrice: "22.00", reason: " " })).toEqual({ ok: false, error: "reason" });
    expect(pickLine(row(), { quantity: "240", unitPrice: "22.00", reason: "Volume deal" })).toMatchObject({
      ok: true,
      line: { unit_price: "22.00", override_reason: "Volume deal" },
    });
  });

  it("posts the request body to the configurator route", async () => {
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: "http://127.0.0.1:3060",
      getCsrfToken: () => "csrf",
      fetch: async (request) => {
        seen.push(request.clone());
        return new Response(JSON.stringify(result([row()])), { status: 200, headers: { "content-type": "application/json" } });
      },
    });
    const out = await resolveConfigurator(configuratorRequest(quote, { ...EMPTY_FILTERS, q: "LK-OT-0450" }, 0), undefined, client);
    expect(out.exact_match).toBe(row().product.id);
    expect(seen[0]!.method).toBe("POST");
    expect(new URL(seen[0]!.url).pathname).toBe(CONFIGURATOR_PATH);
    expect(await seen[0]!.json()).toMatchObject({ q: "LK-OT-0450", currency: "EUR", party_id: quote.party.id });
  });
});

describe("configurator panel", () => {
  const bootstrap = testBootstrap({ permissions: [{ key: "sales.quote.read", scope: "own" }, { key: "sales.quote.update", scope: "own" }] });
  const key = queryKeys.sales.configurator(configuratorRequest(quote, EMPTY_FILTERS, 0));

  it("renders the search, six filters, priced rows with packaging and paging", () => {
    const html = renderWithQueries(<ConfiguratorPanel quote={quote} commands={commands} onAdded={() => undefined} />, (client) =>
      client.setQueryData(key, result([row(), row({ product: { ...row().product, id: "0192a000-0000-7000-8000-0000000000t2", product_name: "Walnut tray" } })])),
    bootstrap);
    const text = textOf(html);
    expect(text).toContain("Search");
    for (const label of ["Category", "Family", "Size", "Thickness", "Decor", "Finish"]) expect(text).toContain(label);
    expect(text).toContain("Oak serving tray");
    expect(text).toContain("450 × 300 mm · 12 mm · D-104 Natural oak · Matt");
    expect(text).toContain("450g · 24/ctn · Poly bag");
    expect(text).toContain("Order-value recommendation: 216 pcs");
    expect(text).not.toMatch(/\bMOQ\b/);
    expect(text).toContain("1–2 of 2");
    expect(html).toContain('aria-label="Choose Walnut tray"');
    expect(text).not.toContain("Exact match");
  });

  it("marks an exact match and says so when nothing matches", () => {
    const one = textOf(renderWithQueries(<ConfiguratorPanel quote={quote} commands={commands} onAdded={() => undefined} />, (client) =>
      client.setQueryData(key, result([row()])), bootstrap));
    expect(one).toContain("Exact match");
    const none = textOf(renderWithQueries(<ConfiguratorPanel quote={quote} commands={commands} onAdded={() => undefined} />, (client) =>
      client.setQueryData(key, result([])), bootstrap));
    expect(none).toContain("No product matches these filters.");
    expect(none).toContain("No matches");
  });

  it("says when a row has no price for this customer instead of showing another currency", () => {
    const unpriced = row({ price: { ...row().price!, status: "not_found", unit_price: null, reason_code: "no_list_in_currency" } });
    const text = textOf(renderWithQueries(<ConfiguratorPanel quote={quote} commands={commands} onAdded={() => undefined} />, (client) =>
      client.setQueryData(key, result([unpriced])), bootstrap));
    expect(text).toContain("No price for this customer");
    expect(text).not.toContain("24.00");
  });
});
