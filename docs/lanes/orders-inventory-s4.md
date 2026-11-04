# Lane report: Slice 4 — sales orders and inventory (`lane/s4-orders-inventory`)

Worktree `D:\lk-wt\identity`, env slot 1, branched from the Slice-3 stage-1 tip `74c8cd5` (owner-sanctioned early
start; the brief says "from main after the Slice-3 checkpoint"). Never pushed. Scope: PLAN Slice 4 orders, inventory
and the challan movement policy; exit = scenario I (barrier test without oversell, one posting per challan, replay
safety, ledger property tests).

## What was built

### Backend — `backend/app/modules/inventory/`
| File | What |
|---|---|
| `models.py`, `enums.py` | warehouses; locations (per warehouse STOCK/QC/REJ + bins; company virtual locations supplier, customer, production, scrap, adjustment, opening, sample consumption; in-transit; one external holding per party; one office location per branch); lots (with measured dimensions); the ledger `inventory_stock_posting` + `inventory_stock_movement` (append-only trigger, UNIQUE(company, source_type, source_id, purpose), UNIQUE(company, idempotency_key), UNIQUE(reverses_posting_id)); projections `inventory_stock_balance` (UNIQUE NULLS NOT DISTINCT key, CHECK non-negative when stock-bearing) and `inventory_stock_summary` (available on hand / reserved, CHECKs ≥ 0); reservations; `inventory_shortage_state`; reorder rules; pick lists, stock counts, adjustments, opening batches (+ lines), transfers (+ lines). SoD CHECKs: approver ≠ creator on adjustments and opening batches, approver ≠ submitter on counts |
| `posting.py` | **the only writer of balances and summaries** (contract-tested): `post_movement` (advisory lock on the source, replay returns the same posting, different payload → 409 `posting_conflict`, validation of products/lots/units/location pairs, lock order summaries → balances → reservations, `negative_stock` / `reserved_stock_conflict` never silent, reservation consumption, `inventory.stock.posted`), `reverse_posting` (swapped, at most once, `inventory.posting.reversed`), the `TRANSITION_MATRIX` |
| `reservations.py` | `reserve` (waits for the same summary row lock as posting; `partial` / `all_or_nothing`; `shortfall_detected` + `conflict_detected` naming every competing demand), `release` (summary before reservation), helpers |
| `shortages.py` | persisted shortage state per (product, warehouse) from registered **demand providers**, `caused_by` refs, detected/changed/resolved with versions (replays change nothing), the `inventory.shortage_refresh:<event>` consumer |
| `integrity.py` | `check()` (balances = Σ ledger, summaries = balances + active reservations, no negative stock-bearing balance) used by the nightly `inventory.projection_check` job (`inventory.projection.mismatch_detected`) and by the tests' `assert_ledger_consistent` |
| `documents.py`, `counts.py`, `picking.py` | warehouses/bins/lots/measure, reorder rules (suggested quantity), relocations, the reversal command (RA step-up; challan postings are corrected by cancelling the challan), adjustments, opening batches (RA to create; MFA + RA to approve; never the creator; refused where non-opening movements exist unless `late_opening`), transfers (dispatch → in transit → receive), stock counts (freeze with seq high-water mark, enter, add line, submit, approve posts `counted − snapshot`), pick lists (release, pick, short pick releases the rest, challan from the picked quantities; picking posts nothing) |
| `reads.py`, `commands.py`, `router.py` | stock by product × warehouse with totals, product position (bins, lots, external, in transit), availability, ledger browser, posting detail, reservations, shortages with cause labels, document lists; 45 routes under `/api/v1/inventory` |
| `policies.py` | warehouse scope: everything is visible through its warehouse's branch; `require_warehouse(uow, id, key)` 404/403; `require_warehouse_for` for keys granted per record owner (reserve) |
| `rules.py`, `readers.py` | briefing families `ops.shortages` (one issue per short product × warehouse, causes as members — root-cause grouping), `ops.picking`, `admin.stock_integrity`; completion checks `shortage_resolved`, `pick_list_picked`; readers `inventory.shortage`, `inventory.pick_list`, `inventory.warehouse` |
| `events.py`, `manifest.py`, `testsupport.py` | event names, sequences `PL-/SC-/ADJ-/OB-/TR-YYYY-NNNN` (yearly), setting `inventory_policy` (`challan_postings_enabled`, `default_warehouse_code`), subscriptions, job + schedule, seed `inventory.world` (order 60, slice 4), the e2e seam `POST /api/v1/_test/inventory/go-live` (test env only) |

