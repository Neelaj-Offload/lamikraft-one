# Lane report: Slice-4 merge (integrator)

Branch `lane/s4-merge` (from `main` 1ed0027 = Checkpoint 4), worktree `D:\lk-wt\integ`, env slot 8. Merges the three
wave-4a lanes in dependency order and declares Checkpoint 5. Never pushed; `main` is not fast-forwarded here.

**Status: DONE_WITH_CONCERNS** — Checkpoint 5; every gate green on the final tree; concerns under "Open items".

## Steps

| # | Step | Commit | Result |
|---|---|---|---|
| 1 | Merge `lane/s4-orders-inventory` d2942ac (report `orders-inventory-s4.md`, branched from CP4a 74c8cd5) | `76bc019` | migration 0040 → `0022_orders_inventory_slice4` (down 0021); no conflicts; api:generate 333 paths (identical to the auto-merge); `test:api` **1612 passed, 7 skipped, 0 failed** (54.6 min) |
| 2 | Merge `lane/s4-production` 27f3697 (report `production-s4.md`, from d2942ac) + requests 3, 5 | `6505e56` | migration 0070 → `0023_production_slice4` (down 0022); no conflicts; api:generate 364 paths; web typecheck; `test:api` **1654 passed, 7 skipped, 0 failed** (56.4 min) |
| 3 | Merge `lane/s4-procurement-logistics` 1c590ce (report `procurement-logistics-s4.md`, from d2942ac) + cross-lane requests | `c4210a3` | migration 0060 → `0024_procurement_quality_logistics_slice4` (down 0023); new `0025_slice4_cross_lane_links`; 5 conflicts (below); api:generate 399 paths; lint, typecheck, vitest 63 files / 685; `test:api` **1688 passed, 7 skipped, 0 failed** (53.9 min) |
| 4 | e2e world at `--slice 4`; production journey spec; axe sweep fills Slice-4 records; CP5 evidence spec | `81b2d14` | check 7/7 on this tree (unit + contract 706, vitest 685) |
| 5 | e2e run 1 → fixes | `1ec051c` | 266 passed / 6 failed (defects 1–3 below) |
| 6 | e2e run 2 → fix | `036096e` | 268 / 3 (defect 4) |
| 7 | e2e run 3 → fix | `2a4d0ad` | 272 / 2 (defect 5; `j-voice interrupt_stops_speech` timed out once with about 1.4 GB free while two other lanes built; it passed in runs 1–2 and in the targeted rerun) |
| 8 | Targeted e2e on `2a4d0ad` (fresh build) | — | production journey, j-voice, scenario I, procure-to-pay: **18 passed, 0 failed** |
| 9 | Final full e2e with the CP5 evidence (`2a4d0ad`) | — | **283 passed, 0 failed**; evidence review → defects 7–8 |
| 10 | Cause labels, header quantities, Slice-1 evidence gate | `d3eb52b` | targeted e2e 210 / 0; check 7/7; `test:api` 1688 / 0 |
| 11 | Docs (PARITY, BUILD_STATE, DECISIONS, evidence, this report) | see `git log` | — |

## Migration chain

`0021_briefings_slice3` (main) → `0022_orders_inventory_slice4` (lane placeholder 0040; also alters
`challans_challan` / `challans_challan_line`) → `0023_production_slice4` (0070) →
`0024_procurement_quality_logistics_slice4` (0060) → `0025_slice4_cross_lane_links` (integrator:
`quality_inspection.work_order_id` → `production_work_order.id`, RESTRICT). Each lane file was renamed and its
`Revision ID` / `Revises` / `revision` / `down_revision` rewritten; no revision on `main` was touched; no test names a
lane revision. `alembic heads` = 1 after every step; `lk db migrate --revision 0021` → `migrate` (head) round trip on
`lk_wt8`; `alembic check` reports only the known migration-only index `uq_vision_capture_conversation_sha` (ADR-061).

## Conflict decisions

Steps 1 and 2 merged without conflicts (`routes.ts`, `query-keys.ts`, `messages/*`, `tasks/rules/consumer.py`,
`seed/world/keys.py`, `identity.PROVISION_ORDER` auto-merged as the lanes wrote them). Step 3:

