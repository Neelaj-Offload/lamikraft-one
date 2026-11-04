# Lane report: Slice 4 — procurement, quality and logistics (`lane/s4-procurement-logistics`)

Worktree `D:\lk-wt\work`, env slot 4, branched from the orders/inventory lane tip `d2942ac` (`lane/s4-orders-inventory`,
itself from the Slice-3 stage-1 tip `74c8cd5`), so goods receipts and QC decisions post stock through the real
`inventory.service.post_movement` — no local fake. Never pushed. The run was stopped once by the owner and resumed;
the backend was committed before the stop, the web part was finished after it.

## What was built

### Backend — `backend/app/modules/procurement/`
| File | What |
|---|---|
| `models.py`, `enums.py` | vendor items (versioned prices: a new price supersedes the active one), requisitions + lines, purchase orders + lines (generated `qty_outstanding`; CHECKs accepted + rejected ≤ received, billed ≤ accepted, cancelled ≤ ordered), goods receipts + lines, vendor bills + lines; SoD CHECKs (requisition decider ≠ requester/submitter, PO approver ≠ submitter) |
| `vendor_items.py` | create / supersede, history, `active_item` for PO price defaults |
| `requisitions.py` | `PR-YYYY-NNNN`; submit / approve / reject / cancel / close with separation of duties; convert to a draft PO (vendor price or entered price) |
| `purchase_orders.py` | `PO-YYYY-NNNN`; submit / approve / reject / issue / close / cancel (`received_cannot_cancel` after a receipt); per-line expected dates (`expected_date_changed`), line cancel; Decimal line amounts HALF_UP; detail with `capabilities` and `allowed_transitions`; read model `qty_receivable`, `qty_pending_qc`, `qty_billable` |
| `receiving.py` | `GRN-YYYY-NNNN`; partial receipts per line (over-receipt tolerance), one posting per receipt through the inventory posting service; QC-required products go to the warehouse's QC hold and request an inspection; lot codes for lot-tracked products; the inspection-decided handler updates accepted / rejected |
| `matching.py` | vendor bills: three-way match PO × GRN (accepted) × bill (`qty_mismatch`, `price_variance` with tolerance, `amount_mismatch`, `pending_qc`, `currency_mismatch`), `mismatch_detected`, `handed_off` (event only in Slice 4) |
| `jobs.py` | `procurement.po_overdue_sweep` every 300 s: `became_overdue` once per line, again after the date moves |
| `rules.py`, `readers.py`, `policies.py`, `service.py` | `ops.receipts` (receive tasks, PO overdue chase) family; completion checks; readers for PO / GRN; scope through the warehouse's branch and the record owner; late PO lines as `caused_by` of shortages (`register_cause_provider("procurement.late_supply")`), shortage refresh on supply events |
| `router.py` | 25 routes under `/api/v1/procurement` |

### Backend — `backend/app/modules/quality/`
Inspections (`QC-YYYY-NNNN`) requested by goods receipts and by production (`production.work_order` subject; the id
stays a plain column until production merges), plus stock already in QC hold (returns, holds by hand); decision with
checklist, accepted + rejected = inspected quantity (CHECK), reject reason code and a failed check or findings; one
posting per decision (QC → STOCK / bin, QC → REJ); `ops.qc` family; 4 routes under `/api/v1/quality`.

### Backend — `backend/app/modules/logistics/`
Packing lists (`packing.py`: cartons, inner packs, part cartons, CBM and net/gross weights in Decimal HALF_UP from the
catalogue packaging snapshot; incomplete / conflicting data flagged, never guessed; entered values need a reason;
`became_stale` on packaging or order changes via `logistics.packing_list_staleness`), shipments (`SH-YYYY-NNNN`,
cutoff in company time → `logistics.shipment.scheduled` → hard-due `ops.dispatch_cutoffs` task; `dispatch` issues the
linked draft challan through the challan transition — the one stock movement; issuing the challan directly sets the
shipment dispatched via `logistics.shipment_status`; delivery needs evidence; exceptions), tracking references,
container profiles, deterministic first-fit-decreasing load suggestions labelled "suggestion"; 16 routes under
`/api/v1/logistics`.

### Cross-module edits
`tasks/rules/consumer.py` (`SLICE4_TRIGGERS` entries for the three families). Seeds `procurement.world` (order 62) and
`logistics.world` (order 64), slice 4. No other module's files changed.

