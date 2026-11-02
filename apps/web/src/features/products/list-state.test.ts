import { describe, expect, it } from "vitest";
import {
  activeFilterCount,
  clearedFiltersHref,
  effectiveSort,
  facetClearHref,
  facetToggleHref,
  isFacetSelected,
  productFilterParams,
  productListHref,
  productListParams,
  productListStateFrom,
  PRODUCTS_PAGE_SIZE,
} from "./list-state";

const CATEGORY = "0192B000-0000-7000-8000-00000000000C";

describe("productListStateFrom", () => {
  it("reads every filter from the URL and ignores values the server would refuse", () => {
    const state = productListStateFrom({
      q: "  oak ",
      category_id: CATEGORY,
      subcategory_id: "not-a-uuid",
      family: "Serving boards",
      size: "450x300",
      thickness: "0.8",
      decor: "0120",
      finish: "Matt",
      status: "under_development",
      brand: "Lamikraft",
      issue: "no_decor",
      include_archived: "true",
      sort: "-updated_at",
      currency: "inr",
      offset: "63",
    });
    expect(state).toEqual({
      q: "oak",
      category_id: CATEGORY.toLowerCase(),
      subcategory_id: null,
      family: "Serving boards",
      size: "450x300",
      thickness: "0.8",
      decor: "0120",
      finish: "Matt",
      status: "under_development",
      brand: "Lamikraft",
      issue: "no_decor",
      include_archived: true,
      sort: "-updated_at",
      currency: "INR",
      offset: 50,
    });
  });

  it("falls back to the defaults for unknown values", () => {
    const state = productListStateFrom({ status: "deleted", sort: "price", currency: "CHF", issue: "bogus", offset: "-5" });
    expect(state.status).toBeNull();
    expect(state.sort).toBeNull();
    expect(state.currency).toBe("EUR");
    expect(state.issue).toBeNull();
    expect(state.offset).toBe(0);
    expect(state.include_archived).toBe(false);
  });

  it("round-trips through productListHref", () => {
    const original = productListStateFrom({ q: "oak", decor: "0120", status: "active", include_archived: "1", sort: "product_name", currency: "USD", offset: String(PRODUCTS_PAGE_SIZE * 2) });
    const href = productListHref(original);
    expect(href).toBe("/products?q=oak&decor=0120&status=active&include_archived=true&sort=product_name&currency=USD&offset=50");
    const url = new URL(href, "http://lamikraft.invalid");
    expect(productListStateFrom(Object.fromEntries(url.searchParams))).toEqual(original);
  });

  it("omits defaults so the plain list is /products", () => {
    expect(productListHref(productListStateFrom({}))).toBe("/products");
    expect(productListHref({ currency: "EUR" })).toBe("/products");
  });
});

describe("facet hrefs", () => {
  const state = productListStateFrom({ q: "oak", decor: "0120", category_id: CATEGORY, subcategory_id: "0192b000-0000-7000-8000-00000000000d", offset: "25" });

  it("applies a value that is not selected and resets the page", () => {
    const href = facetToggleHref(state, "finishes", "Matt");
    const params = new URL(href, "http://x").searchParams;
    expect(params.get("finish")).toBe("Matt");
    expect(params.get("decor")).toBe("0120");
    expect(params.get("offset")).toBeNull();
  });

  it("removes the selected value (a toggle), case-insensitively", () => {
    expect(isFacetSelected(state, "decors", "0120")).toBe(true);
    const params = new URL(facetToggleHref(state, "decors", "0120"), "http://x").searchParams;
    expect(params.get("decor")).toBeNull();
    expect(params.get("q")).toBe("oak");
    expect(isFacetSelected(productListStateFrom({ finish: "matt" }), "finishes", "Matt")).toBe(true);
  });

  it("drops the subcategory when the category changes or clears", () => {
    const other = "0192b000-0000-7000-8000-0000000000ee";
    const changed = new URL(facetToggleHref(state, "categories", other), "http://x").searchParams;
    expect(changed.get("category_id")).toBe(other);
    expect(changed.get("subcategory_id")).toBeNull();
    const cleared = new URL(facetClearHref(state, "categories"), "http://x").searchParams;
    expect(cleared.get("category_id")).toBeNull();
    expect(cleared.get("subcategory_id")).toBeNull();
    expect(cleared.get("decor")).toBe("0120");
  });

  it("counts the active filters and clears them while keeping sort and currency", () => {
    expect(activeFilterCount(state)).toBe(4);
    expect(activeFilterCount(productListStateFrom({}))).toBe(0);
    expect(clearedFiltersHref(productListStateFrom({ q: "oak", sort: "product_name", currency: "USD", include_archived: "true" }))).toBe("/products?sort=product_name&currency=USD");
  });
});

describe("request parameters", () => {
  it("asks for relevance only with a search, product key otherwise", () => {
    expect(effectiveSort({ q: "", sort: null })).toBe("product_key");
    expect(effectiveSort({ q: "oak", sort: null })).toBe("relevance");
    expect(effectiveSort({ q: "", sort: "relevance" })).toBe("product_key");
    expect(effectiveSort({ q: "oak", sort: "-updated_at" })).toBe("-updated_at");
  });

  it("sends only set filters to the facets endpoint and adds paging and currency for the list", () => {
    const state = productListStateFrom({ q: "oak", status: "active", offset: "25", currency: "GBP" });
    expect(productFilterParams(state)).toEqual({
      q: "oak",
      category_id: undefined,
      subcategory_id: undefined,
      family: undefined,
      size: undefined,
      thickness: undefined,
      decor: undefined,
      finish: undefined,
      status: "active",
      brand: undefined,
      issue: undefined,
      include_archived: undefined,
    });
    expect(productListParams(state)).toMatchObject({ q: "oak", status: "active", sort: "relevance", price_currency: "GBP", limit: PRODUCTS_PAGE_SIZE, offset: 25 });
  });
});
