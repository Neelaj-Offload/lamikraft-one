/**
 * URL state of the production records and lists that the old app kept in component state.
 * A plain module (no "use client"), so the server route files can parse their search params
 * with it. Unknown values fall back to the first view.
 */

type Raw = string | string[] | undefined;
const first = (value: Raw) => (Array.isArray(value) ? value[0] : value);

function parser<const T extends readonly string[]>(views: T) {
  return (raw: Raw): T[number] => views.find((view) => view === first(raw)) ?? (views[0] as T[number]);
}

export const WORK_ORDER_VIEWS = ["overview", "materials", "operations", "postings"] as const;
export type WorkOrderView = (typeof WORK_ORDER_VIEWS)[number];
export const workOrderViewFrom = parser(WORK_ORDER_VIEWS);

export const BOM_VIEWS = ["components", "cost"] as const;
export type BomView = (typeof BOM_VIEWS)[number];
export const bomViewFrom = parser(BOM_VIEWS);

/** The URL of a record view; the first view is the bare path. */
export function viewHref(path: string, view: string, firstView: string): string {
  return view === firstView ? path : `${path}?view=${view}`;
}

/** The search text of the bills of materials and routings lists (`?q=`). */
export function versionSearchFrom(params: Record<string, Raw>): string {
  return (first(params.q) ?? "").trim();
}

export function versionListHref(base: string, q: string): string {
  const text = q.trim();
  return text ? `${base}?q=${encodeURIComponent(text)}` : base;
}
