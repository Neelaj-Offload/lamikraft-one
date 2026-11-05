/**
 * The cutting API (INTERIM(api-generate): requestUntyped + parse.ts until schema.d.ts carries the routes):
 * - cutting_list_cut_plans            GET    /api/v1/cutting/plans
 * - cutting_create_cut_plan           POST   /api/v1/cutting/plans
 * - cutting_get_cut_plan              GET    /api/v1/cutting/plans/{plan_id}
 * - cutting_update_cut_plan           PATCH  /api/v1/cutting/plans/{plan_id}
 * - cutting_calculate_cut_plan        POST   /api/v1/cutting/plans/{plan_id}/calculate
 * - cutting_duplicate_cut_plan        POST   /api/v1/cutting/plans/{plan_id}/duplicate
 * - cutting_transition_cut_plan       POST   /api/v1/cutting/plans/{plan_id}/transitions
 * - cutting_verify_cut_plan_boards    POST   /api/v1/cutting/plans/{plan_id}/verify-boards
 * - cutting_search_cutting_products   GET    /api/v1/cutting/products?search=
 * - cutting_list_grain_locks / add / remove under /api/v1/cutting/grain-locks
 * Exports are plain links (cookie-authenticated downloads): export.csv, export.pdf and per-board SVG.
 */

