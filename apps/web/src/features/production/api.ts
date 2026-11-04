/**
 * Production API (backend/app/modules/production/router.py), typed from the generated schema. Reads are scoped by the
 * server (work orders by owner/branch; warehouses by branch); commands carry an Idempotency-Key and answer with the
 * record. Cost figures arrive null (and listed in `redacted_fields`) for anyone without the costing permission.
 */

import { api, idempotencyHeaders, unwrap, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];
export type WorkOrderSummary = Schemas["WorkOrderSummary"];
export type WorkOrderRead = Schemas["WorkOrderRead"];
export type WorkOrderPage = Schemas["Page_WorkOrderSummary_"];
export type MaterialRead = Schemas["MaterialRead"];
export type OperationRead = Schemas["OperationRead"];
export type MasterSummary = Schemas["MasterSummary"];
export type MasterPage = Schemas["Page_MasterSummary_"];
export type BomRead = Schemas["BomRead"];
export type RoutingRead = Schemas["RoutingRead"];
export type WorkCenterSummary = Schemas["WorkCenterSummary"];
export type WorkCenterRead = Schemas["WorkCenterRead"];
export type CapacityRead = Schemas["CapacityRead"];
export type CostRollupRead = Schemas["CostRollupRead"];
export type FeasibilityRead = Schemas["FeasibilityRead"];
export type WorkOrderStatus = WorkOrderSummary["status"];
export type CancelReason = NonNullable<Schemas["WorkOrderTransition"]["reason_code"]>;

export const PAGE_SIZE = 50;
const WO = "/api/v1/production/work-orders/{work_order_id}" as const;

// ---- work orders ----------------------------------------------------------------------------------------------------
export function fetchWorkOrders(
  params: { q?: string; status?: WorkOrderStatus | null; blocked?: boolean; offset?: number; sales_order_id?: string | null },
  signal?: AbortSignal,
  client: ApiClient = api,
): Promise<WorkOrderPage> {
  return unwrap(
    client.GET("/api/v1/production/work-orders", {
      params: {
        query: {
          q: params.q?.trim() || undefined,
          status: params.status ? [params.status] : undefined,
          blocked: params.blocked || undefined,
          sales_order_id: params.sales_order_id || undefined,
          limit: PAGE_SIZE,
          offset: params.offset ?? 0,
        },
      },
      signal,
    }),
  );
}

