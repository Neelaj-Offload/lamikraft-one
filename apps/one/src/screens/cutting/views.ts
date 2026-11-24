/**
 * The `?view=` of a cut plan. A plain module (no "use client"), so the server route file can parse
 * its search params with it. Unknown values fall back to the overview.
 */

type Raw = string | string[] | undefined;
const first = (value: Raw) => (Array.isArray(value) ? value[0] : value);

export const PLAN_VIEWS = ["overview", "pieces", "offcuts", "layout"] as const;
export type PlanView = (typeof PLAN_VIEWS)[number];

export function planViewFrom(raw: Raw): PlanView {
  return PLAN_VIEWS.find((view) => view === first(raw)) ?? "overview";
}

/** The URL of a plan view; the overview is the bare path. */
export function planViewHref(path: string, view: PlanView): string {
  return view === "overview" ? path : `${path}?view=${view}`;
}