### Backend — `backend/app/modules/orders/`
`models.py` (`orders_sales_order` with UNIQUE(company_id, source_quote_id), immutable number/quote; lines with a
generated `qty_remaining` and CHECKs; append-only status history), `service.py` (conversion, list/detail with
capabilities and `allowed_transitions`, logistics edits, confirm/hold/release/cancel table, line cancellation, reserve
and release, fulfilment hooks, challan from order, impact preview, the shortage demand provider), `router.py` (11
routes under `/api/v1/orders/sales-orders`), `policies.py` (own/team/branch/company; `ORDER_RESERVE_POLICY` evaluates
`inventory.stock.reserve` over the order), `readers.py` (`orders.sales_order`), `events.py` (`SO-YYYY-NNNN`).

### Challans (the movement-policy consumer; small edits outside `movement.py`, see Decisions 3)
`challans/movement.py`: `on_issue` (one posting per issue per the policy matrix, SO deliveries/returns in the same
transaction, lock order challan → SO lines → stock), `on_cancel_issued` (reversal posting with
`reverses_posting_id`, SO figures restored, RA step-up for `challans.challan.reverse`), `posting_blocker`
(capabilities), `link_order`. Hooks in `transitions.py` (`_issue`, `_cancel`), `service.issue_blockers`; new columns
`challans_challan.sales_order_id`, line `sales_order_line_id`, `lot_id` (+ `lot_id` on line create/update); FKs on the
warehouse ids; detail exposes `issue_posting_id`, `reversal_posting_id`, `sales_order_id`, line `is_non_stock`.

### Tasks (rule-family wiring)
`tasks/rules/consumer.py`: `SLICE4_TRIGGERS` (six events → lazily imported `app.modules.inventory.rules` functions),
`EVENT_FAMILIES` entries and staleness refs for `inventory.shortage` / `inventory.pick_list`.

### Web
| Route | Screen |
|---|---|
| `/sales/orders` | list (search, status in the URL, pagination, honest empty states) |
| `/sales/orders/[orderId]` | workspace: header, actions only from `allowed_transitions`/`capabilities` (confirm, reserve, create challan, create pick list, release, hold/release hold, cancel with reasons), totals locked to the accepted revision, lines (ordered/reserved/delivered/returned/cancelled/remaining, cancel remaining with reason), reservations, delivery documents, history |
| quote workspace | **Convert to order** on won quotes (idempotent), or "Open SO-…" when the order exists |
| `/operations/inventory` | stock by product × warehouse from the projections, totals facts, search/warehouse/short-only filters |
| `/operations/inventory/movements` | the ledger browser (source links, reversal badge) |
| `/operations/inventory/stock-takes`, `/[countId]` | list + new; freeze, enter counts, submit, approve (variance shown before approval) |
| `/operations/reservations` | reservations (release) and open shortages with their causes |
| `/operations/inventory/pick-lists/[id]`, `/adjustments/[id]`, `/opening/[id]`, `/transfers/[id]` | pick list (release, pick, challan) and document screens (submit/approve/reject/dispatch/receive with the second-person rule explained) |
Operations overview: inventory and reservations rows are links; copy updated. Routes in `src/lib/routes.ts`, query
keys `orders.*`/`inventory.*`, invalidation `inventory.changed`, copy in `src/messages/{orders,inventory}.ts`.

