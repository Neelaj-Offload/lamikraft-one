/**
 * URL helpers of the purchasing and quality records. A plain module (no "use client"), so the
 * server route files can parse their search params with it. Unknown views fall back to the overview.
 */

import type { Route } from "next";

type Raw = string | string[] | undefined;
const first = (value: Raw) => (Array.isArray(value) ? value[0] : value);

function parser<const T extends readonly string[]>(views: T) {
  return (raw: Raw): T[number] => views.find((view) => view === first(raw)) ?? (views[0] as T[number]);
}

export const REQUISITION_VIEWS = ["overview", "lines"] as const;
export type RequisitionView = (typeof REQUISITION_VIEWS)[number];
export const requisitionViewFrom = parser(REQUISITION_VIEWS);

export const PO_VIEWS = ["overview", "lines", "receipts", "bills"] as const;
export type PoView = (typeof PO_VIEWS)[number];
export const poViewFrom = parser(PO_VIEWS);

export const RECEIPT_VIEWS = ["overview", "lines"] as const;
export type ReceiptView = (typeof RECEIPT_VIEWS)[number];
export const receiptViewFrom = parser(RECEIPT_VIEWS);

/** The URL of a record view; the overview is the bare path. */
export function viewHref(path: string, view: string): Route {
  return (view === "overview" ? path : `${path}?view=${view}`) as Route;
}

/** `router.push` and `Link` want typed routes; API paths and built URLs are plain strings. */
export const asRoute = (path: string) => path as Route;
