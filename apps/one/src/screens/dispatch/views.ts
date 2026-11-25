/**
 * The `?view=` of a shipment and of a packing list. A plain module (no "use client"), so the server
 * route files can parse their search params with it. Unknown values fall back to the overview.
 */

type Raw = string | string[] | undefined;
const first = (value: Raw) => (Array.isArray(value) ? value[0] : value);

export const SHIPMENT_VIEWS = ["overview", "documents", "tracking"] as const;
export type ShipmentView = (typeof SHIPMENT_VIEWS)[number];

export const PACKING_VIEWS = ["overview", "lines", "load"] as const;
export type PackingView = (typeof PACKING_VIEWS)[number];

export function shipmentViewFrom(raw: Raw): ShipmentView {
  return SHIPMENT_VIEWS.find((view) => view === first(raw)) ?? "overview";
}

export function packingViewFrom(raw: Raw): PackingView {
  return PACKING_VIEWS.find((view) => view === first(raw)) ?? "overview";
}

/** The URL of a record view; the overview is the bare path. */
export function viewHref(path: string, view: string): string {
  return view === "overview" ? path : `${path}?view=${view}`;
}
