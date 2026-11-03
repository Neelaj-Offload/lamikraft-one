/**
 * The challans API (backend/app/modules/challans/router.py; INTERIM(api-generate): parsed at runtime, see types.ts):
 * - GET    /api/v1/challans/challans                       list (q, status, challan_type, destination_type, period, pending_returnable, scope)
 * - GET    /api/v1/challans/challans/summary               the summary cards over the same filters and scope
 * - GET    /api/v1/challans/challans/export.csv            CSV over the same filters (a real download link)
 * - POST   /api/v1/challans/challans                       create a draft (Idempotency-Key)
 * - GET    /api/v1/challans/challans/{id}                  detail with lines, links, history, capabilities, allowed_transitions
 * - PATCH  /api/v1/challans/challans/{id}                  header of a draft (`expected_version`, dirty fields)
 * - DELETE /api/v1/challans/challans/{id}?expected_version= soft-delete a draft (admin)
 * - POST   /api/v1/challans/challans/{id}/lines            add a line
 * - PATCH  /api/v1/challans/challans/{id}/lines/{line_id}  edit a line (`expected_version`)
 * - DELETE /api/v1/challans/challans/{id}/lines/{line_id}?expected_version=
 * - POST   /api/v1/challans/challans/{id}/transitions      issue / close / cancel (Idempotency-Key)
 * - POST   /api/v1/challans/challans/{id}/duplicate        a new draft copying header and lines
 * - GET    /api/v1/challans/challans/{id}/print            the print-view data (never the internal note)
 * - GET    /api/v1/challans/challans/{id}/document.pdf     the PDF (a real link; inline, sandboxed)
 * - GET/PUT /api/v1/collab/notes?resource_type=challans.challan&resource_id=  the internal note
 * Every command answers with the challan (`ChallanDetail`); if a response is not one, the caller refetches.
 */