### Web
| Route | Screen |
|---|---|
| `/operations/purchasing/requisitions`, `/[requisitionId]` | list (status in the URL) + new requisition (warehouse, needed by, product lines); record: submit / approve / reject / cancel from capabilities, the second-person rule explained, convert to a PO (vendor picker, prices) |
| `/operations/purchasing/orders`, `/[poId]` | list (search, status, only overdue, pagination); record: transitions from capabilities (reason dialogs), lines with ordered / received / accepted / rejected / in QC / outstanding and late flags, move expected date, receive goods (lot code when lot-tracked, vendor challan), receipts, vendor bills (record, match again, hand to finance, exceptions listed) |
| `/operations/purchasing/receipts`, `/[grnId]` | list (only waiting for QC); record with per-line put-to location and the inspection link/status |
| `/operations/quality`, `/[inspectionId]` | inspections (waiting first; status in the URL); decision form: accept all / reject all, accepted + rejected must add up (exact BigInt arithmetic on decimal strings), checklist pass/fail/n.a., reject reason, findings; result view once decided; "waiting for someone with QC rights" when this person may not decide |
| `/operations/dispatch` | shipments ordered by cutoff (search, status), past-cutoff flag, plan a shipment (confirmed order picker, mode, transporter, cutoff date + optional HH:MM) |
| `/operations/dispatch/shipments/[shipmentId]` | transitions from capabilities (deliver with evidence, exception with code, cancel with reason), "link the challan before dispatch", link challan and packing list from the order's documents, tracking references |
| `/operations/dispatch/packing-lists`, `/[packingListId]` | list + create from an order; record: totals strip, lines with part-carton / estimate / fragile / missing-data flags, enter values with a reason, refresh / finalise / cancel, why finalise is blocked, load suggestion against a container profile |
| party record | **Vendor items** section on vendor parties (codes, lead times, prices, history, add / new price) — appended to `features/parties/party-detail.tsx` |
Operations overview: purchasing, quality and dispatch rows are links; copy updated. Routes in `src/lib/routes.ts`
(12 entries; `quality.` added to the Operations prefixes), query keys `procurement.*` / `quality.*` / `logistics.*`
(invalidated with `inventory.changed`), copy in `src/messages/{procurement,quality,logistics}.ts`, URL states in plain
`list-state.ts` modules. Unit tests: `src/features/procurement/procurement.test.tsx` (10).

Backend fixes found while building the screens (commit `659c0c2`): PO line `qty_billable` (the bill form must not do
client arithmetic) and a shipment `add_tracking_ref` capability.

## Migration
`backend/migrations/versions/0060_procurement_quality_logistics_slice4.py` — **placeholder** revision `0060`,
`down_revision = "0040"` (the orders/inventory placeholder). 15 tables, forced fail-closed RLS on every tenant table,
immutable document numbers, enums as varchar + CHECK (contract-tested). The brief named `0031_…`; 0060 follows the
program's placeholder ranges. The integrator renumbers it after 0040's new number.

## Events
All from the frozen catalogue §3.10: `procurement.requisition.{submitted,approved,rejected}`,
`procurement.purchase_order.{approved,issued,closed,cancelled,became_overdue}`,
`procurement.purchase_order_line.expected_date_changed`, `procurement.goods_receipt.posted`,
`procurement.vendor_bill.{mismatch_detected,handed_off}`, `quality.inspection.{requested,passed,failed}`,
`logistics.shipment.{scheduled,dispatched,delivered,exception_recorded}`, `logistics.packing_list.{finalised,became_stale}`.
Consumers: `inventory.shortage_refresh:<event>` for the supply events (plus `became_overdue`, so a newly late line
shows in `caused_by`), `tasks.rules:<event>` for the three families, `logistics.shipment_status` on
`challans.challan.issued`, `logistics.packing_list_staleness:<event>` on `catalogue.product.updated`,
`orders.sales_order_line.cancelled`, `orders.sales_order.cancelled`. Payloads carry ids, numbers and codes only.

## Tests (named)
| Area | Test | Result |
|---|---|---|
| Requisition → PO → partial GRN → QC → bill match → hand-off | `tests/integration/procurement/test_procure_to_pay.py::test_requisition_to_bill_handoff` | pass |
| Receipt replay posts once | `test_procure_to_pay.py::test_receipt_replay_posts_once` | pass |
| SoD + no cancel after receipt | `test_procure_to_pay.py::test_cancel_after_receipt_is_refused_and_po_approver_is_not_submitter` | pass |
| Overdue scheduling | `test_overdue_and_receipts.py::test_overdue_sweep_emits_once_and_again_after_the_date_moves`, `::test_fixture_po_and_expected_date_change`, `::test_receipts_family_receive_task_and_overdue_chase` | pass |
| QC family, late supply as shortage cause, replay | `test_quality_and_supply.py` (3 tests) | pass |
| Packing CBM / weights (Decimal, HALF_UP) | `tests/unit/logistics/test_packing_math.py` (3), `tests/integration/logistics/test_shipments_and_packing.py::test_packing_list_from_order_stale_and_finalise`, `::test_incomplete_lines_need_values_with_a_reason` | pass |
| Cutoff task in company time | `test_shipments_and_packing.py::test_shipment_cutoff_task_in_company_time` | pass |
| Dispatch posts once (shipment or challan) | `test_shipments_and_packing.py::test_dispatch_through_shipment_or_challan_posts_once` | pass |
| Load suggestions | `tests/unit/logistics/test_load_planner.py` (2), `test_shipments_and_packing.py::test_load_suggestion_for_a_packing_list` | pass |
| IDOR matrix (HTTP) | `tests/integration/procurement/test_idor.py` (7 tests: other-branch warehouses, invisible vendors, foreign lines and locations, bills, inspections, logistics by order owner/branch) | pass |
| Lane contracts | `tests/contract/procurement/test_lane_schema.py` (5: enum CHECKs, RLS + immutable numbers, events/consumers registered, stock only through the posting service, catalogued route permissions) | pass |
| Screens | `apps/web/src/features/procurement/procurement.test.tsx` (10) | pass |
| UI path | `apps/web/e2e/scenarios/p-procure-to-pay.spec.ts` (4 tests) | pass (desktop) |