## Scenario I test table
| Step | Test | Result |
|---|---|---|
| Accept once (idempotent under concurrency + retry) | `tests/integration/orders/test_quote_conversion.py::test_concurrent_and_retried_conversion_creates_one_order` (committed DB, barrier, 2 threads + retry, EUR 5,760.0000) | pass |
| Won quote / scope / snapshot survives catalogue change | `test_quote_conversion.py::test_conversion_requires_won_quote_and_linked_party_and_snapshot_survives_catalogue_change` | pass |
| **No oversell (barrier)** | `tests/integration/inventory/test_reservation_concurrency.py::test_no_oversell_under_concurrency` (on-hand 10, 8 threads × 3 → 3+3+3+1, 5 shortfall events, ledger consistent) | pass |
| Reserve vs unreserved posting race | `test_reservation_concurrency.py::test_reserve_and_unreserved_posting_race_never_oversells` | pass |
| No silent negative / reserved stock protected | `tests/integration/inventory/test_posting_engine.py::test_no_silent_negative_stock_and_reserved_stock_conflict` (+ replay, reversal-once, validation tests) | pass |
| Ledger immutable | `tests/integration/inventory/test_ledger_immutability.py::test_update_delete_on_movements_and_postings_rejected_by_trigger` (4 cases) + negative-balance CHECK | pass |
| **Ledger property tests** | `tests/integration/inventory/test_ledger_stateful.py::test_ledger_machine` (`LedgerMachine`, hypothesis stateful, derandomized: inbound, outbound, relocation, approved loss, reserve, consume/release, reverse; invariant `integrity.check() == []`) | pass |
| **One posting per challan** | `tests/integration/challans/test_issue_return_cancel.py::test_issue_posts_exactly_one_movement` (same key replay, new key, re-delivered hook; on-hand once; SO delivered 100 / remaining 140) | pass |
| Partial return linked to the original line; job work company-owned | `test_issue_return_cancel.py::test_job_work_stays_company_owned_and_partial_return_reconciles` | pass |
| Cancellation is an auditable correction | `test_issue_return_cancel.py::test_cancel_issued_creates_reversal` (+ RA step-up, has_return_links) | pass |
| Legacy / pre-go-live challans never move stock | `test_issue_return_cancel.py::test_legacy_and_pre_go_live_challans_never_move_stock` | pass |
| **Replay safety** | `tests/integration/flows/test_duplicate_events.py::test_replayed_outbox_events_have_single_effect` (every relevant event re-delivered twice to every consumer: postings, reservations, order figures, shortage versions, issues, tasks unchanged) | pass |
| End to end | `tests/integration/flows/test_scenario_i_quote_to_return.py::test_end_to_end` | pass |
| Line cancellation | `tests/integration/orders/test_cancellation.py::test_line_cancellation_releases_reservation_and_is_audited` (+ `test_hold_cancel_and_transition_table`) | pass |
| Opening stock second person | `tests/integration/inventory/test_opening_batch.py::test_opening_requires_approval_by_other_user_and_legacy_challans_create_no_stock` | pass |
| Counts, adjustments, transfers, picking, shortages | `tests/integration/inventory/test_documents.py` (5 tests) | pass |
| Briefing families | `tests/integration/inventory/test_briefing_rules.py` (3 tests) | pass |
| IDOR matrix | `tests/integration/inventory/test_idor.py` (6 tests, see Security) | pass |
| Lane contracts | `tests/contract/inventory/test_lane_schema.py` (5 tests) | pass |
| UI path | `apps/web/e2e/scenarios/i-order-fulfilment.spec.ts` (convert once, confirm, reserve; challan from order cut to 100, issue = one movement, read-only, order 100/140, ledger, stock 500) | pass (desktop) |

