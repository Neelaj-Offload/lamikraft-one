import { describe, expect, it, vi } from "vitest";
import { queryKeys } from "@/lib/api/query-keys";
import { renderWithQueries, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { financeMessages as m } from "@/messages/finance";
import type { FinanceSummary, InvoiceDetail } from "./api";
import { documentsCsvHref } from "./api";
import { DocWorkspace } from "./doc-workspace";
import { FinanceHub } from "./finance-screens";
import { ageingDateFrom, docHref, docStateFrom, receiptHref, receiptStateFrom } from "./list-state";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/finance",
  useSearchParams: () => new URLSearchParams(),
}));

const ID = "0192a000-0000-7000-8000-0000000000f1";
const eur = (amount: string) => ({ amount, currency: "EUR" as const });
const ananya = () => testBootstrap({ permissions: [{ key: "finance.invoice.read", scope: "company" }, { key: "finance.invoice.create", scope: "company" }] });
const allow = { allowed: true, reason_code: null };
const deny = { allowed: false, reason_code: "permission_denied" };

/** The server's issue-gate blocker codes (backend/app/modules/finance/enums.py ``Blocker``, contract-tested there). */
const BLOCKERS = [
  "not_approved", "approval_stale", "company_identity_incomplete", "party_billing_incomplete", "tax_profile_missing",
  "tax_profile_unverified", "e_invoice_provider_not_verified", "totals_changed", "quantity_exceeds_delivered",
  "quantity_exceeds_creditable", "no_lines", "zero_total",
];

function summary(): FinanceSummary {
  return {
    as_of: "2026-10-12",
    drafts: 2,
    pending_approval: 1,
    issue_blocked: 1,
    issued_open: 0,
    overdue: 0,
    open_suggestions: 0,
    unallocated_receipts: 1,
    margin_exceptions: 0,
    sync_attention: 0,
    by_currency: [{ currency: "EUR", receivable: eur("0.0000"), overdue: eur("0.0000"), unallocated: eur("2400.0000") }],
    accounting_mode: "demo",
    accounting_state: "not_connected",
    e_invoice_state: "not_connected",
    tax_profiles_verified: 0,
    capabilities: { create_invoice: allow, record_receipt: allow, run_export: deny },
  };
}

function draft(): InvoiceDetail {
  return {
    id: ID,
    doc_type: "invoice",
    draft_ref: "FD-00001",
    document_number: null,
    status: "approved",
    party: { id: "p1", party_number: "P-00001", display_name: "Nordhaus Interiors GmbH" },
    currency: "EUR",
    document_date: null,
    due_date: null,
    total: eur("2400.0000"),
    outstanding: null,
    is_overdue: false,
    tax_status: "not_configured",
    label: "Draft — not valid for trade",
    owner: { id: "u1", display_name: "Ananya Rao" },
    sales_order_id: null,
    original_invoice_id: null,
    created_at: "2026-10-12T03:30:00Z",
    billing: { legal_name: "Nordhaus Interiors GmbH", address_lines: ["Lagerweg 4", "20457 Hamburg"] },
    payment_due_days: 30,
    tax_profile: null,
    subtotal: eur("2400.0000"),
    tax: null,
    allocated: eur("0.0000"),
    credited: eur("0.0000"),
    customer_reference: null,
    notes: null,
    reason_code: null,
    lines: [
      {
        id: "l1", line_no: 1, description: "Oak serving tray", item_code: "LK-OT-0450", hsn_sac: null, quantity: "100", uom_code: "pcs",
        unit_price: eur("24.0000"), amount: eur("2400.0000"), tax_rate_percent: null, tax_amount: null, so_line_id: null,
        challan_id: null, challan_line_id: null, credited_line_id: null, product_id: null, creditable_quantity: null,
      },
    ],
    history: [],
    allocations: [],
    related: [{ id: "c1", kind: "challan", number: "DC-2026-0004", path: "/operations/challans/c1" }],
    approved_by: { id: "u2", display_name: "Sahil Mehta" },
    approved_at: "2026-10-12T03:40:00Z",
    approved_version: 3,
    issued_by: null,
    issued_at: null,
    last_blockers: ["company_identity_incomplete", "tax_profile_missing"],
    gate: {
      can_issue: false,
      label: "Draft — not valid for trade",
      blockers: [
        { code: "company_identity_incomplete", fix_path: "/settings/company", detail: {} },
        { code: "tax_profile_missing", fix_path: "/finance/accounting-sync#tax-profiles", detail: {} },
      ],
    },
    version: 4,
    capabilities: { update: deny, approve: deny, issue: allow, submit: deny, reject: allow, cancel: allow, create_credit_note: deny },
    allowed_transitions: [
      { action: "issue", to_status: "issued", requires_reason: false },
      { action: "reject", to_status: "draft", requires_reason: true },
      { action: "cancel", to_status: "cancelled", requires_reason: true },
    ],
  } as InvoiceDetail;
}

describe("finance URL state", () => {
  it("round-trips the list filters and ignores unknown statuses", () => {
    const s = docStateFrom({ q: " FD-1 ", status: "pending_approval", open: "1", offset: "50" });
    expect(docHref("invoice", s)).toBe("/finance/invoices?q=FD-1&status=pending_approval&open=1&offset=50");
    expect(docStateFrom({ status: "paid" }).status).toBeNull();
    expect(docHref("credit_note", docStateFrom({}))).toBe("/finance/credit-notes");
    expect(receiptHref(receiptStateFrom({ unallocated: "1" }))).toBe("/finance/receipts?unallocated=1");
    expect(ageingDateFrom({ as_of: "2026-11-30" })).toBe("2026-11-30");
    expect(ageingDateFrom({ as_of: "tomorrow" })).toBeNull();
    expect(documentsCsvHref("invoice", s)).toBe("/api/v1/finance/invoices/export.csv?q=FD-1&status=pending_approval&open_only=true");
  });

  it("has plain copy for every issue-gate blocker", () => {
    for (const code of BLOCKERS) expect(m.blockers[code], code).toBeTruthy();
  });
});

describe("finance screens", () => {
  it("shows server figures, the gate explained and Demo integrations on the hub", () => {
    const text = textOf(
      renderWithQueries(<FinanceHub />, (c) => {
        c.setQueryData(queryKeys.finance.summary(), summary());
        c.setQueryData(queryKeys.finance.suggestions(), []);
      }, ananya()),
    );
    expect(text).toContain(m.hub.gateTitle);
    expect(text).toContain("Draft — not valid for trade");
    expect(text).toContain(m.hub.notConnected);
    expect(text).toContain(m.hub.suggestionsEmpty);
    expect(text).toContain("2,400.00");
  });

  it("lists every blocker with its fix and offers only the server's transitions", () => {
    const html = renderWithQueries(<DocWorkspace kind="invoice" id={ID} />, (c) => {
      c.setQueryData(queryKeys.finance.document("invoice", ID), draft());
      c.setQueryData(queryKeys.finance.taxProfiles(), []);
    }, ananya());
    const text = textOf(html);
    expect(text).toContain(m.blockers.company_identity_incomplete);
    expect(text).toContain(m.blockers.tax_profile_missing);
    expect(html).toContain('href="/settings/company"');
    expect(text).toContain(m.doc.issue);
    expect(html).not.toMatch(new RegExp(`>${m.doc.approve}<`));
    expect(text).not.toContain(m.doc.createCreditNote);
    expect(html).toContain(`href="/api/v1/finance/invoices/${ID}/document.pdf"`);
  });
});
