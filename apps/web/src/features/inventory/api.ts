/**
 * Inventory API (backend/app/modules/inventory/router.py), typed from the generated schema. Reads are filtered to the
 * actor's warehouses by the server; commands carry an Idempotency-Key and answer with the document.
 */

import { api, idempotencyHeaders, unwrap, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];
export type StockPage = Schemas["StockPage"];
export type StockRow = Schemas["StockRow"];
export type MovementPage = Schemas["MovementPage"];
export type MovementRow = Schemas["MovementRead"];
export type ReservationPage = Schemas["ReservationPage"];
export type ReservationRow = Schemas["ReservationRead"];
export type Shortage = Schemas["ShortageRead"];
export type Warehouse = Schemas["WarehouseRead"];
export type DocumentSummary = Schemas["DocumentSummary"];
export type DocumentRead = Schemas["DocumentRead"];
export type CountRead = Schemas["CountRead"];
export type PickListRead = Schemas["PickListRead"];
export type DocumentKind = "adjustment" | "opening_batch" | "transfer";

export const PAGE_SIZE = 50;

export function fetchWarehouses(signal?: AbortSignal, client: ApiClient = api): Promise<Warehouse[]> {
  return unwrap(client.GET("/api/v1/inventory/warehouses", { signal }));
}

export function fetchStock(
  params: { q?: string; warehouse_id?: string | null; short_only?: boolean; offset?: number },
  signal?: AbortSignal,
  client: ApiClient = api,
): Promise<StockPage> {
  return unwrap(
    client.GET("/api/v1/inventory/stock", {
      params: {
        query: {
          q: params.q?.trim() || undefined,
          warehouse_id: params.warehouse_id || undefined,
          short_only: params.short_only || undefined,
          limit: PAGE_SIZE,
          offset: params.offset ?? 0,
        },
      },
      signal,
    }),
  );
}

export function fetchMovements(params: { offset?: number; source_id?: string | null }, signal?: AbortSignal, client: ApiClient = api): Promise<MovementPage> {
  return unwrap(
    client.GET("/api/v1/inventory/movements", {
      params: { query: { limit: PAGE_SIZE, offset: params.offset ?? 0, source_id: params.source_id || undefined } },
      signal,
    }),
  );
}

export function fetchReservations(params: { status?: string | null; offset?: number }, signal?: AbortSignal, client: ApiClient = api): Promise<ReservationPage> {
  const status = (["active", "fulfilled", "released", "cancelled"] as const).find((s) => s === params.status);
  return unwrap(client.GET("/api/v1/inventory/reservations", { params: { query: { status, limit: PAGE_SIZE, offset: params.offset ?? 0 } }, signal }));
}