## Security
- **Warehouse-scope IDOR fix (coordinator request).** Three order paths accepted a warehouse id without checking the
  actor's warehouse scope: `reserve_order` now calls `require_warehouse_for(uow, warehouse.id, "inventory.stock.reserve")`
  (branch/company reserve grants must cover the warehouse; own-scope grants — sales — are bounded by warehouse read
  visibility because warehouses have no owner and the order check covers the record), `update_order` with a
  `default_warehouse_id` and `create_challan_for_order` with a `warehouse_id` call `require_warehouse` (404 for an
  invisible warehouse). Swept the other entry points: the challan issue now refuses to post from (or transfer to) a
  warehouse its issuer cannot see (404); pick lists, counts, adjustments, opening batches, transfers, relocations,
  reorder rules, reservations release, availability and the ledger browser already went through `require_warehouse`
  or the visible-warehouse filter; no agent tools were added. Named tests in `test_idor.py`:
  `test_reserve_against_another_branch_warehouse_is_not_found`, `test_setting_another_branch_warehouse_as_order_default_is_not_found`,
  `test_order_challan_from_another_branch_warehouse_is_not_found`, `test_issuing_a_challan_from_another_branch_warehouse_is_not_found`,
  plus the route matrix (`test_inventory_documents_and_stock_of_an_invisible_warehouse`, `test_orders_are_scoped_by_owner_and_branch`).
- Step-up: opening batch create RA, approve MFA + RA; posting reversal RA; challan cancel of a posting challan RA;
  inward company-owned receipts `inventory.stock.receive` RA. Separation of duties is enforced in services and CHECKs.
- Every route declares a catalogued permission (contract test); the route matrix test still proves 401 without a session.

