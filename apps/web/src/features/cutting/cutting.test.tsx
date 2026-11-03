import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "@/lib/api/client";
import { conflictFromError, ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { controlsWithoutVisibleFocus, renderWithQueries, seedQueryError, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { calculatePlan, updatePlan } from "./api";
import { nextZoom, showsLabel } from "./board-canvas";
import { blankRow, formOf, planChanges, rowsToRequest, serverErrors, validateForm } from "./editor-model";
import { GrainLocks } from "./grain-locks";
import { planListHref, planListStateFrom } from "./list-state";
import { parseGrainLocks, parsePlanDetail, parsePlanSummary } from "./parse";
import { calcPollInterval, NewPlan, PlanWorkspace } from "./plan-editor";
import { PlanList } from "./plan-list";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/operations/cutting",
  useSearchParams: () => new URLSearchParams(),
}));

const PLAN = "0192a000-0000-7000-8000-0000000000e1";
const API = `/api/v1/cutting/plans/${PLAN}`;

const opsBootstrap = (extra: { key: string; scope: string }[] = []) =>
  testBootstrap({
    permissions: [
      { key: "cutting.plan.read", scope: "branch" },
      { key: "cutting.plan.create", scope: "company" },
      { key: "cutting.plan.update", scope: "branch" },
      { key: "cutting.calculation.run", scope: "company" },
      { key: "catalogue.product.read", scope: "company" },
      ...extra,
    ],
  });

const areas = {
  raw_area_mm2: "2976800.00", usable_area_mm2: "2940300.00", placed_area_mm2: "1000000.00", trim_area_mm2: "36500.00",
  scrap_area_mm2: "1940300.00", efficiency_usable_pct: "34.01", efficiency_raw_pct: "33.59", scrap_pct: "65.99",
  raw_area_m2: "2.977", placed_area_m2: "1.000", scrap_area_m2: "1.940",
};

const settings = {
  board_length_mm: "2440", board_width_mm: "1220", margin_mm: "5", gap_mm: "6", oversize_enabled: false, oversize_mm: "10",
  mode: "nested", machine_profile_id: null, overproduction_enabled: false, max_extra_qty: 0, max_extra_pct: "0",
  min_offcut_mm: "300", max_boards_per_group: 500, raw_length_mm: "2440", raw_width_mm: "1220", usable_length_mm: "2430",
  usable_width_mm: "1210",
};

function calcWire() {
  return {
    id: "c1", plan_id: PLAN, calc_no: 1, origin: "sync", created_at: "2026-10-12T02:45:00Z",
    created_by: { id: "u1", display_name: "Ravi Kumar" }, algorithm_version: "lk-pack-1.0", mode: "nested",
    input_hash: "a".repeat(64), result_hash: "b".repeat(64), requires_physical_verification: false,
    note: "Heuristic layout, not guaranteed optimal", settings, grain_locked_decors: [],
    totals: { ...areas, boards: 1, required: 2, placed_required: 2, extra: 0, produced: 2, unfit: 0, lower_bound_boards: 1 },
    groups: [
      {
        ...areas, group_no: 1, decor_key: "0457", thickness_mm: "18", mode: "nested", board_count: 1, lower_bound_boards: 1,
        warnings: [],
        items: [{ line_no: 1, sku: "LK-WB-1800-SIDE", length_mm: "1000", width_mm: "500", rotation_allowed: true, required: 2,
                  placed_required: 2, extra: 0, produced: 2, unfit: 0, unfit_reason: null }],
        boards: [{
          index: 1, board_no: 1, source: "standard", raw_length_mm: "2440", raw_width_mm: "1220", margin_mm: "5",
          usable_length_mm: "2430", usable_width_mm: "1210", placed_area_mm2: "1000000.00", efficiency_pct: "34.01",
          placements: [
            { seq: 1, line_no: 1, sku: "LK-WB-1800-SIDE", piece_no: 1, x_mm: "5", y_mm: "5", along_length_mm: "1000", along_width_mm: "500", rotated: false, is_extra: false },
            { seq: 2, line_no: 1, sku: "LK-WB-1800-SIDE", piece_no: 2, x_mm: "1011", y_mm: "5", along_length_mm: "500", along_width_mm: "1000", rotated: true, is_extra: false },
          ],
          offcuts: [{ seq: 1, x_mm: "5", y_mm: "511", length_mm: "1000", width_mm: "704" }],
          cuts: [],
          svg_path: `${API}/calculations/1/boards/1.svg`,
        }],
      },
    ],
  };
}