- `tasks/rules/consumer.py` `SLICE4_TRIGGERS`: union (production's `ops.production_dependencies` triggers and
  procurement's `ops.receipts`, `ops.qc`, `ops.dispatch_cutoffs`).
- `lib/api/query-keys.ts`: union of `production.*` with `procurement.*` / `quality.*` / `logistics.*`; the
  invalidation map keeps procurement's wider `inventory.changed` and production's `production.changed`. The textual
  union dropped production's closing brace (caught by lint/typecheck before the commit) and was repaired.
- `messages/areas.ts`: one Operations copy naming every Slice-4 part; every Slice-4 row links (production, capacity,
  purchasing, quality, dispatch); the live note says every part is available. `challans.test.tsx` and
  `settings.test.tsx` assert the new copy; the "Planned · Slice N" badge check moved to the finance area.
- `openapi.json` / `schema.d.ts`: ours at the conflict, then regenerated.
- `e2e/support/world.ts` merged clean (`ANANYA`); `DEEPA` added.

## Integrator requests

Orders/inventory:

| Request | Status | Where / test |
|---|---|---|
| 1 renumber 0040 | applied (0022) | — |
| 2 events.md handler keys and families | applied | `docs/architecture/events.md` §2, §4 |
| 3 e2e world at `--slice 4` | applied (ADR-065) | `scripts/dev.mjs`; full e2e |
| 4 PARITY rows | applied | `docs/PARITY_MATRIX.md` (GAP-10 repointed to `test_ledger_machine`) |
| 5 block won → sent while an order exists | deferred — a sales state-machine change, not a merge fix [sales] | — |
| 6 ADRs for decisions 2–8 | applied | ADR-062 |
| 7 `mgmt.decisions` reservation-conflict item | deferred — belongs with the management briefing family [briefings] | — |

Production (11 requests):

| Request | Status | Where / test |
|---|---|---|
| 1 renumber 0070 | applied (0023) | — |
| 2 procurement PO lines as feasibility supply | applied: `procurement.service.po_line_supply` registered in the procurement manifest (outstanding quantity, expected date; lines in the product's stock unit only) | `tests/integration/production/test_costing_feasibility.py::test_procurement_purchase_order_lines_are_feasibility_supply`; the lane's two "no provider" tests unregister it (monkeypatch) |
| 3 events.md `production.material_retry`, shortage triggers | applied | `events.md` §2, §4 |
| 4 ledger link for `work_order` sources | deferred — needs a transaction route or `/go` resolver [inventory, production] | — |
| 5 shortage issue names the blocked work order | applied in `inventory.rules.derive_shortage` (`production.wo_material` → work-order evidence member); late PO lines too (`procurement.purchase_order_line` → purchase order) | `test_work_orders.py::test_release_blocks_on_shortage_and_unblocks_on_receipt` (new assertion) |
| 6 PO-2026-0001 as the root cause; fixtures.md Deepa | applied: procurement's cause provider puts the late line in the shortage's `caused_by`, which `ops.shortages` now lists as evidence; fixtures.md §3, §8 | `tests/integration/procurement/test_quality_and_supply.py` |
| 7 PARITY production rows | applied (GAP-12 in progress: job work not built; LM-78, REUSE-05 implemented) | `docs/PARITY_MATRIX.md` |
| 8 ADRs for decisions 1–8 | applied | ADR-063 |
| 9 stray `settings/backups/page.tsx` | checked: the page is committed on `lane/s5-migration` (tracked despite `.gitignore` `backups/`); anchoring the pattern is left to the Slice-5 merge [migration] | — |
| 10 e2e seed at Slice 4, production journey, axe routes | applied | `e2e/production/work-order-journey.spec.ts` (4 tests); the axe sweep fills `workOrderId`, `bomId`, `routingId`, `workCenterId`, `poId`, `batchId` |
| 11 seed-key union | applied: `keys.PURCHASE_ORDERS` / `PURCHASE_ORDER_REFS` (`PO_KAVERI`) next to production's keys; `/_test/fixtures` publishes `purchase_orders` and `work_orders` with their ids | `tests/unit/test_seed_world_summary.py::test_world_summary_publishes_the_slice4_purchase_and_work_order_numbers` |

Procurement/quality/logistics (8 requests):

| Request | Status | Where / test |
|---|---|---|
| 1 renumber 0060 | applied (0024) | — |
| 2 events.md `became_overdue` → shortage refresh; `logistics.packing_list_staleness:<event>` | applied | `events.md` |
| 3 e2e world at `--slice 4` | applied | `scenarios/p-procure-to-pay.spec.ts` in the full e2e |
| 4 PARITY rows | applied (GAP-11 repointed to `test_requisition_to_bill_handoff`; GAP-14) | `docs/PARITY_MATRIX.md` |
| 5 inspections' `work_order_id` FK + production subject | FK applied (0025 and the model); production output of a QC-required product now requests one inspection per output transaction (`wip.output`). The subject **handler** is not registered: production keeps no accepted/rejected figures and rework orders are not built [production, quality] | `test_work_orders.py::test_output_of_a_qc_required_product_requests_one_inspection_linked_to_the_work_order` |
| 6 finance hand-off | noted for Slice 5 [finance] | — |
| 7 expected conflicts | resolved (above) | — |
| 8 design-lint float check inverted | applied (below) | `src/lib/design-lint.test.ts` |

The keys.py suggestion (`PO_KAVERI`, publish PO-2026-0001) is applied with production request 11.

### Design-lint "no float conversion" (procurement request 8)

The check passed `(file) => !moneyCode.has(file)` as its *allow* predicate, so it scanned only the four money modules.
It now allows `moneyCode.has(file) || notMoney.has(file)`. Un-inverted, it flagged 63 lines:
- **Fixed** (decimal quantities): `orders/order-workspace.tsx` (2), `production/feasibility-panel.tsx` (2),
  `production/master-screens.tsx` (9), `production/work-order-screens.tsx` (4) use `isPositiveDecimalStr`,
  `trimDecimalStr` and the new `subtractDecimalStr` (scaled BigInt) in `lib/format/decimal.ts`; `available_minutes`,
  `duration_days` and the compare-version selects parse with `Number.parseInt(x, 10)`.
- **Allowed with a reason** (not money or quantities): login parallax depth, material-viewer millimetres to scene
  units, AI error rates, speech duration, file sizes, time arithmetic, hex colour channels.
- **No longer matched**: base-10 integer parsing `Number.parseInt(x, 10)` (offsets, counts, days); a bare `Number(`,
  `parseInt(` without `Number.`, `parseFloat` and `Math.round` still fail the check.

## Defects found and fixed in the merge

1. (axe) The PO detail's lines table scrolls sideways at 1280 px but its wrapper was not keyboard-reachable
   (`scrollable-region-focusable`). `DataTable` now gives the scroll wrapper `tabIndex=0` only while it overflows
   (measured with a ResizeObserver), so narrow tables add no tab stop.
2. (axe) Date segments on the capacity page's from/to fields were under 24 px (`target-size`): `DatePicker` segments
   are at least 24 × 24 px.
3. (specs) Scenario I asserted on-hand 500 for LK-OT-0450; with inventory live in the seed, earlier specs that issue
   challans of that product move stock too, so it asserts a drop of exactly 100 from the value read before the issue.
   The production journey asserted a "Short" label the materials table does not render.
4. (web, from fix 1) A first version gave the scroll wrapper a region role named by the caption, which made
   `getByRole("region", { name: "Lines" })` ambiguous in three specs; the role was dropped (`036096e`).
5. (web) Work-order dialogs prefilled server quantities at the column scale ("6.000000"); they prefill the plain value
   people edit ("6").
6. (merge) The query-keys union lost production's closing brace (step 3; caught before the commit).
7. (e2e) `e2e/evidence.spec.ts` (Slice 1) gated on `!LK_E2E_EVIDENCE`, so the full run with `LK_E2E_EVIDENCE=cp5`
   also rewrote the 24 PNGs in `docs/evidence/slice-1/` (its tests count among that run's passes). The historical files
   were restored from git (`git checkout -- docs/evidence/slice-1`; no other earlier evidence folder changed) and the
   spec now runs only with `LK_E2E_EVIDENCE=1`, like the cp3/cp4a/cp4/cp5 specs. Only `docs/evidence/checkpoint-5/`
   is written by this merge.
8. (evidence review) The shortages panel showed the raw cause types `production.wo_material` and
   `procurement.purchase_order_line`: `inventory.reads._cause_labels` labelled only order lines. Work-order materials
   ("WO-2026-0001 · material 1") and late PO lines ("PO-2026-0001 · line 1 (expected …)") now get labels and links
   (asserted in `test_release_blocks_on_shortage_and_unblocks_on_receipt`). The work-order header showed
   "Planned 8.000000 set"; it shows the plain quantity.

## Gates (Checkpoint 5)

- `npm run test:api` on `d3eb52b` (final tree; the last backend change is the cause labels): **1688 passed, 7 skipped**
  (`test_golden_live`, live only), **0 failed**, 2 known warnings, 51.5 min. After each lane: 1612 (`76bc019`), 1654
  (`6505e56`), 1688 (`c4210a3`), all 0 failed.
- `npm run check -- --keep-going` on `d3eb52b`: **7/7 PASS** — ruff; pytest unit + contract 706 passed; alembic heads
  == 1; api:check (399 paths); web lint; web typecheck; web vitest 63 files / 685 tests (also 7/7 on `81b2d14`).
- `npm run test:e2e -- --workers=1` on `2a4d0ad` (production build, `LK_NEXT_BUILD_CPUS=2`,
  `NODE_OPTIONS=--max-old-space-size=2048`, own database `lk_wt8_e2e`, `--slice 4`, `LK_E2E_EVIDENCE=cp5`):
  **283 passed, 0 failed**, 650 skipped (project-scoped and opt-in), 16.9 min. Includes scenario I (desktop),
  `scenarios/p-procure-to-pay.spec.ts` 4/4, `production/work-order-journey.spec.ts` 4/4, scenario C with SSE, B, J,
  K, and the axe sweep in light and dark over every manifest route, now with the Slice-4 records the fixture world
  publishes (WO-2026-0001, its BOM, routing and work centre, PO-2026-0001, the opening batch); orders, requisitions,
  receipts, inspections, shipments, packing lists, pick lists, counts, adjustments and transfers are skipped (no
  fixture record). The Next build needed no retry. Runs 1–3: 266/6, 268/3, 272/2 (defects above).
- Targeted e2e on `d3eb52b` (fresh build, after the cause-label fix): `evidence-cp5`, `axe-sweep`, the production
  journey, scenario I, procure-to-pay — **210 passed, 0 failed**, 534 skipped, 11.8 min.
- Evidence: `docs/evidence/checkpoint-5/` (52 PNGs, README).
- Migrations: `migrate --revision 0021` → `migrate`; heads 1; `alembic check` clean apart from the known vision index.
- No dev server or background process left running; the e2e supervisor stopped its API, worker and web.

## Docs

`docs/PARITY_MATRIX.md` (Checkpoint 5 note: +14 implemented, GAP-12 in progress), `docs/BUILD_STATE.md` (header, §2,
§7 rows, §8, new §14), `docs/DECISIONS.md` (ADR-062 to ADR-065), `docs/architecture/events.md`,
`docs/architecture/fixtures.md`, `docs/evidence/checkpoint-5/README.md`.

## Open items (owners)

See `docs/BUILD_STATE.md` section 14: document approvals through the proposals engine and the reservation-conflict
decision [inventory, briefings]; won → sent block with an active order [sales]; ledger link for work-order postings
[inventory, production]; job work, rework from QC rejects, the production inspection handler, master authoring forms
[production, quality]; inventory, logistics and procurement web gaps (create forms, evidence upload, container
profiles, requisition paging) [web]; agent tools for Slice-4 actions [agents]; valuation and AP documents [finance];
the `.gitignore` `backups/` pattern [migration]; axe skips of non-fixture Slice-4 records [web].
