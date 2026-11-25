/**
 * The words of the Stock screens: one label and one tone per status, plus the `?view=` and paging
 * parsers. A plain module (no "use client"), so the server route files can call the parsers.
 */

import type { DocumentKind } from "@/features/inventory/api";
import type { IconName, Tone } from "~/ui";

export interface StatusLook {
  label: string;
  tone: Tone;
}

export function humanise(code: string): string {
  const text = code.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const look = (table: Record<string, StatusLook>, status: string): StatusLook => table[status] ?? { label: humanise(status), tone: "neutral" };

const STOCK_TAKE_STATUS: Record<string, StatusLook> = {
  draft: { label: "Not started", tone: "neutral" },
  frozen: { label: "Counting", tone: "cobalt" },
  submitted: { label: "Awaiting approval", tone: "amber" },
  posted: { label: "Posted", tone: "leaf" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const PICK_LIST_STATUS: Record<string, StatusLook> = {
  draft: { label: "Draft", tone: "neutral" },
  released: { label: "Picking", tone: "cobalt" },
  picked: { label: "Picked", tone: "leaf" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const DOCUMENT_STATUS: Record<string, StatusLook> = {
  draft: { label: "Draft", tone: "neutral" },
  submitted: { label: "Awaiting approval", tone: "amber" },
  posted: { label: "Posted", tone: "leaf" },
  rejected: { label: "Rejected", tone: "ember" },
  dispatched: { label: "In transit", tone: "cobalt" },
  received: { label: "Received", tone: "leaf" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const RESERVATION_STATUS: Record<string, StatusLook> = {
  active: { label: "Held", tone: "cobalt" },
  fulfilled: { label: "Fulfilled", tone: "leaf" },
  released: { label: "Released", tone: "neutral" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export const stockTakeStatus = (status: string) => look(STOCK_TAKE_STATUS, status);
export const pickListStatus = (status: string) => look(PICK_LIST_STATUS, status);
export const documentStatus = (status: string) => look(DOCUMENT_STATUS, status);
export const reservationStatus = (status: string) => look(RESERVATION_STATUS, status);

/** The reservation statuses the API filters by, in the order the chips show them. */
export const RESERVATION_STATUSES = ["active", "fulfilled", "released", "cancelled"] as const;

/** What kind of place a location is. A movement always goes from one kind of place to another. */
const LOCATION_TYPE: Record<string, string> = {
  internal: "Warehouse stock",
  qc_hold: "Quality hold",
  rejected: "Rejected",
  wip: "Work in progress",
  office: "Office",
  in_transit: "In transit",
  external_holding: "Held outside",
  supplier: "Supplier",
  customer: "Customer",
  production: "Production",
  scrap: "Scrap",
  adjustment: "Adjustment",
  opening: "Opening stock",
  sample_consumption: "Samples given away",
};
export const locationType = (type: string) => LOCATION_TYPE[type] ?? humanise(type);

/** The record that caused a movement. */
const MOVEMENT_SOURCE: Record<string, string> = {
  challan: "Challan",
  stock_count: "Stock take",
  adjustment: "Adjustment",
  opening_batch: "Opening stock",
  transfer: "Transfer",
  relocation: "Bin move",
  reversal: "Reversal",
  work_order: "Work order",
};
export const movementSource = (type: string) => MOVEMENT_SOURCE[type] ?? humanise(type);

export const DOCUMENT_KIND: Record<DocumentKind, { name: string; icon: IconName; what: string }> = {
  adjustment: { name: "Stock adjustment", icon: "sliders", what: "This adjustment" },
  opening_batch: { name: "Opening stock", icon: "boxes", what: "This opening stock batch" },
  transfer: { name: "Stock transfer", icon: "truck", what: "This transfer" },
};

const LINE_DIRECTION: Record<string, { label: string; tone: Tone }> = {
  in: { label: "Found, added", tone: "leaf" },
  out: { label: "Lost, removed", tone: "ember" },
};
export const lineDirection = (direction: string) => LINE_DIRECTION[direction] ?? { label: humanise(direction), tone: "neutral" as Tone };

// ---------------------------------------------------------------------------------------------
// URL state

type Raw = string | string[] | undefined;
const first = (value: Raw) => (Array.isArray(value) ? value[0] : value);

/** The two views every stock record has: where it stands, and its lines. */
export const STOCK_RECORD_VIEWS = ["overview", "lines"] as const;
export type StockRecordView = (typeof STOCK_RECORD_VIEWS)[number];
export const stockRecordViewFrom = (raw: Raw): StockRecordView => STOCK_RECORD_VIEWS.find((view) => view === first(raw)) ?? "overview";

/** The URL of a record view; the overview is the bare path. */
export const viewHref = (path: string, view: StockRecordView) => (view === "overview" ? path : `${path}?view=${view}`);

/** A page offset from the URL: a whole number of rows, never negative. */
export function offsetFrom(raw: Raw): number {
  const offset = Number.parseInt(first(raw) ?? "0", 10);
  return Number.isFinite(offset) && offset > 0 ? offset : 0;
}

export const firstParam = (raw: Raw): string | null => first(raw) ?? null;

export const MOVEMENTS_PATH = "/operations/inventory/movements";
export const movementsHref = (offset: number) => (offset > 0 ? `${MOVEMENTS_PATH}?offset=${offset}` : MOVEMENTS_PATH);

export const RESERVATIONS_PATH = "/operations/reservations";
export function reservationsHref(status: string | null, offset = 0): string {
  const search = new URLSearchParams();
  if (status) search.set("status", status);
  if (offset > 0) search.set("offset", String(offset));
  const text = search.toString();
  return text ? `${RESERVATIONS_PATH}?${text}` : RESERVATIONS_PATH;
}

export const plural = (count: number, one: string, many: string) => (count === 1 ? `1 ${one}` : `${count} ${many}`);
