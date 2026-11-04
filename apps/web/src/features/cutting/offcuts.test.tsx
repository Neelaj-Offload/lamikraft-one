import { describe, expect, it, vi } from "vitest";
import { queryKeys } from "@/lib/api/query-keys";
import { renderWithQueries, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { toggledSelection } from "./offcuts";
import { parsePlanDetail } from "./parse";
import { PlanWorkspace } from "./plan-editor";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/operations/cutting",
  useSearchParams: () => new URLSearchParams(),
}));

const PLAN = "0192a000-0000-7000-8000-0000000000e2";
const LOT = "0192a000-0000-7000-8000-0000000000c1";
const API = `/api/v1/cutting/plans/${PLAN}`;
const bootstrap = (stock: boolean) =>
  testBootstrap({
    permissions: [
      { key: "cutting.plan.read", scope: "company" },
      { key: "cutting.plan.update", scope: "company" },
      { key: "cutting.calculation.run", scope: "company" },
      ...(stock ? [{ key: "inventory.stock.read", scope: "branch" }] : []),
    ],
  });

const areas = {
  raw_area_mm2: "3696600.00", usable_area_mm2: "3660100.00", placed_area_mm2: "2654000.00", trim_area_mm2: "36500.00",
  scrap_area_mm2: "1006100.00", efficiency_usable_pct: "72.51", efficiency_raw_pct: "71.80", scrap_pct: "27.49",
  raw_area_m2: "3.697", placed_area_m2: "2.654", scrap_area_m2: "1.006",
};
const settings = {
  board_length_mm: "2440", board_width_mm: "1220", margin_mm: "5", gap_mm: "6", oversize_enabled: false, oversize_mm: "10",
  mode: "nested", machine_profile_id: null, overproduction_enabled: false, max_extra_qty: 0, max_extra_pct: "0",
  min_offcut_mm: "300", max_boards_per_group: 500, raw_length_mm: "2440", raw_width_mm: "1220", usable_length_mm: "2430", usable_width_mm: "1210",
};
const board = (index: number, source: string, extra: Record<string, unknown>) => ({
  index, board_no: index, source, placed_area_mm2: "638000.00", efficiency_pct: "88.64", offcuts: [], cuts: [], svg_path: `${API}/calculations/2/boards/${index}.svg`,
  placements: [{ seq: 1, line_no: 1, sku: "WD-PANEL", piece_no: 1, x_mm: "0", y_mm: "0", along_length_mm: "1100", along_width_mm: "580", rotated: false, is_extra: false }],
  ...extra,
});

