/**
 * The sales API (INTERIM(api-generate): see types.ts). Paths follow the sales lane brief's
 * operationIds; this file and parse.ts are the adapter to adjust after `npm run api:generate`:
 * - sales_list_quotes            GET    /api/v1/sales/quotes
 * - sales_create_quote           POST   /api/v1/sales/quotes
 * - sales_get_quote              GET    /api/v1/sales/quotes/{quote_id}
 * - sales_update_quote           PATCH  /api/v1/sales/quotes/{quote_id}
 * - sales_create_quote_line      POST   /api/v1/sales/quotes/{quote_id}/lines
 * - sales_update_quote_line      PATCH  /api/v1/sales/quotes/{quote_id}/lines/{line_id}
 * - sales_delete_quote_line      DELETE /api/v1/sales/quotes/{quote_id}/lines/{line_id}?expected_version=
 * - sales_transition_quote       POST   /api/v1/sales/quotes/{quote_id}/transitions
 * - sales_list_quote_history     GET    /api/v1/sales/quotes/{quote_id}/history
 * - sales_list_quote_revisions   GET    /api/v1/sales/quotes/{quote_id}/revisions
 * - sales_download_quote_revision_pdf GET /api/v1/sales/quotes/{quote_id}/revisions/{n}/document.pdf
 * - sales_delete_quote           DELETE /api/v1/sales/quotes/{quote_id}?expected_version= (never-issued drafts)
 * - sales_calculate_quote_preview POST  /api/v1/sales/quotes/calculate
 * - enquiries and customer messages under /api/v1/sales/enquiries and /api/v1/sales/customer-messages
 * Commands that change a quote answer with the quote (`QuoteDetail`); if a response is not one,
 * the caller refetches.
 */

