/**
 * Dispatch API (backend/app/modules/logistics/router.py), typed from the generated schema:
 * - packing lists: list, create from an order, detail, refresh packaging, enter values for a line, finalise, cancel
 * - shipments: list (ordered by cutoff), plan, detail, update (link challan / packing list, cutoff), transitions,
 *   tracking references
 * - container profiles and the read-only load suggestion
 * Every command sends an Idempotency-Key; records outside the actor's scope are 404.
 */

import { api, idempotencyHeaders, unwrap, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];
export type PackingListSummary = Schemas["PackingListSummary"];
export type PackingListDetail = Schemas["PackingListDetail"];
export type PackingLine = Schemas["PackingLineRead"];
export type ShipmentSummary = Schemas["ShipmentSummary"];
export type ShipmentDetail = Schemas["ShipmentDetail"];
export type ShipmentAction = Schemas["ShipmentAction"];
export type ShipmentMode = Schemas["ShipmentMode"];
export type EvidenceKind = Schemas["EvidenceKind"];
export type ExceptionCode = Schemas["ExceptionCode"];
export type TrackingRefType = Schemas["TrackingRefType"];
export type ContainerProfile = Schemas["ContainerProfileRead"];
export type LoadSuggestion = Schemas["LoadSuggestion"];

export const PAGE_SIZE = 25;
export const SHIPMENT_STATUSES = ["planned", "booked", "dispatched", "in_transit", "delivered", "exception", "cancelled"] as const;
export const PACKING_STATUSES = ["draft", "final", "cancelled"] as const;
export const SHIPMENT_MODES = ["road", "sea", "air", "courier", "hand"] as const satisfies readonly ShipmentMode[];
export const TRACKING_TYPES = ["awb", "bl", "lr", "container", "seal", "other"] as const satisfies readonly TrackingRefType[];

const pick = <T extends string>(values: readonly T[], value: string | null | undefined): T[] | undefined => {
  const found = values.find((v) => v === value);
  return found ? [found] : undefined;
};

// ---- packing lists ------------------------------------------------------------------------------------------------
export function fetchPackingLists(params: { status?: string | null; salesOrderId?: string | null; offset?: number }, signal?: AbortSignal, client: ApiClient = api) {
  return unwrap(
    client.GET("/api/v1/logistics/packing-lists", {
      params: {
        query: { status: pick(PACKING_STATUSES, params.status), sales_order_id: params.salesOrderId ?? undefined, limit: PAGE_SIZE, offset: params.offset ?? 0 },
      },
      signal,
    }),
  );
}