function wire(overrides: Record<string, unknown> = {}) {
  return {
    id: PLAN, plan_number: "CUT-2026-0002", name: "Walnut doors", notes: null, status: "calculated", owner: { id: "u1", display_name: "Deepa Menon" },
    branch_id: null, created_at: "2026-10-12T02:45:00Z", updated_at: "2026-10-12T02:45:00Z", version: 5, duplicated_from: null,
    items: [{ id: "i1", line_no: 1, product_id: null, sku: "WD-PANEL", decor: "0457", decor_key: "0457", thickness_mm: "18", length_mm: "1100", width_mm: "580", quantity: 1, grain_rule: "inherit", label: null }],
    settings, stale: false,
    calculation: { status: "idle", requested_at: null, error: null, pieces: 1, sync_piece_limit: 300, max_pieces: 5000 },
    verification: { required: false, verified: false, verified_at: null, verified_by: null, assumed_length_mm: null, assumed_width_mm: null, measured: null },
    latest_calculation: {
      id: "c2", plan_id: PLAN, calc_no: 2, origin: "sync", created_at: "2026-10-12T02:50:00Z", created_by: null, algorithm_version: "lk-pack-1.0",
      mode: "nested", input_hash: "a".repeat(64), result_hash: "b".repeat(64), requires_physical_verification: false,
      note: "Heuristic layout, not guaranteed optimal", settings, grain_locked_decors: [],
      totals: { ...areas, boards: 2, offcut_boards: 1, required: 2, placed_required: 2, extra: 0, produced: 2, unfit: 0, lower_bound_boards: 1 },
      groups: [{
        ...areas, group_no: 1, decor_key: "0457", thickness_mm: "18", mode: "nested", board_count: 2, offcut_boards: 1, lower_bound_boards: 1, warnings: [],
        items: [{ line_no: 1, sku: "WD-PANEL", length_mm: "1100", width_mm: "580", rotation_allowed: false, required: 2, placed_required: 2, extra: 0, produced: 2, unfit: 0, unfit_reason: null }],
        boards: [
          board(1, "offcut", { raw_length_mm: "1180", raw_width_mm: "610", margin_mm: "0", usable_length_mm: "1180", usable_width_mm: "610", lot_id: LOT, lot_code: "WO-2026-0001-OC01" }),
          board(2, "standard", { raw_length_mm: "2440", raw_width_mm: "1220", margin_mm: "5", usable_length_mm: "2430", usable_width_mm: "1210", lot_id: null, lot_code: null }),
        ],
      }],
    },
    calculations: [],
    capabilities: {
      update: { allowed: true, reason_code: null }, export: { allowed: true, reason_code: null }, transition: { allowed: true, reason_code: null },
      calculate: { allowed: true, reason_code: null }, duplicate: { allowed: false, reason_code: "permission_denied" }, verify: { allowed: false, reason_code: "verification_not_required" },
    },
    allowed_transitions: [], exports: {}, path: `/operations/cutting/${PLAN}`, warnings: [],
    offcuts: [{ seq: 1, lot_id: LOT, lot_code: "WO-2026-0001-OC01", product_id: "p-board", decor_key: "0457", thickness_mm: "18", length_mm: "1180", width_mm: "610", grain_axis: "length", on_hand: true, used: true, matches_group: true }],
    ...overrides,
  };
}

const render = (w: Record<string, unknown>, stock = true) =>
  textOf(renderWithQueries(<PlanWorkspace planId={PLAN} />, (c) => c.setQueryData(queryKeys.cutting.plan(PLAN), parsePlanDetail(w)), bootstrap(stock)));

describe("offcut reuse on a cut plan", () => {
  it("keeps the planner's order when toggling lots", () => {
    expect(toggledSelection(["a", "b"], "c", true)).toEqual(["a", "b", "c"]);
    expect(toggledSelection(["a", "b", "c"], "b", false)).toEqual(["a", "c"]);
    expect(toggledSelection(["a"], "a", true)).toEqual(["a"]);
  });

  it("lists the chosen offcuts with honest status and labels the offcut board in the layout", () => {
    const text = render(wire());
    expect(text).toContain("Offcuts to use first");
    expect(text).toContain("WO-2026-0001-OC01");
    expect(text).toContain("Used in the layout");
    expect(text).toContain("Choose offcuts");
    expect(text).toContain("From offcuts");
    expect(text).toContain("1 standard sheet");
    expect(text).toContain("Board 1 · offcut WO-2026-0001-OC01");
    expect(text).toContain("Cut from offcut lot WO-2026-0001-OC01; no edge margin");
    const gone = render(wire({ offcuts: [{ seq: 1, lot_id: LOT, lot_code: "OC-9", product_id: "p", decor_key: "0120", thickness_mm: "18", length_mm: "500", width_mm: "400", grain_axis: null, on_hand: false, used: false, matches_group: false }] }));
    expect(gone).toContain("No longer on hand");
    expect(gone).toContain("No piece group has this decor and thickness");
    expect(gone).toContain("Not used in the layout");
  });

  it("offers choosing only to people who may edit the plan and read stock", () => {
    expect(render(wire({ offcuts: [] }), false)).not.toContain("Offcuts to use first");
    const fixed = render(wire({ status: "released", capabilities: { ...wire().capabilities, update: { allowed: false, reason_code: "plan_released_not_editable" } } }));
    expect(fixed).toContain("its offcut choice is fixed");
    expect(fixed).not.toContain("Choose offcuts");
    expect(render(wire({ offcuts: [] }))).toContain("No offcut chosen. The plan uses standard sheets only.");
  });
});
