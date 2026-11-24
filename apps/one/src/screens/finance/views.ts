/**
 * The `?view=` of each finance record and the URL filters of the exceptions screen. A plain module
 * (no "use client"), so the server route files can parse their search params with it. Unknown
 * values fall back to the first view.
 */

type Raw = string | string[] | undefined;
const first = (value: Raw) => (Array.isArray(value) ? value[0] : value);

function parser<const T extends readonly string[]>(views: T) {
  return (raw: Raw): T[number] => views.find((view) => view === first(raw)) ?? (views[0] as T[number]);
}

export const DOCUMENT_VIEWS = ["overview", "lines", "settlements", "activity"] as const;
export type DocumentView = (typeof DOCUMENT_VIEWS)[number];
export const documentViewFrom = parser(DOCUMENT_VIEWS);

export const RECEIPT_VIEWS = ["overview", "allocations"] as const;
export type ReceiptView = (typeof RECEIPT_VIEWS)[number];
export const receiptViewFrom = parser(RECEIPT_VIEWS);

export const EXCEPTION_VIEWS = ["documents", "margin"] as const;
export type ExceptionView = (typeof EXCEPTION_VIEWS)[number];
export const exceptionViewFrom = parser(EXCEPTION_VIEWS);

/** The exception kinds the list can be narrowed to (`?kind=`); anything else means all of them. */
const KINDS = ["issue_blocked", "overdue", "unallocated_receipt", "sync_failed", "sync_mismatch"] as const;
export type ExceptionKindFilter = (typeof KINDS)[number] | null;
export function exceptionKindFrom(raw: Raw): ExceptionKindFilter {
  return KINDS.find((kind) => kind === first(raw)) ?? null;
}

/** The export a link points at on the accounting screen (`?export=<id>`), or null. */
export function exportIdFrom(raw: Raw): string | null {
  const value = first(raw);
  return value && /^[0-9a-fA-F-]{8,64}$/.test(value) ? value : null;
}

/** The URL of a record view; the overview is the bare path. */
export function viewHref(path: string, view: string): string {
  return view === "overview" ? path : `${path}?view=${view}`;
}
