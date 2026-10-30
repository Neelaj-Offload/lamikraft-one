# Lane report: cutting (Slice 2, wave 2) — sheet optimiser

Branch `lane/s2w2-cutting` (from `main` 00721da), worktree `D:\lk-wt\identity`, slot 1.

## What was built

**Backend `backend/app/modules/cutting/`**

- `packer/` (pure Python, no DB, no clock, no new dependencies; ADR-020):
  - `geometry.py`: integer deci-millimetres; inputs with more than one decimal place in mm are rejected.
  - `maxrects.py`: MaxRects with best-short-side-fit, maximal free-rectangle split and containment pruning.
  - `guillotine.py`: guillotine packer using the Shorter-Leftover-Axis split; it records the cut tree (stage, orientation, kerf start, extent, kerf).
  - `engine.py`:
    - Groups by canonical decor plus normalised thickness and sorts largest first.
    - Rotation is allowed unless the decor is grain-locked, the item rule is `locked`, or the decor is blank. Blank decors are treated as locked and raise a warning.
    - Kerf is applied by inflating pieces and the bin; margins are applied.
    - +oversize is a separate setting that flags `requires_physical_verification` (decision #12).
    - Pre-check unfit reasons: `exceeds_usable_board` / `grain_lock_prevents_rotation` / `max_boards_limit`.
    - Deterministic multi-start: 4 orders × 2 scores, selected by (unfit, boards, last-board utilisation, run).
    - Overproduction is bounded: `min(max_qty, floor(required × pct))`, placed round-robin into open boards only.
    - Exact integer area identity: raw = placed + scrap + trim.
    - Reports an area lower bound and a deterministic work budget (`PackBudgetExceeded`), plus `result_hash` and `input_hash`.
  - `remnants.py`: predicted offcuts (greedy, disjoint, gap-clear, ≥ 300 × 300).
  - `checker.py`: independent checks — overlap, bounds, gap, `is_guillotine`, and a cut-tree replay.
- `canonical.py`:
  - Decor keys use the catalogue identifier rule: `0120` ≠ `120`, and `120.0` → `120` with a warning.
  - Thickness `0.8` and `0.80` are one value.
- `models.py` + migration `0010_cutting_slice2.py` (down_revision `0009`), 12 tables:
  - `cutting_settings`, `cutting_machine_profile` and `cutting_grain_lock` (UNIQUE company+decor_key).
  - `cutting_plan`, which holds the settings snapshot, stale flag, verification, the calculation job state and the version.
  - `cutting_plan_item`.
  - Append-only `cutting_calculation` and its results: `cutting_calc_{group,board,placement,item_result,offcut,cut}`.
  - All tables have forced RLS. CHECKs cover enums, positivity, and the area and count identities.
- `policies.py`:
  - `cutting.plan` is scoped own/team/branch/company on `owner_user_id` and `branch_id`.
  - Items and calculations are authorised only through their plan, and result rows only through their calculation.
  - Object rules: editable while draft or calculated, exportable once calculated, archived is read-only.
- `config.py`:
  - Settings: the legacy constants are company defaults (2440 × 1220, margin 5, gap 6, oversize 10). PATCH requires `cutting.settings.manage` plus `expected_version`.
  - Machine profiles set mode and kerf.
  - Grain locks support add, remove and bulk replace. Each change is audited with a before/after diff or with the added, removed and relabelled lists. Writes need `cutting.grain_lock.manage`; reads need any `cutting.` key.
- `plans.py`:
  - **Plan lifecycle:**
    - Create (`CUT-YYYY-NNNN`, yearly).
    - Dirty-field PATCH with `expected_version` (409); changed inputs mark the plan stale.
    - Reopen returns the stored calculation and never recomputes.
    - Duplicate copies inputs only.
    - Archive.
    - `verify-boards`: measured size ≥ assumed size verifies the plan; a smaller measurement marks it stale.
  - **Calculation and job:**
    - Synchronous calculation up to 300 pieces.
    - The `cutting.calculate` durable job handles 301–5000 pieces. It polls through `calculation.status`, and every failure lands on the plan as `failed` with a code.
    - The work budget produces a 422 `cutting_budget_exceeded`.
    - Stateless `POST /cutting/calculate` (legacy parity) is limited to the synchronous size.
  - **Product autocomplete:** goes through `catalogue.list_products`, so catalogue scope applies.
  - Events emitted: `cutting.plan.saved`, `.calculated`, `.verification_required`, `.verified`, `.archived`.
- `exports.py`:
  - Placements CSV and summary CSV, both written by `core/csv_safe` with formula escaping.
  - PDF via `core/documents`: summary, pieces, and one page per board with `board_drawing` plus a placement table.
  - Per-board SVG with a viewBox in mm, margin band, labels, rotation marks, extra-piece hatching and dashed offcuts.
- `router.py`: 17 routes under `/api/v1/cutting`, each declaring catalogued keys.
- Seed `backend/app/seed/world/cutting.py` (order 78, slice 2): CUT-2026-0001, LK-WB-1800 walnut panels, owner Ravi, saved and calculated at D0 08:15.

**Web**

- `apps/web/src/features/cutting/**`:
  - Saved plans list: URL state, filters applied server-side before paging, empty/loading/error/403 states.
  - Plan editor:
    - New plans start with 3 blank rows.
    - Catalogue autocomplete fills SKU, decor, thickness and size.
    - Keyboard: Enter moves to the next row or adds one.
    - Board and machine settings, an oversize switch labelled "verify before release", and bounded overproduction controls.
    - Dirty-field save, the 409 conflict view (reload or keep mine), and 422 errors mapped to rows and fields.
  - Calculate, with polling while the job runs.
  - Results per group: boards vs lower bound, placed/required, efficiency, scrap, m², unfit with reasons, warnings.
  - True-scale SVG board canvas: zoom steps, drag/scroll pan, keyboard zoom, and focusable pieces whose details show on hover or focus.
  - Placement table as the accessible alternative, plus predicted offcuts.
  - Exports, duplicate, archive (confirm dialog) and the board-verification form.
  - Grain-lock admin (read-only without `cutting.grain_lock.manage`).
- Pages under `apps/web/src/app/(app)/operations/cutting/`: `page.tsx`, `new/`, `[planId]/`, `grain-locks/`.
- Shared files (one block each, `// cutting` comment): `src/lib/routes.ts` (4 entries) and `src/lib/api/query-keys.ts` (`cutting.*`).
- `apps/web/e2e/scenarios/h-cutting-canvas.spec.ts` is written but not run.

## PARITY rows → code and test

All tests below pass except the e2e ones, which are written but not run.

| Row | Test(s) |
|---|---|
| LM-71 | `tests/integration/cutting/test_plan_persistence.py::test_save_reopen_preserves_inputs_and_results` |
| LM-72, BR-11, LP-09.2 | `tests/unit/cutting/test_packer_examples.py::test_defaults_and_oversize_effect`; `tests/integration/cutting/test_grain_settings.py::test_settings_defaults_overrides_and_machine_profiles` |
| LM-73 | `tests/unit/cutting/test_packer_examples.py::test_grouping_decor_thickness` |
| LM-74, FG-GRN-02, FG-GRN-03, API-53, UI-74 | `tests/integration/cutting/test_grain_settings.py::test_grain_lock_writes_require_manage_and_canonical_key`; vitest `cutting.test.tsx > grain locks` |
| API-54, API-55, API-56 | `tests/integration/cutting/test_grain_settings.py::test_bulk_replace_and_add_remove` |
| FG-GRN-01 | `tests/unit/cutting/test_packer_examples.py::test_lock_on_120_blocks_rotation_of_120_0` |
| LM-75, SCN-H2 | `tests/unit/cutting/test_packer_properties.py::test_counts_reconcile` |
| LM-76, UI-18 | e2e `h-cutting-canvas.spec.ts::plan_calculate_save_reopen_svg` (written); SVG checked in `test_plan_persistence.py::test_duplicate_copies_inputs_and_exports_escape_formulas`; vitest `plan workspace > shows the editor, the stored layout…` |
| LM-77, LP-09.5 | `tests/unit/cutting/test_packer_examples.py::test_overproduction_bounded` |
| LM-78, UI-76 | `tests/integration/cutting/test_plan_persistence.py::test_duplicate_copies_inputs_and_exports_escape_formulas` (Slice 2 part; WO links are Slice 4) |
| LM-79, API-52, LP-09.1 | `tests/integration/cutting/test_calculate_endpoint.py::test_product_autocomplete_fills_decor_thickness_dimensions` |
| API-51 | `tests/integration/cutting/test_calculate_endpoint.py::test_stateless_calculate_parity` |
| UI-72 | vitest `plan workspace > starts a new plan with three blank rows…`; e2e `plan_calculate_save_reopen_svg` (written) |
| UI-73 | `tests/integration/cutting/test_plan_persistence.py::test_oversize_and_overproduction_have_effects`; e2e `oversize_and_overproduction_have_effects` (written) |
| UI-75 | e2e `svg_no_overlap_inside_boundary_counts_match` (written); vitest `plan workspace` tests |
| BUG-11 | `tests/unit/cutting/test_packer_properties.py::test_no_overlap_with_gap`; `test_remnants.py::test_predicted_offcuts_disjoint_and_clear_of_pieces` |
| LP-09.3 | `tests/unit/cutting/test_packer_properties.py::test_guillotine_mode_is_guillotine_separable` |
| LP-09.4 | `tests/unit/cutting/test_packer_properties.py::test_area_identity_exact` |
| LP-09.6, SCN-H3 | `test_plan_persistence.py::test_save_reopen_preserves_inputs_and_results`, `::test_oversize_and_overproduction_have_effects` (Slice 2 part) |
| SCN-H1 | `tests/unit/cutting/test_packer_properties.py::test_grain_locked_never_rotated`, `::test_no_overlap_with_gap`, `::test_within_usable_bounds` |
| PERM-23 / SEC-03 (cutting part) | `tests/integration/cutting/test_plan_idor.py::test_sales_own_scope_and_child_paths_hide_other_plans`, `::test_restricted_persona_has_no_optimiser`; `tests/contract/cutting/test_lane_schema.py::test_routes_name_only_catalogued_cutting_keys` |
| REUSE-05, OQ-03 (2→4) | Slice 2 part (persisted plans and board verification) is tested as above. `test_plan_release.py` (release, WO link) is Slice 4 and not written. |

Further tests:

- `test_packer_examples.py`: `test_unfit_reasons`, `test_max_boards_limit_reason`, `test_deterministic_result_hash`, `test_guillotine_records_cut_tree`, `test_metrics_reported_in_exact_units`.
- `test_packer_properties.py::test_deterministic_for_identical_input`.
- `test_plan_persistence.py`: `test_edit_marks_stale_and_stale_version_is_409`, `test_archive_makes_the_plan_read_only`, `test_large_plan_calculates_as_a_job`, `test_too_large_and_empty_inputs_are_clear_errors`, `test_budget_exceeded_is_a_clear_error`, `test_plan_list_filters_before_paging`.
- `test_calculate_endpoint.py::test_stateless_calculate_limits_and_permissions`.
- `test_seed_world.py::test_cut_plan_fixture`.
- The contract `test_lane_schema.py` (5 tests).

## Decisions and deviations

- **Canonical decor.** I followed PARITY FG-GRN-01 and PLAN ("`120.0` → `120` with a warning, `0120` stays distinct"). `operations.md` §14 says `'120'` and `'120.0'` form separate groups; that conflicts with the PARITY row and with the catalogue rule. Here they form one group, and `0120` stays separate.
- **Configuration tables have no resource policy.** Settings, machine profiles and grain locks have no `.read` key in the frozen catalogue, so the registry cannot register a policy for them. They are read with an explicit company filter plus RLS, gated by any `cutting.` key.
- **Audit field naming.** The audit `changes` field for grain locks is named `decor`, not `decor_key`. The audit redactor blanks any field containing "key".
- **Result storage.** Calculation results are stored as normalised append-only rows, not as JSONB.
- **Slice 4 scope.** Release and work-order links are not built; `cutting.plan.released` is not emitted.
- **Settings UI.** Settings and machine profiles have an API only; no settings screen was in the brief.
- **Web data access.** The web code uses `requestUntyped` + `parse.ts` (the interim pattern from sales), so it does not depend on the regenerated `schema.d.ts`.

## Requests for the integrator

1. **keys.py:** add `CUT_PLANS = SimpleNamespace(WALNUT="CUT-2026-0001")` (refs key `CUT_PLAN_WALNUT`; constants are in `app/seed/world/cutting.py`: `PLAN_REF`, `PLAN_NUMBER`, `PANELS`, `SAVED_AT`).
2. **Generated API files:** regenerate `backend/openapi.json` and `schema.d.ts`. Afterwards, `features/cutting/api.ts` can move to typed `api.GET/POST`.
3. **Migration:** reparent `0010_cutting_slice2.py` if another lane also used `0010`.
4. **Operations hub:** `operations/page.tsx` (not owned by this lane) is still a placeholder. Link `/operations/cutting` from it; the route is in the manifest as an `operations` context entry.
5. **tasks.rules:** the `ops.cut_plans` consumer for `cutting.plan.calculated` and `.verification_required` belongs to the tasks lane.
6. **PARITY_MATRIX:** move the rows above using the table, and record the canonical-decor decision against `operations.md` §14.
7. **e2e:** run `apps/web/e2e/scenarios/h-cutting-canvas.spec.ts`. It creates its own plans as Ravi.

## Gates

See the final section of the full report (counts pasted from the runs).
