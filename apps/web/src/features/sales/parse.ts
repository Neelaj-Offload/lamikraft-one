/**
 * Runtime readers for the sales API (see types.ts). Required fields are checked; links must
 * stay inside the app; DecimalStr values are validated, never converted.
 */

import { isDecimalStr } from "@/lib/format/decimal";
import { safeAppPath } from "@/lib/safe-path";
import {
  MANUAL_PRESETS,
  PRICE_TYPES,
  QUOTE_STATUSES,
  type Capability,
  type CustomerMessage,
  type Enquiry,
  type Money,
  type Page,
  type PartyRef,
  type QuoteDetail,
  type QuoteHistoryEntry,
  type QuoteLine,
  type QuotePreview,
  type QuoteRevision,
  type QuoteSummary,
  type QuoteTotals,
  type TransitionOption,
  type UserRef,
} from "./types";

export class SalesShapeError extends Error {
  override readonly name = "SalesShapeError";
}

type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => value !== null && typeof value === "object" && !Array.isArray(value);
const str = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);
const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const int = (value: unknown): number | null => (typeof value === "number" && Number.isInteger(value) ? value : null);
const dec = (value: unknown): string | null => (isDecimalStr(value) ? value : null);

function need<T>(value: T | null, what: string): T {
  if (value === null) throw new SalesShapeError(`The sales response could not be read (${what}).`);
  return value;
}

export function money(value: unknown): Money | null {
  return isObject(value) && isDecimalStr(value.amount) && str(value.currency) ? { amount: value.amount, currency: str(value.currency)! } : null;
}

function user(value: unknown): UserRef {
  return isObject(value) && str(value.id) ? { id: str(value.id)!, display_name: str(value.display_name) } : { id: "", display_name: null };
}

function party(value: unknown): PartyRef {
  if (!isObject(value) || !str(value.id)) throw new SalesShapeError("The sales response could not be read (party).");
  return {
    id: str(value.id)!,
    party_number: str(value.party_number) ?? "",
    display_name: str(value.display_name) ?? str(value.party_number) ?? "",
    country_code: str(value.country_code) ?? "",
  };
}

export function capabilities(value: unknown): Record<string, Capability> {
  if (!isObject(value)) return {};
  const out: Record<string, Capability> = {};
  for (const [key, cap] of Object.entries(value)) {
    if (isObject(cap) && typeof cap.allowed === "boolean") out[key] = { allowed: cap.allowed, reason_code: str(cap.reason_code) };
  }
  return out;
}

export function transitions(value: unknown): TransitionOption[] {
  return arr(value).flatMap((entry) =>
    isObject(entry) && str(entry.action)
      ? [{ action: str(entry.action)!, to_status: str(entry.to_status) ?? "", requires_reason: entry.requires_reason === true }]
      : [],
  );
}

export function pageOf<T>(raw: unknown, item: (value: unknown) => T | null): Page<T> {
  if (!isObject(raw) || !Array.isArray(raw.items)) throw new SalesShapeError("The list could not be read (items).");
  const items = raw.items.map(item).filter((entry): entry is T => entry !== null);
  return { items, total: int(raw.total) ?? items.length, limit: int(raw.limit) ?? items.length, offset: int(raw.offset) ?? 0 };
}

export function parseQuoteSummary(raw: unknown): QuoteSummary | null {
  if (!isObject(raw) || !str(raw.id) || !str(raw.quote_number) || int(raw.version) === null) return null;
  const id = str(raw.id)!;
  return {
    id,
    quote_number: str(raw.quote_number)!,
    revision_no: int(raw.revision_no) ?? 0,
    status: QUOTE_STATUSES.find((status) => status === raw.status) ?? "draft",
    party: party(raw.party),
    customer_reference: str(raw.customer_reference),
    currency: str(raw.currency) ?? "",
    line_count: int(raw.line_count) ?? 0,
    grand_total: money(raw.grand_total),
    owner: user(raw.owner),
    origin: str(raw.origin) ?? "user",
    valid_until: str(raw.valid_until),
    issued_at: str(raw.issued_at),
    sent_at: str(raw.sent_at),
    created_at: str(raw.created_at) ?? "",
    updated_at: str(raw.updated_at) ?? "",
    version: int(raw.version)!,
    path: safeAppPath(raw.path) ?? `/sales/quotes/${encodeURIComponent(id)}`,
  };
}

function totals(raw: unknown, currency: string): QuoteTotals {
  const t = isObject(raw) ? raw : {};
  const zero = { amount: "0", currency };
  const minimum = isObject(t.minimum) ? t.minimum : {};
  return {
    currency: str(t.currency) ?? currency,
    gross_subtotal: money(t.gross_subtotal) ?? zero,
    discount_total: money(t.discount_total) ?? zero,
    net_subtotal: money(t.net_subtotal) ?? zero,
    applicable_subtotal: money(t.applicable_subtotal) ?? zero,
    surcharge: money(t.surcharge) ?? zero,
    surcharge_applied: t.surcharge_applied === true,
    surcharge_label: str(t.surcharge_label) ?? "",
    grand_total: money(t.grand_total),
    totals_complete: t.totals_complete !== false,
    line_count: int(t.line_count) ?? 0,
    minimum: {
      status: str(minimum.status) ?? "NOT_EVALUATED",
      minimum_order_value: dec(minimum.minimum_order_value),
      shortfall: dec(minimum.shortfall),
      reason_code: str(minimum.reason_code),
    },
    tax_label: str(t.tax_label) ?? "",
    threshold_note: str(t.threshold_note),
  };
}

