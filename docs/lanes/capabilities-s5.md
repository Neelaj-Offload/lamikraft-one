# Lane report: Slice 5 — new capabilities (`lane/s5-capabilities`)

Worktree `D:\lk-wt\sales`, env slot 6, branched from `c4210a3` (the Slice-4 merge tip: orders/inventory, production
with cut-plan links and measured offcut lots, procurement/logistics; migrations renumbered 0022–0025). Never pushed.
Brief: the "new capabilities" part of `docs/superpowers/briefs/s5-migration-backup.md` (offcut reuse, sample lineage,
what-if views); the migration tooling and backup parts are on `lane/s5-migration` and were not touched. The slot's
databases (`lk_wt6`, `lk_wt6_test`) held the production lane's chain (0070); both were dropped, recreated and migrated
to this branch's head (0090) before testing. The dev database was not reseeded (no e2e ran, see Gates).

## What was built

### Offcut reuse — cut plans consume measured offcut lots
| Where | What |
|---|---|
| `cutting/packer/engine.py` | `StockBoard(ref, decor_key, thickness_key, length_dmm, width_dmm)` and `pack(items, settings, stock=())`. A group's offcut boards are filled first, in the order given, before any standard board is opened; an offcut board has no edge margin (measured saw edges) and never assumes the +oversize board; only offcuts that receive a piece are reported (`source="offcut"`, `stock_ref`). The selection key counts standard boards only; the lower bound subtracts the offcuts' capacity; overproduction only fills boards that already hold a piece. **Without stock the result and both hashes are byte-identical to the Slice-2 engine** (checked against the old engine on 25 random inputs; `stock_ref` is dropped from the hash body when null, `input_hash` adds `stock` only when non-empty). |
| `inventory/offcuts.py` (+ `service.offcut_lots`, `OffcutLot`) | Read-only: measured (`verified`, length and width) `offcut` lots with a positive balance in an **internal** stock-bearing location of a warehouse the actor may read (`inventory.stock.read` scope); WIP / QC / virtual locations never offer one; invisible lots are simply absent. |
| `cutting/models.py` `PlanOffcut` | `cutting_plan_offcut`: the plan's chosen lots (seq = fill order, lot code, product, decor key, thickness key, pinned length/width with the grain along the length — a lot measured with its grain across the width is stored turned; finer than 0.1 mm is rounded down). Child of the plan (`cutting.plan_offcut` policy). `cutting_calc_board.lot_id` gets its FK to `inventory_lot`. |
| `cutting/offcuts.py` | `candidates` (lots on hand with decor from the catalogue product, thickness from the lot or product, `matches_group`, `selected`, `other_plans` that also chose the lot), `replace_selection` (plan `update`; every lot must be a candidate now → 422 `offcut_not_available` — unknown, consumed, unmeasured, standard and invisible-warehouse lots are one answer; `offcut_thickness_unknown`; `duplicate_lot`; 403 without `inventory.stock.read`; a calculated plan becomes stale; audit `cutting.plan.offcuts_changed`; emits `cutting.plan.saved`), `copy_selection` (duplicate keeps it), `planned_offcuts` (the lots the current calculation cuts from). |
| `cutting/plans.py` | calculation passes the selection as stock boards; the input snapshot keeps `offcuts` (lot codes read from it later), `input_hash` covers them; board rows carry `lot_id`; reads add `BoardRead.lot_id/lot_code`, `GroupRead.offcut_boards`, `CalculationTotals.offcut_boards`, `PlanDetail.offcuts` (`on_hand`, `used`, `matches_group`). |
| `cutting/release.py` | `Readiness.offcut_boards`; `boards` still counts every board (the sheet requirement). |
| `production/wip.py` `issue_planned_offcuts` (+ calls in `work_orders._release` and `wip.link_cut_plan`) | When the plan is released for a work order, its offcut lots move from their bin in the WO's warehouse to WIP in one `issue` transaction (lines carry `offcut_reuse{lot_code, cut_plan_id, group_no, board_no}`), counted as issued against the sheet material the plan backs, **before** reservation — so only the standard sheets are reserved. Idempotent; 409 `offcut_not_of_material`; 409 `offcut_unavailable` (lots named; also when a concurrent posting took the lot, `NegativeStockError`) and the whole release rolls back. Consume / return / close then work unchanged on the offcut lots in WIP. |
| Routes | `GET /api/v1/cutting/plans/{id}/offcut-candidates` (`cutting.plan.read` + `inventory.stock.read`; empty with `stock_visible:false` without stock read), `PUT /api/v1/cutting/plans/{id}/offcuts` (`cutting.plan.update` + `inventory.stock.read`, Idempotency-Key). |
| Web `features/cutting/offcuts.tsx` | "Offcuts to use first" on the plan: chosen lots with honest badges (used / not used in the layout, no longer on hand, no matching group), "Choose offcuts" (only with `update` and stock read) listing candidates with warehouse/bin, match and "also chosen for"; saving keeps the tick order. Results: "From offcuts" metric (n standard sheets), board picker "Board n · offcut LOT", note on an offcut board. |

