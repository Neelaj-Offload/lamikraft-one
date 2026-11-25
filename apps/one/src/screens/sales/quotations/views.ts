/**
 * The `?view=` of each record in Sales: deals. A plain module (no "use client"), so the server
 * route files can parse their search params with it. Unknown values fall back to the overview.
 */

type Raw = string | string[] | undefined;
const first = (value: Raw) => (Array.isArray(value) ? value[0] : value);

function parser<const T extends readonly string[]>(views: T) {
  return (raw: Raw): T[number] => views.find((view) => view === first(raw)) ?? (views[0] as T[number]);
}

export const QUOTATION_VIEWS = ["overview", "lines", "terms", "documents", "activity"] as const;
export type QuotationView = (typeof QUOTATION_VIEWS)[number];
export const quotationViewFrom = parser(QUOTATION_VIEWS);

export const ORDER_VIEWS = ["overview", "lines", "fulfilment", "activity"] as const;
export type OrderView = (typeof ORDER_VIEWS)[number];
export const orderViewFrom = parser(ORDER_VIEWS);

export const CUSTOM_PRODUCT_VIEWS = ["overview", "specification", "samples", "costing", "activity"] as const;
export type CustomProductView = (typeof CUSTOM_PRODUCT_VIEWS)[number];
export const customProductViewFrom = parser(CUSTOM_PRODUCT_VIEWS);

/** The URL of a record view; the overview is the bare path. */
export function viewHref(path: string, view: string): string {
  return view === "overview" ? path : `${path}?view=${view}`;
}