export function releaseReservation(reservationId: string, key: string, client: ApiClient = api): Promise<ReservationRow> {
  return unwrap(
    client.POST("/api/v1/inventory/reservations/{reservation_id}/release", {
      params: { path: { reservation_id: reservationId } },
      body: { reason_code: "manual_release" },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function fetchShortages(signal?: AbortSignal, client: ApiClient = api): Promise<Shortage[]> {
  return unwrap(client.GET("/api/v1/inventory/shortages", { signal }));
}

export function fetchDocuments(kind: DocumentKind | "stock_count" | "pick_list", signal?: AbortSignal, client: ApiClient = api): Promise<DocumentSummary[]> {
  return unwrap(client.GET("/api/v1/inventory/documents", { params: { query: { kind, limit: PAGE_SIZE } }, signal }));
}

// ---- stock counts -------------------------------------------------------------------------------------------
export function fetchCount(countId: string, signal?: AbortSignal, client: ApiClient = api): Promise<CountRead> {
  return unwrap(client.GET("/api/v1/inventory/stock-counts/{count_id}", { params: { path: { count_id: countId } }, signal }));
}

export function createCount(warehouseId: string, key: string, client: ApiClient = api): Promise<CountRead> {
  return unwrap(client.POST("/api/v1/inventory/stock-counts", { body: { warehouse_id: warehouseId }, headers: idempotencyHeaders(key) }));
}

export function countAction(count: Pick<CountRead, "id" | "version">, action: "freeze" | "submit" | "cancel", key: string, client: ApiClient = api): Promise<CountRead> {
  return unwrap(
    client.POST("/api/v1/inventory/stock-counts/{count_id}/{action}", {
      params: { path: { count_id: count.id, action } },
      body: { expected_version: count.version },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function enterCounts(count: Pick<CountRead, "id" | "version">, entries: { line_id: string; counted_quantity: string }[], key: string, client: ApiClient = api): Promise<CountRead> {
  return unwrap(
    client.POST("/api/v1/inventory/stock-counts/{count_id}/entries", {
      params: { path: { count_id: count.id } },
      body: { expected_version: count.version, entries },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function approveCount(count: Pick<CountRead, "id" | "version">, key: string, client: ApiClient = api): Promise<CountRead> {
  return unwrap(
    client.POST("/api/v1/inventory/stock-counts/{count_id}/approve", {
      params: { path: { count_id: count.id } },
      body: { expected_version: count.version },
      headers: idempotencyHeaders(key),
    }),
  );
}

// ---- pick lists ---------------------------------------------------------------------------------------------
export function fetchPickList(pickListId: string, signal?: AbortSignal, client: ApiClient = api): Promise<PickListRead> {
  return unwrap(client.GET("/api/v1/inventory/pick-lists/{pick_list_id}", { params: { path: { pick_list_id: pickListId } }, signal }));
}

export function pickListAction(pl: Pick<PickListRead, "id" | "version">, action: "release" | "cancel", key: string, client: ApiClient = api): Promise<PickListRead> {
  return unwrap(
    client.POST("/api/v1/inventory/pick-lists/{pick_list_id}/{action}", {
      params: { path: { pick_list_id: pl.id, action } },
      body: { expected_version: pl.version },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function confirmPick(pl: Pick<PickListRead, "id" | "version">, entries: { line_id: string; picked_quantity: string }[], key: string, client: ApiClient = api): Promise<PickListRead> {
  return unwrap(
    client.POST("/api/v1/inventory/pick-lists/{pick_list_id}/pick", {
      params: { path: { pick_list_id: pl.id } },
      body: { expected_version: pl.version, entries },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function pickListChallan(pickListId: string, key: string, client: ApiClient = api): Promise<PickListRead> {
  return unwrap(client.POST("/api/v1/inventory/pick-lists/{pick_list_id}/challan", { params: { path: { pick_list_id: pickListId } }, headers: idempotencyHeaders(key) }));
}

// ---- adjustments, opening batches, transfers -------------------------------------------------------------------
export function fetchDocument(kind: DocumentKind, id: string, signal?: AbortSignal, client: ApiClient = api): Promise<DocumentRead> {
  if (kind === "adjustment") return unwrap(client.GET("/api/v1/inventory/adjustments/{adjustment_id}", { params: { path: { adjustment_id: id } }, signal }));
  if (kind === "opening_batch") return unwrap(client.GET("/api/v1/inventory/opening-batches/{batch_id}", { params: { path: { batch_id: id } }, signal }));
  return unwrap(client.GET("/api/v1/inventory/transfers/{transfer_id}", { params: { path: { transfer_id: id } }, signal }));
}

export type DocumentAction = "submit" | "approve" | "reject" | "dispatch" | "receive" | "cancel";

export function documentAction(
  doc: Pick<DocumentRead, "id" | "version" | "kind">,
  action: DocumentAction,
  key: string,
  note: string | null = null,
  client: ApiClient = api,
): Promise<DocumentRead> {
  const headers = idempotencyHeaders(key);
  const versioned = { expected_version: doc.version };
  const decision = { expected_version: doc.version, note: note?.trim() || null };
  if (doc.kind === "transfer") {
    const transferAction = action === "dispatch" || action === "receive" ? action : "cancel";
    return unwrap(
      client.POST("/api/v1/inventory/transfers/{transfer_id}/{action}", { params: { path: { transfer_id: doc.id, action: transferAction } }, body: versioned, headers }),
    );
  }
  if (doc.kind === "adjustment") {
    const path = { adjustment_id: doc.id };
    if (action === "submit") return unwrap(client.POST("/api/v1/inventory/adjustments/{adjustment_id}/submit", { params: { path }, body: versioned, headers }));
    if (action === "approve") return unwrap(client.POST("/api/v1/inventory/adjustments/{adjustment_id}/approve", { params: { path }, body: decision, headers }));
    return unwrap(client.POST("/api/v1/inventory/adjustments/{adjustment_id}/reject", { params: { path }, body: decision, headers }));
  }
  const path = { batch_id: doc.id };
  if (action === "submit") return unwrap(client.POST("/api/v1/inventory/opening-batches/{batch_id}/submit", { params: { path }, body: versioned, headers }));
  if (action === "approve") return unwrap(client.POST("/api/v1/inventory/opening-batches/{batch_id}/approve", { params: { path }, body: decision, headers }));
  return unwrap(client.POST("/api/v1/inventory/opening-batches/{batch_id}/reject", { params: { path }, body: decision, headers }));
}
