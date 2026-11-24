/**
 * URL state for "All of today": `?group=<section|snoozed>&kind=<rule family>`. A plain module, so
 * the server page can parse the query and both sides build the same links.
 */

import type { Route } from "next";
import { SECTION_CODES } from "@/features/briefing/parse";
import type { BriefingItem, BriefingView, SectionCode } from "@/features/briefing/types";

export type GroupFilter = SectionCode | "snoozed" | "all";

export interface AllFilter {
  group: GroupFilter;
  kind: string | null;
}

export type AllSearchParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | null {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw && raw.trim() !== "" ? raw : null;
}

export function allFilterFrom(params: AllSearchParams): AllFilter {
  const group = first(params.group);
  const known = group === "snoozed" ? "snoozed" : SECTION_CODES.find((code) => code === group);
  return { group: known ?? "all", kind: first(params.kind) };
}

export function allHref(filter: Partial<AllFilter> = {}): Route {
  const query = new URLSearchParams();
  if (filter.group && filter.group !== "all") query.set("group", filter.group);
  if (filter.kind) query.set("kind", filter.kind);
  const text = query.toString();
  return (text ? `/today/all?${text}` : "/today/all") as Route;
}

export interface AllRow {
  item: BriefingItem;
  group: SectionCode | "snoozed";
}

/** Every item of the briefing, then the snoozed ones, in the server's own order. Nothing is re-ranked. */
export function allRows(view: Pick<BriefingView, "items" | "snoozed">): AllRow[] {
  const rows: AllRow[] = [];
  for (const code of SECTION_CODES) {
    for (const item of view.items) if (item.section === code) rows.push({ item, group: code });
  }
  for (const item of view.snoozed) rows.push({ item, group: "snoozed" });
  return rows;
}

export function filterRows(rows: readonly AllRow[], filter: AllFilter): AllRow[] {
  return rows.filter((row) => (filter.group === "all" || row.group === filter.group) && (filter.kind === null || row.item.family === filter.kind));
}
