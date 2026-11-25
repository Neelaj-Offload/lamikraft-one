"use client";

/**
 * Data helpers for the dispatch screens (`/operations/dispatch`).
 *
 * The API calls, types and list state come from the old app's non-visual modules
 * (`@/features/logistics/{api,list-state}`), and commands run through `useCommand`
 * (`@/features/inventory/use-command`: fresh Idempotency-Key, cache write, invalidation, toasts).
 * This file holds only what lived inside old *view* files: the sales order search behind the
 * order picker and the status vocabulary.
 */

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import { fetchOrders } from "@/features/orders/api";
import { queryKeys } from "@/lib/api/query-keys";
import { useDebouncedValue } from "@/lib/hooks";
import type { IconName, Tone } from "~/ui";

/** `router.push` and `Link` want typed routes; API paths and built URLs are plain strings. */
export const asRoute = (path: string) => path as Route;

export const FAILED = "That did not go through";

// ---------------------------------------------------------------------------------------------
// Vocabulary

export interface StatusLook {
  label: string;
  tone: Tone;
}

const SHIPMENT_STATUS: Record<string, StatusLook> = {
  planned: { label: "Planned", tone: "neutral" },
  booked: { label: "Booked", tone: "cobalt" },
  dispatched: { label: "Dispatched", tone: "cobalt" },
  in_transit: { label: "In transit", tone: "cobalt" },
  delivered: { label: "Delivered", tone: "leaf" },
  exception: { label: "Exception", tone: "ember" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const PACKING_STATUS: Record<string, StatusLook> = {
  draft: { label: "Draft", tone: "neutral" },
  final: { label: "Final", tone: "leaf" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const humanise = (code: string) => {
  const text = code.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};
const look = (table: Record<string, StatusLook>, status: string): StatusLook => table[status] ?? { label: humanise(status), tone: "neutral" };

export const shipmentStatus = (status: string) => look(SHIPMENT_STATUS, status);
export const packingStatus = (status: string) => look(PACKING_STATUS, status);

export const MODE_LABEL: Record<string, string> = { road: "Road", sea: "Sea", air: "Air", courier: "Courier", hand: "By hand" };
export const MODE_ICON: Record<string, IconName> = { road: "truck", sea: "container", air: "send", courier: "box", hand: "handshake" };

export const EVIDENCE_KINDS = [
  { value: "signed_pod", label: "Signed proof of delivery" },
  { value: "photo", label: "Photo at delivery" },
  { value: "courier_confirmation", label: "Courier confirmation" },
  { value: "customer_confirmation", label: "Customer confirmation" },
] as const;

export const EXCEPTION_CODES = [
  { value: "delayed", label: "Delayed" },
  { value: "damaged", label: "Damaged" },
  { value: "lost", label: "Lost" },
  { value: "refused", label: "Refused" },
  { value: "address_issue", label: "Address issue" },
  { value: "other", label: "Something else" },
] as const;

export const TRACKING_LABEL: Record<string, string> = {
  awb: "Air waybill",
  bl: "Bill of lading",
  lr: "Lorry receipt",
  container: "Container number",
  seal: "Seal number",
  other: "Other reference",
};

/** Why a packing line has no complete figures. */
export const INCOMPLETE_REASON: Record<string, string> = {
  missing_carton_qty: "Carton quantity unknown",
  missing_cbm: "CBM unknown",
  missing_net_weight: "Net weight unknown",
  missing_gross_weight: "Gross weight unknown",
  cbm_conflict: "Stated CBM and carton size differ by more than 2%",
};

export const evidenceLabel = (kind: string | null) => EVIDENCE_KINDS.find((item) => item.value === kind)?.label ?? (kind ? humanise(kind) : null);
export const exceptionLabel = (code: string | null) => EXCEPTION_CODES.find((item) => item.value === code)?.label ?? (code ? humanise(code) : null);
export const incompleteReason = (code: string) => INCOMPLETE_REASON[code] ?? humanise(code);

// ---------------------------------------------------------------------------------------------
// The order picker: confirmed (or held) sales orders, searched on the server as the person types

export interface OrderOption {
  id: string;
  label: string;
  description?: string;
}

export function useOrderSearch(text: string, chosen: OrderOption | null) {
  const q = useDebouncedValue(text.trim(), 250);
  const enabled = q.length >= 2;
  const search = useQuery({
    queryKey: queryKeys.orders.list({ q, picker: true }),
    queryFn: ({ signal }) => fetchOrders({ q }, signal),
    enabled,
    staleTime: 30_000,
  });
  const found: OrderOption[] = (search.data?.items ?? [])
    .filter((order) => order.status === "confirmed" || order.status === "on_hold")
    .map((order) => ({ id: order.id, label: order.order_number, description: order.party.display_name }));
  const options = [...(chosen ? [chosen] : []), ...found.filter((order) => order.id !== chosen?.id)];
  return {
    options,
    isSearching: enabled && search.isFetching,
    emptyText: q.length < 2 ? "Type two letters of an order number or customer" : search.isError ? "Orders could not be searched. Try again." : "No confirmed order matches",
  };
}
