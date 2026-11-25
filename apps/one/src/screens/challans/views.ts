/**
 * The `?view=` of a challan record. A plain module (no "use client"), so the server route file can
 * parse its search params with it. Unknown values fall back to the overview.
 */

type Raw = string | string[] | undefined;

export const CHALLAN_VIEWS = ["overview", "lines", "details", "returns", "activity", "note"] as const;
export type ChallanView = (typeof CHALLAN_VIEWS)[number];

export function challanViewFrom(raw: Raw): ChallanView {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return CHALLAN_VIEWS.find((view) => view === value) ?? "overview";
}

/** The URL of a record view; the overview is the bare path. */
export function viewHref(path: string, view: ChallanView): string {
  return view === "overview" ? path : `${path}?view=${view}`;
}