## Decisions (for the integrator / DECISIONS.md)
1. **Table names follow conventions.md** (`inventory_stock_summary`, not the brief's `inv_stock_level`).
2. **Go-live switch**: `inventory_policy.challan_postings_enabled` (default false). Before go-live, and for
   `migration`/`import`-origin challans, the effect stays `none`. The demo seed turns it on after the opening batch.
3. **Challans edits beyond `movement.py`** were unavoidable and minimal: the issue/cancel hooks, the issue blocker,
   three columns (`sales_order_id`, `sales_order_line_id`, `lot_id`), FKs on the warehouse ids, additive read fields.
4. **Transfer challans** post one movement W(A) → W(B) STOCK (or the office location); the two-step in-transit
   transfer is the inventory transfer document. **Returns** go to QC hold for QC-required products, else STOCK.
5. **Returns on orders** are recorded as `qty_returned` with credit disposition: they do not reopen the remaining
   quantity (replacement = a new order). `qty_reserved` is derived from active reservations, not stored.
6. **Approvals** for adjustments, counts and opening batches are direct document actions with SoD in service and
   CHECK, not the proposals engine (ADR-014 lists them as ApprovalTargets; integrating them is a follow-up).
7. **Approved loss/count postings** may eat into reservations; holders get `shortfall_detected` (+ `conflict_detected`).
8. **Shortage demand** = confirmed/held orders' unreserved stock-line remainder via a provider registry
   (`inventory.service.register_demand_provider`), so production/procurement add theirs without touching inventory.

## Public interface for the procurement/quality/logistics and production lanes
- `app.modules.inventory.service`: `post_movement(uow, PostingRequest(...))` / `PostingLine`, `reverse_posting`,
  `find_posting`, `movements_of`, `movements_by_source_line`, `reserve` / `release` / `release_for_demand` /
  `active_for_demand` / `reserved_by_demand` / `remaining`, `stock_quantity`, `summary_of`, `resolve_warehouse`,
  `default_warehouse`, `default_location`, `warehouse_location(uow, wh, LocationType.QC_HOLD)`, `holding_location`,
  `office_location`, `company_location(uow, LocationType.SUPPLIER|PRODUCTION|...)`, `challan_postings_enabled`,
  `register_demand_provider` (WO materials), `register_cause_provider` (late PO lines → `caused_by`),
  `register_pair_resolver(event_prefix, fn)` (make your events refresh shortages; also add them to
  `SHORTAGE_TRIGGERS`). Source types already enumerated: `goods_receipt`, `work_order`, `qc_inspection`; purposes
  `receive`, `consume`, `output`, `qc`, `write_off`. Demand type `wo_material` exists.
- `app.modules.orders.service`: `lock_lines`, `record_delivery`, `reverse_delivery`, `record_return`, `open_demand`,
  `order_for_quote`, `create_challan_for_order` (logistics dispatch issues the linked challan through the challan
  transition; never post directly).
- `app.modules.challans.movement`: `on_issue` is replay-safe (returns the existing posting), `link_order`.
- Events emitted (all from the frozen catalogue §3.10): `orders.sales_order.{created,confirmed,put_on_hold,completed,cancelled}`,
  `orders.sales_order_line.{cancelled,delivered}`, `inventory.stock.posted`, `inventory.posting.reversed`,
  `inventory.reservation.{created,released,shortfall_detected,conflict_detected}`, `inventory.shortage.{detected,changed,resolved}`,
  `inventory.adjustment.posted`, `inventory.stock_count.{frozen,posted}`, `inventory.opening_batch.posted`,
  `inventory.pick_list.{released,picked}`, `inventory.projection.mismatch_detected`, `inventory.lot.measured`.

## Integrator requests
1. Renumber `0040_orders_inventory_slice4.py` onto the chain after CP4 (revision `0040` → next; `down_revision` = the
   CP4 head). It also alters `challans_challan` / `challans_challan_line`.
2. `docs/architecture/events.md` §2/§4: handler keys are `inventory.shortage_refresh:<event>` (one per trigger, like
   `tasks.rules:<event>`); add families `ops.picking` and `admin.stock_integrity`; `ops.shortages` is live.
3. e2e: the world is seeded at `--slice 2`, so the scenario-I spec turns inventory on through the test seam. Decide
   whether `dev.mjs` seeds `--slice 4` after the other Slice-4 lanes merge (after go-live every issued challan in
   other specs posts stock; the four fixture products have opening stock, LK-WB-1800 needs a lot on the line).
4. PARITY_MATRIX: mark SCN-I1…I4, LP-10.5, LP-10.6, REUSE-06, GAP-10 implemented with the test names above
   (`test_ledger_stateful.py::LedgerMachine` runs as `test_ledger_machine`).
5. Sales: the state table comment says won → sent correction "is blocked while an active sales order exists" — not
   enforced yet; `orders.service.order_for_quote` is the check to call. [sales]
6. ADRs for Decisions 2–8.
7. The fixture `mgmt.decisions` item for the reservation conflict (fixtures.md §10, Sahil's fourth decision) is not
   built: `inventory.reservation.conflict_detected` is emitted with `demand_refs`; the family belongs with the
   briefings/management work.

## Not done (with reasons)
- Agent tools (`get_stock_availability`, `propose_stock_movement`, `propose_reservation`): not in this brief's
  deliverables; `propose_stock_movement` stays the agents runtime test's example of an uninstalled tool.
- Approvals through the proposals engine (Decision 6); valuation/costs on movements (future scope).
- Web: no create forms for adjustments, opening batches and transfers (API and detail screens exist; opening stock
  arrives through the seed / import path); count lines cannot be added from the UI (API exists).

## Gates (2026-11-04, worktree `D:\lk-wt\identity`, slot 1)

| Gate | Command | Result |
|---|---|---|
| API suite | `npm run test:api` | **1521 passed, 7 skipped, 0 failed** (1:00:27) |
| check | `npm run check -- --keep-going` | **7/7 PASS**: ruff, pytest unit + contract 638, alembic heads 1, api:check, web lint, typecheck, vitest 57 files / 636 tests |
| API generate | `npm run api:generate` | committed (`backend/openapi.json` 315 paths; `apps/web/src/lib/api/schema.d.ts`) |
| Demo seed | `lk seed demo --anchor-date 2026-10-12 --slice 4` on `lk_wt1` | ok (WH-MAIN, BIN A-12, OB-2026-0001 approved, go-live) |
| e2e (this lane's spec) | `LK_NEXT_BUILD_CPUS=2 NODE_OPTIONS=--max-old-space-size=2048 npm run test:e2e -- e2e/scenarios/i-order-fulfilment.spec.ts --workers=1` | **2 passed** (desktop), 4 skipped (tablet/phone: `onlyOnProjects("desktop")`) |

Not run here: the full e2e suite and the axe sweep for the new routes (the world is seeded at Slice 2; integrator
request 3). The slot's databases were dropped, recreated and migrated to this branch's head (`0040`) before testing.
