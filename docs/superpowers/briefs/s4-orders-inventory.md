# Lane brief: Slice 4 — sales orders and inventory (ledger, reservations, picking, counts, challan postings)

Branch `lane/s4-orders-inventory` from `main` (after the Slice-3 checkpoint). Module owner:
`backend/app/modules/orders/**`, `backend/app/modules/inventory/**`, the challan movement-policy consumer
(`modules/challans/movement.py` posting hook only — the challans module exists), `apps/web/src/features/orders/**`,
`apps/web/src/features/inventory/**`, pages under `src/app/(app)/sales/orders/**` and
`src/app/(app)/operations/inventory/**`, copy `src/messages/{orders,inventory}.ts`. Never push; small named
commits; never two test suites at once; never leave dev servers running.

## Contracts (read first)
1. `docs/design/source/operations.md` §0–§3 (cross-cutting rules, sales orders, inventory: warehouses, locations,
   lots, the double-entry immutable movement ledger with projections updated in the same transaction,
   reservations with row locks and no oversell, pick lists, counts, adjustments, transfers, reversals, opening
   batches), §4 challans (movement policy per type: exactly one posting per source event, return reconciliation
   against original lines), §10–§12 (file layout, API, events), §14 tests (scenario I).
2. `docs/PLAN.md` Slice 4 (orders, inventory, challan movement policy) and scenario I; `docs/architecture/events.md`
   §3.10 (`orders.*`, `inventory.*`, consumers incl. `inventory.shortage_refresh`), `permissions.md` §7.7
   (`orders.*`, `inventory.*`), `conventions.md` (money/quantity, UOM integer rule), `fixtures.md`,
   `docs/DECISIONS.md` (ownership transfer at challan issue; rounding; opening balances approved by a second
   person).
3. Existing modules you integrate with: `modules/sales` (quote → order: `UNIQUE(source_quote_id)`, won quotes),
   `modules/challans` (issue event → posting), `modules/catalogue` (product stock attributes: `is_stock_tracked`,
   `track_lots`, `stock_uom_code`), `platform/numbering`, `platform/events` (outbox, consumers), `modules/tasks`
   rules registry (briefing families `ops.shortages`, picking tasks), `platform/org/workcal`.
4. Web: `docs/superpowers/specs/2026-11-02-checkpoint-2-build-guide.md`; `features/sales/**` and
   `features/challans/**` as patterns; the Operations overview (`features/areas/area-overview.tsx`) rows you turn
   into real links.

## Deliverables
- **Orders**: sales orders from accepted quotes (idempotent via `UNIQUE(source_quote_id)`), lines with ordered,
  reserved, delivered and cancelled quantities, partial fulfilment, holds and cancellation with reasons, numbering
  `SO-YYYY-NNNN`, state machine with `allowed_transitions`, events `orders.*`, briefing rules.
- **Inventory**: warehouses/locations/lots; `inventory_posting` + `inventory_movement` double-entry ledger
  (immutable, append-only, enforced by trigger), projections (`inv_stock_level`, `inv_shortage_state`) updated in
  the same transaction with a mismatch detector job (`inventory.projection.mismatch_detected`); reservations with
  `SELECT … FOR UPDATE` on the level row, no oversell, no silent negatives (`inventory.reservation.shortfall_detected`
  / `.conflict_detected`); pick lists (release, pick, short-pick); stock counts (freeze, count, post variance);
  adjustments with approval; transfers; reversals (`inventory.posting.reverse`, RA + step-up); opening-stock
  batches created by one person and approved by another (MFA step-up, never the creator); reorder rules.
- **Challan movement policy**: on `challans.challan.issued` post exactly one posting according to the policy
  matrix recorded by the challans module (`inventory_effect`), with replay safety (idempotent on
  `(source_type, source_id)`), return reconciliation posting on `challans.return.received` against the original
  lines, document-only cancel of an issued challan producing a reversal posting (`challans.challan.cancelled`
  carries `reversal_posting_id`).
- **Briefing families**: `ops.shortages` (root-cause grouping by `caused_by`), picking tasks, integrity issues.
- **Web**: `/sales/orders` list and `/sales/orders/[orderId]` workspace (lines, reservations, fulfilment, documents),
  "Convert to order" on won quotes; `/operations/inventory` (stock by product/warehouse with real projections),
  `/operations/inventory/movements` (ledger browser), `/operations/inventory/stock-takes`, `/operations/reservations`,
  pick lists; the Operations overview rows for inventory/reservations become links. Routes registered in
  `src/lib/routes.ts`, query keys added, copy in messages, honest states, controls only from `capabilities`.
- **Tests**: scenario I end to end (accept once → reserve without oversell under concurrency, a barrier test with
  two sessions → fulfil partially → issue the challan with exactly one movement → partial return linked to the
  original line → duplicate events cannot post again → cancellation creates an auditable correction); Hypothesis
  property tests for the ledger (sum of movements = projection; no negative on-hand without an explicit
  allow-negative flag, which does not exist); IDOR matrix for every new route.

## Migration
`backend/migrations/versions/0030_orders_inventory_slice4.py` with `down_revision` = the current head on `main`
(the integrator reparents if other Slice-4 lanes land first).

## Verification and report
`npm run check -- --keep-going` 7/7, `npm run test:api`, `npm run api:generate` committed, web gates, scenario I
e2e spec written and run; `docs/lanes/orders-inventory-s4.md` (built, scenario I test table, decisions, integrator
requests, gate output). Final message: branch tip, counts, unfinished items with reasons.