import { api, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import {
  pageOf,
  parseCustomerMessage,
  parseEnquiry,
  parseHistory,
  parsePreview,
  parseQuoteDetail,
  parseQuoteSummary,
  parseRevisions,
  SalesShapeError,
} from "./parse";
import type {
  CustomerMessage,
  Enquiry,
  LineCreateRequest,
  LineUpdateRequest,
  Page,
  PreviewLineRequest,
  QuoteCreateRequest,
  QuoteDetail,
  QuoteHeaderFields,
  QuoteHistoryEntry,
  QuotePreview,
  QuoteRevision,
  QuoteSummary,
  QuoteTransitionRequest,
} from "./types";

export const QUOTES_PATH = "/api/v1/sales/quotes";
export const QUOTES_PAGE_SIZE = 25;

const quotePath = (quoteId: string): `/api/v1/${string}` => `${QUOTES_PATH}/${encodeURIComponent(quoteId)}`;

export interface QuoteListParams {
  q?: string | null;
  status?: string | null;
  scope?: "mine" | "all" | null;
  offset?: number | null;
}

export async function fetchQuotes(params: QuoteListParams, signal?: AbortSignal, client: ApiClient = api): Promise<Page<QuoteSummary>> {
  const raw = await requestUntyped<unknown>(client, "get", QUOTES_PATH, {
    params: {
      query: {
        q: params.q?.trim() || undefined,
        status: params.status || undefined,
        scope: params.scope ?? undefined,
        offset: params.offset ?? 0,
        limit: QUOTES_PAGE_SIZE,
      },
    },
    signal,
  });
  return pageOf(raw, parseQuoteSummary);
}

export async function fetchQuote(quoteId: string, signal?: AbortSignal, client: ApiClient = api): Promise<QuoteDetail> {
  return parseQuoteDetail(await requestUntyped<unknown>(client, "get", quotePath(quoteId), { signal }));
}

/** A command's answer as the quote, or null when it is not one (the caller refetches). */
function quoteOrNull(raw: unknown): QuoteDetail | null {
  try {
    return parseQuoteDetail(raw);
  } catch (error) {
    if (error instanceof SalesShapeError) return null;
    throw error;
  }
}

export async function createQuote(body: QuoteCreateRequest, idempotencyKey: string, client: ApiClient = api): Promise<QuoteDetail> {
  return parseQuoteDetail(await requestUntyped<unknown>(client, "post", QUOTES_PATH, { body, headers: idempotencyHeaders(idempotencyKey) }));
}

export async function updateQuoteHeader(
  quote: Pick<QuoteDetail, "id" | "version">,
  changes: Partial<QuoteHeaderFields>,
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<QuoteDetail | null> {
  const raw = await requestUntyped<unknown>(client, "patch", quotePath(quote.id), {
    body: { expected_version: quote.version, ...changes },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return quoteOrNull(raw);
}

export async function addQuoteLine(
  quote: Pick<QuoteDetail, "id" | "version">,
  line: LineCreateRequest,
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<QuoteDetail | null> {
  const raw = await requestUntyped<unknown>(client, "post", `${quotePath(quote.id)}/lines`, {
    body: { expected_version: quote.version, ...line },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return quoteOrNull(raw);
}

export async function updateQuoteLine(
  quote: Pick<QuoteDetail, "id" | "version">,
  lineId: string,
  changes: LineUpdateRequest,
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<QuoteDetail | null> {
  const raw = await requestUntyped<unknown>(client, "patch", `${quotePath(quote.id)}/lines/${encodeURIComponent(lineId)}`, {
    body: { expected_version: quote.version, ...changes },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return quoteOrNull(raw);
}

export async function removeQuoteLine(
  quote: Pick<QuoteDetail, "id" | "version">,
  lineId: string,
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<QuoteDetail | null> {
  const raw = await requestUntyped<unknown>(client, "delete", `${quotePath(quote.id)}/lines/${encodeURIComponent(lineId)}`, {
    params: { query: { expected_version: quote.version } },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return quoteOrNull(raw);
}

export async function transitionQuote(
  quote: Pick<QuoteDetail, "id" | "version">,
  request: QuoteTransitionRequest,
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<QuoteDetail | null> {
  const body: Record<string, unknown> = { action: request.action, expected_version: quote.version };
  for (const key of ["reason", "reason_code", "sent_to", "note", "valid_until"] as const) {
    const value = request[key]?.trim();
    if (value) body[key] = value;
  }
  const raw = await requestUntyped<unknown>(client, "post", `${quotePath(quote.id)}/transitions`, {
    body,
    headers: idempotencyHeaders(idempotencyKey),
  });
  return quoteOrNull(raw);
}

/** Soft-deletes a never-issued draft (`capabilities.delete`); the number stays reserved. */
export async function deleteQuote(quote: Pick<QuoteDetail, "id" | "version">, idempotencyKey: string, client: ApiClient = api): Promise<void> {
  await requestUntyped<unknown>(client, "delete", quotePath(quote.id), {
    params: { query: { expected_version: quote.version } },
    headers: idempotencyHeaders(idempotencyKey),
  });
}

export async function fetchQuoteHistory(quoteId: string, signal?: AbortSignal, client: ApiClient = api): Promise<QuoteHistoryEntry[]> {
  return parseHistory(await requestUntyped<unknown>(client, "get", `${quotePath(quoteId)}/history`, { signal }));
}

export async function fetchQuoteRevisions(quoteId: string, signal?: AbortSignal, client: ApiClient = api): Promise<QuoteRevision[]> {
  return parseRevisions(await requestUntyped<unknown>(client, "get", `${quotePath(quoteId)}/revisions`, { signal }), quoteId);
}

export async function previewQuote(
  input: { currency: string; party_id: string; price_type: string; surcharge_requested: boolean; lines: PreviewLineRequest[] },
  signal?: AbortSignal,
  client: ApiClient = api,
): Promise<QuotePreview> {
  return parsePreview(await requestUntyped<unknown>(client, "post", `${QUOTES_PATH}/calculate`, { body: input, signal }));
}

// ---- enquiries and customer messages ----------------------------------------------------------

export const ENQUIRIES_PATH = "/api/v1/sales/enquiries";
export const MESSAGES_PATH = "/api/v1/sales/customer-messages";

export async function fetchEnquiries(
  params: { q?: string | null; status?: string | null; offset?: number | null },
  signal?: AbortSignal,
  client: ApiClient = api,
): Promise<Page<Enquiry>> {
  const raw = await requestUntyped<unknown>(client, "get", ENQUIRIES_PATH, {
    params: { query: { q: params.q?.trim() || undefined, status: params.status || undefined, offset: params.offset ?? 0, limit: QUOTES_PAGE_SIZE } },
    signal,
  });
  return pageOf(raw, parseEnquiry);
}

export async function fetchEnquiry(enquiryId: string, signal?: AbortSignal, client: ApiClient = api): Promise<Enquiry> {
  const parsed = parseEnquiry(await requestUntyped<unknown>(client, "get", `${ENQUIRIES_PATH}/${encodeURIComponent(enquiryId)}`, { signal }));
  if (!parsed) throw new SalesShapeError("The enquiry could not be read.");
  return parsed;
}

export async function fetchCustomerMessages(
  params: { status?: string | null; offset?: number | null },
  signal?: AbortSignal,
  client: ApiClient = api,
): Promise<Page<CustomerMessage>> {
  const raw = await requestUntyped<unknown>(client, "get", MESSAGES_PATH, {
    params: { query: { status: params.status || undefined, offset: params.offset ?? 0, limit: QUOTES_PAGE_SIZE } },
    signal,
  });
  return pageOf(raw, parseCustomerMessage);
}

export async function markMessageReplied(
  message: Pick<CustomerMessage, "id" | "version">,
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<CustomerMessage | null> {
  const raw = await requestUntyped<unknown>(client, "post", `${MESSAGES_PATH}/${encodeURIComponent(message.id)}/replied`, {
    body: { expected_version: message.version, reply_ref_type: "manual" },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return parseCustomerMessage(raw);
}

/** Closes an enquiry with an outcome code (`allowed_transitions` offers `close` with a reason). */
export async function closeEnquiry(
  enquiry: Pick<Enquiry, "id" | "version">,
  outcomeCode: string,
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<Enquiry | null> {
  const raw = await requestUntyped<unknown>(client, "patch", `${ENQUIRIES_PATH}/${encodeURIComponent(enquiry.id)}`, {
    body: { expected_version: enquiry.version, status: "closed", outcome_code: outcomeCode },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return parseEnquiry(raw);
}


// ---- Slice 2 (commercial-2 lane): duplicate, currency change, revisions compare/restore, CSV exports ----------

/** The quote list as CSV for the current filters (a real download within the export scope). */
export function quotesExportHref(params: QuoteListParams): string {
  const query = new URLSearchParams();
  if (params.q?.trim()) query.set("q", params.q.trim());
  if (params.status) query.set("status", params.status);
  if (params.scope) query.set("scope", params.scope);
  const search = query.toString();
  return search ? `${QUOTES_PATH}/export.csv?${search}` : `${QUOTES_PATH}/export.csv`;
}

export function quoteLinesCsvHref(quoteId: string): string {
  return `${quotePath(quoteId)}/lines.csv`;
}

export async function duplicateQuote(quoteId: string, body: { price_mode?: "keep" | "refresh"; from_revision_no?: number }, idempotencyKey: string, client: ApiClient = api): Promise<QuoteDetail> {
  return parseQuoteDetail(await requestUntyped<unknown>(client, "post", `${quotePath(quoteId)}/duplicate`, { body, headers: idempotencyHeaders(idempotencyKey) }));
}

export interface CurrencyPreviewLine {
  line_id: string;
  line_no: number;
  description: string;
  from_unit_price: string | null;
  to_unit_price: string | null;
  method: string;
  status: "ok" | "blocked";
  reason_code: string | null;
  explanation: string;
  fx_rate: string | null;
  fx_rate_date: string | null;
}

export interface CurrencyPreview {
  from_currency: string;
  to_currency: string;
  applicable: boolean;
  blocked_count: number;
  lines: CurrencyPreviewLine[];
}

export async function previewCurrencyChange(quoteId: string, currency: string, signal?: AbortSignal, client: ApiClient = api): Promise<CurrencyPreview> {
  return requestUntyped<CurrencyPreview>(client, "get", `${quotePath(quoteId)}/currency-change`, { params: { query: { to_currency: currency } }, signal });
}

export async function changeQuoteCurrency(quote: Pick<QuoteDetail, "id" | "version">, currency: string, idempotencyKey: string, client: ApiClient = api): Promise<QuoteDetail | null> {
  const raw = await requestUntyped<unknown>(client, "post", `${quotePath(quote.id)}/currency-change`, {
    body: { to_currency: currency, expected_version: quote.version },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return quoteOrNull(raw);
}

export interface RevisionCompare {
  currency_before: string;
  currency_after: string;
  from_revision_no: number;
  to_revision_no: number | null;
  header: { field: string; before: unknown; after: unknown }[];
  lines: { line_key: string; change: string; line_no_before: number | null; line_no_after: number | null; description: string; changes: { field: string; before: unknown; after: unknown }[] }[];
  totals: { field: string; before: string | null; after: string | null; delta: string | null }[];
  summary: string;
}

export async function compareRevisions(quoteId: string, from: number, to: number | null, signal?: AbortSignal, client: ApiClient = api): Promise<RevisionCompare> {
  return requestUntyped<RevisionCompare>(client, "get", `${quotePath(quoteId)}/revisions/compare`, {
    params: { query: { from_revision_no: from, to_revision_no: to ?? undefined } },
    signal,
  });
}

export async function restoreRevision(quote: Pick<QuoteDetail, "id" | "version">, revisionNo: number, reason: string | null, idempotencyKey: string, client: ApiClient = api): Promise<QuoteDetail | null> {
  const raw = await requestUntyped<unknown>(client, "post", `${quotePath(quote.id)}/revisions/${revisionNo}/restore`, {
    body: { expected_version: quote.version, ...(reason?.trim() ? { reason: reason.trim() } : {}) },
    headers: idempotencyHeaders(idempotencyKey),
  });
  return quoteOrNull(raw);
}