function line(raw: unknown): QuoteLine | null {
  if (!isObject(raw) || !str(raw.id) || !isDecimalStr(raw.quantity)) return null;
  const product = isObject(raw.product_snapshot) ? raw.product_snapshot : null;
  const rec = isObject(raw.recommendation) ? raw.recommendation : null;
  return {
    id: str(raw.id)!,
    line_no: int(raw.line_no) ?? 0,
    line_key: str(raw.line_key) ?? str(raw.id)!,
    line_type: raw.line_type === "manual" ? "manual" : raw.line_type === "custom" ? "custom" : "catalog",
    product_id: str(raw.product_id),
    product_key: product ? str(product.product_key) : null,
    description: str(raw.description) ?? (product ? (str(product.product_name) ?? "") : ""),
    manual_preset: MANUAL_PRESETS.find((preset) => preset === raw.manual_preset) ?? null,
    quantity: raw.quantity,
    unit_code: str(raw.unit_code) ?? "",
    default_unit_price: dec(raw.default_unit_price),
    unit_price: dec(raw.unit_price),
    currency: str(raw.currency) ?? "",
    is_overridden: raw.is_overridden === true,
    override_reason: str(raw.override_reason),
    discount_pct: dec(raw.discount_pct),
    line_total: dec(raw.line_total),
    remarks: str(raw.remarks),
    recommendation:
      rec && str(rec.label)
        ? {
            status: str(rec.status) ?? "",
            quantity: int(rec.quantity),
            carton_qty: int(rec.carton_qty),
            explanation: str(rec.explanation) ?? "",
            label: str(rec.label)!,
          }
        : null,
    advisories: arr(raw.advisories).filter((code): code is string => typeof code === "string"),
    current_unit_price: dec(raw.current_unit_price),
  };
}

export function parseQuoteDetail(raw: unknown): QuoteDetail {
  const summary = need(parseQuoteSummary(raw), "quote");
  const body = raw as Json;
  const snapshot = isObject(body.party_snapshot) ? body.party_snapshot : null;
  const review = isObject(body.review) ? body.review : {};
  return {
    ...summary,
    party_snapshot: snapshot
      ? {
          display_name: str(snapshot.display_name) ?? summary.party.display_name,
          legal_name: str(snapshot.legal_name) ?? "",
          country_code: str(snapshot.country_code) ?? "",
          default_currency: str(snapshot.default_currency) ?? "",
          contact_name: str(snapshot.contact_name),
          contact_email: str(snapshot.contact_email),
        }
      : null,
    enquiry_id: str(body.enquiry_id),
    origin_message_id: str(body.origin_message_id),
    brand: str(body.brand) ?? "",
    price_type: PRICE_TYPES.find((type) => type === body.price_type) ?? "export",
    incoterm: str(body.incoterm),
    incoterm_place: str(body.incoterm_place),
    payment_terms: str(body.payment_terms),
    validity_days: int(body.validity_days) ?? 30,
    remarks: str(body.remarks),
    apply_minimum_surcharge: body.apply_minimum_surcharge === true,
    lost_reason_code: str(body.lost_reason_code),
    cancelled_reason_code: str(body.cancelled_reason_code),
    lines: arr(body.lines)
      .map(line)
      .filter((entry): entry is QuoteLine => entry !== null)
      .sort((a, b) => a.line_no - b.line_no),
    totals: totals(body.totals, summary.currency),
    content_hash: str(body.content_hash) ?? "",
    review: {
      requires_approval: review.requires_approval === true,
      reasons: arr(review.reasons).filter((reason): reason is string => typeof reason === "string"),
      review_proposal_id: str(review.review_proposal_id),
      approved_proposal_id: str(review.approved_proposal_id),
      approval_current: review.approval_current === true,
    },
    capabilities: capabilities(body.capabilities),
    allowed_transitions: transitions(body.allowed_transitions),
  };
}

export function parseHistory(raw: unknown): QuoteHistoryEntry[] {
  const list = isObject(raw) && Array.isArray(raw.items) ? raw.items : arr(raw);
  return list.flatMap((entry) => {
    if (!isObject(entry) || !str(entry.id) || !str(entry.occurred_at)) return [];
    return [
      {
        id: str(entry.id)!,
        action: str(entry.action) ?? "",
        from_status: str(entry.from_status) ?? "",
        to_status: str(entry.to_status) ?? "",
        actor: isObject(entry.actor) ? user(entry.actor) : null,
        reason_code: str(entry.reason_code),
        reason: str(entry.reason),
        occurred_at: str(entry.occurred_at)!,
        quote_version: int(entry.quote_version) ?? 0,
      },
    ];
  });
}

