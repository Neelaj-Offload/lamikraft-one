# Lane brief: Slice 4 — procurement, quality and logistics

Branch `lane/s4-procurement-logistics` from `main` (after the Slice-3 checkpoint). Module owner:
`backend/app/modules/procurement/**`, `backend/app/modules/quality/**`, `backend/app/modules/logistics/**`,
`apps/web/src/features/{procurement,quality,logistics}/**`, pages under `src/app/(app)/operations/{purchasing,
quality,dispatch}/**`, copy `src/messages/{procurement,quality,logistics}.ts`. The inventory lane owns postings:
goods receipts post stock **through the inventory module's posting service** (coordinate on its signature:
`inventory.service.post(source_type, source_id, purpose, lines)`; if the inventory lane has not merged yet, code
against that signature with a local fake and let the integrator wire it). Never push; small named commits; never
two test suites at once; never leave dev servers running.

## Contracts (read first)
1. `docs/design/source/operations.md` §5 procurement (vendor items, requisition → PO → partial GRN → QC → vendor-bill
   handoff), §8 logistics (packing lists from packaging snapshots, CBM and weights, shipments with cutoffs, load
   suggestions, evidence), §1 cross-cutting rules, §10–§12 (layout, API, events), §14 tests.
2. `docs/PLAN.md` Slice 4 (procurement, logistics, operational briefing families: receipts, dispatch cutoffs, QC);
   `docs/architecture/events.md` §3.10 (`quality.*`, `procurement.*`, `logistics.*`), `permissions.md` §7.7
   (`quality.*`, `procurement.*`, `logistics.*`), `conventions.md`, `fixtures.md`, `docs/DECISIONS.md`.
3. Existing modules: `modules/parties` (vendor role), `modules/catalogue` (packaging fields for packing lists:
   carton qty, carton dimensions, net/gross weight, CBM), `modules/challans` (`logistics.shipment_status` sets
   shipment dispatched when the linked challan is issued), `platform/numbering`, `platform/events`, `modules/tasks`
   rules registry, `platform/org/workcal` (cutoffs in company time).

## Deliverables
- **Procurement**: vendor items (vendor, product, vendor code, lead time, price with currency), requisitions
  (`PR-YYYY-NNNN`, submit/approve/reject with separation of duties), purchase orders (`PO-YYYY-NNNN`, approve, issue,
  close, cancel; expected dates per line; `became_overdue` scheduled event; `expected_date_changed`), goods
  receipts (partial, per line, posting stock through inventory; QC-required products create an inspection before
  stock becomes available), vendor bills (three-way match: PO, GRN, bill; `mismatch_detected`; `handed_off` to
  finance as an event only in Slice 4).
- **Quality**: inspections requested by GRN and by production (`quality.inspection.requested/passed/failed`),
  checklist results, hold/release of the inspected quantity (through inventory lots' QC status), tasks family `ops.qc`.
- **Logistics**: packing lists from packaging snapshots (cartons, inner packs, net/gross weight, CBM computed
  server-side with Decimal, `became_stale` when the order changes), shipments (`SH-YYYY-NNNN`, scheduled with
  cutoff → `ops.dispatch_cutoffs` hard-due task, dispatched when the challan issues, delivered with evidence,
  exceptions), load suggestions (deterministic greedy by CBM/weight, labelled "suggestion").
- **Briefing families**: `ops.receipts`, `ops.qc`, `ops.dispatch_cutoffs`, PO overdue.
- **Web**: `/operations/purchasing/{requisitions,orders,receipts}` lists and records, `/operations/quality`,
  `/operations/dispatch` (packing lists, shipments with cutoffs), vendor items under the vendor's party record
  (a tab in `features/parties` — append-only addition); the Operations overview rows become links. Routes, query
  keys, messages, honest states, capabilities-driven controls.
- **Tests**: requisition → PO → partial GRN → QC → bill match end to end; overdue PO scheduling; packing-list CBM
  and weight arithmetic (Decimal, HALF_UP to the minor unit); shipment cutoff tasks in company time; IDOR matrix.

## Migration
`backend/migrations/versions/0031_procurement_quality_logistics_slice4.py`, `down_revision` = current head on
`main` (integrator reparents).

## Verification and report
`npm run check -- --keep-going` 7/7, `npm run test:api`, `npm run api:generate` committed, web gates;
`docs/lanes/procurement-logistics-s4.md`. Final message: branch tip, counts, unfinished items with reasons.
