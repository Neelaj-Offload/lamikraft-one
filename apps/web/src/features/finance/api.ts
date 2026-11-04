/**
 * Finance API (backend/app/modules/finance/router.py), typed from the generated schema. Reads are scoped by the
 * server; commands carry an Idempotency-Key. A refused issue is not an error: the answer says `issued: false` and
 * lists the blockers. PDFs, CSVs and journals are real links (authenticated by the session cookie, no token in URLs).
 */

import { api, idempotencyHeaders, unwrap, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { DocKind, DocListState, ReceiptListState } from "./list-state";

type Schemas = components["schemas"];
export type FinanceSummary = Schemas["FinanceSummary"];
export type InvoiceSummary = Schemas["InvoiceSummary"];
export type InvoiceDetail = Schemas["InvoiceDetail"];
export type InvoiceLine = Schemas["InvoiceLineRead"];
export type InvoicePage = Schemas["Page_InvoiceSummary_"];
export type TransitionResult = Schemas["InvoiceTransitionResult"];
export type GateBlocker = Schemas["GateBlocker"];
export type ReceiptSummary = Schemas["ReceiptSummary"];
export type ReceiptDetail = Schemas["ReceiptDetail"];
export type ReceiptPage = Schemas["Page_ReceiptSummary_"];
export type AllocationRead = Schemas["AllocationRead"];
export type AgeingReport = Schemas["AgeingReport"];
export type ExceptionsRead = Schemas["ExceptionsRead"];
export type Suggestion = Schemas["SuggestionRead"];
export type TaxProfile = Schemas["TaxProfileRead"];
export type AccountingStatus = Schemas["AccountingStatus"];
export type ExportRead = Schemas["ExportRead"];
export type ExportPage = Schemas["Page_ExportRead_"];
export type InvoiceAction = "submit" | "approve" | "reject" | "issue" | "cancel";

export const FINANCE = "/api/v1/finance";
export const PAGE_SIZE = 50;

export function fetchSummary(signal?: AbortSignal, client: ApiClient = api): Promise<FinanceSummary> {
  return unwrap(client.GET("/api/v1/finance/summary", { signal }));
}

function docQuery(s: DocListState) {
  const status = (["draft", "pending_approval", "approved", "issued", "cancelled"] as const).filter((x) => x === s.status);
  return {
    q: s.q.trim() || undefined,
    status: status.length ? status : undefined,
    open_only: s.open || undefined,
    overdue_only: s.overdue || undefined,
    limit: PAGE_SIZE,
    offset: s.offset,
  };
}

export function fetchDocuments(kind: DocKind, s: DocListState, signal?: AbortSignal, client: ApiClient = api): Promise<InvoicePage> {
  const query = docQuery(s);
  return kind === "credit_note"
    ? unwrap(client.GET("/api/v1/finance/credit-notes", { params: { query }, signal }))
    : unwrap(client.GET("/api/v1/finance/invoices", { params: { query }, signal }));
}

export function documentsCsvHref(kind: DocKind, s: DocListState): string {
  const search = new URLSearchParams();
  const q = docQuery(s);
  if (q.q) search.set("q", q.q);
  if (q.status) q.status.forEach((x) => search.append("status", x));
  if (q.open_only) search.set("open_only", "true");
  if (q.overdue_only) search.set("overdue_only", "true");
  const base = `${FINANCE}/${kind === "credit_note" ? "credit-notes" : "invoices"}/export.csv`;
  return search.toString() ? `${base}?${search}` : base;
}

export function fetchDocument(kind: DocKind, id: string, signal?: AbortSignal, client: ApiClient = api): Promise<InvoiceDetail> {
  return kind === "credit_note"
    ? unwrap(client.GET("/api/v1/finance/credit-notes/{credit_note_id}", { params: { path: { credit_note_id: id } }, signal }))
    : unwrap(client.GET("/api/v1/finance/invoices/{invoice_id}", { params: { path: { invoice_id: id } }, signal }));
}

export function pdfHref(d: Pick<InvoiceDetail, "id" | "doc_type">): string {
  return `${FINANCE}/${d.doc_type === "credit_note" ? "credit-notes" : "invoices"}/${d.id}/document.pdf`;
}

export function transitionDocument(
  d: Pick<InvoiceDetail, "id" | "doc_type" | "version">,
  action: InvoiceAction,
  key: string,
  reason: { code?: string | null; note?: string } = {},
  client: ApiClient = api,
): Promise<TransitionResult> {
  const body = { action, expected_version: d.version, reason_code: reason.code || undefined, reason: reason.note?.trim() || undefined };
  const headers = idempotencyHeaders(key);
  return d.doc_type === "credit_note"
    ? unwrap(client.POST("/api/v1/finance/credit-notes/{credit_note_id}/transitions", { params: { path: { credit_note_id: d.id } }, body, headers }))
    : unwrap(client.POST("/api/v1/finance/invoices/{invoice_id}/transitions", { params: { path: { invoice_id: d.id } }, body, headers }));
}

export function updateTaxProfile(d: Pick<InvoiceDetail, "id" | "doc_type" | "version">, profileId: string | null, key: string, client: ApiClient = api): Promise<InvoiceDetail> {
  const body = { expected_version: d.version, tax_profile_id: profileId ?? undefined, clear_tax_profile: profileId === null };
  const headers = idempotencyHeaders(key);
  return d.doc_type === "credit_note"
    ? unwrap(client.PATCH("/api/v1/finance/credit-notes/{credit_note_id}", { params: { path: { credit_note_id: d.id } }, body, headers }))
    : unwrap(client.PATCH("/api/v1/finance/invoices/{invoice_id}", { params: { path: { invoice_id: d.id } }, body, headers }));
}

export function createCreditNote(invoiceId: string, lines: { invoice_line_id: string; quantity: string }[], reasonCode: string, key: string, client: ApiClient = api): Promise<InvoiceDetail> {
  return unwrap(
    client.POST("/api/v1/finance/credit-notes", {
      body: { original_invoice_id: invoiceId, reason_code: reasonCode, lines },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function draftFromSuggestion(suggestionId: string, key: string, client: ApiClient = api): Promise<InvoiceDetail> {
  return unwrap(client.POST("/api/v1/finance/invoices", { body: { suggestion_id: suggestionId }, headers: idempotencyHeaders(key) }));
}

export function fetchSuggestions(signal?: AbortSignal, client: ApiClient = api): Promise<Suggestion[]> {
  return unwrap(client.GET("/api/v1/finance/invoice-suggestions", { signal }));
}

export function dismissSuggestion(s: Suggestion, reasonCode: string, key: string, client: ApiClient = api): Promise<Suggestion> {
  return unwrap(
    client.POST("/api/v1/finance/invoice-suggestions/{suggestion_id}/dismiss", {
      params: { path: { suggestion_id: s.id } },
      body: { expected_version: s.version, reason_code: reasonCode },
      headers: idempotencyHeaders(key),
    }),
  );
}

// ---- receipts -----------------------------------------------------------------------------------------------
export function fetchReceipts(s: ReceiptListState, signal?: AbortSignal, client: ApiClient = api): Promise<ReceiptPage> {
  return unwrap(
    client.GET("/api/v1/finance/receipts", {
      params: { query: { q: s.q.trim() || undefined, unallocated_only: s.unallocated || undefined, limit: PAGE_SIZE, offset: s.offset } },
      signal,
    }),
  );
}

export function fetchReceipt(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<ReceiptDetail> {
  return unwrap(client.GET("/api/v1/finance/receipts/{receipt_id}", { params: { path: { receipt_id: id } }, signal }));
}

export interface ReceiptInput {
  party_id: string;
  amount: string;
  currency: "INR" | "EUR" | "USD" | "GBP";
  received_on: string;
  method: "bank_transfer" | "cheque" | "cash" | "card" | "other";
  reference?: string;
  bank_account_label?: string;
}

export function recordReceipt(input: ReceiptInput, key: string, client: ApiClient = api): Promise<ReceiptDetail> {
  return unwrap(
    client.POST("/api/v1/finance/receipts", {
      body: { ...input, reference: input.reference?.trim() || undefined, bank_account_label: input.bank_account_label?.trim() || undefined },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function allocateReceipt(receiptId: string, invoiceId: string, amount: string, key: string, client: ApiClient = api): Promise<ReceiptDetail> {
  return unwrap(
    client.POST("/api/v1/finance/receipts/{receipt_id}/allocations", {
      params: { path: { receipt_id: receiptId } },
      body: { invoice_id: invoiceId, amount },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function reverseAllocation(allocationId: string, reasonCode: string, key: string, client: ApiClient = api): Promise<AllocationRead> {
  return unwrap(
    client.POST("/api/v1/finance/allocations/{allocation_id}/reverse", {
      params: { path: { allocation_id: allocationId } },
      body: { reason_code: reasonCode },
      headers: idempotencyHeaders(key),
    }),
  );
}

export function reverseReceipt(r: Pick<ReceiptDetail, "id" | "version">, reasonCode: string, note: string, key: string, client: ApiClient = api): Promise<ReceiptDetail> {
  return unwrap(
    client.POST("/api/v1/finance/receipts/{receipt_id}/reverse", {
      params: { path: { receipt_id: r.id } },
      body: { expected_version: r.version, reason_code: reasonCode, reason: note.trim() || undefined },
      headers: idempotencyHeaders(key),
    }),
  );
}

// ---- reports ------------------------------------------------------------------------------------------------
export function fetchAgeing(asOf: string | null, signal?: AbortSignal, client: ApiClient = api): Promise<AgeingReport> {
  return unwrap(client.GET("/api/v1/finance/ageing", { params: { query: { as_of: asOf || undefined } }, signal }));
}

export function fetchExceptions(signal?: AbortSignal, client: ApiClient = api): Promise<ExceptionsRead> {
  return unwrap(client.GET("/api/v1/finance/exceptions", { signal }));
}

// ---- accounting and configuration ---------------------------------------------------------------------------
export function fetchAccountingStatus(signal?: AbortSignal, client: ApiClient = api): Promise<AccountingStatus> {
  return unwrap(client.GET("/api/v1/finance/accounting/status", { signal }));
}

export function fetchExports(signal?: AbortSignal, client: ApiClient = api): Promise<ExportPage> {
  return unwrap(client.GET("/api/v1/finance/accounting/exports", { params: { query: { limit: 20 } }, signal }));
}

export function runExport(adapter: "csv" | "demo", key: string, client: ApiClient = api): Promise<ExportRead> {
  return unwrap(client.POST("/api/v1/finance/accounting/exports", { body: { adapter }, headers: idempotencyHeaders(key) }));
}

export function reconcileExport(exportId: string, key: string, client: ApiClient = api): Promise<ExportRead> {
  return unwrap(
    client.POST("/api/v1/finance/accounting/exports/{export_id}/reconcile", {
      params: { path: { export_id: exportId } },
      body: {},
      headers: idempotencyHeaders(key),
    }),
  );
}

export function journalHref(exportId: string): string {
  return `${FINANCE}/accounting/exports/${exportId}/journal.csv`;
}

export function fetchTaxProfiles(signal?: AbortSignal, client: ApiClient = api): Promise<TaxProfile[]> {
  return unwrap(client.GET("/api/v1/finance/tax-profiles", { signal }));
}

export function verifyTaxProfile(p: TaxProfile, key: string, client: ApiClient = api): Promise<TaxProfile> {
  return unwrap(
    client.POST("/api/v1/finance/tax-profiles/{profile_id}/verify", {
      params: { path: { profile_id: p.id } },
      body: { expected_version: p.version },
      headers: idempotencyHeaders(key),
    }),
  );
}
