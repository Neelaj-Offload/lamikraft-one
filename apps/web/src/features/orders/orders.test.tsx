import { describe, expect, it, vi } from "vitest";
import { queryKeys } from "@/lib/api/query-keys";
import { controlsWithoutVisibleFocus, renderWithQueries, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { StockScreen, stockHref, stockStateFrom } from "@/features/inventory/stock-screens";
import { DocumentScreen, PickListScreen } from "@/features/inventory/document-screens";
import type { DocumentRead, PickListRead, StockPage } from "@/features/inventory/api";
import type { OrderDetail, OrderPage } from "./api";
import { OrderList, orderListHref, orderListStateFrom } from "./order-list";
import { OrderWorkspace } from "./order-workspace";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/sales/orders",
  useSearchParams: () => new URLSearchParams(),
}));

const ID = "0192a000-0000-7000-8000-0000000000a1";
const LINE = "0192a000-0000-7000-8000-0000000000a2";
const WH = { id: "0192a000-0000-7000-8000-0000000000b1", code: "WH-MAIN", name: "Main Warehouse" };
const eur = (amount: string) => ({ amount, currency: "EUR" as const });

function order(overrides: Partial<OrderDetail> = {}): OrderDetail {
  return {
    id: ID,
    order_number: "SO-2026-0001",
    order_date: "2026-10-12",
    party: { id: "p1", party_number: "P-00001", display_name: "Nordhaus Interiors GmbH" },
    quote: { id: "q1", quote_number: "LK-QT-2026-0009", revision_no: 1 },
    status: "confirmed",
    fulfilment_state: "partial",
    total: eur("5760.0000"),
    line_count: 1,
    requested_delivery_date: null,
    promised_date: null,
    owner: { id: "u1", display_name: "Meera Iyer" },
    branch_id: null,
    created_at: "2026-10-12T03:30:00Z",
    updated_at: "2026-10-12T03:30:00Z",
    version: 3,
    path: `/sales/orders/${ID}`,
    currency: "EUR",
    subtotal: eur("5760.0000"),
    surcharge: eur("0.0000"),
    terms: {},
    snapshot_hash: "abc",
    default_warehouse: WH,
    ship_to: null,
    customer_reference: null,
    confirmed_at: "2026-10-12T03:31:00Z",
    hold_reason_code: null,
    hold_reason: null,
    cancelled_at: null,
    cancel_reason_code: null,
    cancel_reason: null,
    completed_at: null,
    lines: [
      {
        id: LINE,
        line_no: 1,
        line_kind: "catalog",
        fulfilment_mode: "stock",
        product_id: "pr1",
        product_key: "LK-OT-0450",
        description: "Oak serving tray 450",
        unit: "pcs",
        unit_price: eur("24.0000"),
        line_total: eur("5760.0000"),
        qty_ordered: "240",
        qty_reserved: "140",
        qty_delivered: "100",
        qty_returned: "10",
        qty_cancelled: "0",
        qty_remaining: "140",
        qty_unreserved: "0",
        cancel_reason_code: null,
        version: 4,
      },
    ],
    reservations: [{ id: "r1", line_id: LINE, warehouse: WH, quantity: "240", remaining: "140", unit: "pcs", status: "active", created_at: "2026-10-12T03:32:00Z" }],
    documents: [{ kind: "challan", id: "c1", number: "DC-2026-0004", status: "issued", path: "/operations/challans/c1" }],
    history: [{ action: "create", from_status: "new", to_status: "draft", line_id: null, actor: null, reason_code: null, reason: null, reference: "LK-QT-2026-0009", occurred_at: "2026-10-12T03:30:00Z" }],
    capabilities: {
      update: { allowed: true, reason_code: null },
      transition: { allowed: true, reason_code: null },
      reserve: { allowed: true, reason_code: null },
      release_reservations: { allowed: true, reason_code: null },
      create_challan: { allowed: true, reason_code: null },
      create_pick_list: { allowed: false, reason_code: "permission_denied" },
      cancel_line: { allowed: true, reason_code: null },
    },
    allowed_transitions: [{ action: "hold", to_status: "on_hold", requires_reason: true }],
    ...overrides,
  };
}

const meera = () => testBootstrap({ permissions: [{ key: "orders.sales_order.read", scope: "own" }, { key: "inventory.stock.read", scope: "company" }] });

