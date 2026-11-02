import { describe, expect, it } from "vitest";
import { priceListItemsStateFrom, priceListListHref, priceListListStateFrom } from "./list-state";
import { parsePriceListDetail, parsePriceListItem, parsePriceListItemPage, parseProductPrices, PriceListsShapeError } from "./parse";

const LIST = "0192c000-0000-7000-8000-000000000001";
const PRODUCT = "0192b000-0000-7000-8000-000000000001";

const listWire = (overrides: Record<string, unknown> = {}) => ({
  id: LIST,
  code: "EXP-EUR-2026",
  name: "Export EUR 2026",
  price_type: "export",
  scope_kind: "standard",
  party: null,
  customer_type: null,
  currency: "EUR",
  default_unit_code: "pcs",
  valid_from: "2026-01-01",
  valid_to: null,
  status: "active",
  priority: 10,
  item_count: 120,
  path: `/products/price-lists/${LIST}`,
  notes: null,
  activated_at: "2026-01-01T06:00:00Z",
  retired_at: null,
  version: 2,
  capabilities: {},
  allowed_transitions: [],
  redacted_fields: ["price_basis", "source_kind", "source_ref"],
  ...overrides,
});

const itemWire = (overrides: Record<string, unknown> = {}) => ({
  id: "0192c000-0000-7000-8000-0000000000aa",
  price_list_id: LIST,
  price_list_code: "EXP-EUR-2026",
  product_id: PRODUCT,
  product_key: "LK-0120-450",
  display_sku: "LK-0120-450-S",
  unit_code: "pcs",
  unit_price: { amount: "24.0000", currency: "EUR" },
  final_price: null,
  moq: { value: "48", uom: "pcs" },
  notes: null,
  valid_from: "2026-01-01",
  valid_to: null,
  status: "active",
  superseded_by_item_id: null,
  version: 1,
  redacted_fields: ["base_price", "addon_price"],
  ...overrides,
});

describe("price list readers", () => {
  it("reads a list detail and leaves guarded fields null when redacted", () => {
    const list = parsePriceListDetail(listWire());
    expect(list).toMatchObject({ code: "EXP-EUR-2026", status: "active", priority: 10, item_count: 120, version: 2, price_basis: null, source_kind: null });
    expect(list.redacted_fields).toContain("price_basis");
    expect(list.path).toBe(`/products/price-lists/${LIST}`);
    expect(() => parsePriceListDetail(listWire({ version: undefined }))).toThrow(PriceListsShapeError);
  });

  it("reads items with money as {amount, currency} and drops rows without a valid price", () => {
    const item = parsePriceListItem(itemWire())!;
    expect(item.unit_price).toEqual({ amount: "24.0000", currency: "EUR" });
    expect(item.moq).toEqual({ value: "48", uom: "pcs" });
    expect(item.base_price).toBeNull();
    expect(parsePriceListItem(itemWire({ unit_price: { amount: 24, currency: "EUR" } }))).toBeNull();
    const page = parsePriceListItemPage({ items: [itemWire(), itemWire({ base_price: { amount: "20.00", currency: "EUR" }, base_price_label: "Board", thickness_mm: "0.8" })], total: 2, limit: 25, offset: 0 });
    expect(page.items[1]).toMatchObject({ base_price: { amount: "20.00", currency: "EUR" }, base_price_label: "Board", thickness_mm: "0.8" });
  });

  it("reads product prices with the cost of record only when sent", () => {
    const withCost = parseProductPrices({
      product_id: PRODUCT,
      product_key: "LK-0120-450",
      on_date: "2026-11-02",
      prices: [{ ...itemWire(), price_list_name: "Export EUR 2026", price_type: "export", scope_kind: "customer", party: { id: "0192d000-0000-7000-8000-000000000001", party_number: "P-00001", display_name: "Acme" }, customer_type: null }],
      current_cost: { id: "0192e000-0000-7000-8000-000000000001", product_id: PRODUCT, cost_version: 2, unit_cost: { amount: "9.5000", currency: "EUR" }, unit_code: "pcs", cost_components: [{ label: "Board", amount: "7.00" }], source_kind: "manual", effective_from: "2026-01-01", recorded_at: "2026-01-01T06:00:00Z" },
    });
    expect(withCost.prices[0]).toMatchObject({ price_list_name: "Export EUR 2026", scope_kind: "customer", party: { display_name: "Acme" } });
    expect(withCost.current_cost?.unit_cost).toEqual({ amount: "9.5000", currency: "EUR" });
    expect(withCost.current_cost?.cost_components).toEqual([{ label: "Board", amount: "7.00" }]);
    const redacted = parseProductPrices({ product_id: PRODUCT, product_key: "LK-0120-450", on_date: "2026-11-02", prices: [], redacted_fields: ["current_cost"] });
    expect(redacted.current_cost).toBeNull();
    expect(() => parseProductPrices({ prices: [] })).toThrow(PriceListsShapeError);
  });
});

describe("price list URL state", () => {
  it("round-trips the list filters", () => {
    const state = priceListListStateFrom({ q: "exp", status: "active", price_type: "export", currency: "eur", scope_kind: "customer", offset: "30" });
    expect(state).toEqual({ q: "exp", status: "active", price_type: "export", currency: "EUR", scope_kind: "customer", offset: 25 });
    const href = priceListListHref(state);
    expect(href).toBe("/products/price-lists?q=exp&status=active&price_type=export&currency=EUR&scope_kind=customer&offset=25");
    expect(priceListListStateFrom(Object.fromEntries(new URL(href, "http://x").searchParams))).toEqual(state);
    expect(priceListListHref(priceListListStateFrom({ status: "bogus" }))).toBe("/products/price-lists");
  });

  it("reads the item filters", () => {
    expect(priceListItemsStateFrom({ q: "LK", include_history: "true", offset: "50" })).toEqual({ q: "LK", include_history: true, offset: 50 });
    expect(priceListItemsStateFrom({})).toEqual({ q: "", include_history: false, offset: 0 });
  });
});
