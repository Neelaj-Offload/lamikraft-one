/**
 * Test-only sales payloads shaped like sales/schemas.py `QuoteDetail` (the scenario C draft:
 * Nordhaus, 240 oak trays at EUR 24.0000). Never imported by product code.
 */

export interface TestQuoteOptions {
  id?: string;
  version?: number;
  status?: string;
  overridden?: boolean;
  transitions?: { action: string; to_status: string; requires_reason: boolean }[];
  capabilities?: Record<string, { allowed: boolean; reason_code: string | null }>;
  surcharge?: boolean;
}

export function testQuoteWire(options: TestQuoteOptions = {}): Record<string, unknown> {
  const id = options.id ?? "0192a000-0000-7000-8000-000000000009";
  const overridden = options.overridden ?? false;
  const unit = overridden ? "22.0000" : "24.0000";
  const lineTotal = overridden ? "5280.00" : "5760.00";
  const money = (amount: string) => ({ amount, currency: "EUR" });
  return {
    id,
    quote_number: "LK-QT-2026-0009",
    revision_no: 0,
    status: options.status ?? "draft",
    party: { id: "0192a000-0000-7000-8000-0000000000p1", party_number: "P-00001", display_name: "Nordhaus Interiors GmbH", country_code: "DE" },
    customer_reference: null,
    currency: "EUR",
    line_count: 1,
    grand_total: money(lineTotal),
    owner: { id: "0192a000-0000-7000-8000-00000000000a", display_name: "Meera Iyer" },
    created_by: null,
    branch_id: null,
    origin: "agent",
    valid_until: null,
    issued_at: null,
    sent_at: null,
    created_at: "2026-10-12T03:26:00Z",
    updated_at: "2026-10-12T03:26:00Z",
    version: options.version ?? 1,
    path: `/sales/quotes/${id}`,
    party_snapshot: {
      party_id: "0192a000-0000-7000-8000-0000000000p1",
      party_number: "P-00001",
      display_name: "Nordhaus Interiors GmbH",
      legal_name: "Nordhaus Interiors GmbH",
      country_code: "DE",
      default_currency: "EUR",
      customer_type: "standard",
      contact_name: "Lena Brandt",
      contact_email: null,
      addresses: [],
      taken_at: "2026-10-12T03:26:00Z",
    },
    enquiry_id: null,
    origin_message_id: "0192a000-0000-7000-8000-0000000000m1",
    brand: "LK",
    price_type: "export",
    incoterm: "FOB",
    incoterm_place: null,
    payment_terms: null,
    validity_days: 30,
    remarks: null,
    apply_minimum_surcharge: options.surcharge ?? false,
    won_at: null,
    accepted_revision_id: null,
    lost_reason_code: null,
    cancelled_reason_code: null,
    deleted_at: null,
    lines: [
      {
        id: "0192a000-0000-7000-8000-0000000000l1",
        line_no: 1,
        line_key: "0192a000-0000-7000-8000-0000000000k1",
        line_type: "catalog",
        product_id: "0192a000-0000-7000-8000-0000000000x1",
        description: "Oak serving tray 450",
        manual_preset: null,
        quantity: "240",
        unit_code: "pcs",
        default_unit_price: "24.0000",
        unit_price: unit,
        currency: "EUR",
        is_overridden: overridden,
        override_reason: overridden ? "Long-standing customer" : null,
        discount_pct: null,
        gross_amount: lineTotal,
        discount_amount: "0.00",
        line_total: lineTotal,
        remarks: null,
        internal_note: null,
        price_list_item_id: null,
        product_snapshot: { product_key: "LK-OT-0450", product_name: "Oak serving tray 450" },
        packaging_snapshot: null,
        media_snapshot: null,
        commercial_snapshot: null,
        recommendation: { status: "AVAILABLE", quantity: 216, carton_qty: 24, explanation: "216 pcs reach the order minimum.", label: "216 pcs reach EUR 5,000.00" },
        advisories: [],
      },
    ],
    totals: {
      currency: "EUR",
      gross_subtotal: money(lineTotal),
      discount_total: money("0.00"),
      net_subtotal: money(lineTotal),
      applicable_subtotal: money(lineTotal),
      surcharge: money(options.surcharge ? "400.00" : "0.00"),
      surcharge_applied: options.surcharge ?? false,
      surcharge_reason_code: "NOT_APPLICABLE",
      surcharge_label: "Minimum order surcharge",
      grand_total: money(lineTotal),
      totals_complete: true,
      line_count: 1,
      minimum: { status: "MEETS", minimum_order_value: "5000.00", shortfall: null, reason_code: null },
      tax_status: "EXCLUDED",
      tax_label: "Excluding taxes",
      threshold_note: null,
      engine_version: "1",
      rule_set_version: 1,
      input_hash: null,
    },
    calculation: null,
    content_hash: "b".repeat(64),
    review: { requires_approval: overridden, reasons: overridden ? ["price_override"] : [], review_proposal_id: null, approved_proposal_id: null, approval_current: false },
    capabilities: options.capabilities ?? {
      update: { allowed: true, reason_code: null },
      delete: { allowed: true, reason_code: null },
      override_price: { allowed: true, reason_code: null },
    },
    allowed_transitions: options.transitions ?? [
      { action: "submit_review", to_status: "internal_review", requires_reason: false },
      { action: "mark_sent", to_status: "sent", requires_reason: false },
      { action: "cancel", to_status: "cancelled", requires_reason: true },
      { action: "delete", to_status: "deleted", requires_reason: false },
    ],
    redacted_fields: [],
  };
}
