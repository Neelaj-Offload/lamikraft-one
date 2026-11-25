/**
 * Proforma invoices (module 3, backend/app/modules/sales/proforma.py):
 * - GET   /api/v1/sales/proforma-invoices                 list (q, status, party_id, quote_id, limit, offset)
 * - GET   /api/v1/sales/proforma-invoices/{id}            detail with capabilities
 * - GET   /api/v1/sales/proforma-invoices/{id}/document   the PDF (draft carries a watermark)
 * - POST  /api/v1/sales/quotes/{quoteId}/proforma-invoices  create a draft (or, with pi_number + pi_date, a past PI)
 * - PATCH /api/v1/sales/proforma-invoices/{id}            edit a draft's header
 * - POST  /api/v1/sales/proforma-invoices/{id}/issue      number, date and freeze
 * - POST  /api/v1/sales/proforma-invoices/{id}/cancel     with a reason
 */

import { useQuery } from "@tanstack/react-query";
import { api, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type { components } from "@/lib/api/schema";

type S = components["schemas"];
export type ProformaSummary = S["ProformaSummary"];
export type ProformaDetail = S["ProformaDetail"];
export type ProformaStatus = ProformaSummary["status"];
export interface ProformaPage {
  items: ProformaSummary[];
  total: number;
  limit: number;
  offset: number;
}

const BASE = "/api/v1/sales/proforma-invoices";
export const PROFORMA_PAGE_SIZE = 25;
const one = (id: string): `/api/v1/${string}` => `${BASE}/${encodeURIComponent(id)}`;

export const proformaKeys = {
  all: () => ["sales", "proformas"] as const,
  list: (params: Record<string, unknown>) => ["sales", "proformas", "list", params] as const,
  detail: (id: string) => ["sales", "proformas", "detail", { id }] as const,
};

/** A PI command refreshes PI views and the quotation and customer screens that list PIs. */
export const PROFORMA_INVALIDATE = [proformaKeys.all(), queryKeys.sales.all(), ["parties"] as const] as const;

export interface ProformaQuery {
  q?: string;
  status?: ProformaStatus | null;
  party_id?: string | null;
  quote_id?: string | null;
  offset?: number;
  limit?: number;
}

export function proformaQueryParams(q: ProformaQuery): Record<string, string | number | undefined> {
  return {
    q: q.q?.trim() || undefined,
    status: q.status || undefined,
    party_id: q.party_id || undefined,
    quote_id: q.quote_id || undefined,
    offset: q.offset ?? 0,
    limit: q.limit ?? PROFORMA_PAGE_SIZE,
  };
}

export function useProformas(q: ProformaQuery, enabled = true) {
  const params = proformaQueryParams(q);
  return useQuery({
    queryKey: proformaKeys.list(params),
    queryFn: ({ signal }) => requestUntyped<ProformaPage>(api, "get", BASE, { params: { query: params }, signal }),
    enabled,
  });
}

export function useProforma(id: string) {
  return useQuery({ queryKey: proformaKeys.detail(id), queryFn: ({ signal }) => requestUntyped<ProformaDetail>(api, "get", one(id), { signal }) });
}

export function proformaDocumentHref(id: string): string {
  return `${one(id)}/document`;
}

export interface ProformaFieldsInput {
  port_of_loading?: string | null;
  port_of_discharge?: string | null;
  payment_terms?: string | null;
  delivery_terms?: string | null;
  bank_account_label?: string | null;
  declaration?: string | null;
  notes?: string | null;
}

export function createProforma(
  quoteId: string,
  body: ProformaFieldsInput & { pi_number?: string; pi_date?: string },
  key: string,
  client: ApiClient = api,
): Promise<ProformaDetail> {
  return requestUntyped<ProformaDetail>(client, "post", `/api/v1/sales/quotes/${encodeURIComponent(quoteId)}/proforma-invoices`, {
    body,
    headers: idempotencyHeaders(key),
  });
}

export function updateProforma(id: string, body: ProformaFieldsInput & { expected_version: number }, key: string, client: ApiClient = api): Promise<ProformaDetail> {
  return requestUntyped<ProformaDetail>(client, "patch", one(id), { body, headers: idempotencyHeaders(key) });
}

export function issueProforma(id: string, body: { expected_version: number; pi_date?: string | null }, key: string, client: ApiClient = api): Promise<ProformaDetail> {
  return requestUntyped<ProformaDetail>(client, "post", `${one(id)}/issue`, { body, headers: idempotencyHeaders(key) });
}

export function cancelProforma(id: string, body: { expected_version: number; reason: string }, key: string, client: ApiClient = api): Promise<ProformaDetail> {
  return requestUntyped<ProformaDetail>(client, "post", `${one(id)}/cancel`, { body, headers: idempotencyHeaders(key) });
}
