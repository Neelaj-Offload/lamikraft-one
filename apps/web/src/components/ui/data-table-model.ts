/** Pure state helpers for DataTable: sorting, selection and pagination arithmetic on integers. */

export type SortDirection = "ascending" | "descending";

export interface SortState {
  column: string;
  direction: SortDirection;
}

/** A new column sorts ascending; pressing the active column flips its direction. */
export function nextSortState(current: SortState | null, column: string): SortState {
  if (current?.column === column) {
    return { column, direction: current.direction === "ascending" ? "descending" : "ascending" };
  }
  return { column, direction: "ascending" };
}

export function ariaSortFor(current: SortState | null, column: string): SortDirection | "none" {
  return current?.column === column ? current.direction : "none";
}

/** URL form used by list screens: `name` or `-name` (descending), as the API's `sort` param. */
export function sortToParam(sort: SortState | null): string | null {
  if (!sort) return null;
  return sort.direction === "descending" ? `-${sort.column}` : sort.column;
}

export function sortFromParam(param: string | null | undefined, allowed: readonly string[]): SortState | null {
  if (!param) return null;
  const descending = param.startsWith("-");
  const column = descending ? param.slice(1) : param;
  if (!allowed.includes(column)) return null;
  return { column, direction: descending ? "descending" : "ascending" };
}

export type SelectionSummary = "none" | "some" | "all";

export function selectionSummary(rowIds: readonly string[], selected: ReadonlySet<string>): SelectionSummary {
  if (rowIds.length === 0) return "none";
  let count = 0;
  for (const id of rowIds) if (selected.has(id)) count += 1;
  if (count === 0) return "none";
  return count === rowIds.length ? "all" : "some";
}

/** Select-all on the visible page; selections on other pages are kept. */
export function toggleAllRows(rowIds: readonly string[], selected: ReadonlySet<string>): Set<string> {
  const next = new Set(selected);
  if (selectionSummary(rowIds, selected) === "all") for (const id of rowIds) next.delete(id);
  else for (const id of rowIds) next.add(id);
  return next;
}

export function toggleRow(id: string, selected: ReadonlySet<string>): Set<string> {
  const next = new Set(selected);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

export interface OffsetRange {
  /** 1-based index of the first row shown; 0 when the page is empty. */
  first: number;
  last: number;
  total: number;
  previousOffset: number | null;
  nextOffset: number | null;
}

/** `Page{items,total,limit,offset}` (api-conventions §9) → what the pagination bar shows. */
export function offsetRange(total: number, limit: number, offset: number, shown: number): OffsetRange {
  const safeLimit = Math.max(1, limit);
  const safeOffset = Math.max(0, offset);
  const first = shown > 0 ? safeOffset + 1 : 0;
  const last = shown > 0 ? safeOffset + shown : 0;
  return {
    first,
    last,
    total,
    previousOffset: safeOffset > 0 ? Math.max(0, safeOffset - safeLimit) : null,
    nextOffset: safeOffset + safeLimit < total ? safeOffset + safeLimit : null,
  };
}
