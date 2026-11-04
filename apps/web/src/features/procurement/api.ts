/**
 * Purchasing API (backend/app/modules/procurement/router.py), typed from the generated schema:
 * - requisitions: list, create, detail, transitions (submit / approve / reject / cancel / close), convert to a PO
 * - purchase orders: list (status, overdue, q), create, detail, transitions, line expected date, line cancel, bills
 * - goods receipts: list (awaiting QC), create (+ post), detail, post
 * - vendor bills: create (matches at once), match again, hand off; vendor items per vendor
 * Every command sends an Idempotency-Key; scope is enforced by the server (404 outside it).
 */

import { api, idempotencyHeaders, unwrap, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];
export type RequisitionSummary = Schemas["RequisitionSummary"];
export type RequisitionDetail = Schemas["RequisitionDetail"];
export type PoSummary = Schemas["PoSummary"];
export type PoDetail = Schemas["PoDetail"];
export type PoLine = Schemas["PoLineRead"];
export type GrnSummary = Schemas["GrnSummary"];
export type GrnDetail = Schemas["GrnDetail"];
export type BillRead = Schemas["BillRead"];
export type VendorItem = Schemas["VendorItemRead"];
export type PoAction = Schemas["PoTransitionAction"];
export type RequisitionAction = Schemas["RequisitionAction"];

export const PAGE_SIZE = 25;
export const REQUISITION_STATUSES = ["draft", "submitted", "approved", "rejected", "closed", "cancelled"] as const;
export const PO_STATUSES = ["draft", "pending_approval", "approved", "issued", "partially_received", "received", "closed", "cancelled"] as const;

const pick = <T extends string>(values: readonly T[], value: string | null | undefined): T[] | undefined => {
  const found = values.find((v) => v === value);
  return found ? [found] : undefined;
};

// ---- requisitions -------------------------------------------------------------------------------------------------
export function fetchRequisitions(params: { status?: string | null; offset?: number }, signal?: AbortSignal, client: ApiClient = api) {
  return unwrap(
    client.GET("/api/v1/procurement/requisitions", {
      params: { query: { status: pick(REQUISITION_STATUSES, params.status), limit: PAGE_SIZE, offset: params.offset ?? 0 } },
      signal,
    }),
  );
}