### Sample lineage
| Where | What |
|---|---|
| `sales/sample_lineage.py` | `link_challan` (`POST /api/v1/sales/samples/{id}/challan`, `sales.sample.update` + `challans.challan.read`): while `requested`, link or unlink the delivery challan that will carry the sample; the challan must be visible (404 otherwise), of the sample's customer (`challan_of_other_party`), `sample`/`outward` (`challan_not_outbound`) and not cancelled (`challan_cancelled`); dispatched samples are fixed (409 `sample_not_requested`); linking an issued/closed challan dispatches at the challan's issue time. `dispatch_linked_samples`: **resolves the open item "`challans.challan.issued` carries `sample_id = null`" from the sales side** — the `sales.sample_dispatch` subscription now dispatches every requested sample linked to the issued challan (the explicit `sample_id` path is kept). `lineage` (`GET /api/v1/sales/samples/{id}/lineage`): custom product, spec revision, quote, challan, catalogue product (own or promoted), sibling samples of the custom product, dated timeline in lifecycle order, `missing` links; each record through its own module's scope, `not_visible` without identity otherwise. |
| `sales/samples.py` | the manual `dispatch` with a `challan_id` gets the same challan checks (it accepted any existing id before); `capabilities.link_challan`; `dispatch_by_challan(at=)`. |
| Web `features/samples/lineage.tsx` | "Lineage" section on the sample (links, "Linked, but outside what you can see", "Not linked yet", siblings, timeline) and the challan link dialog (draft/issued sample or outward challans of the customer the viewer can see; unlink), capability-driven. |

### What-if views
`features/production/what-if.tsx` at `/operations/production/what-if` (route `operations-production-what-if`, tab
"What-if" shown only with `production.simulation.run`; the screen shows the permission state otherwise): up to five
checks (approved-BOM product, quantity, need-by, warehouse), stock changes (catalogue product search, warehouse, ± delta)
and capacity changes (work centre, machine count, extra minutes per day) → `POST /api/v1/production/simulations`.
Results side by side ("Today" / "With the change") with the server's read-only label, "The answer changes" / "Same
answer", and a note when the form no longer matches the shown run. Results are cached per request body
(`queryKeys.production.simulation(body)`); the server's `read_only` guard is unchanged.

House style: routes manifest entry, query keys (`production.simulation`, `cutting.offcutCandidates`,
`sales.sampleLineage`, `sales.sampleChallans`), copy in `messages/production.ts`, `features/cutting/messages.ts`,
`messages/commercial.ts`; capability-driven controls; loading / error / empty / forbidden states; new endpoints use the
typed client from the regenerated `schema.d.ts`.

## Migration
`backend/migrations/versions/0090_capabilities_slice5.py` — **placeholder number** `revision = "0090"`,
`down_revision = "0025"` (this branch's head, the Slice-4 integrator's renumbered chain). Creates `cutting_plan_offcut`
(forced RLS, unique (plan, lot) and (plan, seq), CHECKs), adds `fk_cutting_calc_board_lot_id_inventory_lot` and
`ck_cutting_calc_board_offcut_has_lot` (the column existed since Slice 2 and was always null). Downgrade drops them;
upgrade → downgrade → upgrade was run on `lk_wt6`. Sample lineage and what-if need no schema change.

