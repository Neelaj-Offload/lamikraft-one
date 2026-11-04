# Checkpoint 5 evidence — Slice 4 on the merged branch (2026-11-05)

52 screenshots of the screens the Slice-4 lanes (orders/inventory, production, procurement/quality/logistics) added, at
1440 px and 390 px wide, light and dark (`<screen>-<width>-<theme>.png`). Taken by `e2e/evidence-cp5.spec.ts` against
the production build of `d3eb52b`, on a fresh demo world seeded at `--slice 4` with `--anchor-date 2026-10-12`
(the evidence spec runs first, so WO-2026-0001 is still blocked and PO-2026-0001 not yet received):

```
LK_E2E_EVIDENCE=cp5 npm run test:e2e -- --workers=1 e2e/evidence-cp5.spec.ts e2e/axe-sweep.spec.ts \
  e2e/production/work-order-journey.spec.ts e2e/scenarios/i-order-fulfilment.spec.ts e2e/scenarios/p-procure-to-pay.spec.ts
```

| Screen | Route | Signed in as |
|---|---|---|
| operations-overview | `/operations` (every Slice-4 part available and linked) | Ravi |
| sales-orders | `/sales/orders` (the seeded world has no order: the honest empty state) | Meera |
| inventory-stock | `/operations/inventory` (stock by product × warehouse, totals, short filter) | Ravi |
| inventory-movements | `/operations/inventory/movements` (the ledger: opening batch, source links) | Ravi |
| reservations-shortages | `/operations/reservations` (LK-WB-1800 short by 8, caused by PO-2026-0001 line 1 and WO-2026-0001 material 1, both linked; the work order's reservation) | Ravi |
| work-orders | `/operations/production/work-orders` | Deepa |
| work-order | `/operations/production/work-orders/<WO-2026-0001>` (blocked banner with the shortage, materials 48 required / 40 reserved, operations) | Deepa |
| bom | `/operations/production/boms/<BOM v1>` (approved version, components, cost rollup card) | Deepa |
| capacity | `/operations/production/capacity` (per work centre and day, from/to dates) | Deepa |
| purchase-orders | `/operations/purchasing/orders` | Priya |
| purchase-order | `/operations/purchasing/orders/<PO-2026-0001>` (sent, overdue, lines, Receive goods) | Priya |
| quality | `/operations/quality?status=all` (no inspection yet in the fresh world) | Ravi |
| dispatch | `/operations/dispatch` (no shipment yet: the empty state with Plan a shipment) | Ravi |

Inspected by the integrator: work-order (1440 light, 390 light), purchase-order (390 dark), capacity (1440 dark),
reservations-shortages (390 light, 1440 dark) and operations-overview (1440 light) checked by eye; both themes legible,
no horizontal overflow at 390 px. The first take (from the full run on `2a4d0ad`) showed the shortage causes as raw
ref types and "Planned 8.000000 set" in the work-order header; both were fixed in `d3eb52b` and the set was retaken.
Observation (open item, not fixed here): the shortage line still prints the server scale ("short by 8.000000 sheets").

The flows behind these screens are exercised by `e2e/scenarios/i-order-fulfilment.spec.ts` (convert once, reserve,
challan from the order, one movement), `e2e/scenarios/p-procure-to-pay.spec.ts` (order, approval by a second person,
receipt into QC, inspection, bill match), `e2e/production/work-order-journey.spec.ts` (blocked → receipt and QC accept
unblock → issue / consume / output → BOM version approved by a second person) and the axe sweep of the same build in
light and dark (Slice-4 records filled from the fixture world: WO-2026-0001, its BOM, routing and work centre,
PO-2026-0001, the opening batch).

The full run with `LK_E2E_EVIDENCE=cp5` also triggered the Slice-1 evidence spec, which rewrote
`docs/evidence/slice-1/`; those files were restored from git and that spec now runs only with `LK_E2E_EVIDENCE=1`.
