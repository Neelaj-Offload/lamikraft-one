/**
 * URL state helpers for the product record and the taxonomy page. A plain module (no
 * "use client"), so server pages can read their search params with it and the client views can
 * build links with it; a server component must never call a function from a client module.
 */

export const PRODUCT_TABS = ["overview", "specification", "packaging", "prices", "material", "media", "history"] as const;
export type ProductTab = (typeof PRODUCT_TABS)[number];

/** `?tab=` → a known tab; anything else is the overview. */
export function productTabFrom(value: string | string[] | undefined): ProductTab {
  const raw = Array.isArray(value) ? value[0] : value;
  return PRODUCT_TABS.find((tab) => tab === raw) ?? "overview";
}

/** The server's section keys (`sections[].key`, also the last path segment of `sections[].path`) → the record's tab. */
const SECTION_TABS: Record<string, ProductTab> = {
  overview: "overview",
  specifications: "specification",
  packaging: "packaging",
  pricing: "prices",
  media: "media",
  history: "history",
  material: "material",
};

export function productTabForSection(section: string): ProductTab | null {
  return SECTION_TABS[section] ?? null;
}

export function productTabHref(productId: string, tab: ProductTab): string {
  const base = `/products/${encodeURIComponent(productId)}`;
  return tab === "overview" ? base : `${base}?${new URLSearchParams({ tab }).toString()}`;
}

export function taxonomyHref(includeInactive: boolean): string {
  return includeInactive ? "/products/taxonomy?include_inactive=true" : "/products/taxonomy";
}

export function includeInactiveFrom(value: string | string[] | undefined): boolean {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw === "true" || raw === "1";
}
