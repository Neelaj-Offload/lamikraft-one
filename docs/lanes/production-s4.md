# Lane report: Slice 4 — production (`lane/s4-production`)

Worktree `D:\lk-wt\sales`, env slot 6, branched from `lane/s4-orders-inventory` d2942ac (Slice 2 with the cutting
optimiser and saved plans, the Slice-3 agent runtime and WhatsApp, and the finished orders/inventory lane). Never
pushed. Brief: `docs/superpowers/briefs/s4-production.md`. Migration placeholder `0070`, `down_revision = "0040"`.
The slot's databases (`lk_wt6`, `lk_wt6_test`) held the migration branch's chain; both were dropped, recreated,
migrated to this branch's head and the dev database reseeded with `lk seed demo --anchor-date 2026-10-12 --slice 4`
before testing (reseeding also reset Priya's TOTP on this slot).

## What was built

### Backend — `backend/app/modules/production/`
| File | What |
|---|---|
| `models.py`, `enums.py` | `production_work_center` (+ `production_capacity_exception`), versioned `production_bom` / `_bom_line` and `production_routing` / `_routing_operation` (CHECK `approved_by <> created_by`; partial unique index: one approved version per product), `production_work_order` (pinned BOM, routing and warehouse; blocked flag + `blocked_causes`), `production_wo_material` (the `wo_material` reservation demand), `production_wo_operation` (planned minutes, planned day, linked cut plan + calculation; a plan backs one operation), `production_wo_transaction` (append-only; its id is the posting source), `production_cost_rollup` (append-only, unique per input hash), `production_capacity_overload` (state per work centre and day) |
| `masters.py` | work centres (capacity per shift from workcal, protected hourly rate), capacity exceptions, BOM and routing versions: create / copy-from / update while draft, approve (author refused 403 `separation_of_duties`; validates units against the component's stock unit, alternates, BOM cycles through approved sub-BOMs, active work centres; retires the previous approved version), retire |
| `work_orders.py` | plan (standalone or from a visible order line; pins the approved versions; materials from the BOM's primary lines with scrap, integer units rounded up), update while draft, the table-driven `TRANSITIONS` (release / complete / close / cancel), release (cut plans must be ready → 409 `cut_plan_not_ready`; schedules operations; reserves every material through `inventory.reserve`; short → blocked with `caused_by` = the inventory shortage ids), `recheck`, the `production.material_retry` consumer (stock posted / posting reversed / reservation released → blocked work orders reserve again and unblock), the inventory demand provider and pair resolver |
| `wip.py` | issue (internal bin of the work order's warehouse → WIP, consuming reservations first), consume (WIP → production), return (WIP → stock, reserved again), output (production → stock or QC hold; lot from the WO number for lot-tracked products), operation completion and rescheduling, cut-plan link (sheet material requirement = the plan's boards, `requirement_source=cut_plan`), measured offcut lots; every event is one posting through `inventory.post_movement` |
| `capacity.py` | calendar minutes per work centre and day (shifts × machines × efficiency, holidays, exceptions), load from pending operations of released / in-progress work orders, overload state with `production.capacity.overloaded` once per transition, first-fit forward scheduling for feasibility |
| `costing.py` | deterministic rollups (recursive BOM explosion, costs of record, approved FX on or before the date, routing minutes × hourly rates, 4 dp HALF_UP lines), `missing_inputs`, input hash (same hash → stored result, `reused`), `production.cost_rollup.computed` |
| `feasibility.py` | read-only `assess` (stock, supply providers, components, capacity; `feasible` / `at_risk` / `not_feasible` / `estimate`), `assess_order_line`, `simulate` (overlay of stock deltas, machine counts, extra minutes; baseline vs scenario), the supply-provider registry for procurement |
| `common.py` | refs, business date, and `read_only(uow)`: a `before_flush` guard plus refused `emit` / `enqueue` / `audit` / `allocate_number` / `add`, so feasibility and what-if cannot write |
| `wo_reads.py`, `schemas.py`, `service.py`, `router.py` | read models (capabilities and allowed transitions decided by the server), 37 routes under `/api/v1/production` |
| `readers.py`, `rules.py` | readers `production.work_order`, `production.capacity_overload`; the `ops.production_dependencies` family: blocked work order (root) grouped with its shortage (evidence; same shortage id as `ops.shortages`), a task for the owner until unblocked; overloaded day with a reschedule task; incomplete rollup as an informational issue (no figures) |
| `policies.py`, `events.py`, `manifest.py` | scopes (§7.7), `WO-YYYY-NNNN`, subscriptions, completion checks `work_order_unblocked` / `capacity_not_overloaded`, seed `production.world` (order 65, slice 4) |

### Edits outside the module (small, additive)
- `inventory/locations.py` + `service.py`: `wip_location(uow, warehouse_id)` (per-warehouse `WIP`, created on first
  use), `record_measured_lot(...)` (create + measure in one step; emits `inventory.lot.measured`).
- `inventory/events.py`: `SHORTAGE_TRIGGERS` gains `production.work_order.{released,completed,closed,cancelled}`.
- `cutting/release.py` (new file): plan readiness, `release_for_work_order` (status `released`,
  `cutting.plan.released{plan_id, work_order_id}`), predicted offcuts of a calculation.
- `tasks/rules/consumer.py`: the production triggers in `SLICE4_TRIGGERS`; staleness ref for `production.work_order`.
- `seed/world/keys.py`, `identity.py`: persona **Deepa Menon** (`DEEPA`, template `production`, company, slice 4),
  production fixture keys; `seed/world/production.py`.
- Web: `features/orders/order-workspace.tsx` gains the feasibility panel; `messages/inventory.ts` names the
  `work_order` posting source; `messages/areas.ts` links production and capacity from the Operations overview
  (`features/challans/challans.test.tsx` asserts the overview copy, updated to name production).

### Web
| Route | Screen |
|---|---|
| `/operations/production/work-orders` | list (search, status and "blocked only" in the URL, paging) |
| `/operations/production/work-orders/new` | plan a work order for a product with an approved BOM |
| `/operations/production/work-orders/[workOrderId]` | header actions only from `allowed_transitions` / `capabilities`; blocked banner with the shortage cause and "Check materials again"; materials (required, reserved, issued, in WIP, consumed, free, cut-plan requirement); operations (complete, link cut plan, record offcut); stock postings; dialogs for issue (bin/lot from the stock position), consume, return, output, offcut (prefilled from predicted offcuts), cut plan, cancel with reason |
| `/operations/production/boms`, `/[bomId]` | versions; approve (hidden for the author with the separation-of-duties note), retire with reason, new version from this one; components; cost rollup card (partial label, missing inputs, figures only with `pricing.cost.read`) |
| `/operations/production/routings`, `/[routingId]` | versions and operations (board-cutting operation flagged) |
| `/operations/production/work-centres`, `/[workCenterId]` | standard day, calendar and shifts, rate (hidden without costing), capacity exceptions (set / remove) |
| `/operations/production/capacity` | per work centre per day: capacity, load, use, overloaded, work orders; `from`/`to` in the URL |
| sales order workspace | "Can we deliver this?" per open stock line (read-only evidence) |
Routes in `src/lib/routes.ts` (`requiredPermission: "production."`), query keys `production.*`, invalidation
`production.changed`, copy in `src/messages/production.ts`.

## Migration
`backend/migrations/versions/0070_production_slice4.py` — **placeholder number** `revision = "0070"`,
`down_revision = "0040"` (the orders/inventory lane's placeholder; the brief named `0032` on top of `main`'s head,
but this lane builds on `lane/s4-orders-inventory` and references its tables, so it sits after `0040`; the
integrator renumbers). Twelve tables: `production_work_center`, `production_capacity_exception`,
`production_capacity_overload`, `production_bom`, `production_bom_line`, `production_routing`,
`production_routing_operation`, `production_cost_rollup`, `production_work_order`, `production_wo_material`,
`production_wo_operation`, `production_wo_transaction`; company RLS policies on each; CHECKs (author ≠ approver,
positive quantities / versions / batch sizes, alternates never self); partial unique indexes (one approved BOM /
routing version per product; a cut plan backs one operation); append-only triggers on `production_cost_rollup` and
`production_wo_transaction`; `helpers.immutable_columns` on the work order's number and pinned
product / BOM / routing / warehouse, and on BOM / routing product + version. Downgrade drops everything. No columns
added to other modules' tables (offcut lots use the existing `inventory_lot` columns).

## Events
All names and fields are the frozen catalogue (`events.md` §3.10 and the cutting / inventory rows); payloads carry ids,
numbers, versions and status codes only.
- **Emitted (production)**: `production.bom.approved`, `production.routing.approved`,
  `production.work_order.{released,blocked,unblocked,completed,closed,cancelled}` (`work_order_id`, `wo_number`,
  `caused_by[{type, id}]`), `production.capacity.overloaded` (`work_center_id`, `date`; once per transition into
  overload), `production.cost_rollup.computed` (`rollup_id`, `product_id`, `status`; never figures).
- **Emitted on production's behalf by other modules**: `cutting.plan.released {plan_id, work_order_id}`
  (`cutting/release.py`), `inventory.lot.measured {lot_id, lot_kind}` (`inventory.record_measured_lot`); stock
  postings emit the inventory module's own `inventory.stock.posted` / reservation events.
- **Consumed**: `production.material_retry:<event>` on `inventory.stock.posted`, `inventory.posting.reversed`,
  `inventory.reservation.released` (blocked work orders reserve again; idempotent on replay);
  `inventory.shortage_refresh:<event>` gains the four `production.work_order.*` state events (pair resolver in the
  production manifest); `tasks.rules` (`ops.production_dependencies`) on the six work-order events,
  `production.capacity.overloaded` and `production.cost_rollup.computed`.

## Shared seed keys (`seed/world/keys.py`) — requests to the integrator
Added in this lane (additive; please keep the names when merging the procurement/logistics lane's keys):
- Persona `DEEPA` — Deepa Menon, template `production`, company scope, `slice_no=4`; `identity.PROVISION_ORDER`
  gains `DEEPA` before `ARJUN`.
- `PRODUCTION_PRODUCTS.WALNUT_PANEL_SET = "LK-WP-0001"` (+ `PRODUCTION_PRODUCT_NAMES`),
  `WORK_CENTERS.{PANEL_SAW,EDGE_BAND,ASSEMBLY}` (+ `WORK_CENTER_REFS` = `WC_*`),
  `WORK_ORDERS.PANEL_SETS = "WO-2026-0001"` (+ `WORK_ORDER_REFS`), `PRODUCTION_REFS.{BOM_PANEL_SET,ROUTING_PANEL_SET}`,
  `WALNUT_BOARD_COST = "2450.0000"`.
- Request: the procurement lane's PO keys (PO-2026-0001 for the walnut board) should be the late supply that
  fixtures.md §8 names as WO-2026-0001's root cause (integrator request 6); `fixtures.md` §8/§10 add Deepa.

## Cut-plan links and offcut lots (for the Slice-5 "offcut reuse" follow-up)
- A work order's board-cutting operation links one cutting plan (`production_wo_operation.cut_plan_id` +
  `cut_calculation_id` pinned at link time; a plan backs one operation only). The chosen sheet material then requires
  the plan's boards (sum of `cutting_calc_group.boards` of the linked calculation). Releasing the work order (or
  linking to an already released one) releases the plan: `cutting_plan.status = 'released'` and
  `cutting.plan.released {plan_id, work_order_id}`. A stale, recalculated or unverified (oversize) plan refuses the
  release (409 `cut_plan_not_ready` / `cut_plan_recalculated`).
- **Offcut lots**: `POST /api/v1/production/work-orders/{id}/offcuts` creates an `inventory_lot` with
  **`lot_kind = 'offcut'`**, `lot_code` `WO-YYYY-NNNN-OCnn` (or given), the sheet component as `product_id`,
  `parent_lot_id` = the board lot it came from (optional), and the **measured** `length_mm`, `width_mm`,
  `thickness_mm` (NUMERIC 12,3 / 8,3), `grain_axis` (`length` | `width` | `none`), `verification_status = 'verified'`,
  `measured_by/at`; it emits `inventory.lot.measured {lot_id, lot_kind: "offcut"}` and posts 1 unit (the component's
  stock unit) production → the warehouse's stock location as a `work_order` posting (purpose `output`, transaction kind
  `offcut`, the transaction's `lines[0].offcut` keeps the measured size and the predicted offcut id it confirms).
  Offcut lots never count as available (`posting._counts_available`), so the optimiser's reuse must read them
  explicitly: lots of kind `offcut` with a positive stock-bearing balance and measured dimensions.

## Test table
| Brief item | Test | Result |
|---|---|---|
| BOM/routing approval separation of duties | `tests/integration/production/test_masters.py::test_bom_approval_separation_of_duties_and_immutability`, `::test_database_rejects_an_author_approving_their_own_version`, `::test_one_approved_version_per_product_in_the_database`, `::test_routing_approval_separation_and_retirement`, `::test_bom_cycle_and_bad_alternate_rejected_at_approval` | pass |
| Release blocks on shortage and unblocks on receipt (events) | `test_work_orders.py::test_release_blocks_on_shortage_and_unblocks_on_receipt` (seeded WO-2026-0001 blocked 40/48; briefing issue with the shortage; a supplier → stock posting of 8 sheets unblocks it through the consumer; replaying every stock event changes nothing) | pass |
| Issue / consume / complete postings reconcile with the ledger | `test_work_orders.py::test_issue_consume_return_output_reconcile_with_the_ledger` (one posting per event, each the source of exactly one transaction; WIP balance 0; stock and output figures; `assert_ledger_consistent`), `::test_close_refuses_material_left_in_wip_and_cancel_refuses_postings`, `::test_transition_table`, `::test_invalid_transition_is_a_conflict`, `::test_plan_from_an_order_line_reserves_through_inventory_and_releases_on_cancel` | pass |
| Rollup determinism and missing-input flags | `test_costing_feasibility.py::test_rollup_is_deterministic_and_lists_missing_inputs` (INR 14,700 + 960 + 600 = 16,260 incomplete; same inputs reused; a new rate → complete 16,660; events carry no figures; informational issue), `::test_missing_cost_of_record_and_fx_are_listed_not_borrowed` | pass |
| Feasibility evidence | `::test_feasibility_evidence_from_stock_components_and_capacity`, `::test_order_line_feasibility_follows_order_visibility`; unit `tests/unit/production/test_capacity_math.py` (4) | pass |
| What-if / feasibility never write | `::test_feasibility_and_simulation_write_nothing` (row counts of postings, movements, reservations, events, audit, rollups unchanged; the guard raises on a flush, an add and an emit) | pass |
| Redaction canary for cost figures | `::test_cost_redaction_canary` (operations sees status and missing inputs, never figures; `for_model` strips them even for production; readers carry no money), contract `test_lane_schema.py::test_cost_figures_are_guarded_and_never_model_exposed`, HTTP replay + redaction in `test_idor.py` | pass |
| Cut-plan links, offcut lots, capacity | `test_cut_plans_capacity.py` (4: link + release + `cutting.plan.released`, stale plan refuses release, offcut lot measured/posted/not available, load/overload once/exceptions/rescheduling/non-working day + briefing issue) | pass |
| IDOR matrix | `test_idor.py` (11, see Security) | pass |
| Lane contracts | `tests/contract/production/test_lane_schema.py` (5) | pass |
| Web | `apps/web/src/features/production/production.test.tsx` (6) | pass |

## Security
Every entry point that takes a warehouse, location, work-order, material, operation, order-line or cut-plan id
enforces scope, with named tests in `tests/integration/production/test_idor.py`:
- `test_work_order_of_another_branch_is_not_found_on_every_path` — 12 paths (get, patch, transitions, recheck, issue,
  consume, return, output, operation complete / schedule / cut-plan, offcuts) are 404 for operations scoped to HO;
  the list and the number lookup do not reveal it.
- `test_creating_a_work_order_in_an_invisible_warehouse_is_not_found` — 404 (`require_warehouse`).
- `test_posting_against_an_invisible_warehouse_is_not_found_and_without_post_forbidden` — the warehouse scope
  (`inventory.stock.post` over the WO's warehouse) is checked **before** the work order's state rule, so a
  readable work order in an invisible warehouse is 404; management (reads WOs, no post) is 403.
- `test_releasing_a_work_order_whose_warehouse_is_invisible_is_not_found` — release needs
  `require_warehouse_for(..., "inventory.stock.reserve")`.
- `test_issuing_from_a_location_of_another_warehouse_is_rejected` — 422 `location_not_in_warehouse` (same answer
  for an unknown location: never confirms another warehouse's bin).
- `test_foreign_material_and_operation_ids_are_refused` — 422 `material_not_found` / 404.
- `test_planning_from_an_invisible_order_line_is_not_found` — the line's order must be visible (or 404, also for a
  random id).
- `test_linking_an_invisible_cut_plan_is_not_found` — the plan through the cutting resource policy (404).
- `test_feasibility_for_an_invisible_warehouse_or_order_line_is_not_found` — feasibility, order-line feasibility
  and simulation stock changes.
- `test_unknown_permission_holders_are_forbidden`, `test_idempotent_issue_replay_and_cost_redaction_over_http`.
Offcut recording also needs `inventory.lot.manage` over the warehouse. Every route declares a catalogued permission
(contract test); no agent tools were added.

## Decisions (for the integrator / DECISIONS.md)
1. **One posting per stock event** via a transaction row whose id is the posting source
   (`source_type="work_order"`, `source_id=<transaction id>`, purposes `issue|consume|return|output`), because a work
   order has many issues and UNIQUE(company, source_type, source_id, purpose) allows one per source. The ledger
   browser shows the label `WO-… issue`; it has no link for `work_order` sources yet (integrator request 4).
2. **WIP is a per-warehouse location** (`WIP`, type `wip`, stock-bearing, not available), created on first use by
   `inventory.wip_location`. Lot accounting inside WIP is per work order from its own transactions.
3. **Blocked is a flag on released / in-progress work orders**, not a status (the frozen events name
   `blocked`/`unblocked`, and the WO can still be worked on with the reserved part). `caused_by` names the
   `inventory.shortage` ids (the same refs `ops.shortages` groups by).
4. **Returned material is reserved again** until the work order completes; completion releases what was never
   issued. Cancel is refused once output or consumption was posted (complete and close instead).
5. **Cost inputs**: costs of record (`pricing_product_cost`, latest effective on the date) and the work centre's
   hourly rate (a guarded field). `production.cost_version.manage` and separate cost versions are not used: the
   pricing cost versions and the input hash give determinism. Rollups read approved versions as they are now (the
   as-of date selects costs of record and FX rates).
6. **Overload state** is persisted per (work centre, day) so a day emits `production.capacity.overloaded` once per
   transition into overload; resolution has no event (the task's completion check reads the state).
7. **Feasibility supply** comes from a provider registry (`production.service.register_supply_provider`): with no
   provider registered (procurement not merged), a short purchased component makes the result an `estimate` with
   `lead_time:<product>` missing — never a guess.
8. **One approved version per product**; approving a new one retires the previous (work orders keep their pinned
   versions).

## Integrator requests
1. Renumber `0070_production_slice4.py` after the orders/inventory (0040 → …) and procurement (0060+) revisions; it
   references `inventory_*`, `orders_*` and `cutting_*` tables.
2. Procurement lane: register open purchase-order lines as feasibility supply in its manifest `on_load`:
   `production.service.register_supply_provider("procurement.purchase_order_line", fn)` returning
   `production.service.Supply(ref_type, ref_id, label, quantity, expected_date, lead_time_source)` per (product,
   warehouse). Its goods receipts post `inventory.stock.posted`, which already unblocks waiting work orders.
3. `docs/architecture/events.md`: add handler key `production.material_retry` (§2) and the production triggers of
   `inventory.shortage_refresh`; `ops.production_dependencies` is live (§4).
4. `inventory.reads.SOURCE_PATHS`: a `work_order` source is a transaction id; link it once a `/go` resolver or a
   transaction route exists.
5. `inventory.rules.derive_shortage` lists only sales-order causes as members; add `production.wo_material` causes
   (resolve material → work order) so the shortage issue names the blocked work order too.
6. Fixture: WO-2026-0001 is blocked by the shortage as fixtures.md §8 says; its root cause becomes the late PO line
   once procurement seeds PO-2026-0001 (cause provider). fixtures.md §8/§10 need Deepa (`DEEPA`, production) added.
7. PARITY_MATRIX: production rows (BOM/routing/WO/capacity/cost/feasibility/what-if) → the tests above.
8. ADRs for Decisions 1–8.
9. Stray file: this worktree held an **ignored** `apps/web/src/app/(app)/settings/backups/page.tsx` from the
   migration lane's earlier use of slot 6 (`.gitignore` line `backups/` matches it, so that lane's page may be
   uncommitted). It broke this lane's typecheck and was moved to the scratchpad; check the migration branch.
10. e2e: raise the e2e seed (`scripts/dev.mjs`, `--slice 2`) to Slice 4 or add a production test seam, then add a
    production journey (Deepa: WO-2026-0001 blocked → receipt unblocks → issue / consume / output; BOM approval by
    a second person; capacity overload) and the new `/operations/production/**` routes to the axe sweep.
11. Seed keys: merge `seed/world/keys.py` additions (see "Shared seed keys") with the procurement/logistics lane's.

## Not done (with reasons)
- Agent tools (`assess_delivery`, `simulate_what_if`): not in this brief's deliverables.
- Job-work operations through challans (external holding consumption): design §6 mentions it; the routing flag
  `is_job_work` is stored, the challan receipt path is not built.
- QC rejects of production output into rework WOs: quality belongs to the procurement/quality lane
  (`quality.inspection.*`); output of a QC-required product lands in QC hold.
- Web forms to author BOM lines and routing operations (the API supports create / update / copy; the seed and
  "new version from this one" cover the demo) and to create work centres.
- Saved feasibility checks and simulations (results are never stored; read-only by construction).
- **e2e for the production screens**: no Playwright spec was written or run. The brief lists no production
  scenario (PLAN Slice 4's exit is scenario I, run by the orders/inventory lane), and the e2e world is seeded at
  Slice 2 (`scripts/dev.mjs`: `lk seed demo --slice 2`), so it holds no work centres, BOMs, work orders or the
  `DEEPA` persona; a spec would need the e2e seed raised to Slice 4 or a production test seam (integrator request 10).
  The screens are covered by `production.test.tsx` (vitest) and the API by the integration suite.

## Gates (2026-11-04, worktree `D:\lk-wt\sales`, slot 6, at f3cb604)

| Gate | Command | Result |
|---|---|---|
| Production suite | `cd backend && uv run --locked pytest tests/integration/production -q` | **33 passed** |
| check | `npm run check -- --keep-going` | **7/7 PASS**: ruff, pytest unit + contract 647, alembic heads 1, api:check, web lint, typecheck, vitest 58 files / 642 tests (the first run failed 1 vitest: `challans.test.tsx` asserted the old Operations overview copy; fixed in f3cb604) |
| API suite | `npm run test:api` | **1563 passed, 7 skipped, 0 failed** (1:13:02) |
| API generate | `npm run api:generate` | committed in 126c54c (`backend/openapi.json`, `apps/web/src/lib/api/schema.d.ts`); `api:check` matches |
| Demo seed | `lk seed demo --anchor-date 2026-10-12 --slice 4` on `lk_wt6` | ok (run by the earlier session before testing, see the header; not rerun here) |
| e2e | — | not run: no production spec; the e2e world seeds at Slice 2 (see "Not done", integrator request 10) |
