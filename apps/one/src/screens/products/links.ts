/**
 * URL helpers for the Products area. A plain module (no "use client"), so server pages can read
 * their params with it and client screens can build links with it.
 */

import type { Route } from "next";
import { productListHref, type ProductListState } from "@/features/products/list-state";

type SearchValue = string | string[] | undefined;
const first = (value: SearchValue) => (Array.isArray(value) ? value[0] : value);

// ---- the catalogue: grid or table, kept in `?view=` ----

export const CATALOGUE_LAYOUTS = ["grid", "table"] as const;
export type CatalogueLayout = (typeof CATALOGUE_LAYOUTS)[number];

export function catalogueLayoutFrom(value: SearchValue): CatalogueLayout {
  return first(value) === "table" ? "table" : "grid";
}

/** The catalogue URL for a set of filters and a layout; the grid is the default and leaves no trace. */
export function catalogueHref(state: Partial<ProductListState>, layout: CatalogueLayout): Route {
  const href = productListHref(state);
  if (layout === "grid") return href as Route;
  return `${href}${href.includes("?") ? "&" : "?"}view=table` as Route;
}

// ---- one product: its views are the server's section paths ----

export const PRODUCT_VIEWS = ["summary", "details", "specifications", "packaging", "pricing", "material", "media", "history"] as const;
export type ProductView = (typeof PRODUCT_VIEWS)[number];

/** `/products/{id}/{section}` → a view, or null for a section this app does not have. */
export function productViewFrom(section: string): ProductView | null {
  if (section === "overview") return "summary";
  return PRODUCT_VIEWS.find((view) => view === section && view !== "summary") ?? null;
}

export function productViewHref(productId: string, view: ProductView): Route {
  const base = `/products/${encodeURIComponent(productId)}`;
  return (view === "summary" ? base : `${base}/${view}`) as Route;
}

/** The old app kept the view in `?tab=`; links written that way still land on the right view. */
const OLD_TAB_VIEW: Record<string, ProductView> = {
  specification: "specifications",
  packaging: "packaging",
  prices: "pricing",
  material: "material",
  media: "media",
  history: "history",
};

export function productViewForOldTab(value: SearchValue): ProductView | null {
  const raw = first(value);
  return raw ? (OLD_TAB_VIEW[raw] ?? null) : null;
}

/** Where a completeness gap is fixed on the product record. */
const ISSUE_VIEW: Record<string, ProductView> = {
  no_decor: "details",
  no_hsn_sac: "details",
  shared_display_sku: "details",
  no_specification: "specifications",
  no_thickness: "specifications",
  no_size: "specifications",
  unparsed_dimensions: "specifications",
  no_packaging: "packaging",
  no_carton_qty: "packaging",
  no_unit_weight: "packaging",
};

export function issueFixHref(productId: string, code: string): Route {
  if (code === "category_inactive") return "/products/taxonomy" as Route;
  return productViewHref(productId, ISSUE_VIEW[code] ?? "details");
}

export function priceListHref(priceListId: string): Route {
  return `/products/price-lists/${encodeURIComponent(priceListId)}` as Route;
}