## keys.py requests
None needed: the seeds use existing keys (`KAVERI`, `WALNUT_BOARD`, `WAREHOUSE_REFS.MAIN`, people). Suggested: add
`PO_KAVERI` (today a local ref in `seed/world/procurement.py`) to `keys.py` and publish `PO-2026-0001` in
`/_test/fixtures` facts when the e2e world moves to `--slice 4`.

## Integrator requests
1. Renumber `0060` onto the chain after the orders/inventory migration (`down_revision`).
2. `docs/architecture/events.md`: add `procurement.purchase_order.became_overdue` to the `inventory.shortage_refresh`
   consumers (done in code); handler keys `logistics.packing_list_staleness:<event>`.
3. e2e world: decide `--slice 4` for `dev.mjs` (with orders/inventory request 3). The procure-to-pay spec turns
   inventory on through the existing `_test/inventory/go-live` seam and creates its PO through the API.
4. PARITY_MATRIX: procurement / QC / logistics rows → the tests above.
5. Production lane: inspections with subject `production.work_order` keep `work_order_id` as a plain column — add the
   FK and the subject handler when production merges (`quality.service.register_subject_handler`).
6. Finance (Slice 5): `procurement.vendor_bill.handed_off` is the handoff; there is no AP document yet.
7. Merge conflicts to expect: `messages/areas.ts` (production lane edits the same Operations rows), `lib/routes.ts`,
   `lib/api/query-keys.ts`, `tasks/rules/consumer.py` `SLICE4_TRIGGERS`, `e2e/support/world.ts` (`PersonKey` gained
   `ANANYA`).
8. Shared-code finding (not this lane's file): `src/lib/design-lint.test.ts` "formats money and quantities without
   converting strings to floats" passes `(file) => !moneyCode.has(file)` as the *allow* predicate, so it only scans
   the money modules and checks nothing else. This lane's code compares decimals as strings, but other features use
   `Number(...)` on quantities; inverting the predicate will flag them.

## Concerns / not done
- Evidence files on delivery: the API accepts `evidence_file_id`, the UI records the evidence kind and a note only
  (no upload control yet).
- Container profiles have no management screen (API only; the load-suggestion panel says when none exists).
- Requisitions list has no pagination (status filter only); goods-receipt create is always "create and post" from
  the PO screen (draft receipts are API-only).
- Agent tools for purchasing / dispatch: not in this brief.

## Gates (2026-11-04, worktree `D:\lk-wt\work`, slot 4)
| Gate | Command | Result |
|---|---|---|
| check | `npm run check -- --keep-going` | **7/7 PASS**: ruff, pytest unit + contract 648, alembic heads 1, api:check, web lint, typecheck, vitest 58 files / 646 tests |
| API generate | `npm run api:generate` | committed (`backend/openapi.json` 350 paths; `schema.d.ts`) |
| API suite | `npm run test:api` | **1552 passed, 7 skipped, 0 failed** (1:10:09) |
| e2e (this lane's spec) | `LK_NEXT_BUILD_CPUS=2 NODE_OPTIONS=--max-old-space-size=2048 npm run test:e2e -- e2e/scenarios/p-procure-to-pay.spec.ts --workers=1` | **4 passed** (desktop: order + SoD, receipt into QC, inspection 18/2, vendor bill matched), 8 skipped (tablet/phone: `onlyOnProjects("desktop")`) |

The first e2e run passed the order and receipt tests and stopped at the inspection: number fields commit on blur, so
the spec now tabs out before reading the reject-reason control; the decision form also showed its blocked reason
twice (fixed). Not run here: the full e2e suite and the axe sweep over the new routes (the e2e world is seeded at
Slice 2; integrator request 3). Memory was tight (about 1.4 GB free with two other lanes building); the build ran
with the limits above. No servers or background processes were left running.
