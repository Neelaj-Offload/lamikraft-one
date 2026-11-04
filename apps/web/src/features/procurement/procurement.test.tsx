import { describe, expect, it, vi } from "vitest";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { controlsWithoutVisibleFocus, renderWithQueries, seedQueryError, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import type { PackingListDetail, ShipmentDetail } from "@/features/logistics/api";
import { packingListHref, packingStateFrom, shipmentListHref, shipmentStateFrom } from "@/features/logistics/list-state";
import { PackingListScreen } from "@/features/logistics/packing-screens";
import { ShipmentScreen } from "@/features/logistics/shipment-screens";
import { addsUpTo, type InspectionDetail } from "@/features/quality/api";
import { InspectionScreen } from "@/features/quality/inspection-screens";
import { inspectionListHref, inspectionStateFrom } from "@/features/quality/list-state";
import type { PoDetail, PoLine } from "./api";
import { poListHref, poStateFrom, receiptListHref, receiptStateFrom } from "./list-state";
import { PurchaseOrderScreen } from "./po-screens";
import { positive } from "./shared";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/operations/purchasing/orders",
  useSearchParams: () => new URLSearchParams(),
}));

const ID = "0192b000-0000-7000-8000-0000000000a1";
const WH = { id: "0192b000-0000-7000-8000-0000000000b1", code: "WH-MAIN", name: "Main Warehouse" };
const VENDOR = { id: "0192b000-0000-7000-8000-0000000000c1", party_number: "P-00031", display_name: "Shree Timber Traders" };
const PRODUCT = { id: "0192b000-0000-7000-8000-0000000000d1", product_key: "LK-RM-OAK18", name: "Oak board 18 mm", stock_unit: "sqm", qc_required: true, track_lots: false };
const allow = { allowed: true, reason_code: null };
const deny = (reason_code: string) => ({ allowed: false, reason_code });

const buyer = () =>
  testBootstrap({
    permissions: [
      { key: "procurement.purchase_order.read", scope: "company" },
      { key: "quality.inspection.read", scope: "company" },
      { key: "logistics.shipment.read", scope: "company" },
      { key: "logistics.packing_list.read", scope: "company" },
    ],
  });

function poLine(overrides: Partial<PoLine> = {}): PoLine {
  return {
    id: "0192b000-0000-7000-8000-0000000000e1",
    line_no: 1,
    product: PRODUCT,
    quantity: "100",
    unit: "sqm",
    unit_price: "850.0000",
    price_override_reason: null,
    line_amount: "85000.0000",
    lead_time_days_assumed: 10,
    expected_date: "2026-10-20",
    is_overdue: true,
    over_receipt_tolerance_pct: "0",
    qty_received: "40",
    qty_accepted: "30",
    qty_rejected: "0",
    qty_pending_qc: "10",
    qty_cancelled: "0",
    qty_billed: "0",
    qty_billable: "30",
    qty_outstanding: "60",
    qty_receivable: "60",
    requisition_line_id: null,
    version: 2,
    ...overrides,
  };
}

function po(overrides: Partial<PoDetail> = {}): PoDetail {
  return {
    id: ID,
    po_number: "PO-2026-0007",
    status: "partially_received",
    vendor: VENDOR,
    warehouse: WH,
    owner: { id: "u1", display_name: "Arjun Rao" },
    currency: "INR",
    total_amount: "85000.0000",
    order_date: "2026-10-08",
    next_expected_date: "2026-10-20",
    is_overdue: true,
    path: `/operations/purchasing/orders/${ID}`,
    version: 5,
    vendor_reference: null,
    notes: null,
    requisition: { id: "r1", number: "PR-2026-0003", status: "closed", path: "/operations/purchasing/requisitions/r1" },
    submitted_by: null,
    submitted_at: null,
    approved_by: { id: "u2", display_name: "Sahil Mehta" },
    approved_at: null,
    issued_at: null,
    closed_at: null,
    cancelled_at: null,
    status_reason_code: null,
    status_reason: null,
    lines: [poLine()],
    receipts: [{ id: "g1", number: "GRN-2026-0004", status: "posted", path: "/operations/purchasing/receipts/g1" }],
    bills: [],
    allowed_transitions: ["close"],
    capabilities: {
      submit: deny("invalid_status"),
      approve: deny("invalid_status"),
      reject: deny("invalid_status"),
      issue: deny("invalid_status"),
      close: allow,
      cancel: deny("invalid_status"),
      update: deny("invalid_status"),
      change_expected_date: allow,
      receive: allow,
      bill: deny("permission_denied"),
    },
    ...overrides,
  };
}