import { api, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import { challanOrNull, parseChallanDetail, parseChallanPage, parseChallanPrint, parseChallanSummary, parseNote } from "./parse";
import type {
  ChallanCreateRequest,
  ChallanDetail,
  ChallanHeaderFields,
  ChallanPrint,
  ChallanSummary,
  ChallanSummaryRow,
  InternalNote,
  LineCreateRequest,
  LineUpdateRequest,
  Page,
} from "./types";

export const CHALLANS_PATH = "/api/v1/challans/challans";
export const CHALLANS_PAGE_SIZE = 25;
const NOTES_PATH = "/api/v1/collab/notes";
export const CHALLAN_RESOURCE = "challans.challan";

type Versioned = Pick<ChallanDetail, "id" | "version">;
const challanPath = (challanId: string): `/api/v1/${string}` => `${CHALLANS_PATH}/${encodeURIComponent(challanId)}`;
const linePath = (challanId: string, lineId: string): `/api/v1/${string}` => `${challanPath(challanId)}/lines/${encodeURIComponent(lineId)}`;

export interface ChallanListParams {
  q?: string | null;
  status?: string | null;
  challan_type?: string | null;
  destination_type?: string | null;
  period?: string | null;
  pending_returnable?: boolean | null;
  scope?: "mine" | "all" | null;
  offset?: number | null;
}

/** The filter part of the query string (the list, the summary and the CSV send the same filters). */
export function challanFilterQuery(params: ChallanListParams): Record<string, string | boolean | undefined> {
  return {
    q: params.q?.trim() || undefined,
    status: params.status || undefined,
    challan_type: params.challan_type || undefined,
    destination_type: params.destination_type || undefined,
    period: params.period || undefined,
    pending_returnable: params.pending_returnable ? true : undefined,
    scope: params.scope === "mine" ? "mine" : undefined,
  };
}

export function challanListQuery(params: ChallanListParams): Record<string, string | number | boolean | undefined> {
  return { ...challanFilterQuery(params), offset: params.offset ?? 0, limit: CHALLANS_PAGE_SIZE };
}

function toSearch(query: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) if (value !== undefined) search.set(key, String(value));
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function challanListUrl(params: ChallanListParams): `/api/v1/${string}` {
  return `${CHALLANS_PATH}${toSearch(challanListQuery(params))}`;
}

export function challanSummaryUrl(params: ChallanListParams): `/api/v1/${string}` {
  return `${CHALLANS_PATH}/summary${toSearch(challanFilterQuery(params))}`;
}

/** The CSV of the filtered set: a plain link (attachment), so the browser downloads it with the session cookie. */
export function challanCsvHref(params: ChallanListParams): string {
  return `${CHALLANS_PATH}/export.csv${toSearch(challanFilterQuery(params))}`;
}

export function challanPdfHref(challanId: string): string {
  return `${challanPath(challanId)}/document.pdf`;
}

export async function fetchChallans(params: ChallanListParams, signal?: AbortSignal, client: ApiClient = api): Promise<Page<ChallanSummaryRow>> {
  return parseChallanPage(await requestUntyped<unknown>(client, "get", CHALLANS_PATH, { params: { query: challanListQuery(params) }, signal }));
}

export async function fetchChallanSummary(params: ChallanListParams, signal?: AbortSignal, client: ApiClient = api): Promise<ChallanSummary> {
  return parseChallanSummary(await requestUntyped<unknown>(client, "get", `${CHALLANS_PATH}/summary`, { params: { query: challanFilterQuery(params) }, signal }));
}

export async function fetchChallan(challanId: string, signal?: AbortSignal, client: ApiClient = api): Promise<ChallanDetail> {
  return parseChallanDetail(await requestUntyped<unknown>(client, "get", challanPath(challanId), { signal }));
}

export async function fetchChallanPrint(challanId: string, signal?: AbortSignal, client: ApiClient = api): Promise<ChallanPrint> {
  return parseChallanPrint(await requestUntyped<unknown>(client, "get", `${challanPath(challanId)}/print`, { signal }));
}

export async function createChallan(body: ChallanCreateRequest, idempotencyKey: string, client: ApiClient = api): Promise<ChallanDetail> {
  return parseChallanDetail(await requestUntyped<unknown>(client, "post", CHALLANS_PATH, { body, headers: idempotencyHeaders(idempotencyKey) }));
}

export async function updateChallanHeader(challan: Versioned, changes: Partial<ChallanHeaderFields>, idempotencyKey: string, client: ApiClient = api): Promise<ChallanDetail | null> {
  const raw = await requestUntyped<unknown>(client, "patch", challanPath(challan.id), {
    body: { expected_version: challan.version, ...changes },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return challanOrNull(raw);
}

export async function addChallanLine(challan: Versioned, line: LineCreateRequest, idempotencyKey: string, client: ApiClient = api): Promise<ChallanDetail | null> {
  const raw = await requestUntyped<unknown>(client, "post", `${challanPath(challan.id)}/lines`, {
    body: { expected_version: challan.version, ...line },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return challanOrNull(raw);
}

export async function updateChallanLine(
  challan: Versioned,
  lineId: string,
  changes: LineUpdateRequest,
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<ChallanDetail | null> {
  const raw = await requestUntyped<unknown>(client, "patch", linePath(challan.id, lineId), {
    body: { expected_version: challan.version, ...changes },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return challanOrNull(raw);
}

export async function removeChallanLine(challan: Versioned, lineId: string, idempotencyKey: string, client: ApiClient = api): Promise<ChallanDetail | null> {
  const raw = await requestUntyped<unknown>(client, "delete", linePath(challan.id, lineId), {
    params: { query: { expected_version: challan.version } },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return challanOrNull(raw);
}

export async function transitionChallan(
  challan: Versioned,
  body: { action: string; reason?: string | null; reason_code?: string | null },
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<ChallanDetail | null> {
  const raw = await requestUntyped<unknown>(client, "post", `${challanPath(challan.id)}/transitions`, {
    body: { expected_version: challan.version, ...body },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return challanOrNull(raw);
}

export async function duplicateChallan(challanId: string, idempotencyKey: string, client: ApiClient = api): Promise<ChallanDetail> {
  return parseChallanDetail(await requestUntyped<unknown>(client, "post", `${challanPath(challanId)}/duplicate`, { body: {}, headers: idempotencyHeaders(idempotencyKey) }));
}

export async function deleteChallan(challan: Versioned, idempotencyKey: string, client: ApiClient = api): Promise<ChallanDetail | null> {
  const raw = await requestUntyped<unknown>(client, "delete", challanPath(challan.id), {
    params: { query: { expected_version: challan.version } },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return challanOrNull(raw);
}

export async function fetchChallanNote(challanId: string, signal?: AbortSignal, client: ApiClient = api): Promise<InternalNote> {
  return parseNote(await requestUntyped<unknown>(client, "get", NOTES_PATH, { params: { query: { resource_type: CHALLAN_RESOURCE, resource_id: challanId } }, signal }));
}

export async function saveChallanNote(challanId: string, body: string, expectedVersion: number, client: ApiClient = api): Promise<InternalNote> {
  return parseNote(
    await requestUntyped<unknown>(client, "put", NOTES_PATH, {
      params: { query: { resource_type: CHALLAN_RESOURCE, resource_id: challanId } },
      body: { body, expected_version: expectedVersion },
    }),
  );
}