import { api, idempotencyHeaders, requestUntyped, unwrap, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { parseGrainLocks, parsePage, parsePlanDetail, parsePlanSummary, parseProducts } from "./parse";
import type { CuttingProduct, GrainLockList, Page, PlanDetail, PlanItemRequest, PlanSettingsRequest, PlanSummary } from "./types";

export const CUTTING_API = "/api/v1/cutting";
export const PLANS_PATH = "/api/v1/cutting/plans";
export const PLANS_PAGE_SIZE = 25;

const planPath = (planId: string): `/api/v1/${string}` => `${PLANS_PATH}/${encodeURIComponent(planId)}`;

export interface PlanListParams {
  q?: string | null;
  status?: string | null;
  scope?: "mine" | "all" | null;
  offset?: number | null;
}

export async function fetchPlans(params: PlanListParams, signal?: AbortSignal, client: ApiClient = api): Promise<Page<PlanSummary>> {
  const raw = await requestUntyped<unknown>(client, "get", PLANS_PATH, {
    params: {
      query: {
        q: params.q?.trim() || undefined,
        status: params.status || undefined,
        scope: params.scope ?? undefined,
        include_archived: params.status === "archived" ? true : undefined,
        offset: params.offset ?? 0,
        limit: PLANS_PAGE_SIZE,
      },
    },
    signal,
  });
  return parsePage(raw, parsePlanSummary);
}

export async function fetchPlan(planId: string, signal?: AbortSignal, client: ApiClient = api): Promise<PlanDetail> {
  return parsePlanDetail(await requestUntyped<unknown>(client, "get", planPath(planId), { signal }));
}

export interface PlanWrite {
  name?: string;
  items?: PlanItemRequest[];
  settings?: PlanSettingsRequest;
}

export async function createPlan(body: PlanWrite, idempotencyKey: string, client: ApiClient = api): Promise<PlanDetail> {
  return parsePlanDetail(await requestUntyped<unknown>(client, "post", PLANS_PATH, { body, headers: idempotencyHeaders(idempotencyKey) }));
}

export async function updatePlan(
  plan: Pick<PlanDetail, "id" | "version">,
  changes: PlanWrite,
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<PlanDetail> {
  const raw = await requestUntyped<unknown>(client, "patch", planPath(plan.id), {
    body: { expected_version: plan.version, ...changes },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return parsePlanDetail(raw);
}

export async function calculatePlan(plan: Pick<PlanDetail, "id" | "version">, idempotencyKey: string, client: ApiClient = api): Promise<PlanDetail> {
  const raw = await requestUntyped<unknown>(client, "post", `${planPath(plan.id)}/calculate`, {
    body: { expected_version: plan.version },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return parsePlanDetail(raw);
}

export async function duplicatePlan(plan: Pick<PlanDetail, "id">, idempotencyKey: string, client: ApiClient = api): Promise<PlanDetail> {
  return parsePlanDetail(await requestUntyped<unknown>(client, "post", `${planPath(plan.id)}/duplicate`, { headers: idempotencyHeaders(idempotencyKey) }));
}

export async function archivePlan(plan: Pick<PlanDetail, "id" | "version">, idempotencyKey: string, client: ApiClient = api): Promise<PlanDetail> {
  const raw = await requestUntyped<unknown>(client, "post", `${planPath(plan.id)}/transitions`, {
    body: { action: "archive", expected_version: plan.version },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return parsePlanDetail(raw);
}

export async function verifyBoards(
  plan: Pick<PlanDetail, "id" | "version">,
  measured: { length_mm: string; width_mm: string; note?: string },
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<PlanDetail> {
  const raw = await requestUntyped<unknown>(client, "post", `${planPath(plan.id)}/verify-boards`, {
    body: {
      expected_version: plan.version,
      measured_length_mm: measured.length_mm,
      measured_width_mm: measured.width_mm,
      ...(measured.note?.trim() ? { note: measured.note.trim() } : {}),
    },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return parsePlanDetail(raw);
}

// ---- offcut reuse (Slice 5; typed from the generated schema) ------------------------------------------------------
export type OffcutCandidates = components["schemas"]["OffcutCandidates"];
export type OffcutCandidate = OffcutCandidates["items"][number];

/** Measured offcut lots on hand in warehouses the viewer can read, with whether a group of the plan matches. */
export function fetchOffcutCandidates(planId: string, signal?: AbortSignal, client: ApiClient = api): Promise<OffcutCandidates> {
  return unwrap(client.GET("/api/v1/cutting/plans/{plan_id}/offcut-candidates", { params: { path: { plan_id: planId } }, signal }));
}

/** Replace the plan's offcut choice (filled in this order before standard sheets); a calculated plan becomes stale. */
export async function saveOffcuts(plan: Pick<PlanDetail, "id" | "version">, lotIds: string[], idempotencyKey: string, client: ApiClient = api): Promise<PlanDetail> {
  const raw = await requestUntyped<unknown>(client, "put", `${planPath(plan.id)}/offcuts`, {
    body: { expected_version: plan.version, lot_ids: lotIds },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return parsePlanDetail(raw);
}

export async function searchCuttingProducts(search: string, signal?: AbortSignal, client: ApiClient = api): Promise<CuttingProduct[]> {
  const raw = await requestUntyped<unknown>(client, "get", `${CUTTING_API}/products`, { params: { query: { search: search.trim(), limit: 10 } }, signal });
  return parseProducts(raw);
}

export const GRAIN_LOCKS_PATH = "/api/v1/cutting/grain-locks";

export async function fetchGrainLocks(signal?: AbortSignal, client: ApiClient = api): Promise<GrainLockList> {
  return parseGrainLocks(await requestUntyped<unknown>(client, "get", GRAIN_LOCKS_PATH, { signal }));
}

export async function addGrainLock(body: { decor: string; label?: string | null }, idempotencyKey: string, client: ApiClient = api): Promise<GrainLockList> {
  const payload = { decor: body.decor.trim(), ...(body.label?.trim() ? { label: body.label.trim() } : {}) };
  return parseGrainLocks(await requestUntyped<unknown>(client, "post", GRAIN_LOCKS_PATH, { body: payload, headers: idempotencyHeaders(idempotencyKey) }));
}

export async function removeGrainLock(decorKey: string, idempotencyKey: string, client: ApiClient = api): Promise<GrainLockList> {
  return parseGrainLocks(
    await requestUntyped<unknown>(client, "delete", `${GRAIN_LOCKS_PATH}/${encodeURIComponent(decorKey)}`, { headers: idempotencyHeaders(idempotencyKey) }),
  );
}
