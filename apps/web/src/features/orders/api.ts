/**
 * Sales orders API (backend/app/modules/orders/router.py), typed from the generated schema:
 * - GET  /api/v1/orders/sales-orders                         list (q, status, scope, limit, offset)
 * - POST /api/v1/orders/sales-orders/convert                 convert a won quote (idempotent: `created` false on repeats)
 * - GET  /api/v1/orders/sales-orders/by-quote/{quote_id}     the order converted from a quote (null when none)
 * - GET  /api/v1/orders/sales-orders/{id}                    detail with lines, reservations, documents, history, capabilities
 * - POST /api/v1/orders/sales-orders/{id}/transitions        confirm / hold / release_hold / cancel (Idempotency-Key)
 * - POST /api/v1/orders/sales-orders/{id}/lines/{line}/cancel  cancel what remains of a line
 * - POST /api/v1/orders/sales-orders/{id}/reserve            reserve stock (never oversells; shortfall per line)
 * - POST /api/v1/orders/sales-orders/{id}/release-reservations
 * - POST /api/v1/orders/sales-orders/{id}/challans           a draft delivery challan linked to the order lines
 */

import { api, idempotencyHeaders, unwrap, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { ORDER_STATUSES } from "./list-state";

export { ORDER_STATUSES };

type Schemas = components["schemas"];
export type OrderSummary = Schemas["SalesOrderSummary"];
export type OrderDetail = Schemas["SalesOrderDetail"];
export type OrderLine = Schemas["OrderLineRead"];
export type OrderPage = Schemas["Page_SalesOrderSummary_"];
export type Conversion = Schemas["ConversionResult"];
export type ReserveResponse = Schemas["ReserveResponse"];

export const ORDERS_PAGE_SIZE = 25;

export interface OrderListParams {
  q?: string | null;
  status?: string | null;
  offset?: number;
}

export function fetchOrders(params: OrderListParams, signal?: AbortSignal, client: ApiClient = api): Promise<OrderPage> {
  const status = ORDER_STATUSES.find((s) => s === params.status);
  return unwrap(
    client.GET("/api/v1/orders/sales-orders", {
      params: { query: { q: params.q?.trim() || undefined, status: status ? [status] : undefined, limit: ORDERS_PAGE_SIZE, offset: params.offset ?? 0 } },
      signal,
    }),
  );
}

export function fetchOrder(orderId: string, signal?: AbortSignal, client: ApiClient = api): Promise<OrderDetail> {
  return unwrap(client.GET("/api/v1/orders/sales-orders/{order_id}", { params: { path: { order_id: orderId } }, signal }));
}

export function fetchOrderForQuote(quoteId: string, signal?: AbortSignal, client: ApiClient = api): Promise<OrderSummary | null> {
  return unwrap(client.GET("/api/v1/orders/sales-orders/by-quote/{quote_id}", { params: { path: { quote_id: quoteId } }, signal }));
}

export function convertQuote(quoteId: string, key: string, client: ApiClient = api): Promise<Conversion> {
  return unwrap(client.POST("/api/v1/orders/sales-orders/convert", { body: { quote_id: quoteId }, headers: idempotencyHeaders(key) }));
}

export type OrderAction = "confirm" | "hold" | "release_hold" | "cancel";

export function transitionOrder(
  order: Pick<OrderDetail, "id" | "version">,
  action: OrderAction,
  key: string,
  reason: { code?: string | null; note?: string | null } = {},
  client: ApiClient = api,
): Promise<OrderDetail> {
  return unwrap(
    client.POST("/api/v1/orders/sales-orders/{order_id}/transitions", {
      params: { path: { order_id: order.id } },
      body: { action, expected_version: order.version, reason_code: reason.code || null, reason: reason.note?.trim() || null },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function cancelLine(
  orderId: string,
  line: Pick<OrderLine, "id" | "version">,
  reasonCode: string,
  note: string | null,
  key: string,
  client: ApiClient = api,
): Promise<OrderDetail> {
  return unwrap(
    client.POST("/api/v1/orders/sales-orders/{order_id}/lines/{line_id}/cancel", {
      params: { path: { order_id: orderId, line_id: line.id } },
      body: { expected_version: line.version, reason_code: reasonCode as Schemas["CancelReason"], reason: note?.trim() || null },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function reserveOrder(orderId: string, key: string, client: ApiClient = api): Promise<ReserveResponse> {
  return unwrap(
    client.POST("/api/v1/orders/sales-orders/{order_id}/reserve", {
      params: { path: { order_id: orderId } },
      body: { policy: "partial" },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function releaseReservations(orderId: string, key: string, client: ApiClient = api): Promise<OrderDetail> {
  return unwrap(
    client.POST("/api/v1/orders/sales-orders/{order_id}/release-reservations", {
      params: { path: { order_id: orderId } },
      body: { reason_code: "manual_release" },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function createOrderChallan(orderId: string, key: string, client: ApiClient = api): Promise<Schemas["ChallanCreated"]> {
  return unwrap(
    client.POST("/api/v1/orders/sales-orders/{order_id}/challans", { params: { path: { order_id: orderId } }, body: {}, headers: idempotencyHeaders(key) }),
  );
}

export function createPickList(orderId: string, key: string, client: ApiClient = api): Promise<Schemas["PickListRead"]> {
  return unwrap(client.POST("/api/v1/inventory/pick-lists", { body: { order_id: orderId }, headers: idempotencyHeaders(key) }));
}