## Events
No new event names or payload fields. Emitted as before: `cutting.plan.saved` (offcut choice changed),
`cutting.plan.calculated`, `cutting.plan.released`, `sales.sample.dispatched {sample_id, challan_id}` (now also for
samples linked to an issued challan), stock postings' own `inventory.stock.posted` for the offcut issue (source
`work_order`, purpose `issue`). Consumed: `challans.challan.issued` → `sales.sample_dispatch` (handler extended, key
unchanged). New audit actions: `cutting.plan.offcuts_changed`, `sales.sample.challan_linked`, `sales.sample.challan_unlinked`.

## keys.py requests
None (tests create their own lots, plans and challans).

## Tests
| Brief item | Test | Result |
|---|---|---|
| Packer offcut reuse | `tests/unit/cutting/test_offcut_reuse.py` (7: offcuts first, unused not reported + overflow, other decor/thickness ignored, grain-locked orientation, hashes + no oversize on offcuts, duplicate refs, hypothesis invariants) | pass |
| Offcut reuse end to end | `tests/integration/production/test_offcut_reuse.py::test_plan_cuts_from_an_offcut_and_release_issues_it_to_wip` (candidate, pinned turned size, stale, offcut board + lot, requirement 2, release issues the lot to WIP, reserves 1 sheet, lot gone from candidates, ledger consistent) | pass |
| Double claim | `::test_a_lot_taken_by_another_work_order_refuses_the_release` (409 `offcut_unavailable`, WO stays draft, plan stays calculated, `on_hand: false`) | pass |
| Selection validation / replay | `::test_selection_validation_and_replay` | pass |
| IDOR (offcuts) | `::test_offcut_scope_warehouses_plans_and_permissions` (invisible-warehouse lot never offered and the same 422 when named; Neha 404 on Meera's plan for candidates and selection; finance refused; no stock read → empty + 403) | pass |
| Sample lineage | `tests/integration/sales/test_sample_lineage.py::test_linked_challan_issue_dispatches_and_lineage_shows_every_link`, `::test_linking_an_issued_challan_dispatches_at_its_issue_time_and_unlink_while_requested` | pass |
| IDOR (samples) | `::test_challan_checks_on_link_and_on_manual_dispatch` (other party / inward / cancelled 422; another owner's challan and a random id 404; manual dispatch checked; Neha 404), `::test_lineage_hides_records_outside_the_actors_scope` (`not_visible` without identity; management sees it) | pass |
| Contract | `tests/contract/cutting/test_lane_schema.py` (table count 12 → 13; RLS/append-only flags), route permission declarations covered by the existing contract tests | pass |
| Web | `features/production/what-if.test.tsx` (4), `features/cutting/offcuts.test.tsx` (3), `features/samples/lineage.test.tsx` (2); routes and design-lint tests | pass |

PARITY rows for the integrator: **OQ-03** (offcut reuse S5 part) → `test_offcut_reuse.py::test_plan_cuts_from_an_offcut_and_release_issues_it_to_wip`;
**LP-09.6** (measured offcuts, S5 part) → the same + `tests/unit/cutting/test_offcut_reuse.py::test_layouts_on_offcuts_keep_the_invariants`;
**REUSE-05** (persisted against production orders, offcut part) → `::test_a_lot_taken_by_another_work_order_refuses_the_release`;
**LP-08.5** (sample/spec history; lineage) → `test_sample_lineage.py::test_linked_challan_issue_dispatches_and_lineage_shows_every_link`;
BUILD_STATE §10/§13 open item "`challans.challan.issued` carries `sample_id = null`" → resolved from the sales side
by the same test. The what-if views have no PARITY_MATRIX row (PLAN Slice 5 "New capabilities" only); if the integrator adds one, point
it at vitest `features/production/what-if.test.tsx` and the production lane's API test
`tests/integration/production/test_costing_feasibility.py::test_feasibility_and_simulation_write_nothing`.

## Integrator requests
1. Renumber `0090_capabilities_slice5.py` into the Slice-5 chain (needs 0013 cutting and 0022 `inventory_lot`).
2. `docs/architecture/events.md`: `sales.sample_dispatch` also dispatches samples linked to the issued challan
   (`sales_sample.challan_id`); the challans payload's `sample_id` can stay null.
3. PARITY_MATRIX: move the rows above; BUILD_STATE: close the `sample_id = null` item.
4. e2e: no spec was written (see Not done). When the e2e seed reaches Slice 4 (production request 10), a journey:
   Deepa records an offcut on WO-2026-0001, a second plan chooses it, releasing its WO issues it; Meera links a sample
   challan and Ravi issues it; Deepa runs a what-if with +8 walnut sheets. Add `/operations/production/what-if` to the
   axe sweep.
5. Agent tools over these reads (`simulate_what_if`, sample lineage reader) are not in this brief.
6. The production work-order screen lists the offcut issue as an ordinary issue transaction (lot code shown); a
   dedicated "offcut reused" label is a small follow-up in `features/production`.

## Concerns / decisions
1. **Offcut lots are issued at release, not reserved**: offcut lots never count as available stock, so the inventory
   reservation model cannot hold them; issuing them to the work order's WIP when the plan is released is the claim.
   Two plans may choose the same lot; the second release is refused (409) and the planner recalculates.
2. **No edge margin on offcut boards** (measured saw edges) and the gap/kerf applies as on sheets.
3. **Offcut lots must be of the product of the sheet material the plan backs** (409 otherwise); a plan with several
   decor groups still backs one material (production's existing rule).
4. The manual sample `dispatch` naming a `challan_id` now validates the challan (scope, party, type, status) — a
   behaviour tightening; no existing test or screen sent a challan id that would now fail.
5. Production-module files were edited (`wip.py`, `work_orders.py`) for the release hook; outside the brief's
   "append-only in inventory and cutting" wording but needed for consumption; additive only.

## Not done (with reasons)
- **e2e**: no Playwright spec; the e2e world seeds at Slice 2 (`scripts/dev.mjs`), so it has no production world,
  offcut lots or Deepa (same blocker as the production lane's request 10).
- Saved what-if scenarios (results are never stored; the simulation is read-only by construction).
- Offcut reuse in the stateless `POST /cutting/calculate` (legacy parity endpoint; plans only).

## Gates (2026-11-05, worktree `D:\lk-wt\sales`, slot 6, one suite at a time)

| Gate | Command | Result |
|---|---|---|
| check | `npm run check -- --keep-going` (log `D:\lk-wt\capabilities-check.log`) | **7/7 PASS** at a8d525e: ruff, pytest unit + contract **713 passed**, alembic heads 1, api:check (`backend/openapi.json matches the app`), web lint, typecheck, vitest **66 files / 694 tests**. The first run (at 6ef4f3d) failed ruff only (I001 import order in `test_sample_lineage.py`), fixed in a8d525e. |
| API suite | `npm run test:api` (log `D:\lk-wt\capabilities-testapi.log`, written only there) | **1703 passed, 7 skipped, 0 failed**, 2 warnings (Gemini adapter deprecation, PIL decompression-bomb test) — log tail: `1703 passed, 7 skipped, 2 warnings in 4567.17s (1:16:07)`, `exit=0` |
| API generate | `npm run api:generate` | committed in 1917c92 (`backend/openapi.json` 403 paths, `apps/web/src/lib/api/schema.d.ts`); `api:check` matches |
| Migration round trip | alembic downgrade 0025 → upgrade head on `lk_wt6` | ok |
| e2e | — | **not run**: no spec; the e2e world seeds at Slice 2 (no production world, offcut lots or Deepa) — integrator request 4 |

Concern 4 (manual dispatch now validates the challan) is covered by the full API suite above: no existing test regressed.
