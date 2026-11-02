/**
 * Sales (quotes, enquiries, customer messages) as the web uses them.
 *
 * The shapes mirror the sales lane's Pydantic models (backend/app/modules/sales/schemas.py:
 * `QuoteSummary`, `QuoteDetail`, `QuoteLineRead`, `QuoteTotals`, `QuoteHistoryRead`,
 * `QuoteRevisionSummary`, `EnquiryRead`, `CustomerMessageRead`, `QuoteCreate`, `QuoteUpdate`,
 * `QuoteLineCreate`, `QuoteLineUpdate`, `QuoteTransition`, `QuotePreviewIn/Out`). The router is
 * is committed in that lane (D:\lk-wt\sales, router.py) and these types were checked against it.
 * INTERIM(api-generate): replace with `components["schemas"][...]`; `api.ts` and `parse.ts`
 * are the only places that touch the wire.
 *
 * Money and quantities are DecimalStr strings throughout; the web never does arithmetic on them.
 */

export interface Money {
  amount: string;
  currency: string;
}

export interface Capability {
  allowed: boolean;
  reason_code: string | null;
}

export interface TransitionOption {
  action: string;
  to_status: string;
  requires_reason: boolean;
}

export interface UserRef {
  id: string;
  display_name: string | null;
}

export interface PartyRef {
  id: string;
  party_number: string;
  display_name: string;
  country_code: string;
}

export const QUOTE_STATUSES = ["draft", "internal_review", "sent", "revised", "won", "lost", "cancelled", "archived"] as const;
export type QuoteStatus = (typeof QUOTE_STATUSES)[number];

export const PRICE_TYPES = ["export", "domestic", "sample", "distributor"] as const;
export type PriceType = (typeof PRICE_TYPES)[number];

export const INCOTERMS = ["FOB", "CIF", "CFR", "EXW", "DDP", "DAP", "FCA"] as const;

export const MANUAL_PRESETS = ["development", "tooling", "special_packaging", "freight", "sample", "miscellaneous"] as const;
export type ManualPreset = (typeof MANUAL_PRESETS)[number];

export const UOM_CODES = ["pcs", "nos", "sheets", "kg", "g", "m", "mm", "cm", "sqm", "sqft", "box", "set", "roll", "bundle", "carton"] as const;

export interface QuoteSummary {
  id: string;
  quote_number: string;
  revision_no: number;
  status: QuoteStatus;
  party: PartyRef;
  customer_reference: string | null;
  currency: string;
  line_count: number;
  grand_total: Money | null;
  owner: UserRef;
  origin: string;
  valid_until: string | null;
  issued_at: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
  version: number;
  path: string;
}

export interface MinimumRead {
  status: string;
  minimum_order_value: string | null;
  shortfall: string | null;
  reason_code: string | null;
}

export interface QuoteTotals {
  currency: string;
  gross_subtotal: Money;
  discount_total: Money;
  net_subtotal: Money;
  applicable_subtotal: Money;
  surcharge: Money;
  surcharge_applied: boolean;
  surcharge_label: string;
  grand_total: Money | null;
  totals_complete: boolean;
  line_count: number;
  minimum: MinimumRead;
  tax_label: string;
  threshold_note: string | null;
}

export interface RecommendationRead {
  status: string;
  quantity: number | null;
  carton_qty: number | null;
  explanation: string;
  label: string;
}

export interface QuoteLine {
  id: string;
  line_no: number;
  line_key: string;
  line_type: "catalog" | "manual" | "custom";
  product_id: string | null;
  product_key: string | null;
  description: string;
  manual_preset: ManualPreset | null;
  quantity: string;
  unit_code: string;
  default_unit_price: string | null;
  unit_price: string | null;
  currency: string;
  is_overridden: boolean;
  override_reason: string | null;
  discount_pct: string | null;
  line_total: string | null;
  remarks: string | null;
  recommendation: RecommendationRead | null;
  advisories: string[];
  current_unit_price: string | null;
}

export interface ReviewRead {
  requires_approval: boolean;
  reasons: string[];
  review_proposal_id: string | null;
  approved_proposal_id: string | null;
  approval_current: boolean;
}

export interface PartySnapshot {
  display_name: string;
  legal_name: string;
  country_code: string;
  default_currency: string;
  contact_name: string | null;
  contact_email: string | null;
}