export function fetchRequisition(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<RequisitionDetail> {
  return unwrap(client.GET("/api/v1/procurement/requisitions/{requisition_id}", { params: { path: { requisition_id: id } }, signal }));
}

export interface RequisitionDraft {
  warehouse_id: string;
  required_by: string | null;
  notes: string;
  lines: { product_id: string; quantity: string }[];
}

export function createRequisition(draft: RequisitionDraft, key: string, client: ApiClient = api): Promise<RequisitionDetail> {
  return unwrap(
    client.POST("/api/v1/procurement/requisitions", {
      body: { warehouse_id: draft.warehouse_id, required_by: draft.required_by, notes: draft.notes.trim() || null, lines: draft.lines },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function requisitionAction(r: Pick<RequisitionDetail, "id" | "version">, action: RequisitionAction, key: string, note?: string | null, client: ApiClient = api) {
  return unwrap(
    client.POST("/api/v1/procurement/requisitions/{requisition_id}/transitions", {
      params: { path: { requisition_id: r.id } },
      body: { action, expected_version: r.version, note: note?.trim() || null },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function convertRequisition(
  r: Pick<RequisitionDetail, "id" | "version">,
  vendorId: string,
  unitPrices: Record<string, string>,
  key: string,
  client: ApiClient = api,
): Promise<PoDetail> {
  return unwrap(
    client.POST("/api/v1/procurement/requisitions/{requisition_id}/convert", {
      params: { path: { requisition_id: r.id } },
      body: { expected_version: r.version, vendor_party_id: vendorId, unit_prices: unitPrices },
      headers: idempotencyHeaders(key),
    }),
  );
}

// ---- purchase orders ----------------------------------------------------------------------------------------------
export interface PoListParams {
  q?: string | null;
  status?: string | null;
  overdue?: boolean;
  offset?: number;
}

export function fetchPurchaseOrders(params: PoListParams, signal?: AbortSignal, client: ApiClient = api) {
  return unwrap(
    client.GET("/api/v1/procurement/purchase-orders", {
      params: {
        query: {
          q: params.q?.trim() || undefined,
          status: pick(PO_STATUSES, params.status),
          overdue: params.overdue || undefined,
          limit: PAGE_SIZE,
          offset: params.offset ?? 0,
        },
      },
      signal,
    }),
  );
}

export function fetchPurchaseOrder(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<PoDetail> {
  return unwrap(client.GET("/api/v1/procurement/purchase-orders/{po_id}", { params: { path: { po_id: id } }, signal }));
}

export function poAction(po: Pick<PoDetail, "id" | "version">, action: PoAction, key: string, reason?: string | null, client: ApiClient = api): Promise<PoDetail> {
  return unwrap(
    client.POST("/api/v1/procurement/purchase-orders/{po_id}/transitions", {
      params: { path: { po_id: po.id } },
      body: { action, expected_version: po.version, reason: reason?.trim() || null },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function moveExpectedDate(poId: string, line: Pick<PoLine, "id" | "version">, date: string, key: string, client: ApiClient = api): Promise<PoDetail> {
  return unwrap(
    client.POST("/api/v1/procurement/purchase-orders/{po_id}/lines/{line_id}/expected-date", {
      params: { path: { po_id: poId, line_id: line.id } },
      body: { expected_version: line.version, expected_date: date },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function fetchBills(poId: string, signal?: AbortSignal, client: ApiClient = api) {
  return unwrap(client.GET("/api/v1/procurement/purchase-orders/{po_id}/bills", { params: { path: { po_id: poId } }, signal }));
}

// ---- goods receipts -----------------------------------------------------------------------------------------------
export function fetchReceipts(params: { awaitingQc?: boolean; offset?: number }, signal?: AbortSignal, client: ApiClient = api) {
  return unwrap(
    client.GET("/api/v1/procurement/goods-receipts", {
      params: { query: { awaiting_qc: params.awaitingQc || undefined, limit: PAGE_SIZE, offset: params.offset ?? 0 } },
      signal,
    }),
  );
}

export function fetchReceipt(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<GrnDetail> {
  return unwrap(client.GET("/api/v1/procurement/goods-receipts/{grn_id}", { params: { path: { grn_id: id } }, signal }));
}

export interface ReceiptLineDraft {
  po_line_id: string;
  quantity: string;
  lot_code?: string | null;
}

/** Create and post a receipt in one command (one stock posting). */
export function receiveGoods(poId: string, lines: ReceiptLineDraft[], vendorChallan: string, key: string, client: ApiClient = api): Promise<GrnDetail> {
  return unwrap(
    client.POST("/api/v1/procurement/goods-receipts", {
      body: {
        purchase_order_id: poId,
        vendor_challan_ref: vendorChallan.trim() || null,
        post: true,
        lines: lines.map((l) => ({ po_line_id: l.po_line_id, quantity: l.quantity, lot_code: l.lot_code?.trim() || null })),
      },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function postReceipt(grn: Pick<GrnDetail, "id" | "version">, key: string, client: ApiClient = api): Promise<GrnDetail> {
  return unwrap(
    client.POST("/api/v1/procurement/goods-receipts/{grn_id}/post", {
      params: { path: { grn_id: grn.id } },
      body: { expected_version: grn.version },
      headers: idempotencyHeaders(key),
    }),
  );
}

// ---- vendor bills -------------------------------------------------------------------------------------------------
export interface BillDraft {
  bill_number: string;
  bill_date: string;
  subtotal_amount: string;
  tax_amount: string;
  total_amount: string;
  lines: { po_line_id: string; quantity: string; unit_price: string }[];
}

export function createBill(poId: string, draft: BillDraft, key: string, client: ApiClient = api): Promise<BillRead> {
  return unwrap(client.POST("/api/v1/procurement/vendor-bills", { body: { purchase_order_id: poId, ...draft }, headers: idempotencyHeaders(key) }));
}

export function billAction(bill: Pick<BillRead, "id" | "version">, action: "match" | "hand-off", key: string, client: ApiClient = api): Promise<BillRead> {
  const body = { expected_version: bill.version };
  const options = { params: { path: { bill_id: bill.id } }, body, headers: idempotencyHeaders(key) };
  return unwrap(
    action === "match"
      ? client.POST("/api/v1/procurement/vendor-bills/{bill_id}/match", options)
      : client.POST("/api/v1/procurement/vendor-bills/{bill_id}/hand-off", options),
  );
}

// ---- vendor items -------------------------------------------------------------------------------------------------
export function fetchVendorItems(vendorId: string, history: boolean, signal?: AbortSignal, client: ApiClient = api) {
  return unwrap(
    client.GET("/api/v1/procurement/vendor-items", { params: { query: { vendor_party_id: vendorId, include_history: history || undefined } }, signal }),
  );
}

export interface VendorItemDraft {
  vendor_party_id: string;
  product_id: string;
  vendor_code: string;
  lead_time_days: number | null;
  unit_price: string;
  currency: "INR" | "EUR" | "USD" | "GBP";
}

export function saveVendorItem(draft: VendorItemDraft, key: string, client: ApiClient = api): Promise<VendorItem> {
  return unwrap(
    client.POST("/api/v1/procurement/vendor-items", {
      body: { ...draft, vendor_code: draft.vendor_code.trim() || null },
      headers: idempotencyHeaders(key),
    }),
  );
}
