import { describe, expect, it, vi } from "vitest";
import { queryKeys } from "@/lib/api/query-keys";
import { controlsWithoutVisibleFocus, renderWithQueries, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import type { CostRollupRead, FeasibilityRead, WorkOrderPage, WorkOrderRead } from "./api";
import { Outcome } from "./feasibility-panel";
import { capacityStateFrom, workOrderStateFrom, workOrdersHref } from "./list-state";
import { BomScreen } from "./master-screens";
import { WorkOrderScreen, WorkOrdersScreen } from "./work-order-screens";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/operations/production/work-orders",
  useSearchParams: () => new URLSearchParams(),
}));

const ID = "0192a000-0000-7000-8000-0000000000f1";
const MAT = "0192a000-0000-7000-8000-0000000000f2";
const SHORTAGE = "0192a000-0000-7000-8000-0000000000f3";
const WH = { id: "0192a000-0000-7000-8000-0000000000b1", code: "WH-MAIN", name: "Main Warehouse" };
const SET = { id: "p-set", product_key: "LK-WP-0001", name: "Walnut cabinet panel set", stock_uom_code: "set" };
const BOARD = { id: "p-board", product_key: "LK-WB-1800", name: "Walnut veneered board 18 mm", stock_uom_code: "sheets" };
const allowed = { allowed: true, reason_code: null };
const denied = { allowed: false, reason_code: "permission_denied" };
const deepa = () => testBootstrap({ permissions: [{ key: "production.work_order.read", scope: "company" }, { key: "production.work_order.create", scope: "company" }, { key: "production.feasibility.run", scope: "company" }] });
const ravi = () => testBootstrap({ permissions: [{ key: "production.work_order.read", scope: "branch" }, { key: "production.bom.read", scope: "company" }] });

function master(kind: "bom" | "routing") {
  return {
    id: `${kind}-1`,
    product: SET,
    version_no: 1,
    status: "approved" as const,
    author: { id: "u-deepa", display_name: "Deepa Menon" },
    approved_by: { id: "u-sahil", display_name: "Sahil Mehta" },
    approved_at: "2026-10-07T09:30:00Z",
    updated_at: "2026-10-07T09:30:00Z",
    line_count: 1,
  };
}

function workOrder(overrides: Partial<WorkOrderRead> = {}): WorkOrderRead {
  return {
    id: ID,
    wo_number: "WO-2026-0001",
    product: SET,
    qty_planned: "8",
    uom_code: "set",
    qty_good: "0",
    status: "released",
    is_blocked: true,
    warehouse: WH,
    owner: { id: "u-deepa", display_name: "Deepa Menon" },
    planned_start_date: "2026-10-12",
    due_date: "2026-10-17",
    sales_order: null,
    updated_at: "2026-10-12T02:55:00Z",
    bom: master("bom"),
    routing: master("routing"),
    qty_scrap: "0",
    blocked_causes: [{ type: "inventory.shortage", id: SHORTAGE, label: "Short of LK-WB-1800", path: "/operations/reservations" }],
    blocked_since: "2026-10-12T02:55:00Z",
    notes: null,
    materials: [
      {
        id: MAT, line_no: 1, component: BOARD, uom_code: "sheets", qty_required: "48", qty_required_bom: "48", qty_reserved: "40",
        qty_issued: "0", qty_consumed: "0", qty_returned: "0", qty_in_wip: "0", qty_to_issue: "48", qty_free: "0", short: true,
        requirement_source: "bom", is_sheet_material: true, cut_plan_id: null, alternates: [], version: 2,
      },
    ],
    operations: [
      {
        id: "op-10", seq: 10, name: "Cut panels", work_center: { id: "wc-saw", code: "PANEL-SAW", name: "Panel saw" }, setup_minutes: "30",
        run_minutes_per_unit: "18", planned_minutes: "174", planned_date: "2026-10-12", actual_minutes: null, status: "pending",
        is_board_cutting: true, cut_plan: null, predicted_offcuts: [], completed_at: null, completed_by: null, version: 1,
      },
    ],
    transactions: [],
    released_at: "2026-10-12T02:55:00Z",
    completed_at: null,
    closed_at: null,
    cancelled_at: null,
    cancel_reason_code: null,
    cancel_reason: null,
    version: 3,
    capabilities: {
      update: { allowed: false, reason_code: "work_order_released" }, issue: allowed, consume: { allowed: false, reason_code: "nothing_in_wip" },
      return: { allowed: false, reason_code: "nothing_in_wip" }, output: allowed, record_offcut: allowed, complete_operation: allowed,
      schedule_operation: allowed, link_cut_plan: allowed, recheck: allowed, release: { allowed: false, reason_code: "work_order_released" },
      complete: { allowed: false, reason_code: "no_output" }, close: { allowed: false, reason_code: "work_order_released" }, cancel: allowed,
    },
    allowed_transitions: [{ action: "cancel", to_status: "cancelled", requires_reason: true }],
    ...overrides,
  };
}