export function fetchWorkOrder(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<WorkOrderRead> {
  return unwrap(client.GET(WO, { params: { path: { work_order_id: id } }, signal }));
}

export function createWorkOrder(
  body: { product_id: string; quantity: string; warehouse_id?: string | null; planned_start_date?: string | null; due_date?: string | null; notes?: string | null; sales_order_line_id?: string | null },
  key: string,
  client: ApiClient = api,
): Promise<WorkOrderRead> {
  return unwrap(client.POST("/api/v1/production/work-orders", { body: body as Schemas["WorkOrderCreate"], headers: idempotencyHeaders(key) }));
}

export function transitionWorkOrder(
  wo: WorkOrderRead,
  action: "release" | "complete" | "close" | "cancel",
  key: string,
  extra: { reason_code?: CancelReason; reason?: string } = {},
  client: ApiClient = api,
): Promise<WorkOrderRead> {
  return unwrap(
    client.POST(`${WO}/transitions`, {
      params: { path: { work_order_id: wo.id } },
      body: { action, expected_version: wo.version, ...extra },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function recheckWorkOrder(wo: WorkOrderRead, key: string, client: ApiClient = api): Promise<WorkOrderRead> {
  return unwrap(client.POST(`${WO}/recheck`, { params: { path: { work_order_id: wo.id } }, body: { expected_version: wo.version }, headers: idempotencyHeaders(key) }));
}

export type IssueLine = { material_id: string; quantity: string; lot_id?: string | null; from_location_id?: string | null };
export type WipLine = { material_id: string; quantity: string; lot_id?: string | null };

export function issueMaterials(wo: WorkOrderRead, lines: IssueLine[], key: string, client: ApiClient = api): Promise<WorkOrderRead> {
  return unwrap(client.POST(`${WO}/issue`, { params: { path: { work_order_id: wo.id } }, body: { expected_version: wo.version, lines }, headers: idempotencyHeaders(key) }));
}

export function moveFromWip(wo: WorkOrderRead, kind: "consume" | "return", lines: WipLine[], key: string, client: ApiClient = api): Promise<WorkOrderRead> {
  const path = kind === "consume" ? (`${WO}/consume` as const) : (`${WO}/return` as const);
  return unwrap(client.POST(path, { params: { path: { work_order_id: wo.id } }, body: { expected_version: wo.version, lines }, headers: idempotencyHeaders(key) }));
}

export function reportOutput(wo: WorkOrderRead, body: { qty_good: string; qty_scrap?: string }, key: string, client: ApiClient = api): Promise<WorkOrderRead> {
  return unwrap(client.POST(`${WO}/output`, { params: { path: { work_order_id: wo.id } }, body: { expected_version: wo.version, qty_good: body.qty_good, qty_scrap: body.qty_scrap ?? "0" }, headers: idempotencyHeaders(key) }));
}

export function completeOperation(wo: WorkOrderRead, operationId: string, key: string, client: ApiClient = api): Promise<WorkOrderRead> {
  return unwrap(
    client.POST(`${WO}/operations/{operation_id}/complete`, {
      params: { path: { work_order_id: wo.id, operation_id: operationId } },
      body: { expected_version: wo.version },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function linkCutPlan(wo: WorkOrderRead, operationId: string, cutPlanId: string, key: string, client: ApiClient = api): Promise<WorkOrderRead> {
  return unwrap(
    client.POST(`${WO}/operations/{operation_id}/cut-plan`, {
      params: { path: { work_order_id: wo.id, operation_id: operationId } },
      body: { expected_version: wo.version, cut_plan_id: cutPlanId },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function recordOffcut(
  wo: WorkOrderRead,
  body: { material_id: string; operation_id?: string | null; length_mm: string; width_mm: string; thickness_mm?: string | null; predicted_offcut_id?: string | null },
  key: string,
  client: ApiClient = api,
): Promise<WorkOrderRead> {
  return unwrap(client.POST(`${WO}/offcuts`, { params: { path: { work_order_id: wo.id } }, body: { expected_version: wo.version, ...body }, headers: idempotencyHeaders(key) }));
}

// ---- masters -----------------------------------------------------------------------------------------------------------
export function fetchBoms(params: { q?: string; product_id?: string | null }, signal?: AbortSignal, client: ApiClient = api): Promise<MasterPage> {
  return unwrap(client.GET("/api/v1/production/boms", { params: { query: { q: params.q?.trim() || undefined, product_id: params.product_id || undefined, limit: PAGE_SIZE } }, signal }));
}

export function fetchBom(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<BomRead> {
  return unwrap(client.GET("/api/v1/production/boms/{bom_id}", { params: { path: { bom_id: id } }, signal }));
}

export function bomAction(bom: BomRead, action: "approve" | "retire", key: string, reason?: string, client: ApiClient = api): Promise<BomRead> {
  const path = action === "approve" ? ("/api/v1/production/boms/{bom_id}/approve" as const) : ("/api/v1/production/boms/{bom_id}/retire" as const);
  return unwrap(client.POST(path, { params: { path: { bom_id: bom.id } }, body: { expected_version: bom.version, reason: reason || null }, headers: idempotencyHeaders(key) }));
}

export function copyBom(bom: BomRead, key: string, client: ApiClient = api): Promise<BomRead> {
  return unwrap(client.POST("/api/v1/production/boms", { body: { product_id: bom.product.id, copy_from_id: bom.id } as Schemas["BomCreate"], headers: idempotencyHeaders(key) }));
}

export function fetchRoutings(params: { q?: string; product_id?: string | null }, signal?: AbortSignal, client: ApiClient = api): Promise<MasterPage> {
  return unwrap(client.GET("/api/v1/production/routings", { params: { query: { q: params.q?.trim() || undefined, product_id: params.product_id || undefined, limit: PAGE_SIZE } }, signal }));
}

export function fetchRouting(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<RoutingRead> {
  return unwrap(client.GET("/api/v1/production/routings/{routing_id}", { params: { path: { routing_id: id } }, signal }));
}

export function routingAction(routing: RoutingRead, action: "approve" | "retire", key: string, reason?: string, client: ApiClient = api): Promise<RoutingRead> {
  const path = action === "approve" ? ("/api/v1/production/routings/{routing_id}/approve" as const) : ("/api/v1/production/routings/{routing_id}/retire" as const);
  return unwrap(client.POST(path, { params: { path: { routing_id: routing.id } }, body: { expected_version: routing.version, reason: reason || null }, headers: idempotencyHeaders(key) }));
}

export function copyRouting(routing: RoutingRead, key: string, client: ApiClient = api): Promise<RoutingRead> {
  return unwrap(client.POST("/api/v1/production/routings", { body: { product_id: routing.product.id, copy_from_id: routing.id } as Schemas["RoutingCreate"], headers: idempotencyHeaders(key) }));
}

export function fetchWorkCentres(signal?: AbortSignal, client: ApiClient = api): Promise<WorkCenterSummary[]> {
  return unwrap(client.GET("/api/v1/production/work-centers", { signal }));
}

export function fetchWorkCentre(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<WorkCenterRead> {
  return unwrap(client.GET("/api/v1/production/work-centers/{work_center_id}", { params: { path: { work_center_id: id } }, signal }));
}

export function setCapacityException(id: string, body: { exception_date: string; available_minutes: number; reason: string }, key: string, client: ApiClient = api): Promise<WorkCenterRead> {
  return unwrap(client.PUT("/api/v1/production/work-centers/{work_center_id}/capacity-exceptions", { params: { path: { work_center_id: id } }, body, headers: idempotencyHeaders(key) }));
}

export function deleteCapacityException(id: string, exceptionId: string, client: ApiClient = api): Promise<WorkCenterRead> {
  return unwrap(client.DELETE("/api/v1/production/work-centers/{work_center_id}/capacity-exceptions/{exception_id}", { params: { path: { work_center_id: id, exception_id: exceptionId } } }));
}

// ---- planning ------------------------------------------------------------------------------------------------------------
export function fetchCapacity(params: { from?: string | null; to?: string | null }, signal?: AbortSignal, client: ApiClient = api): Promise<CapacityRead> {
  return unwrap(client.GET("/api/v1/production/capacity", { params: { query: { from: params.from || undefined, to: params.to || undefined } }, signal }));
}

export function runCostRollup(productId: string, key: string, client: ApiClient = api): Promise<CostRollupRead> {
  return unwrap(client.POST("/api/v1/production/cost-rollups", { body: { product_id: productId }, headers: idempotencyHeaders(key) }));
}

export function fetchCostRollups(productId: string, signal?: AbortSignal, client: ApiClient = api): Promise<Schemas["Page_CostRollupRead_"]> {
  return unwrap(client.GET("/api/v1/production/cost-rollups", { params: { query: { product_id: productId, limit: 5 } }, signal }));
}

export function fetchOrderLineFeasibility(lineId: string, needBy: string | null, signal?: AbortSignal, client: ApiClient = api): Promise<FeasibilityRead> {
  return unwrap(client.GET("/api/v1/production/feasibility/order-lines/{line_id}", { params: { path: { line_id: lineId }, query: { need_by: needBy || undefined } }, signal }));
}

// ---- what-if (Slice 5): read-only simulation over the feasibility engine --------------------------------------------------
export type SimulationRequest = Schemas["SimulationRequest"];
export type SimulationRead = Schemas["SimulationRead"];

/** Baseline vs scenario for each check; the server refuses every write while simulating (nothing is reserved, posted or saved). */
export function runSimulation(body: SimulationRequest, signal?: AbortSignal, client: ApiClient = api): Promise<SimulationRead> {
  return unwrap(client.POST("/api/v1/production/simulations", { body, signal }));
}

/** Where a component sits (bins and lots) so an issue names the lot and bin it takes from. */
export type ProductPosition = Schemas["ProductPosition"];
export function fetchPosition(productId: string, signal?: AbortSignal, client: ApiClient = api): Promise<ProductPosition> {
  return unwrap(client.GET("/api/v1/inventory/stock/{product_id}", { params: { path: { product_id: productId } }, signal }));
}