export interface QuoteDetail extends QuoteSummary {
  party_snapshot: PartySnapshot | null;
  enquiry_id: string | null;
  origin_message_id: string | null;
  brand: string;
  price_type: PriceType;
  incoterm: string | null;
  incoterm_place: string | null;
  payment_terms: string | null;
  validity_days: number;
  remarks: string | null;
  apply_minimum_surcharge: boolean;
  lost_reason_code: string | null;
  cancelled_reason_code: string | null;
  lines: QuoteLine[];
  totals: QuoteTotals;
  content_hash: string;
  review: ReviewRead;
  capabilities: Readonly<Record<string, Capability>>;
  allowed_transitions: TransitionOption[];
}

export interface QuoteHistoryEntry {
  id: string;
  action: string;
  from_status: string;
  to_status: string;
  actor: UserRef | null;
  reason_code: string | null;
  reason: string | null;
  occurred_at: string;
  quote_version: number;
}

export interface QuoteRevision {
  id: string;
  revision_no: number;
  issued_at: string;
  issued_by: UserRef | null;
  valid_until: string;
  document_sha256: string;
  /** Same-origin API path of the PDF; rendered as a plain <a href>. */
  document_path: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Enquiry {
  id: string;
  enquiry_number: string;
  party: PartyRef;
  channel: string;
  received_at: string;
  owner: UserRef;
  subject: string | null;
  body: string | null;
  status: "received" | "assigned" | "quoted" | "closed";
  outcome_code: string | null;
  quote_id: string | null;
  quote_number: string | null;
  closed_at: string | null;
  version: number;
  path: string;
  capabilities: Readonly<Record<string, Capability>>;
  allowed_transitions: TransitionOption[];
}

export interface CustomerMessage {
  id: string;
  party: PartyRef;
  contact_name: string | null;
  channel: string;
  received_at: string;
  assignee: UserRef;
  enquiry_id: string | null;
  quote_id: string | null;
  quote_number: string | null;
  subject: string | null;
  body: string;
  status: "received" | "replied";
  replied_at: string | null;
  version: number;
  path: string;
  capabilities: Readonly<Record<string, Capability>>;
  allowed_transitions: TransitionOption[];
}

// ---------------------------------------------------------------------------------------------
// Requests

export interface QuoteCreateRequest {
  party_id: string;
  brand?: string;
  price_type?: PriceType;
  currency?: string;
  incoterm?: string | null;
  incoterm_place?: string | null;
  validity_days?: number;
  customer_reference?: string | null;
  remarks?: string | null;
  apply_minimum_surcharge?: boolean;
  enquiry_id?: string | null;
  origin_message_id?: string | null;
}

export interface QuoteHeaderFields {
  price_type: PriceType;
  incoterm: string | null;
  incoterm_place: string | null;
  payment_terms: string | null;
  validity_days: number;
  customer_reference: string | null;
  remarks: string | null;
  apply_minimum_surcharge: boolean;
}

export interface CatalogLineRequest {
  line_type: "catalog";
  product_id: string;
  quantity: string;
  unit_code?: string;
  unit_price?: string;
  override_reason?: string;
}

export interface ManualLineRequest {
  line_type: "manual";
  quantity: string;
  unit_code?: string;
  unit_price: string;
  description?: string;
  manual_preset?: ManualPreset;
}

export type LineCreateRequest = CatalogLineRequest | ManualLineRequest;

export interface LineUpdateRequest {
  quantity?: string;
  unit_price?: string;
  override_reason?: string;
  clear_override?: boolean;
}

export interface QuoteTransitionRequest {
  action: string;
  reason?: string;
  reason_code?: string;
  sent_to?: string;
  note?: string;
}

export interface PreviewLineRequest {
  line_key: string;
  line_type: "catalog" | "manual";
  product_id?: string;
  quantity: string;
  unit_code?: string;
  unit_price?: string;
  discount_pct?: string;
}

/** `QuotePreviewOut.calculation` reduced to what the live totals show. */
export interface QuotePreview {
  currency: string;
  applicable_subtotal: string;
  discount_total: string;
  surcharge_applied: boolean;
  surcharge_amount: string;
  surcharge_label: string;
  grand_total: string | null;
  totals_complete: boolean;
  minimum_status: string;
  recommendation: string | null;
  line_totals: Record<string, string | null>;
  warnings: string[];
}

/** `GET /sales/quotes/status-counts`: a count per status the server reported. */
export type QuoteStatusCounts = Partial<Record<QuoteStatus, number>>;
