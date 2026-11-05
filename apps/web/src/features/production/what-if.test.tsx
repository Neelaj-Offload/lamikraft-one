import { describe, expect, it, vi } from "vitest";
import { queryKeys } from "@/lib/api/query-keys";
import { renderWithQueries, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import type { FeasibilityRead, SimulationRead, SimulationRequest } from "./api";
import { ProductionTabs } from "./common";
import { simulationBody, SimulationResults, WhatIfScreen } from "./what-if";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/operations/production/what-if",
  useSearchParams: () => new URLSearchParams(),
}));

const WH = { id: "0192a000-0000-7000-8000-0000000000b1", code: "WH-MAIN", name: "Main Warehouse" };
const SET = { id: "p-set", product_key: "LK-WP-0001", name: "Walnut cabinet panel set", stock_uom_code: "set" };
const simulator = () =>
  testBootstrap({ permissions: [{ key: "production.work_order.read", scope: "company" }, { key: "production.bom.read", scope: "company" }, { key: "production.simulation.run", scope: "company" }] });
const reader = () => testBootstrap({ permissions: [{ key: "production.work_order.read", scope: "branch" }] });

const bomPage = (status: "approved" | "draft") => ({
  items: [{ id: "bom-1", product: SET, version_no: 1, status, author: null, approved_by: null, approved_at: null, updated_at: "2026-10-07T09:30:00Z", line_count: 1 }],
  total: 1,
  limit: 50,
  offset: 0,
});

function outcome(o: FeasibilityRead["outcome"], earliest: string | null): FeasibilityRead {
  return {
    outcome: o, product: SET, quantity: "8", uom_code: "set", warehouse: WH, need_by: "2026-10-16", from_stock: "0", to_make: "8",
    earliest_completion: earliest, missing_inputs: [], computed_at: "2026-10-12T03:00:00Z", read_only: true,
    evidence: [{ kind: "components", status: o === "feasible" ? "ok" : "short", label: o === "feasible" ? "LK-WB-1800: enough" : "LK-WB-1800: short 8 sheets", facts: {} }],
  };
}

describe("what-if", () => {
  it("builds the request from complete rows only", () => {
    const checks = [
      { key: 1, product: "p-set", quantity: "8", needBy: "2026-10-16", warehouse: null },
      { key: 2, product: "p-set", quantity: null, needBy: "2026-10-16", warehouse: null },
    ];
    const stock = [
      { key: 3, product: { id: "p-board", product_key: "LK-WB-1800", product_name: "Walnut board", decor: null, unit_of_sale: null, carton_qty: null }, text: "Walnut", warehouse: WH.id, delta: "8" },
      { key: 4, product: null, text: "", warehouse: null, delta: "5" },
      { key: 5, product: { id: "p-x", product_key: "X", product_name: "X", decor: null, unit_of_sale: null, carton_qty: null }, text: "X", warehouse: null, delta: "0" },
    ];
    const capacity = [
      { key: 6, workCentre: "wc-saw", machines: "2", extraMinutes: null },
      { key: 7, workCentre: "wc-asm", machines: null, extraMinutes: "-30" },
      { key: 8, workCentre: "wc-edge", machines: "1.5", extraMinutes: null },
    ];
    expect(simulationBody(checks, stock, capacity)).toEqual({
      checks: [{ product_id: "p-set", quantity: "8", need_by: "2026-10-16", warehouse_id: null }],
      stock_changes: [{ product_id: "p-board", warehouse_id: WH.id, delta: "8" }],
      capacity_changes: [
        { work_center_id: "wc-saw", machine_count: 2, extra_minutes_per_day: null },
        { work_center_id: "wc-asm", machine_count: null, extra_minutes_per_day: -30 },
      ],
    });
    expect(simulationBody([{ key: 1, product: null, quantity: "1", needBy: null, warehouse: null }], [], [])).toBeNull();
  });

  it("is only for people who may run simulations; lists approved-BOM products", () => {
    expect(textOf(renderWithQueries(<WhatIfScreen />, () => undefined, reader()))).toContain("You don't have access to What-if");
    const seeded = (status: "approved" | "draft") => (c: Parameters<Parameters<typeof renderWithQueries>[1]>[0]) => {
      c.setQueryData(queryKeys.production.boms({ status: "approved" }), bomPage(status));
      c.setQueryData(queryKeys.inventory.warehouses(), [WH]);
      c.setQueryData(queryKeys.production.workCentres(), []);
    };
    const text = textOf(renderWithQueries(<WhatIfScreen />, seeded("approved"), simulator()));
    expect(text).toContain("What to check");
    expect(text).toContain("The change to try");
    expect(text).toContain("Run the simulation");
    expect(text).toContain("Nothing is reserved, posted or saved.");
    expect(textOf(renderWithQueries(<WhatIfScreen />, seeded("draft"), simulator()))).toContain("nothing to simulate");
  });

  it("compares today with the change, says when the answer changes and when the form moved on", () => {
    const body: SimulationRequest = { checks: [{ product_id: SET.id, quantity: "8", need_by: "2026-10-16", warehouse_id: null }], stock_changes: [], capacity_changes: [] };
    const result: SimulationRead = {
      simulation: true, label: "What-if simulation: nothing was reserved, posted or saved", computed_at: "2026-10-12T03:00:00Z",
      baseline: [outcome("not_feasible", null)], scenario: [outcome("feasible", "2026-10-14")],
    };
    const render = (stale: boolean) =>
      textOf(renderWithQueries(<SimulationResults body={body} stale={stale} />, (c) => c.setQueryData(queryKeys.production.simulation(body), result), simulator()));
    const text = render(false);
    expect(text).toContain("What-if simulation: nothing was reserved, posted or saved");
    expect(text).toContain("The answer changes");
    expect(text).toContain("Today");
    expect(text).toContain("With the change");
    expect(text).toContain("Not feasible");
    expect(text).toContain("LK-WB-1800: enough");
    expect(text).not.toContain("Run it again");
    expect(render(true)).toContain("Run it again to see their effect.");
  });

  it("shows the What-if tab only to people who may simulate", () => {
    expect(textOf(renderWithQueries(<ProductionTabs current="capacity" />, () => undefined, simulator()))).toContain("What-if");
    expect(textOf(renderWithQueries(<ProductionTabs current="capacity" />, () => undefined, reader()))).not.toContain("What-if");
  });
});