function planWire(overrides: Record<string, unknown> = {}) {
  return {
    id: PLAN, plan_number: "CUT-2026-0001", name: "Walnut panels", notes: null, status: "calculated",
    owner: { id: "u1", display_name: "Ravi Kumar" }, branch_id: null, created_at: "2026-10-12T02:45:00Z",
    updated_at: "2026-10-12T02:45:00Z", version: 3, duplicated_from: null,
    items: [{ id: "i1", line_no: 1, product_id: null, sku: "LK-WB-1800-SIDE", decor: "0457", decor_key: "0457", thickness_mm: "18",
              length_mm: "1000", width_mm: "500", quantity: 2, grain_rule: "inherit", label: null }],
    settings, stale: false,
    calculation: { status: "idle", requested_at: null, error: null, pieces: 2, sync_piece_limit: 300, max_pieces: 5000 },
    verification: { required: false, verified: false, verified_at: null, verified_by: null, assumed_length_mm: null, assumed_width_mm: null, measured: null },
    latest_calculation: calcWire(),
    calculations: [{ id: "c1", calc_no: 1, created_at: "2026-10-12T02:45:00Z", boards: 1, efficiency_usable_pct: "34.01", unfit: 0 }],
    capabilities: {
      update: { allowed: true, reason_code: null }, export: { allowed: true, reason_code: null },
      transition: { allowed: true, reason_code: null }, calculate: { allowed: true, reason_code: null },
      duplicate: { allowed: true, reason_code: null }, verify: { allowed: false, reason_code: "verification_not_required" },
    },
    allowed_transitions: [{ action: "archive", to_status: "archived", requires_reason: false }],
    exports: { csv: `${API}/export.csv`, summary_csv: `${API}/export.csv?kind=summary`, pdf: `${API}/export.pdf` },
    path: `/operations/cutting/${PLAN}`,
    warnings: [],
    ...overrides,
  };
}

function fakeClient(respond: (request: Request) => Response, seen: Request[] = []) {
  return createApiClient({
    baseUrl: "http://127.0.0.1:3010",
    getCsrfToken: () => "csrf",
    fetch: async (request) => {
      seen.push(request.clone());
      return respond(request);
    },
  });
}

const problemResponse = (status: number, code: string, extra: Record<string, unknown> = {}) =>
  new Response(JSON.stringify({ type: "about:blank", title: "Problem", status, code, detail: "Changed by someone else", request_id: "req-1", ...extra }), {
    status,
    headers: { "content-type": "application/problem+json" },
  });

function renderPlan(wire: Record<string, unknown>, bootstrap = opsBootstrap()) {
  return renderWithQueries(<PlanWorkspace planId={PLAN} />, (client) => client.setQueryData(queryKeys.cutting.plan(PLAN), parsePlanDetail(wire)), bootstrap);
}

describe("plan list", () => {
  it("normalises the URL state and builds canonical links", () => {
    expect(planListStateFrom({ q: " walnut ", status: "bogus", scope: "mine", offset: "37" })).toEqual({ q: " walnut ", status: null, scope: "mine", offset: 25 });
    expect(planListStateFrom({ offset: "-5" })).toEqual({ q: "", status: null, scope: "all", offset: 0 });
    expect(planListHref({ q: "walnut", status: "draft", scope: "all", offset: 0 })).toBe("/operations/cutting?q=walnut&status=draft");
  });

  it("renders saved plans with boards and use, and New only with create permission", () => {
    const state = { q: "", status: null, scope: "all" as const, offset: 0 };
    const seed = (client: Parameters<Parameters<typeof renderWithQueries>[1]>[0]) =>
      client.setQueryData(queryKeys.cutting.plans({ q: null, status: null, scope: "all", offset: 0 }), {
        items: [parsePlanSummary({ ...planWire(), item_count: 1, piece_count: 2, boards: 1, efficiency_usable_pct: "34.01", requires_physical_verification: true, verified: false, calc_status: "idle" })],
        total: 1, limit: 25, offset: 0,
      });
    const text = textOf(renderWithQueries(<PlanList state={state} />, seed, opsBootstrap()));
    expect(text).toContain("CUT-2026-0001");
    expect(text).toContain("Walnut panels · Verify boards");
    expect(text).toContain("34.01 %");
    expect(text).toContain("New cut plan");
    const viewer = testBootstrap({ permissions: [{ key: "cutting.plan.read", scope: "company" }] });
    expect(textOf(renderWithQueries(<PlanList state={state} />, seed, viewer))).not.toContain("New cut plan");
  });

  it("shows the empty, loading and forbidden states", () => {
    const state = { q: "", status: null, scope: "all" as const, offset: 0 };
    const key = queryKeys.cutting.plans({ q: null, status: null, scope: "all", offset: 0 });
    expect(textOf(renderWithQueries(<PlanList state={state} />, (c) => c.setQueryData(key, { items: [], total: 0, limit: 25, offset: 0 }), opsBootstrap())))
      .toContain("Create a plan, add the pieces to cut and calculate the layout.");
    expect(renderWithQueries(<PlanList state={state} />, () => undefined, opsBootstrap())).toContain('aria-busy="true"');
    const forbidden = ProblemError.fromResponse(new Response(null, { status: 403 }), { title: "Forbidden", status: 403, code: "permission_denied" });
    expect(textOf(renderWithQueries(<PlanList state={state} />, (c) => seedQueryError(c, key, forbidden), opsBootstrap())))
      .toContain("You don't have access to the sheet optimiser");
  });
});