/** PDF links must be same-origin API paths (they are streamed by the backend, not a page). */
export function documentPath(raw: unknown, quoteId: string, revisionNo: number): string {
  const path = safeAppPath(raw);
  return path && path.startsWith("/api/v1/sales/quotes/")
    ? path
    : `/api/v1/sales/quotes/${encodeURIComponent(quoteId)}/revisions/${revisionNo}/document.pdf`;
}

export function parseRevisions(raw: unknown, quoteId: string): QuoteRevision[] {
  const list = isObject(raw) && Array.isArray(raw.items) ? raw.items : arr(raw);
  return list.flatMap((entry) => {
    if (!isObject(entry) || int(entry.revision_no) === null || !str(entry.issued_at)) return [];
    const revisionNo = int(entry.revision_no)!;
    return [
      {
        id: str(entry.id) ?? String(revisionNo),
        revision_no: revisionNo,
        issued_at: str(entry.issued_at)!,
        issued_by: isObject(entry.issued_by) ? user(entry.issued_by) : null,
        valid_until: str(entry.valid_until) ?? "",
        document_sha256: str(entry.document_sha256) ?? "",
        document_path: documentPath(entry.document_path, quoteId, revisionNo),
      },
    ];
  });
}

export function parseEnquiry(raw: unknown): Enquiry | null {
  if (!isObject(raw) || !str(raw.id) || !str(raw.enquiry_number) || int(raw.version) === null) return null;
  const id = str(raw.id)!;
  const status = raw.status === "assigned" || raw.status === "quoted" || raw.status === "closed" ? raw.status : "received";
  return {
    id,
    enquiry_number: str(raw.enquiry_number)!,
    party: party(raw.party),
    channel: str(raw.channel) ?? "other",
    received_at: str(raw.received_at) ?? "",
    owner: user(raw.owner),
    subject: str(raw.subject),
    body: str(raw.body),
    status,
    outcome_code: str(raw.outcome_code),
    quote_id: str(raw.quote_id),
    quote_number: str(raw.quote_number),
    closed_at: str(raw.closed_at),
    version: int(raw.version)!,
    path: safeAppPath(raw.path) ?? `/sales/enquiries/${encodeURIComponent(id)}`,
    capabilities: capabilities(raw.capabilities),
  };
}

export function parseCustomerMessage(raw: unknown): CustomerMessage | null {
  if (!isObject(raw) || !str(raw.id) || typeof raw.body !== "string" || int(raw.version) === null) return null;
  return {
    id: str(raw.id)!,
    party: party(raw.party),
    contact_name: str(raw.contact_name),
    channel: str(raw.channel) ?? "other",
    received_at: str(raw.received_at) ?? "",
    assignee: user(raw.assignee),
    enquiry_id: str(raw.enquiry_id),
    quote_id: str(raw.quote_id),
    quote_number: str(raw.quote_number),
    subject: str(raw.subject),
    body: raw.body,
    status: raw.status === "replied" ? "replied" : "received",
    replied_at: str(raw.replied_at),
    version: int(raw.version)!,
    path: safeAppPath(raw.path) ?? "/sales/customer-messages",
    capabilities: capabilities(raw.capabilities),
    allowed_transitions: transitions(raw.allowed_transitions),
  };
}

/** `QuotePreviewOut{calculation, lines, warnings}` reduced to the live totals. */
export function parsePreview(raw: unknown): QuotePreview {
  if (!isObject(raw) || !isObject(raw.calculation)) throw new SalesShapeError("The totals preview could not be read.");
  const c = raw.calculation;
  const surcharge = isObject(c.surcharge) ? c.surcharge : {};
  const minimum = isObject(c.minimum) ? c.minimum : {};
  const lineTotals: Record<string, string | null> = {};
  for (const entry of arr(c.lines)) if (isObject(entry) && str(entry.line_key)) lineTotals[str(entry.line_key)!] = dec(entry.net);
  const recommended = arr(c.lines)
    .map((entry) => (isObject(entry) && isObject(entry.recommendation) ? str(entry.recommendation.label) : null))
    .find((label) => label && label.trim() !== "");
  return {
    currency: str(c.currency) ?? "",
    applicable_subtotal: dec(c.applicable_subtotal) ?? "0",
    discount_total: dec(c.discount_total) ?? "0",
    surcharge_applied: surcharge.applied === true,
    surcharge_amount: dec(surcharge.amount) ?? "0",
    surcharge_label: str(surcharge.label) ?? "",
    grand_total: dec(c.grand_total),
    totals_complete: c.totals_complete !== false,
    minimum_status: str(minimum.status) ?? "NOT_EVALUATED",
    recommendation: recommended ?? null,
    line_totals: lineTotals,
    warnings: arr(raw.warnings).filter((warning): warning is string => typeof warning === "string"),
  };
}