describe("production list state", () => {
  it("round-trips the work-order filters and ignores unknown statuses", () => {
    const state = workOrderStateFrom({ q: "walnut", status: "released", blocked: "1", offset: "50" });
    expect(workOrdersHref(state)).toBe("/operations/production/work-orders?q=walnut&status=released&blocked=1&offset=50");
    expect(workOrderStateFrom({ status: "bogus" }).status).toBeNull();
    expect(capacityStateFrom({ from: "2026-10-12", to: "not-a-date" })).toEqual({ from: "2026-10-12", to: null });
  });
});

describe("work-order screens", () => {
  it("lists work orders with their blocked state and links", () => {
    const page: WorkOrderPage = { items: [workOrder()], total: 1, limit: 50, offset: 0 };
    const state = workOrderStateFrom({});
    const html = renderWithQueries(<WorkOrdersScreen state={state} />, (c) => c.setQueryData(queryKeys.production.workOrders({ ...state }), page), deepa());
    const text = textOf(html);
    expect(text).toContain("WO-2026-0001");
    expect(text).toContain("Blocked");
    expect(html).toContain(`href="/operations/production/work-orders/${ID}"`);
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("shows a blocked work order's shortage and only the allowed actions", () => {
    const html = renderWithQueries(<WorkOrderScreen workOrderId={ID} />, (c) => c.setQueryData(queryKeys.production.workOrder(ID), workOrder()), deepa());
    const text = textOf(html);
    expect(text).toContain("Blocked by a material shortage");
    expect(text).toContain("Short of LK-WB-1800");
    for (const label of ["Issue", "Post output", "Cancel", "Check materials again", "Link cut plan", "Record offcut"]) expect(text).toContain(label);
    for (const label of ["Release", "Complete", "Consume"]) expect(text).not.toMatch(new RegExp(`>${label}<`));
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("hides commands the capabilities deny", () => {
    const closed = workOrder({
      status: "closed", is_blocked: false, blocked_causes: [], allowed_transitions: [],
      capabilities: Object.fromEntries(Object.keys(workOrder().capabilities).map((k) => [k, denied])),
    });
    const text = textOf(renderWithQueries(<WorkOrderScreen workOrderId={ID} />, (c) => c.setQueryData(queryKeys.production.workOrder(ID), closed), ravi()));
    for (const label of ["Post output", "Check materials again", "Link cut plan", "Record offcut", "Cancel"]) expect(text).not.toContain(label);
  });
});

describe("cost rollup and feasibility", () => {
  it("says a rollup is partial and hides figures without the costing permission", () => {
    const bom = {
      ...master("bom"), notes: null, retired_at: null, version: 2, allowed_transitions: [],
      capabilities: { update: denied, approve: denied, retire: denied, new_version: denied },
      lines: [{ id: "l1", line_no: 1, component: BOARD, qty_per: "6", uom_code: "sheets", scrap_pct: "0", is_sheet_material: true, alternate_for_line_no: null, has_approved_bom: false, notes: null }],
    };
    const rollup: CostRollupRead = {
      id: "r1", product: SET, bom_id: "bom-1", routing_id: "routing-1", as_of: "2026-10-12", currency: "INR", batch_qty: "1",
      input_hash: "abc", status: "incomplete", computed_at: "2026-10-12T03:00:00Z", computed_by: null, reused: false,
      missing_inputs: [{ kind: "work_centre_rate", ref_type: "production.work_center", ref_id: "wc-asm", label: "ASSEMBLY: no hourly rate", reason_code: "rate_missing" }],
      material_total: null, operation_total: null, total: null, lines: null, redacted_fields: ["lines", "material_total", "operation_total", "total"],
    };
    const html = renderWithQueries(<BomScreen bomId="bom-1" />, (c) => {
      c.setQueryData(queryKeys.production.bom("bom-1"), bom);
      c.setQueryData(queryKeys.production.costRollups(SET.id), { items: [rollup], total: 1, limit: 5, offset: 0 });
    }, ravi());
    const text = textOf(html);
    expect(text).toContain("Partial total: some inputs are missing");
    expect(text).toContain("ASSEMBLY: no hourly rate");
    expect(text).toContain("Cost figures need the costing permission.");
    expect(text).not.toContain("Roll up cost"); // operations may not run rollups
    expect(text).not.toMatch(/>Approve</);
  });

  it("renders the feasibility outcome with its evidence and missing inputs", () => {
    const result: FeasibilityRead = {
      outcome: "estimate", product: SET, quantity: "2", uom_code: "set", warehouse: WH, need_by: "2026-10-16", from_stock: "0", to_make: "2",
      earliest_completion: null, missing_inputs: ["lead_time:LK-WB-1800"], computed_at: "2026-10-12T03:00:00Z", read_only: true,
      evidence: [
        { kind: "stock", status: "short", label: "0 set free at WH-MAIN", facts: {} },
        { kind: "components", status: "missing", label: "LK-WB-1800: short 12 sheets; no purchase-order source to tell when more arrives", facts: {} },
      ],
    };
    const text = textOf(renderWithQueries(<Outcome result={result} />, () => undefined, deepa()));
    expect(text).toContain("Estimate only");
    expect(text).toContain("no purchase-order source");
    expect(text).toContain("lead_time:LK-WB-1800");
  });
});