describe("purchasing", () => {
  it("round-trips the list states and ignores junk offsets", () => {
    const state = poStateFrom({ q: " shree ", status: "issued", overdue: "1", offset: "25" });
    expect(poListHref(state)).toBe("/operations/purchasing/orders?q=shree&status=issued&overdue=1&offset=25");
    expect(poStateFrom({ offset: "-3" }).offset).toBe(0);
    expect(receiptListHref(receiptStateFrom({ awaiting_qc: "1" }))).toBe("/operations/purchasing/receipts?awaiting_qc=1");
    expect(shipmentListHref(shipmentStateFrom({ q: "SH-2026", status: "planned" }))).toBe("/operations/dispatch?q=SH-2026&status=planned");
    expect(packingListHref(packingStateFrom({}))).toBe("/operations/dispatch/packing-lists");
  });

  it("defaults the quality list to what is still waiting", () => {
    expect(inspectionStateFrom({}).status).toBe("pending");
    expect(inspectionStateFrom({ status: "all" }).status).toBeNull();
    expect(inspectionListHref({ status: null, offset: 0 })).toBe("/operations/quality?status=all");
  });

  it("compares quantities as decimal strings, never floats", () => {
    expect(positive("0.001")).toBe(true);
    expect(positive("0")).toBe(false);
    expect(positive(null)).toBe(false);
    expect(addsUpTo("7.5", "2.50", "10")).toBe(true);
    expect(addsUpTo("0.1", "0.2", "0.3")).toBe(true);
    expect(addsUpTo("7", "2", "10")).toBe(false);
    expect(addsUpTo("-1", "11", "10")).toBe(false);
  });

  it("a purchase order shows received, QC and outstanding quantities and only the allowed commands", () => {
    const html = renderWithQueries(<PurchaseOrderScreen poId={ID} />, (c) => c.setQueryData(queryKeys.procurement.order(ID), po()), buyer());
    const text = textOf(html);
    expect(html).toMatch(/<h1[^>]*>Shree Timber Traders<\/h1>/);
    expect(text).toContain("PO-2026-0007");
    expect(text).toContain("Overdue");
    expect(text).toContain("Receive goods");
    expect(text).toContain("Close");
    expect(text).toContain("Move date");
    expect(text).toContain("GRN-2026-0004");
    expect(html).not.toMatch(/>Approve</);
    for (const absent of ["Submit for approval", "Mark sent to vendor", "Record vendor bill"]) expect(text).not.toContain(absent);
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("explains separation of duties when the submitter may not approve", () => {
    const pending = po({ status: "pending_approval", capabilities: { ...po().capabilities, approve: deny("approver_is_submitter"), close: deny("invalid_status"), receive: deny("invalid_status") } });
    const html = renderWithQueries(<PurchaseOrderScreen poId={ID} />, (c) => c.setQueryData(queryKeys.procurement.order(ID), pending), buyer());
    const text = textOf(html);
    expect(text).toContain("never approves it");
    expect(html).not.toMatch(/>Approve</);
    expect(text).not.toContain("Receive goods");
  });

  it("an out-of-scope purchase order is the same as a missing one", () => {
    const html = renderWithQueries(
      <PurchaseOrderScreen poId={ID} />,
      (c) => seedQueryError(c, queryKeys.procurement.order(ID), new ProblemError({ title: "Not found", status: 404, code: "not_found" })),
      buyer(),
    );
    expect(textOf(html)).not.toContain("PO-2026-0007");
    expect(html).toContain("<h1");
  });
});

function inspection(overrides: Partial<InspectionDetail> = {}): InspectionDetail {
  return {
    id: ID,
    inspection_number: "QC-2026-0002",
    status: "pending",
    subject_type: "procurement.goods_receipt_line",
    subject_id: "g1",
    subject_label: "GRN-2026-0004 line 1",
    source_path: "/operations/purchasing/receipts/g1",
    product: { id: PRODUCT.id, product_key: PRODUCT.product_key, name: PRODUCT.name },
    warehouse: WH,
    lot_code: null,
    quantity: "10",
    unit: "sqm",
    qty_accepted: "0",
    qty_rejected: "0",
    requested_at: "2026-10-12T05:00:00Z",
    decided_at: null,
    path: `/operations/quality/${ID}`,
    version: 1,
    checklist: [],
    findings: null,
    reject_reason_code: null,
    decided_by_name: null,
    posting_id: null,
    work_order_id: null,
    suggested_checklist: [{ code: "surface", label: "Surface free of damage", result: "pass", note: null }],
    capabilities: { decide: allow },
    ...overrides,
  };
}

describe("quality", () => {
  it("offers the decision form with the suggested checklist while waiting", () => {
    const html = renderWithQueries(<InspectionScreen inspectionId={ID} />, (c) => c.setQueryData(queryKeys.quality.inspection(ID), inspection()), buyer());
    const text = textOf(html);
    expect(text).toContain("QC-2026-0002");
    expect(text).toContain("Record the result");
    expect(text).toContain("Surface free of damage");
    expect(html).toContain('href="/operations/purchasing/receipts/g1"');
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("shows the result and no form once decided, and says who may decide when this person may not", () => {
    const decided = inspection({ status: "failed", qty_accepted: "8", qty_rejected: "2", reject_reason_code: "surface_damage", decided_by_name: "Kabir Shah", capabilities: { decide: deny("invalid_status") } });
    const text = textOf(renderWithQueries(<InspectionScreen inspectionId={ID} />, (c) => c.setQueryData(queryKeys.quality.inspection(ID), decided), buyer()));
    expect(text).toContain("Surface damage");
    expect(text).toContain("Kabir Shah");
    expect(text).not.toContain("Record result");
    const waiting = inspection({ capabilities: { decide: deny("permission_denied") } });
    const other = textOf(renderWithQueries(<InspectionScreen inspectionId={ID} />, (c) => c.setQueryData(queryKeys.quality.inspection(ID), waiting), buyer()));
    expect(other).toContain("waiting for someone with QC rights");
    expect(other).not.toContain("Record result");
  });
});

const ORDER = { id: "o1", number: "SO-2026-0001", status: "confirmed", path: "/sales/orders/o1" };

function packingList(overrides: Partial<PackingListDetail> = {}): PackingListDetail {
  return {
    id: ID,
    packing_list_number: "PK-2026-0001",
    status: "draft",
    order: ORDER,
    party_name: "Nordhaus Interiors GmbH",
    total_cartons: 20,
    total_cbm: "0.864",
    total_net_kg: "120.000",
    total_gross_kg: "131.000",
    totals_partial: true,
    has_estimates: false,
    is_stale: true,
    created_at: "2026-10-12T06:00:00Z",
    path: `/operations/dispatch/packing-lists/${ID}`,
    version: 2,
    challan: null,
    stale_since: "2026-10-12T07:00:00Z",
    stale_reason: "packaging_changed",
    finalised_at: null,
    notes: null,
    lines: [
      {
        id: "l1",
        line_no: 1,
        product_id: "p1",
        product_key: "LK-OT-0450",
        description: "Oak serving tray 450",
        quantity: "240",
        unit: "pcs",
        carton_qty: 12,
        inner_qty: null,
        carton_dimensions_cm: "60×40×30",
        stated_carton_cbm: "0.0720",
        unit_weight_kg: "0.500",
        carton_net_kg: "6.000",
        carton_gross_kg: "6.550",
        packing_type: "carton",
        is_fragile: false,
        full_cartons: 20,
        loose_qty: "0",
        cartons: 20,
        inner_packs: null,
        is_part_carton: false,
        carton_cbm: "0.0432",
        cbm: "0.864",
        net_kg: "120.000",
        gross_kg: "131.000",
        is_estimate: false,
        incomplete_reasons: ["cbm_conflict"],
        override_reason: null,
      },
    ],
    capabilities: { refresh: allow, override: allow, finalise: deny("packing_list_stale"), cancel: allow },
    ...overrides,
  };
}

function shipment(overrides: Partial<ShipmentDetail> = {}): ShipmentDetail {
  return {
    id: ID,
    shipment_number: "SH-2026-0001",
    status: "planned",
    mode: "road",
    party_name: "Nordhaus Interiors GmbH",
    order: ORDER,
    challan: null,
    transporter_name: "VRL Logistics",
    planned_dispatch_date: null,
    cutoff_at: "2026-10-14T12:00:00Z",
    cutoff_local: "14 Oct 2026, 17:30",
    is_past_cutoff: true,
    path: `/operations/dispatch/shipments/${ID}`,
    version: 1,
    packing_list: null,
    dispatched_at: null,
    dispatch_posting_id: null,
    delivered_at: null,
    evidence_kind: null,
    evidence_file_id: null,
    evidence_note: null,
    exception_code: null,
    exception_note: null,
    exception_at: null,
    notes: null,
    tracking_refs: [],
    allowed_actions: ["book", "dispatch", "cancel"],
    capabilities: {
      book: allow,
      dispatch: deny("challan_required"),
      in_transit: deny("invalid_status"),
      deliver: deny("invalid_status"),
      record_exception: deny("invalid_status"),
      resolve_exception: deny("invalid_status"),
      cancel: allow,
      update: deny("permission_denied"),
      add_tracking_ref: deny("permission_denied"),
    },
    ...overrides,
  };
}

describe("dispatch", () => {
  it("a stale, partial packing list says why it cannot be finalised and flags the conflicting line", () => {
    const html = renderWithQueries(<PackingListScreen packingListId={ID} />, (c) => c.setQueryData(queryKeys.logistics.packingList(ID), packingList()), buyer());
    const text = textOf(html);
    expect(text).toContain("PK-2026-0001");
    expect(text).toContain("Refresh packaging");
    expect(text).not.toContain("Finalise");
    expect(text).toContain("Refresh the packaging before finalising.");
    expect(text).toContain("Stated CBM and carton size disagree");
    expect(text).toContain("Enter values");
    expect(text).toContain("0.864");
  });

  it("a shipment without a challan cannot be dispatched and says so; only allowed actions show", () => {
    const html = renderWithQueries(<ShipmentScreen shipmentId={ID} />, (c) => c.setQueryData(queryKeys.logistics.shipment(ID), shipment()), buyer());
    const text = textOf(html);
    expect(text).toContain("SH-2026-0001");
    expect(text).toContain("Mark booked");
    expect(text).toContain("Cancel shipment");
    expect(html).not.toMatch(/<button[^>]*>(?:<[^>]*>)*Dispatch</);
    expect(text).toContain("Link the delivery challan before dispatch.");
    expect(text).toContain("The cutoff has passed.");
    expect(text).not.toContain("Save links");
    expect(text).not.toContain("Record delivery");
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });
});