export function fetchPackingList(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<PackingListDetail> {
  return unwrap(client.GET("/api/v1/logistics/packing-lists/{packing_list_id}", { params: { path: { packing_list_id: id } }, signal }));
}

export function createPackingList(salesOrderId: string, key: string, client: ApiClient = api): Promise<PackingListDetail> {
  return unwrap(client.POST("/api/v1/logistics/packing-lists", { body: { sales_order_id: salesOrderId }, headers: idempotencyHeaders(key) }));
}

export function packingListAction(pl: Pick<PackingListDetail, "id" | "version">, action: "refresh" | "finalise" | "cancel", key: string, client: ApiClient = api): Promise<PackingListDetail> {
  const options = { params: { path: { packing_list_id: pl.id } }, body: { expected_version: pl.version }, headers: idempotencyHeaders(key) };
  return unwrap(
    action === "refresh"
      ? client.POST("/api/v1/logistics/packing-lists/{packing_list_id}/refresh", options)
      : action === "finalise"
        ? client.POST("/api/v1/logistics/packing-lists/{packing_list_id}/finalise", options)
        : client.POST("/api/v1/logistics/packing-lists/{packing_list_id}/cancel", options),
  );
}

export interface LineOverrideDraft {
  cbm: string | null;
  net_kg: string | null;
  gross_kg: string | null;
  reason: string;
}

export function overrideLine(pl: Pick<PackingListDetail, "id" | "version">, lineId: string, draft: LineOverrideDraft, key: string, client: ApiClient = api): Promise<PackingListDetail> {
  return unwrap(
    client.POST("/api/v1/logistics/packing-lists/{packing_list_id}/lines/{line_id}/override", {
      params: { path: { packing_list_id: pl.id, line_id: lineId } },
      body: { expected_version: pl.version, cbm: draft.cbm, net_kg: draft.net_kg, gross_kg: draft.gross_kg, reason: draft.reason.trim() },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function fetchContainerProfiles(signal?: AbortSignal, client: ApiClient = api) {
  return unwrap(client.GET("/api/v1/logistics/container-profiles", { signal }));
}

export function suggestLoad(packingListId: string, containerProfileId: string, client: ApiClient = api): Promise<LoadSuggestion> {
  return unwrap(client.POST("/api/v1/logistics/load-suggestions", { body: { packing_list_id: packingListId, container_profile_id: containerProfileId } }));
}

// ---- shipments ----------------------------------------------------------------------------------------------------
export function fetchShipments(params: { q?: string | null; status?: string | null; offset?: number }, signal?: AbortSignal, client: ApiClient = api) {
  return unwrap(
    client.GET("/api/v1/logistics/shipments", {
      params: { query: { q: params.q?.trim() || undefined, status: pick(SHIPMENT_STATUSES, params.status), limit: PAGE_SIZE, offset: params.offset ?? 0 } },
      signal,
    }),
  );
}

export function fetchShipment(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<ShipmentDetail> {
  return unwrap(client.GET("/api/v1/logistics/shipments/{shipment_id}", { params: { path: { shipment_id: id } }, signal }));
}

export interface ShipmentDraft {
  sales_order_id: string;
  mode: ShipmentMode;
  transporter_name: string;
  cutoff_date: string | null;
  cutoff_time: string | null;
}

export function planShipment(draft: ShipmentDraft, key: string, client: ApiClient = api): Promise<ShipmentDetail> {
  return unwrap(
    client.POST("/api/v1/logistics/shipments", {
      body: {
        sales_order_id: draft.sales_order_id,
        mode: draft.mode,
        transporter_name: draft.transporter_name.trim() || null,
        cutoff_date: draft.cutoff_date,
        cutoff_time: draft.cutoff_date && draft.cutoff_time ? draft.cutoff_time : null,
      },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function linkShipment(sh: Pick<ShipmentDetail, "id" | "version">, link: { challan_id?: string; packing_list_id?: string }, key: string, client: ApiClient = api): Promise<ShipmentDetail> {
  return unwrap(
    client.PATCH("/api/v1/logistics/shipments/{shipment_id}", {
      params: { path: { shipment_id: sh.id } },
      body: { expected_version: sh.version, ...link },
      headers: idempotencyHeaders(key),
    }),
  );
}

export interface TransitionExtras {
  evidence_kind?: EvidenceKind;
  evidence_note?: string;
  exception_code?: ExceptionCode;
  note?: string;
  reason?: string;
}

export function transitionShipment(sh: Pick<ShipmentDetail, "id" | "version">, action: ShipmentAction, extras: TransitionExtras, key: string, client: ApiClient = api): Promise<ShipmentDetail> {
  const text = (v: string | undefined) => (v?.trim() ? v.trim() : null);
  return unwrap(
    client.POST("/api/v1/logistics/shipments/{shipment_id}/transitions", {
      params: { path: { shipment_id: sh.id } },
      body: {
        action,
        expected_version: sh.version,
        evidence_kind: extras.evidence_kind ?? null,
        evidence_note: text(extras.evidence_note),
        exception_code: extras.exception_code ?? null,
        note: text(extras.note),
        reason: text(extras.reason),
      },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function addTrackingRef(shipmentId: string, refType: TrackingRefType, value: string, key: string, client: ApiClient = api): Promise<ShipmentDetail> {
  return unwrap(
    client.POST("/api/v1/logistics/shipments/{shipment_id}/tracking-refs", {
      params: { path: { shipment_id: shipmentId } },
      body: { ref_type: refType, value: value.trim() },
      headers: idempotencyHeaders(key),
    }),
  );
}