describe("sales orders", () => {
  it("round-trips the list state and drops unknown statuses", () => {
    const state = orderListStateFrom({ q: " nord ", status: "on_hold", offset: "25" });
    expect(state).toEqual({ q: " nord ", status: "on_hold", offset: 25 });
    expect(orderListHref(state)).toBe("/sales/orders?q=nord&status=on_hold&offset=25");
    expect(orderListStateFrom({ status: "shipped", offset: "-1" })).toEqual({ q: "", status: null, offset: 0 });
  });

  it("lists orders with their status, delivery state and total", () => {
    const page: OrderPage = { items: [order()], total: 1, limit: 25, offset: 0 };
    const state = orderListStateFrom({});
    const html = renderWithQueries(<OrderList state={state} />, (c) => c.setQueryData(queryKeys.orders.list({ q: "", status: null, offset: 0 }), page), meera());
    const text = textOf(html);
    expect(text).toContain("SO-2026-0001");
    expect(text).toContain("Partly delivered");
    expect(text).toContain("LK-QT-2026-0009");
    expect(html).toContain(`href="/sales/orders/${ID}"`);
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("shows ordered, reserved, delivered, returned and remaining quantities and only the allowed actions", () => {
    const html = renderWithQueries(<OrderWorkspace orderId={ID} />, (c) => c.setQueryData(queryKeys.orders.order(ID), order()), meera());
    const text = textOf(html);
    expect(html).toMatch(/<h1[^>]*>Nordhaus Interiors GmbH<\/h1>/);
    for (const label of ["Reserve stock", "Create delivery challan", "Release reservations", "Put on hold", "Cancel remaining"]) expect(text).toContain(label);
    expect(text).not.toContain("Create pick list"); // capability denied: no dead control
    expect(text).not.toContain("Confirm order");
    expect(text).toContain("From LK-QT-2026-0009 (revision 1)");
    expect(text).toContain("DC-2026-0004");
    expect(text).toContain("never change on the order");
  });

  it("a cancelled order offers no commands", () => {
    const closed = order({
      status: "cancelled",
      allowed_transitions: [],
      capabilities: Object.fromEntries(Object.keys(order().capabilities).map((k) => [k, { allowed: false, reason_code: "order_closed" }])),
    });
    const text = textOf(renderWithQueries(<OrderWorkspace orderId={ID} />, (c) => c.setQueryData(queryKeys.orders.order(ID), closed), meera()));
    for (const label of ["Reserve stock", "Create delivery challan", "Put on hold", "Cancel order", "Cancel remaining"]) expect(text).not.toContain(label);
  });
});

describe("inventory screens", () => {
  it("round-trips the stock filters", () => {
    const state = stockStateFrom({ q: "oak", warehouse: WH.id, short: "1", offset: "50" });
    expect(stockHref(state)).toBe(`/operations/inventory?q=oak&warehouse=${WH.id}&short=1&offset=50`);
  });

  it("shows stock from the projections with the shortage marker", () => {
    const page: StockPage = {
      items: [
        {
          product: { id: "pr1", product_key: "LK-MT-0300", name: "Maple trivet 300", stock_unit: "pcs", track_lots: false },
          warehouse: { id: WH.id, code: WH.code, name: WH.name },
          on_hand: "300",
          reserved: "300",
          available: "0",
          qc_hold: "0",
          rejected: "0",
          unit: "pcs",
          shortage: "300",
          reorder_min: null,
          below_reorder: false,
          version: 4,
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
      totals: { products: 1, short_products: 1, below_reorder: 0 },
    };
    const state = stockStateFrom({});
    const html = renderWithQueries(
      <StockScreen state={state} />,
      (c) => {
        c.setQueryData(queryKeys.inventory.stock({ q: "", warehouse: null, short: false, offset: 0 }), page);
        c.setQueryData(queryKeys.inventory.warehouses(), []);
      },
      meera(),
    );
    const text = textOf(html);
    expect(text).toContain("LK-MT-0300");
    expect(text).toContain("Short");
    expect(text).toContain("Available is on hand");
  });

  it("a pick list explains that picking moves nothing and shows only allowed actions", () => {
    const pl: PickListRead = {
      id: "pl1",
      number: "PL-2026-0001",
      status: "released",
      warehouse: { id: WH.id, code: WH.code, name: WH.name },
      order_id: ID,
      order_number: "SO-2026-0001",
      assignee: { id: "k", display_name: "Kabir Shah" },
      released_at: "2026-10-12T04:00:00Z",
      picked_at: null,
      challan_id: null,
      challan_number: null,
      lines: [],
      created_at: "2026-10-12T04:00:00Z",
      version: 2,
      capabilities: {
        release: { allowed: false, reason_code: "invalid_status" },
        pick: { allowed: true, reason_code: null },
        cancel: { allowed: true, reason_code: null },
        create_challan: { allowed: false, reason_code: "invalid_status" },
      },
    };
    const text = textOf(renderWithQueries(<PickListScreen pickListId="pl1" />, (c) => c.setQueryData(queryKeys.inventory.pickList("pl1"), pl), meera()));
    expect(text).toContain("Confirm picked quantities");
    expect(text).not.toContain("Release for picking");
    expect(text).toContain("Picking moves nothing");
  });

  it("an adjustment created by the viewer explains the second-person rule instead of offering approval", () => {
    const doc: DocumentRead = {
      id: "a1",
      kind: "adjustment",
      number: "ADJ-2026-0001",
      status: "submitted",
      warehouse: { id: WH.id, code: WH.code, name: WH.name },
      to_warehouse: null,
      reason_code: "damage",
      reason: "Water damage",
      notes: null,
      created_by: { id: "u2", display_name: "Ravi Kumar" },
      created_at: "2026-10-12T04:00:00Z",
      decided_by: null,
      decided_at: null,
      decision_note: null,
      posting_id: null,
      second_posting_id: null,
      lines: [],
      version: 2,
      capabilities: {
        submit: { allowed: false, reason_code: "invalid_status" },
        approve: { allowed: false, reason_code: "approver_is_creator" },
        reject: { allowed: false, reason_code: "approver_is_creator" },
      },
    };
    const text = textOf(renderWithQueries(<DocumentScreen kind="adjustment" id="a1" />, (c) => c.setQueryData(queryKeys.inventory.document("adjustment", "a1"), doc), meera()));
    expect(text).toContain("ADJ-2026-0001");
    expect(text).toContain("A different person approves");
    expect(text).not.toContain("Approve and post");
  });
});
