# Lane brief: Slice 4 — production (BOMs, routings, work orders, capacity, cost rollups, feasibility, what-if)

Branch `lane/s4-production` from `main` (after the Slice-3 checkpoint). Module owner:
`backend/app/modules/production/**`, `apps/web/src/features/production/**`, pages under
`src/app/(app)/operations/production/**`, copy `src/messages/production.ts`. Stock issue and consumption post
**through the inventory module's posting service** (same coordination rule as the procurement lane). Never push;
small named commits; never two test suites at once; never leave dev servers running.

## Contracts (read first)
1. `docs/design/source/operations.md` §6 production (versioned BOMs and routings with approval, work centres,
   work orders, issue and consumption, cut-plan links, offcut lots, capacity calendars from workcal, deterministic
   cost rollups with missing-input flags, delivery feasibility with evidence, read-only what-if), §7 cutting
   (the cutting module exists on `main`; link work orders to cut plans and record offcut lots from results), §1,
   §10–§12, §14.
2. `docs/PLAN.md` Slice 4 (production; briefing family `ops.production_dependencies`); `events.md` §3.10
   (`production.*`), `permissions.md` §7.7 (`production.*`; cost figures need `pricing.cost.read`),
   `conventions.md`, `fixtures.md`, `docs/DECISIONS.md`.
3. Existing modules: `modules/cutting` (plans, results, metrics, grain locks), `modules/pricing` (product costs of
   record, `COST_GUARD` redaction with `model_exposure="deny"`), `modules/catalogue`, `platform/org/workcal`
   (capacity calendars, shifts), `platform/events`, `modules/tasks` rules registry, `modules/inventory` service
   signature (posting; lots).

## Deliverables
- **Masters**: work centres with capacity per shift from workcal; BOMs (versioned, approved by someone other
  than the author, components with quantities per unit and scrap %, alternates), routings (versioned, operations
  with work centre and standard times).
- **Work orders** `WO-YYYY-NNNN`: planned from an order line or standalone; release (checks component
  availability through inventory reservations → `blocked` with `caused_by` when short, `unblocked` when resolved),
  material issue and consumption postings, operation completion, cut-plan link (a work order's board operation
  references a cutting plan; offcut lots recorded as `inventory.lot.measured`), completion posting of finished
  goods, close/cancel; `ops.production_dependencies` tasks.
- **Capacity**: load per work centre per day from released work orders vs calendar capacity;
  `production.capacity.overloaded`.
- **Cost rollups**: deterministic, Decimal, from BOM components' costs of record + routing standard times ×
  work-centre rates; `status complete|incomplete` with the missing inputs listed; figures redacted without
  `pricing.cost.read` and never model-exposed; `production.cost_rollup.computed`.
- **Feasibility**: "can we deliver N of product by date" with evidence (stock, open POs, capacity, lead times),
  read-only; **what-if** simulation (read-only, labelled, never writes).
- **Web**: `/operations/production/{work-orders,boms,routings,work-centres,capacity}` with records; feasibility
  panel on the order line; the Operations overview rows become links. Routes, query keys, messages, honest states.
- **Tests**: BOM/routing approval separation of duties; release blocks on shortage and unblocks on receipt
  (events); issue/consume/complete postings reconcile with the ledger; rollup determinism and missing-input
  flags; feasibility evidence; redaction canary for cost figures; IDOR matrix.

## Migration
`backend/migrations/versions/0032_production_slice4.py`, `down_revision` = current head on `main` (integrator
reparents).

## Verification and report
`npm run check -- --keep-going` 7/7, `npm run test:api`, `npm run api:generate` committed, web gates;
`docs/lanes/production-s4.md`. Final message: branch tip, counts, unfinished items with reasons.