describe("plan workspace (server render)", () => {
  it("shows the editor, the stored layout with a true-scale canvas and the placement table", () => {
    const html = renderPlan(planWire());
    const text = textOf(html);
    expect(html).toMatch(/<h1[^>]*>CUT-2026-0001<\/h1>/);
    expect(html).toContain('viewBox="0 0 2440 1220"');
    expect(html).toContain('aria-label="LK-WB-1800-SIDE, 500 × 1000 mm, at 1011, 5 mm, rotated 90°"');
    expect((html.match(/<g tabindex="0" role="img"/g) ?? []).length).toBe(2);
    expect(text).toContain("Heuristic layout, not guaranteed optimal.");
    expect(text).toContain("Placement table (2)");
    expect(text).toContain("1000 × 704 mm");
    expect(text).toContain("Calculate layout");
    expect(html).toContain(`href="${API}/export.pdf"`);
    expect(html).toContain(`href="${API}/calculations/1/boards/1.svg"`);
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("is read-only without update, offers no archive without the transition", () => {
    const html = renderPlan(
      planWire({
        status: "archived",
        capabilities: { update: { allowed: false, reason_code: "plan_archived" }, export: { allowed: true, reason_code: null }, duplicate: { allowed: false, reason_code: "permission_denied" } },
        allowed_transitions: [],
      }),
    );
    const text = textOf(html);
    expect(text).toContain("This plan can't be edited in its current status.");
    expect(text).not.toContain("Calculate layout");
    expect(html).not.toMatch(/>Archive</);
    expect(text).not.toContain("Duplicate");
    expect(html).not.toMatch(/<input[^>]*aria-label="Length \(mm\), Row 1"/);
  });

  it("explains a queued calculation, a stale layout and the oversize verification", () => {
    const text = textOf(
      renderPlan(
        planWire({
          stale: true,
          calculation: { status: "queued", requested_at: null, error: null, pieces: 360, sync_piece_limit: 300, max_pieces: 5000 },
          verification: { required: true, verified: false, verified_at: null, verified_by: null, assumed_length_mm: "2460", assumed_width_mm: "1240", measured: null },
          capabilities: { ...planWire().capabilities, verify: { allowed: true, reason_code: null } },
        }),
      ),
    );
    expect(text).toContain("360 pieces: the layout is being calculated in the background.");
    expect(text).toContain("Calculate again to update it.");
    expect(text).toContain("This layout assumes boards of 2460 × 1240 mm.");
    expect(text).toContain("Record measurement");
  });

  it("starts a new plan with three blank rows and the legacy board defaults", () => {
    const html = renderWithQueries(<NewPlan />, () => undefined, opsBootstrap());
    expect((html.match(/aria-label="Length \(mm\), Row \d"/g) ?? []).length).toBe(3);
    expect(html).toContain('value="2440"');
    expect(html).toContain('value="1220"');
    expect(textOf(html)).toContain("Create plan");
    expect(textOf(html)).toContain("Plans using oversize are marked verify before release");
  });

  it("shows not-available for an invisible plan", () => {
    const missing = ProblemError.fromResponse(new Response(null, { status: 404 }), { title: "Not found", status: 404, code: "not_found" });
    const html = renderWithQueries(<PlanWorkspace planId={PLAN} />, (c) => seedQueryError(c, queryKeys.cutting.plan(PLAN), missing), opsBootstrap());
    expect(textOf(html)).toContain("Not found or not available to you");
  });

  it("polls only while the calculation job runs", () => {
    expect(calcPollInterval(parsePlanDetail(planWire()))).toBe(false);
    expect(calcPollInterval(parsePlanDetail(planWire({ calculation: { status: "queued", pieces: 400 } })))).toBe(1500);
    expect(calcPollInterval(undefined)).toBe(false);
  });
});

describe("editor model", () => {
  const base = formOf(parsePlanDetail(planWire()));

  it("sends only what changed, skipping blank rows", () => {
    expect(planChanges(base, base)).toEqual({});
    const named = { ...base, name: " Walnut doors " };
    expect(planChanges(base, named)).toEqual({ name: "Walnut doors" });
    const withRow = { ...base, rows: [...base.rows, blankRow("b1"), { ...blankRow("b2"), sku: "NEW", thickness_mm: "18", length_mm: "300", width_mm: "200", quantity: "4" }] };
    const changes = planChanges(base, withRow);
    expect(changes.items?.map((i) => i.sku)).toEqual(["LK-WB-1800-SIDE", "NEW"]);
    expect(changes.items?.[1]).toEqual({ product_id: null, sku: "NEW", decor: null, thickness_mm: "18", length_mm: "300", width_mm: "200", quantity: "4", grain_rule: "inherit" });
    expect(planChanges(base, { ...base, settings: { ...base.settings, oversize_enabled: true } })).toEqual({ settings: { oversize_enabled: true } });
    expect(rowsToRequest([blankRow()])).toEqual([]);
  });

  it("checks rows before saving: one decimal place in mm, whole quantities", () => {
    const bad = { ...base, rows: [{ ...base.rows[0]!, length_mm: "12.25", quantity: "1.5" }] };
    const errors = validateForm(bad);
    expect(Object.keys(errors.rows[bad.rows[0]!.key] ?? {}).sort()).toEqual(["length_mm", "quantity"]);
    expect(validateForm({ ...base, name: " " }).name).toBe("Give the plan a name.");
  });

  it("maps a 422 back onto the row the server counted (blank rows are not sent)", () => {
    const rows = [blankRow("blank"), { ...base.rows[0]!, key: "real" }];
    const errors = serverErrors(
      [
        { loc: ["body", "items", 0, "decor"], msg: "decor must be at most 40 characters", code: "invalid_decor" },
        { loc: ["body", "settings", "margin_mm"], msg: "The margins leave no usable area on the board", code: "margin_too_large" },
        { loc: ["body", "items"], msg: "A plan holds at most 5000 pieces", code: "cutting_input_too_large" },
      ],
      rows,
    );
    expect(errors.rows).toEqual({ real: { decor: "decor must be at most 40 characters" } });
    expect(errors.settings).toEqual({ margin_mm: "The margins leave no usable area on the board" });
    expect(errors.general).toEqual(["A plan holds at most 5000 pieces"]);
  });
});

describe("commands", () => {
  it("sends expected_version and the Idempotency-Key, and turns a 409 into conflict info", async () => {
    const seen: Request[] = [];
    const ok = fakeClient(() => Response.json(planWire({ version: 4 })), seen);
    const saved = await updatePlan({ id: PLAN, version: 3 }, { name: "Walnut doors" }, "key-1", ok);
    expect(await seen[0]!.json()).toEqual({ expected_version: 3, name: "Walnut doors" });
    expect(seen[0]!.headers.get("Idempotency-Key")).toBe("key-1");
    expect(saved.version).toBe(4);
    const conflict = fakeClient(() => problemResponse(409, "version_conflict", { current_version: 5 }));
    const error = await calculatePlan({ id: PLAN, version: 3 }, "key-2", conflict).catch((caught: unknown) => caught);
    expect(conflictFromError(error)?.currentVersion).toBe(5);
  });
});

describe("board canvas helpers", () => {
  it("zooms in steps and labels only pieces large enough", () => {
    expect(nextZoom(1, 1)).toBe(1.5);
    expect(nextZoom(1, -1)).toBe(1);
    expect(nextZoom(6, 1)).toBe(6);
    expect(showsLabel({ along_length_mm: "250", along_width_mm: "80" })).toBe(true);
    expect(showsLabel({ along_length_mm: "249.9", along_width_mm: "500" })).toBe(false);
  });
});

describe("grain locks", () => {
  const list = (canManage: boolean) =>
    parseGrainLocks({
      items: [{ id: "g1", decor_key: "120", decor_source: "120.0", label: "Rift oak", updated_at: "2026-10-12T02:45:00Z", updated_by: { id: "u9", display_name: "Priya Nair" } }],
      can_manage: canManage,
      warnings: [],
    });

  it("lets managers add and remove; others read", () => {
    const managed = renderWithQueries(<GrainLocks />, (c) => c.setQueryData(queryKeys.cutting.grainLocks(), list(true)), opsBootstrap());
    expect(textOf(managed)).toContain("Add lock");
    expect(managed).toContain('aria-label="Remove the lock on 120"');
    expect(textOf(managed)).toContain("(120.0)");
    const readOnly = textOf(renderWithQueries(<GrainLocks />, (c) => c.setQueryData(queryKeys.cutting.grainLocks(), list(false)), opsBootstrap()));
    expect(readOnly).toContain("Only people who manage grain settings can change this list.");
    expect(readOnly).not.toContain("Add lock");
  });
});
