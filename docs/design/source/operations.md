> Design-workflow output (2026-10-12), kept as source material. Where it conflicts with docs/architecture/*, the architecture docs win.

# Connected operations and initial finance (sales orders, inventory ledger and reservations, challans, purchasing, production, sheet cutting optimiser, logistics, invoices/receipts/accounting handoff)

# Connected Operations and Initial Finance: Subsystem Design

## 0. Scope, dependencies, slices

This subsystem owns these modules under `backend/app/modules/`: `orders`, `inventory`, `challans`, `procurement`, `production`, `cutting`, `logistics` and `finance`. Each has the standard files (models, schemas, service, router, events, tools, policies) plus the extra files listed in section 10.

**Platform interfaces it depends on.** The names are indicative; the platform designer may refine them.
- `numbering.next(session, company_id, series_key, local_date)`: does a row-locked `UPDATE document_sequences ... RETURNING` per (company, series, period). Numbers are never reused.
- `outbox.emit(session, name, subject_refs, payload)`. `consumers.once(session, consumer, event_id)` uses a unique constraint on `processed_events(consumer, event_id)` so each consumer handles an event once.
- `Idempotency-Key` middleware on every command POST. `permissions.require(actor, "<module>.<action>", record)`. Query scope helpers. Costing redaction.
- `proposals`: versioned approvals, rechecked at execution. Audit/status history. `documents.render_pdf` (Unicode, repeating headers). `exports.safe_csv` (formula escaping). Authenticated downloads with no token in the URL.
- Master data: parties, addresses and tax ids. Products, with `product_key`, `base_uom`, `track_lots`, `qc_required`, `hsn_sac` and canonical packaging. `uoms` (with `is_integer`) and `uom_conversions`. FX snapshots. Company settings: TZ, workweek, shifts, legal identity, document terms, signature labels.
- Quotes: `sales.service.lock_accepted_snapshot(quote_id)` returns the accepted immutable revision and its calculation result. The `pricing.calc` Decimal engine is reused for invoices.

| Slice | Parts |
|---|---|
| 2 | Full cutting optimiser: saved plans, exports, grain settings, property tests. Full challans as documents (`inventory_effect=none`), including document-level return links. |
| 4 | Warehouses, locations, lots, ledger, reservations. Counts, adjustments, transfers, reversals. Opening batches. Sales orders. Challan movement policies. Procurement. Production: BOM, routing, WO, QC, capacity, cost rollup, feasibility. Cut-plan links to WOs and board lots. Logistics. Briefing events. |
| 5 | Finance. Offcut reuse in the optimiser. What-if simulation. Job-work ageing. |
| 6 | Acceptance runs for H and I, plus role isolation. |

## 1. Cross-cutting rules

- **Quantities.** Stored as NUMERIC(18,4) plus `uom_code`. The ledger stores quantity in the product's base UOM and also keeps the entered qty/UOM. Conversion uses master-data conversions only; a missing conversion is a 422. Integer UOMs (pcs, nos, sheets, box, set, roll, bundle) reject fractions. Every quantity must be > 0.
- **Money.** NUMERIC(18,4) plus currency, computed by `pricing.calc`. Amounts in different currencies are never summed without an FX snapshot.
- **Lock order** (prevents deadlocks): document header -> lines (by id) -> `inv_stock_summaries` (product_id, warehouse_id) -> `inv_stock_balances` (key) -> `inv_reservations` (id). On deadlock or serialisation failure the unit of work retries up to 3 times. This is safe because every command carries an idempotency key.
- **Immutability.** A DB trigger `forbid_mutation()` blocks UPDATE and DELETE on `inv_stock_postings`, `inv_stock_movements`, `chl_return_links` and `fin_receipt_allocations`. Corrections are always new rows that point to the original.
- **State machines.** All are table-driven `TRANSITIONS` dicts in `policies.py`, with table tests.
- **Search.** Parameterised ILIKE with escaped wildcards; no regex. Filters apply before pagination.
- **AI tools.** Reads run immediately. Commitments (order conversion, reservation, posting, challan issue, PO approval, invoice issue) go through proposal -> approval -> `execute_approved_proposal`, which calls the same service function as the UI endpoint.

## 2. Sales orders (`orders`)

**Tables**
- `ord_sales_orders`:
  - Standard columns plus `order_number` (SO-YYYY-NNNN, unique per company), `party_id`, ship-to address id and snapshot.
  - `source_quote_id` and `source_quote_revision_id`. **UNIQUE(company_id, source_quote_id)**.
  - `status` in {draft, confirmed, on_hold, completed, cancelled}; `fulfilment_state` in {none, partial, complete}.
  - `currency` and `terms_snapshot` JSONB: incoterm, payment terms text, `payment_due_days`, validity, brand, customer snapshot, and the calc result with rule versions. Also `snapshot_hash`.
  - `subtotal`, `surcharge`, `tax`, `total`, all copied from the accepted calc result.
  - `requested_delivery_date`, `promised_date`, `default_warehouse_id`, `owner_user_id`, `cancel_reason`.
  - Indexes: (company_id, status, requested_delivery_date) and (company_id, party_id).
- `ord_sales_order_lines`:
  - `line_no`, `source_quote_line_id` (UNIQUE).
  - `line_kind` in {catalog, custom, manual, charge}; the EUR 400 surcharge becomes a `charge` line. `fulfilment_mode` in {stock, make_to_order, non_stock}.
  - `product_id`, `custom_product_id`, `description_snapshot` JSONB, `uom_code`, `unit_price` + currency, `line_total`.
  - Quantities: `qty_ordered`, `qty_delivered`, `qty_returned_replace`, `qty_returned_credit`, `qty_cancelled`, `qty_invoiced`, `qty_credited`.
  - Generated stored column `qty_remaining = qty_ordered - qty_cancelled - (qty_delivered - qty_returned_replace)`. CHECKs: all quantities >= 0, `qty_remaining >= 0`, `qty_delivered >= qty_returned_replace + qty_returned_credit`.

**Converting a quote: `convert_quote(actor, quote_id)`. Idempotent.**
1. Require `orders.create` within scope. `lock_accepted_snapshot` takes a FOR UPDATE lock on the quote row.
2. If an order already exists for this `source_quote_id`, return it with `created=false`.
3. Validate:
   - the quote status is won and has an accepted immutable revision;
   - the quote has a linked `party_id` (legacy free-text customer -> `party_link_required`);
   - no line has an unavailable price;
   - the sum of snapshot line totals equals the calc subtotal (otherwise `snapshot_inconsistent`).
4. Insert the order (status `draft`: only logistics fields are editable; commercial fields are locked). Copy lines from the snapshot and materialise surcharge/charge lines. Catch the unique-violation error and reload the existing order instead.
5. Emit `orders.sales_order.created`. Catalogue or price changes after this point never touch the order.

**Confirm** (`orders.confirm`, through policy/approval) moves draft -> confirmed and allows reservations. Commercial amendments are not edited on the order: either cancel the remaining quantity, or create a supplementary order from a new quote.

**Cancelling** a line's remaining quantity (or the whole order) requires a reason:
- Under the line lock, `qty_cancelled += qty`.
- Linked active reservations are released.
- A status history entry and `orders.sales_order_line.cancelled` are written.
- Delivered or invoiced quantity is never cancelled; that goes through the return and credit-note paths.

**Preview** `preview_order_impact(order)` is read-only. Per line it returns availability, the outcome a reservation would have, shortages and feasibility.

## 3. Inventory (`inventory`)

**Location types (`inv_locations.location_type`)**

| Type | Stock-bearing (balance >= 0) | Counts as available | Notes |
|---|---|---|---|
| internal (bins via parent_id) | yes | yes | belongs to a warehouse |
| qc_hold, rejected, wip, office | yes | no | company locations |
| in_transit | yes | no | transfers between warehouses |
| external_holding | yes | no | one per party (fabricator, job worker, customer holding returnable or sample goods); stock stays **company-owned** |
| supplier, customer, production, scrap, adjustment, opening, sample_consumption | no (virtual, may go negative) | no | one each per company; the party is recorded on the movement |

**Ownership.** `owner_party_id` NULL means company-owned. Non-null means customer- or vendor-owned material. Party-owned stock never counts as available and can only be consumed by WOs that name that owner.

**Tables**
- `inv_warehouses`: code, name, branch_id, address, is_active.
- `inv_locations`: warehouse_id (NULL for virtual/external), code, parent_id, location_type, party_id, `is_stock_bearing`, `counts_available`. UNIQUE(company_id, warehouse_id, code).
- `inv_lots`:
  - product_id, `lot_code` (unique per product), `lot_kind` in {standard, board_lot, offcut}.
  - supplier_lot_ref, grn_line_id, parent_lot_id.
  - Measured dimensions `length_mm`, `width_mm`, `thickness_mm`, `grain_axis`, plus `verification_status` and `measured_by/at`.
- `inv_stock_postings`: the posting event.
  - source_type, source_id, purpose, idempotency_key, payload_hash, effective_at, posted_by, reason, proposal_id, `reverses_posting_id`.
  - UNIQUE(company_id, idempotency_key). **UNIQUE(company_id, source_type, source_id, purpose)**. UNIQUE(reverses_posting_id).
- `inv_stock_movements`:
  - `seq` BIGSERIAL, posting_id, line_no, product_id, lot_id, owner_party_id, `from_location_id`, `to_location_id`, quantity (base UOM, > 0), base uom, entered_qty and entered_uom, counterparty_party_id, reservation_id, source_line_type and source_line_id, optional informational unit_cost.
  - CHECK from <> to. Indexes: (company_id, product_id, seq) and (company_id, posting_id).
- `inv_stock_balances`: a projection of the ledger.
  - Key (company_id, product_id, location_id, lot_id, owner_party_id) with **UNIQUE NULLS NOT DISTINCT**, which needs PG >= 15; pgserver bundles PG16.
  - quantity, `enforce_non_negative`, last_movement_at. **CHECK (NOT enforce_non_negative OR quantity >= 0)**.
- `inv_stock_summaries`: (company_id, product_id, warehouse_id) unique. `available_on_hand` = company-owned quantity in available locations, excluding offcut lots. `reserved`, version. CHECK reserved >= 0 and available_on_hand >= 0.
- `inv_reservations`:
  - product_id, warehouse_id, optional location_id and lot_id, quantity, consumed_qty, released_qty.
  - status in {active, fulfilled, released, cancelled}. demand_type in {so_line, wo_material, transfer_line} plus demand_id, priority, expires_at, reason, version.
  - CHECK consumed + released <= quantity. Partial index on (company, product, warehouse) WHERE status='active'.
- Documents: `inv_adjustments` (+ lines, reason codes), `inv_stock_counts` (+ lines with `system_qty_at_snapshot`, `snapshot_seq`, counted_qty), `inv_opening_batches` (+ lines with source import row ref, file hash), `inv_qc_inspections` (subject_type in {grn_line, wo_output, return_line}, accepted_qty, rejected_qty, reason, inspector_id), `inv_reorder_rules` (min, max, reorder_qty).

**Definitions**
- On-hand = the balance quantity.
- Available (product, warehouse) = `available_on_hand - reserved`.
- Positions views also show external, in-transit, QC and party-owned stock separately.

**Posting engine: `post_movement(session, PostingRequest)`**
1. Look up the idempotency key. If a posting exists with the same payload_hash, return it. If the hash differs, return 409.
2. Validate the request:
   - products are stock-tracked;
   - lots belong to the product, and a lot is present when `track_lots`;
   - locations belong to the company;
   - each (from type -> to type) pair is in the allowed `TRANSITION_MATRIX`;
   - UOM conversions exist.
3. Lock the affected summaries and balances in the documented order, creating missing rows first with `INSERT ... ON CONFLICT DO NOTHING`.
4. For each line, apply from -= q and to += q. If a stock-bearing balance would go below 0, raise `NegativeStockError` (with product, location, lot, shortfall) and roll back. Negative stock is never silent.
5. Reservation consumption: lock the reservation, add to `consumed_qty` (it may not exceed the remaining reservation), and reduce `reserved` on the summary.
6. Outbound moves that do not consume a reservation must leave `available_on_hand >= reserved`. Otherwise raise `ReservedStockConflict`.
   - Exception: an approved loss/count adjustment may still post; it then emits `inventory.reservation.shortfall_detected`.
7. Insert the posting and its movements, emit `inventory.stock.posted`, and return a receipt.

**Reversal: `reverse_posting(id, reason)`** (permission plus approval policy). Creates a new posting with from and to swapped, the same lots and owners, `reverses_posting_id` set, and idempotency key `reversal:{id}`. The same negative-stock checks apply. Reservations are not recreated; a briefing item suggests re-reserving.

**Reservations: `reserve(demand, warehouse, qty, lot?, location?, policy=partial|all_or_nothing)`**
1. Lock the demand line. Unreserved = remaining - sum of its active reservations; the request must be <= unreserved.
2. Lock the summary row (and the lot balances if a lot is pinned). Compute available, and the lot's free quantity (lot balance minus active pinned reservations).
3. Grant `min(requested, available)` under `partial`; grant nothing under `all_or_nothing` if short. If anything is short, emit `inventory.reservation.shortfall_detected` with the shortfall.
4. Insert the reservation, increase `reserved`, bump the version, emit `inventory.reservation.created`. **Reserving stock has to wait for the same summary row lock as posting, so two requests cannot both take the same units.** Release reverses the reservation and emits `.released`.

**Other operations**
- **Relocation** (bin to bin): a direct posting.
- **Adjustments:** draft -> submitted -> approved (approver must not be the creator) -> posted, against the `adjustment` location.
- **Stock count:**
  - Freeze records `system_qty_at_snapshot` and the movement `seq` high-water mark.
  - Approval posts delta = counted - snapshot, so movements after the snapshot stay valid.
  - The variance is shown before approval.
- **Opening stock:** only through `inv_opening_batches`.
  - Created from import staging. Validation rejects any (product, warehouse) that already has non-opening movements, unless the line is flagged `late_opening`.
  - Approval requires `inventory.approve_opening` by a different user. One posting per batch from the `opening` location.
  - No code path derives opening stock from challans.
- **Offcut library:** recording a measured offcut creates an `inv_lots` row (kind offcut, with dimensions and grain) and a posting production -> internal.
- **Nightly projection check:** a worker job compares balances with the ledger sum and summaries with balances plus reservations, and emits `inventory.projection.mismatch_detected`.

## 4. Challans (`challans`)

**Tables**
- `chl_challans`. Every legacy field is kept, plus structure:
  - Legacy fields: `challan_number` (DC-YYYY-NNNN), `challan_date` (local), `challan_type`, `return_type` (returnable | non_returnable), `source_location` (display text), `destination_type`, `destination_party`, `shipping_name`, `gstin`, `phone`, `email`, `address`, `reference_no`, `remarks` (printed), `internal_notes` (never printed).
  - Structured fields: `source_warehouse_id`, `party_id`, `consignee_party_id`, `destination_warehouse_id`, `office_location_id`, `direction`, `expected_return_date`, `so_id`.
  - `status`, `inventory_effect` in {none, posting}, `issue_posting_id`, `reversal_posting_id`, issued/closed/cancelled at and by, cancel_reason, `deleted_at` (soft delete), legacy provenance, version.
  - Indexes: (company_id, status, challan_date), (company_id, party_id), (company_id, challan_type), and a trigram index on number, party and reference.
- `chl_challan_lines`:
  - `line_type` (catalog | custom | manual), product_id, custom_product_id, `item_code`, `item_name`, `hsn_sac`, quantity (> 0), `uom_code`, `remarks`, sort_order.
  - lot_id, from_location_id, so_line_id, reservation_id, wo_operation_id, `is_non_stock`.
  - `returned_qty`, `consumed_qty` (job work), `written_off_qty`, `received_qty` (transfer).
  - CHECK returned + consumed + written_off <= quantity.
- `chl_return_links`: return_line_id (**UNIQUE**), original_line_id, quantity, kind in {returned, consumed_in_job_work, written_off}, disposition in {replace, credit, restock}.

**Statuses.** draft -> issued | cancelled. issued -> closed | cancelled. closed and cancelled are terminal. Issued challans are immutable except for internal notes. Corrections are made by cancelling and duplicating.
- Closing happens automatically when every returnable line's outstanding quantity is 0. Closing manually with outstanding returnable quantity requires a write-off (`challans.write_off`, with reason and approval), which posts external_holding -> adjustment.
- Deleting a draft requires `challans.delete_draft` (admin template only) and is a soft delete. The number is never reused.

**Movement policy (`movement_policy.py`).** Invalid combinations return 422. With `inventory_effect=posting`, every line is either linked to a stock product or explicitly `is_non_stock`. Manual and custom lines are non-stock unless a product is linked.

| Type | Return type | Allowed destinations | Movement on issue |
|---|---|---|---|
| Outward | non-returnable | Customer, Fabricator, Vendor, Transporter (consignee required) | internal -> customer (virtual); consumes SO reservation when the line is linked |
| Outward | returnable | Customer, Fabricator, Vendor, Transporter | internal -> external_holding(party), company-owned |
| Inward | non-returnable | any except Warehouse | supplier/customer -> qc_hold. Party-owned (owner = party) or company-owned; company-owned without a GRN needs `inventory.receive_unplanned` |
| Return (inbound) | inherits original | party of the original | external_holding(party) -> qc_hold, or for sold goods customer -> qc_hold; must link to original lines |
| Return (to Vendor) | non-returnable | Vendor | rejected/internal -> supplier; links to a GRN line |
| Job Work | returnable (forced) | Fabricator, Vendor | internal -> external_holding(party); stays company-owned |
| Transfer | non-returnable | Warehouse | issue: internal(A) -> in_transit; receive: in_transit -> internal(B) |
| Sample | returnable | any except Warehouse | internal -> external_holding(party), or the office location |
| Sample | non-returnable | any except Warehouse | internal -> sample_consumption |

**Issue algorithm (`issue(challan_id)`)**
1. Lock the challan. If it is already issued, return the existing receipt (idempotent).
2. Validate against the policy.
3. Call `inventory.post_movement` with source ('challan', id, 'issue'). Because of the UNIQUE constraint on source, **one challan issue = one posting**.
4. For SO-linked lines, call `orders.record_delivery` (line lock, `qty_delivered += q`) in the same transaction.
5. Set status issued, emit `challans.challan.issued`.

**Dispatch.** Logistics "dispatch" issues the linked draft challan through this same function. Shipments only reference the challan and its `issue_posting_id`; they never post stock.

**Returns: `issue` of a Return challan.**
1. Lock the original lines, sorted.
2. Outstanding = quantity - returned - consumed - written_off. For sold goods, use delivered net of earlier returns.
3. If the return quantity exceeds outstanding, return 422 `excess_return`. If the original line belongs to a different party or a non-returnable original without a sales link, return 422.
4. Insert links. The unique `return_line_id` plus the idempotent issue blocks duplicate receipts.
5. Update the counters, post the movement, update the SO `qty_returned_*` fields, and auto-close the original if complete.

**Cancelling an issued challan** requires `challans.cancel_issued`, a reason, and the approval policy. It is rejected if any return links or invoices reference the challan. It calls `reverse_posting`, reduces SO delivered quantities, and keeps all history.

**Numbering.** Numbers are assigned at creation (legacy behaviour) by `numbering.next('challan', company-local date)`, with a yearly reset. Migrated legacy numbers initialise the counter to the year's maximum plus 1. Legacy challans import as `inventory_effect=none`.

**Lists and summaries**
- Filters: search (number, party, reference), status, type, destination type, party, this week / this month / date range (company TZ, configurable week start), and pending-returnable.
- `GET /summary` applies the same filters and scope: total, this_week, this_month, pending_returnable (count and outstanding quantity), and counts by type, destination and status.

**Output and editing**
- CSV through `safe_csv`. PDF and print show FROM/TO, the line table, total quantity, configured terms, and signature boxes (Delivered By, Received By, Authorised Signatory). Internal notes are omitted.
- Draft editing: 600 ms debounced PATCH carrying `version`. A 409 conflict opens a reload/merge prompt. Failed saves show inline with a retry and are never swallowed. Quantity rules come from the schema (UOM integer rule, > 0, max 4 dp).

## 5. Procurement (`procurement`)

**Tables**
- `pur_vendor_items`: vendor party, product, vendor_sku, price + currency, price_uom, min_order_qty, `lead_time_days`, valid_from/valid_to, `superseded_by_id`, source/provenance. Append-only versions; changes create a new row, so history is kept.
- `pur_requisitions` (PR-YYYY-NNNN): draft -> submitted -> approved | rejected -> closed.
  - Lines: product, `qty_requested`, uom, required_by, demand links (so_line_id, wo_material_id, shortage snapshot), suggested vendor_item_id, `qty_ordered` (sum of PO lines).
- `pur_purchase_orders` (PO-YYYY-NNNN): vendor, currency, status draft -> pending_approval -> approved -> sent (marked sent; actual delivery goes through the channel adapter) -> partially_received -> received -> closed. Also cancelled. `approved_version`.
  - Any edit after approval clears the approval and returns the PO to draft.
  - Lines: product, `qty_ordered`, uom, unit_price (snapshot from vendor_item, or an override with reason), `vendor_item_id`, `lead_time_days_assumed`, `expected_date`, requisition_line_id, `qty_received`, `qty_accepted`, `qty_rejected`, `qty_cancelled`, `over_receipt_tolerance_pct` (default 0).
  - `qty_outstanding = qty_ordered - qty_accepted - qty_cancelled` (generated). CHECK accepted + rejected <= received.
- `pur_grns` (GRN-YYYY-NNNN): PO, warehouse, vendor challan/invoice refs, received_at, status draft -> posted.
  - Lines: po_line_id, qty_received, lot (board lots with supplier ref and optional measured dimensions).
- `pur_vendor_bill_handoffs`: vendor bill no/date/amounts as entered, lines (grn_line, qty_billed, unit price), `match_status` in {matched, qty_mismatch, price_variance, pending}, handed_off_at, accounting sync ref.

**Algorithms**
- **Shortages** (deterministic query, `GET /inventory/shortages`). Per (product, warehouse):
  - demand = unreserved remaining on confirmed stock SO lines + (required - issued - reserved) on released WO materials;
  - supply = available + outstanding on approved POs;
  - shortage = max(0, demand - supply) plus reorder-rule triggers, each with source evidence;
  - "Create requisition" turns the selected shortages into draft PR lines.
- **Receiving.**
  1. Lock the PO line.
  2. Require `received + q <= ordered * (1 + tol) - cancelled`.
  3. Post supplier -> qc_hold (or -> internal if the product has `qc_required=false`) and create lots.
- **QC.** An inspection posts accepted qty qc_hold -> internal and rejected qty qc_hold -> rejected, and updates the PO line. Rejected goods go back to the vendor on a Return challan.
- **Vendor bill match.**
  - billed qty <= accepted - previously billed;
  - price variance is compared with Decimal against a configured tolerance;
  - mismatches become exceptions;
  - the handoff goes to the accounting adapter (section 9).

## 6. Production (`production`)

**Tables**
- `prd_boms`: product, `version_no` (UNIQUE(company, product, version_no)), status draft -> approved -> retired, effective_from, output qty + uom. Lines: component, qty_per, uom, scrap_pct, `is_sheet_material`.
  - Approved versions are immutable. A BOM cycle is rejected at approval.
- `prd_routings`: versioned the same way. Operations: seq, work_center_id, setup_minutes, run_minutes_per_unit, `is_job_work`, job_work_party_id.
- `prd_work_centers`: kind internal/external, machine_count, efficiency_pct. `prd_capacity_exceptions`: work_center, date, available_minutes, reason. Daily capacity comes from company shifts x machines x efficiency, unless an exception applies.
- `prd_work_orders` (WO-YYYY-NNNN): product, pinned bom_version_id and routing_version_id, qty_planned, so_line_id, warehouse, status draft -> released -> in_progress -> completed -> closed. Also cancelled.
- `prd_wo_materials`: qty_required, `requirement_source` in {bom, cut_plan}, qty_issued, qty_consumed, qty_returned. Reservations use demand_type wo_material.
- `prd_wo_operations`: planned and actual minutes, status, job-work challan link.
- `prd_wo_outputs`: qty_good, qty_rework, qty_scrap, lot, posting.
- `prd_scrap_records`.
- Costing: `prd_cost_versions` (code, currency, status draft -> frozen, fx_snapshot_ids). `prd_cost_inputs`: cost_version, input_type in {material, labour_rate, machine_rate, job_work, overhead}, ref, amount + currency per uom, source and provenance. `prd_cost_rollups`: product, bom_version, routing_version, cost_version, input_hash, breakdown JSONB, total, `status` in {complete, incomplete}, `missing_inputs` JSONB.
- `prd_feasibility_checks` and `prd_simulations`: saved, read-only results.

**Postings**
- Issue: internal -> wip. Consumption: wip -> production. Return: wip -> internal. Output: production -> qc_hold or internal.
- QC rejects either go to a rework WO (linked to its parent) or are posted rejected -> scrap with a reason.
- Job work: the challan sends material to external_holding. The operation receipt posts external_holding -> production (consumption) plus the output, and updates the challan line's `consumed_qty`. Unprocessed material comes back on a Return challan.

**Release checks:** approved BOM and routing are pinned; materials are reserved, or the shortage is acknowledged with a reason by an authorised user; linked cut plans are released and, if oversize was assumed, physically verified.

**Cost rollup (deterministic)**
1. Explode the BOM recursively over approved versions effective on the cost-version date.
2. Material: `qty_per x (1 + scrap_pct) x input(cost_version, component, uom)`.
3. Labour/machine: `(setup/batch_qty + run) x rate`. Job work uses its rate.
4. Overhead: only explicit inputs.
5. An input that is missing, or in another currency without an FX snapshot, is added to `missing_inputs` and excluded. The total is labelled "partial".
6. Decimal context 28; storage rounding to 4 dp, ROUND_HALF_UP.
7. The same input_hash produces an identical result. Costing requires `production.view_costing` and is redacted from exports and AI context.

**Delivery feasibility: `assess_delivery(product, qty, warehouse, date)`. Read-only.**
- Evidence considered, in order:
  - available stock now, with the time of the last movement (stale beyond N hours is a flag);
  - outstanding approved PO quantity due by the date, with the lead-time assumption and its source vendor_item;
  - BOM and component availability;
  - routing minutes scheduled forward, first-fit, into the capacity calendar after the existing released load.
- Result: `feasible | at_risk | not_feasible | estimate`. Any missing input (no lead time, no routing times, no calendar, stale stock) forces `estimate` and lists the missing items.

**What-if simulation.** `simulate(scenario)` runs the reservation allocation and feasibility functions over an in-memory `AvailabilityOverlay` loaded from read-only queries. The service receives a session guarded by `before_flush` (raises if anything is pending), so it never writes movements. Saving a simulation stores only the result.

## 7. Sheet cutting optimiser (`cutting`)

**Pure packer package** `cutting/packer/` with no DB imports: `geometry.py`, `maxrects.py`, `guillotine.py`, `engine.py`, `remnants.py`, `checker.py`.

**Decision: own implementation, not rectpack.** rectpack only allows rotation globally per packer, exposes no guillotine cut tree, warns about float precision, and was last released in 2021.

**Units and coordinates**
- Integer deci-millimetres (dmm). mm input with more than 1 decimal place is a 422. Areas are integers in dmm squared, so all reconciliation is exact.
- Origin at the raw board's top-left. x runs along board length (the grain), y along width.

**Inputs**
- Per item: SKU (catalogue autocomplete via `GET /cutting/products`, which fills decor, thickness, length and width), decor_key (trimmed text, so leading zeros and "120.0" are preserved), thickness (normalised Decimal), length, width, qty, and `grain_rule` in {inherit, locked, free}.
- Settings defaults:
  - board 2440 x 1220, margin 5, gap 6;
  - `oversize_enabled=false` with `oversize_mm=10`;
  - mode {nested, guillotine} taken from the machine profile;
  - overproduction disabled;
  - `use_offcuts`.

**Groups.** Items group by (decor_key, thickness). Rotation is allowed only if the decor is not in `cut_grain_locks` and the item rule is not locked. A lock always wins. A blank decor is treated as locked and shows a warning.

**Board model** (per group, bins tried in order):
1. Measured offcut lots, smallest area first.
2. Selected board lots, using their measured dimensions.
3. Standard boards.

For standard boards with oversize enabled, `raw = (L + 2o) x (W + 2o)`, and the plan gets `requires_physical_verification=true`. Oversize is never applied to measured lots.

**Usable area** = `(raw_L - 2m) x (raw_W - 2m)` (offcuts use `offcut_margin_mm`).

**Kerf and gap model.** Each piece is inflated to `(l+g, w+g)` and the bin to `(U_L+g, U_W+g)`. Non-overlapping inflated rectangles mean real pieces are at least g apart and stay inside the usable area.

**Pre-check.** A piece fits if some allowed orientation fits the largest bin template. Unfit reasons:
- `exceeds_usable_board`;
- `grain_lock_prevents_rotation`: it would fit rotated, but rotation is locked;
- `board_supply_exhausted`: the lots ran out and standard boards are disabled;
- `max_boards_limit`.

Zero or negative dimensions are a 422 at validation.

**Nested mode (MaxRects)**
- Each board keeps a list F of maximal free rectangles.
- For each piece, in sort order, search all open boards x all f in F x allowed orientations.
  - The score is BSSF `(min leftover side, max leftover side)`, or BAF/BLSF in other runs.
  - Ties break on (board index, f.y, f.x, orientation 0 before 90).
  - If nothing fits, open the next bin template.
- Placing rectangle r:
  1. Every f that intersects r is replaced by up to 4 maximal sub-rectangles (left, right, top, bottom).
  2. **Prune** any f contained in another; for exact duplicates keep the first in deterministic order.
- Invariant: every f is disjoint from every placed rectangle.

**Guillotine mode (panel saw)**
- F is a set of disjoint free rectangles. Choose (f, orientation) by BAF, then BSSF, then position. Place at f's corner.
- Split with the Shorter-Leftover-Axis rule: `dw<dh` means horizontal first. This gives cut1 across the whole of f and cut2 inside the strip.
- Cuts are recorded in `cut_calc_cuts` (stage = tree depth, orientation, kerf start = real piece edge, extent, kerf width g).
- No free-rectangle merging, so the tree stays valid. The guillotine property holds by construction, and the independent `checker.is_guillotine` verifies it.

**Multi-start.** A fixed set of runs: sort orders {area desc, longest side desc, perimeter desc, length desc} x the mode's two scores. Pick the run by (unfit count, boards, minimum utilisation of the last board, run index). There is no time-based cutoff, so results are deterministic. Sync limit is 300 pieces; larger plans run as a durable worker job; the hard cap is 5,000.

**Overproduction (bounded).** After the required pieces are placed, if enabled:
- `cap_i = min(max_extra_qty, floor(required_i x max_extra_pct))`;
- extras are placed one at a time, round-robin by line_no, **into already-open boards only**;
- extra pieces are flagged `is_extra`, so `produced_i = placed_required_i + extra_i`.

When disabled, extra is 0. The UI shows the setting only with these semantics.

**Metrics**
- raw = sum of raw board areas; usable = sum of usable areas; placed = sum of real piece areas.
- `trim = raw - usable`; `scrap = usable - placed` (includes kerf and remnants).
- `efficiency_usable = placed/usable` and `efficiency_raw = placed/raw`, each 2 dp; `scrap_pct = 100 - efficiency_usable_pct`.
- An area lower bound `ceil(sum of inflated piece area / inflated bin area)` is shown. The UI says "Heuristic layout, not guaranteed optimal".

**Predicted offcuts.**
1. Select disjoint free rectangles greedily, largest first, subtracting each from the rest.
2. Clip them to the usable area, and subtract g on edges that touch a piece.
3. Keep those at least `min_offcut` (300 x 300) as *predicted* offcuts. They do not become stock until measured (section 3).

**Tables**
- `cut_settings` (one per company) and `cut_machine_profiles`.
- `cut_grain_locks`: UNIQUE(company, decor_key), label, updated_by/at.
- `cut_plans`:
  - `plan_number` CUT-YYYY-NNNN, name, status draft -> calculated -> released -> archived, plus a settings snapshot (columns).
  - `inputs_changed_since_calc`, `requires_physical_verification`, verified_by/at with measurements, duplicated_from_id, latest_calculation_id, version.
- `cut_plan_items`: CHECK length, width and qty > 0.
- `cut_calculations`: calc_no, algorithm_version, settings_snapshot, input_hash, result_hash.
- `cut_calc_groups`, `cut_calc_boards` (source, lot_id), `cut_calc_placements` (x, y, along-length, along-width, rotated, is_extra), `cut_calc_item_results` (required, placed_required, extra, produced, unfit, reason), `cut_calc_offcuts`, `cut_calc_cuts`.
- `cut_plan_links` (work_order_id, wo_material_id).

**Lifecycle**
- Calculating appends an immutable calculation. Reopening shows the stored latest calculation without recomputing. Editing inputs marks it stale.
- Duplicating copies inputs only.
- Verifying boards compares measured board dimensions with the assumed raw size. If measured >= assumed, the plan is verified; otherwise it needs recalculation.
- Releasing requires a WO link and verification when oversize was assumed. On release, sheet-material WO lines take `requirement_source=cut_plan` (boards per group) and pin the board or offcut lots.

**Exports.** Placements and summary CSV; a PDF with one page per board (SVG plus table); per-board SVG. The SVG viewBox is in mm, with a shaded margin band, labelled pieces, a rotation marker and dashed offcuts. The web canvas renders the same placements at true scale.

**Legacy endpoint.** `POST /cutting/calculate` (stateless) keeps parity.

## 8. Logistics (`logistics`)

**Tables**
- `log_packing_lists` (PL-YYYY-NNNN): order, challans, status draft -> final.
  - Lines snapshot the canonical packaging at creation: carton_qty, carton dimensions in cm, carton_cbm, gross/net kg with `weight_basis`, unit_weight_kg, packing type, fragile flag, source updated_at.
  - If the catalogue's packaging changes later, drafts are flagged stale; final lists are not changed.
- `log_shipments` (SH-YYYY-NNNN): mode, transporter party, status planned -> booked -> dispatched (set when the challan is issued) -> in_transit -> delivered (with evidence) or exception. Linked to challans and their postings. Attached documents.
- `log_tracking_refs`: type in {AWB, BL, LR, container, seal}, value.
- `log_container_profiles`: entered internal volume in m3, max payload kg, fill factor (entered, not assumed).

**Packing math (Decimal)**
- `full = floor(qty/carton_qty)`, `loose = qty - full x carton_qty`, `cartons = full + (loose>0)` (the part carton is flagged).
- `cbm = cartons x carton_cbm`, or from dimensions L x W x H / 1e6.
- Gross weight = full x carton gross + loose x unit weight. If the part-carton tare is unknown, the line is flagged as an estimate.
- Missing data or a stated-vs-dimension CBM conflict over 2% marks the line incomplete. The totals are then labelled partial, and finalising is blocked until a value is entered with a reason.

**Load suggestion** (read-only).
- First-fit decreasing by CBM, splitting lines by whole cartons into containers, respecting `capacity x fill_factor` and max payload.
- Output: number of containers, utilisation, and which constraint is binding.
- Labelled "volume/weight check only; no 3D stowage, stacking or carrier acceptance verified". Fragile or non-stackable lines are flagged for manual planning.

## 9. Finance, initial scope (`finance`)

**Tables**
- `fin_invoices`:
  - doc_type in {invoice, credit_note}, `draft_ref`, `document_number` (assigned **only at issue**, UNIQUE(company, doc_type, number)), series_id.
  - status draft -> pending_approval -> approved -> issued -> cancelled (via credit note).
  - party + billing snapshot, order_id, currency, fx_snapshot_id, issue_date, payment_due_days, due_date, tax_profile_id, tax_status, totals, approved_version, original_invoice_id.
  - Lines: so_line_id, challan_line_id, description, hsn_sac, qty, uom, unit price, amount, tax code/rate/amount from the profile only.
- `fin_tax_profiles`: business-entered scenarios and rates with a source reference, status draft or verified (verified_by/at).
- `fin_provider_configs`: kind in {e_invoice, e_way_bill, accounting}, status in {not_configured, demo, configured, verified}. The UI never shows "connected" unless status is verified.
- `fin_document_series`: prefix, reset_period in {calendar_year, financial_year_apr}.
- `fin_receipts` (RCPT-YYYY-NNNN): party, amount + currency, received_on, method, reference, bank account label, status recorded or voided (a void is a reversal record).
- `fin_receipt_allocations`: source_type in {receipt, credit_note}, source_id, invoice_id, same-currency amount, `reverses_allocation_id`. Immutable.
- `fin_account_mappings`, `fin_accounting_exports` (batch, adapter, file key, sha256), `fin_accounting_sync_items` (doc, external_ref, status in {pending, exported, acknowledged, rejected, mismatch}).

**Drafts.** Created from delivered-but-not-invoiced SO quantities, from charge lines (invoiced once), or manually. Amounts come from `pricing.calc`. Drafts are always allowed. Their PDF is watermarked "DRAFT - not issued / tax not configured" when applicable.

**Issue gate (`issuance_gate.check`).** Returns a list of blockers:
- series configured;
- company legal identity complete;
- party billing details complete;
- tax profile verified for the scenario;
- if the profile requires e-invoicing, the e-invoice provider is verified;
- an approval exists for the current version from an authorised user who is not the creator;
- recomputed totals equal the stored totals;
- per SO line, quantity <= delivered - invoiced + credited.

On issue, the number is assigned and `qty_invoiced` is updated, both in the same transaction.

**Credit notes.** Quantity and amount must not exceed what is still creditable. A Return challan with disposition credit suggests a draft credit note.

**Allocations.** Lock the receipt and invoice rows. The receipt's total allocations must not exceed its amount, and an invoice's allocations must not exceed its outstanding. Cross-currency allocation is deferred.

**Ageing.** Per (party, currency) as of a date: outstanding = total - allocations. Buckets: current, 1-30, 31-60, 61-90, >90. Amounts are never summed across currencies. An invoice with no due date is flagged.

**Adapters** (`finance/adapters/`).
- `AccountingAdapter.export(batch)` and `fetch_status(refs)`.
- `CsvExportAdapter`: journal-ready, formula-escaped. A missing account mapping blocks that document.
- `DemoAdapter`: labelled Demo.
- Reconciliation imports the accounting-side references and totals and lists mismatches.
- There is no general ledger, no tax filing and no bank payment execution.

## 10. File layout

- `orders/`: + `conversion.py`, `fulfilment.py`.
- `inventory/`: + `posting.py`, `reservations.py`, `counts.py`, `opening.py`, `availability.py`, `shortages.py`, `jobs.py` (projection check).
- `challans/`: + `movement_policy.py`, `returns.py`, `exports.py`, `templates/challan.html`.
- `procurement/`: + `receiving.py`, `matching.py`.
- `production/`: + `bom.py`, `capacity.py`, `costing.py`, `feasibility.py`, `simulation.py`.
- `cutting/`: + `packer/*`, `svg.py`, `exports.py`.
- `logistics/`: + `packing.py`, `load_planner.py`.
- `finance/`: + `issuance_gate.py`, `allocations.py`, `ageing.py`, `adapters/`.
- Migrations: one Alembic revision per module, including the immutability triggers.

**Web routes**
- `/sales/orders[/id]`
- `/operations/inventory/{positions,movements,reservations,counts,adjustments,opening,offcuts}`
- `/operations/challans[/new|/id|/id/print]`
- `/operations/purchasing/{requisitions,orders,receipts,vendor-prices}`
- `/operations/production/{work-orders,boms,routings,capacity,costing,feasibility}`
- `/operations/cutting[/planId]`
- `/operations/dispatch/{shipments,packing-lists,load-planner}`
- `/finance/{invoices,receipts,ageing,accounting}`

## 11. API (prefix `/api`; commands accept `Idempotency-Key`)

- **Orders:** `POST /sales/quotes/{id}/convert-to-order`; `GET /orders`, `GET|PATCH /orders/{id}`; `POST /orders/{id}/{confirm|hold|cancel|reserve|release-reservations|challans}`; `POST /orders/{id}/lines/{lid}/cancel`; `GET /orders/{id}/impact-preview`.
- **Inventory:** CRUD for `warehouses`, `locations` and `lots`; `GET availability|positions|movements|postings/{id}|shortages`; `POST postings/{id}/reverse`; `reservations` (GET, POST, `/{id}/release`); `POST relocations`; `adjustments` and `stock-counts` (CRUD plus `/freeze|/submit|/approve|/reject`); `opening-batches` (`/validate|/approve`); `offcuts` (GET, POST measure).
- **Challans:** `GET|POST /challans`; `GET|PATCH|DELETE /challans/{id}`; `POST|PATCH|DELETE /challans/{id}/lines[/{lid}]`; `POST /challans/{id}/{issue|receive|close|cancel|duplicate|returns|write-off}`; `GET /challans/{id}/reconciliation`; `GET /challans/summary`, `GET /challans/export.csv`, `GET /challans/{id}/document.pdf`.
- **Procurement:** `vendor-items`; `requisitions` (`/submit|/approve|/reject|/convert-to-po`); `purchase-orders` (`/submit|/approve|/mark-sent|/lines/{l}/cancel|/close`); `grns` (`/post`, `/lines/{l}/qc`); `vendor-bills`.
- **Production:** `boms` and `routings` (`/versions`, `/approve`, `/retire`); `work-centers`; `capacity`; `work-orders` (`/release|/reserve-materials|/issue|/consume|/return-material|/outputs|/operations/{o}/complete|/complete|/close|/cancel`); `qc`; `cost-versions` (`/freeze`); `POST cost-rollups`; `POST feasibility`; `POST simulations`.
- **Cutting:** `POST /cutting/calculate`; `plans` (CRUD, `/calculate|/duplicate|/verify-boards|/release|/archive`); `GET /cutting/plans/{id}/calculations/{n}`; `/export.csv|/export.pdf`; `/calculations/{n}/boards/{i}.svg`; `grain-locks` (GET, PUT, POST, DELETE `/{decor}`); `GET /cutting/products?search=`; `settings`; `machine-profiles`.
- **Logistics:** `packing-lists` (`/finalise`, exports); `shipments` (`/tracking-refs|/status|/documents`); `container-profiles`; `POST load-suggestions`.
- **Finance:** `invoices` and `credit-notes` (`/submit|/approve|/issue`); `receipts` (`/allocations`); `GET receivables/ageing`; `configuration`; `accounting-exports`; `accounting-reconciliations`.

**Permissions** follow `<module>.<action>` with scope:
- `orders.{view,create,confirm,cancel}`
- `inventory.{view,reserve,post,adjust,approve_adjustment,count,approve_count,approve_opening,receive_unplanned,reverse}`
- `challans.{view,create,edit,issue,close,cancel_issued,write_off,delete_draft,export}`
- `procurement.*`, `production.*` (including `view_costing`), `cutting.{view,plan,release,manage_grain_settings}`, `logistics.*`, `finance.{view,draft,approve,issue,record_receipt,allocate,export,configure}`

Every approver must be a different user from the creator.

## 12. Events

**Emitted.** Each event carries company, branch, subject refs, owner, due date and source version, which is what the briefing needs.
- `orders.sales_order.{created,confirmed,cancelled,completed}`, `orders.sales_order_line.cancelled`
- `inventory.reservation.{created,released,shortfall_detected}`, `inventory.stock.posted`, `inventory.posting.reversed`, `inventory.adjustment.pending_approval`, `inventory.stock_count.variance_submitted`, `inventory.opening_batch.pending_approval`, `inventory.projection.mismatch_detected`
- `challans.challan.{issued,closed,cancelled}`, `challans.return.received`, `challans.returnable.{due_soon,overdue}` (scheduled)
- `procurement.requisition.submitted`, `procurement.purchase_order.{pending_approval,approved,overdue}`, `procurement.goods_receipt.posted`, `procurement.qc.rejected`, `procurement.vendor_bill.{mismatch_detected,handed_off}`
- `production.work_order.{released,blocked,completed}`, `production.qc.failed`, `production.capacity.overloaded`, `production.cost_rollup.incomplete`
- `cutting.plan.{calculated,verification_required,released}`
- `logistics.shipment.{dispatched,delivered,exception}`, `logistics.packing_list.incomplete`
- `finance.invoice.{pending_approval,issue_blocked,issued,overdue}`, `finance.receipt.recorded`, `finance.accounting_export.{failed,mismatch_detected}`

**Consumed.** All consumers use `consumers.once`.
- `sales.quote.status_changed` (to won): suggest conversion; it is never automatic.
- `catalogue.packaging.updated`: flag draft packing lists as stale.
- `inventory.reservation.shortfall_detected`: refresh the shortage list and propose a draft PR.
- `procurement.goods_receipt.posted` and `production.work_order.completed` (output): suggest reservations for waiting demand.
- `challans.challan.issued`: suggest a draft invoice and update shipment status.

**AI tools (`tools.py`):** `get_stock_availability`, `preview_order_impact`, `propose_order_from_quote`, `propose_reservation`, `draft_challan`, `propose_stock_movement`, `optimise_cut_plan`, `assess_delivery`, `simulate_what_if`, `draft_requisition`, `draft_purchase_order`, `draft_invoice`, `get_receivable_ageing`.

## 13. Explicit future scope

- Inventory valuation and FIFO/average cost; a native general ledger and chart of accounts.
- Live Tally or Zoho Books adapters (needs the business's choice); GST, e-invoice and e-way-bill integrations; bank payment execution; cross-currency allocation.
- Carrier APIs; 3D container stowage.
- Guillotine stage limits and trim-cut sequencing for a specific saw; offcut grain rotation for non-rectangular remnants.
- Finite-capacity scheduling beyond first-fit; MRP time-phasing; serial numbers.
- Order amendment revisions; advance or proforma invoicing; delivery confirmation that posts in-transit -> customer for transporter handover.

## 14. Tests (H and I in detail)

**Infrastructure.** Integration tests run on real PostgreSQL through a pgserver session fixture (Docker is not required). Concurrency tests use threads with separate connections and a `threading.Barrier`. Property tests use hypothesis with `derandomize=True` in CI. A shared `assert_ledger_consistent(session)` helper checks:
- balances == SUM(movements);
- summaries == balances and active reservations;
- no stock-bearing balance below 0.


## Decisions
- **Write our own packer (MaxRects with free-rectangle pruning for nested layouts, plus a guillotine packer that records its cut tree) instead of using rectpack** — rectpack 0.2.2 (last release 2021) only allows rotation globally per packer, exposes no guillotine cut sequence, and warns about float precision. We need per-piece grain rules, offcut bins of different sizes, integer deci-mm geometry, deterministic tie-breaks and a cut list a panel saw can follow. The pure package is small and is proven by property tests and an independent guillotine checker.
- **Model kerf/gap by inflating each piece and the usable bin by g, with margin = edge trim and oversize = an assumed larger raw board** — Non-overlapping inflated rectangles provably give at least g between pieces and keep pieces inside the usable area, with exact integer metrics. Oversize changes only the assumed raw size and always marks the plan as needing physical verification before release.
- **Use a double-entry style ledger: each movement goes from one location to another; virtual locations (supplier, customer, production, scrap, adjustment, opening) may go negative** — Every quantity has an origin and a destination, so returns, job work, in-transit stock and reversals are symmetric and auditable. Ownership (company vs party) and external holding locations come out naturally.
- **Maintain balance and summary projection tables in the same transaction as each posting; reserving and posting lock the same summary row** — This gives a concrete row lock that serialises competing reservations and outbound postings (no oversell), lets DB CHECK constraints enforce non-negative stock, and keeps availability queries O(1). A nightly job compares the projections with the immutable ledger.
- **Each source event gets exactly one posting: UNIQUE(company, source_type, source_id, purpose) plus UNIQUE(idempotency_key)** — Dispatch and challan issue call the same function, and a shipment only references the posting. Retries, replayed events and double clicks therefore cannot decrement stock twice, and this is guaranteed by the database, not just application code.
- **The challan is the movement document for dispatch, transfer, job work, samples and returns; there is no separate delivery or transfer document** — This keeps the legacy semantics and avoids two documents competing to post. The policy matrix makes the stock effect of each type explicit, and invalid type/destination combinations are rejected.
- **Challan numbers are assigned at draft creation (legacy behaviour), never reused, with a yearly reset by company-local date; invoice numbers are assigned only at issue** — Users already refer to draft challan numbers. Invoice series need to be consecutive for issued documents, so drafts use draft refs and never consume a number.
- **Quote conversion is idempotent through UNIQUE(company_id, source_quote_id) plus a quote row lock and a create-or-return response** — This meets the 'cannot create duplicate orders' requirement even under concurrent or retried calls. Commercial amendments go through new quotes, so an order's snapshot always matches an accepted revision.
- **Return reconciliation keeps counters on the original line (returned, consumed, written_off) under a row lock, plus an immutable link table with a unique return_line_id** — Excess returns fail with the original line locked, and duplicate receipts are blocked by the unique link and the idempotent issue. Partial returns stay traceable line by line.
- **Before inventory go-live, and for migrated legacy challans, inventory_effect is none; after go-live, document-only challans are not allowed and non-stock items use explicit is_non_stock lines** — Slice 2 can deliver challan parity without fake stock. Legacy challans never create stock. After go-live there is no loophole for skipping stock movements.
- **Opening stock is posted only from an approved opening batch (approver is not the creator); it is rejected where non-opening movements already exist, unless flagged late_opening** — Meets the requirement for an explicit, approved migration and prevents counting stock twice.
- **Stock counts post the delta against a snapshot taken at freeze time (with a movement-sequence high-water mark), so warehouses do not need to stop moving stock** — Count variances are correct without blocking operations, and every adjustment is a traceable posting.
- **Simulation and feasibility are pure reads: an in-memory availability overlay on a session that raises if anything tries to write** — Guarantees 'simulation never writes real movements', and a test can check it mechanically.
- **Cost rollups use only inputs in an explicit cost version; missing inputs are listed and excluded, and the total is labelled partial** — Results are deterministic and honest (the same input hash gives the same result) and never fabricate or borrow costs from other versions.
- **Finance stops at operational documents and a CSV/demo accounting adapter, behind an issue gate that checks verified tax profiles and provider status** — Meets the initial scope without inventing GST or e-invoice rules or claiming statutory compliance. Drafts stay usable and clearly labelled.
- **Integration and concurrency tests use pgserver (bundles PostgreSQL 16, has Windows wheels)** — The Docker daemon is not running and there is no local PostgreSQL. Row-lock and NULLS NOT DISTINCT behaviour has to be tested on real Postgres, not SQLite.

## Risks
- MaxRects with pruning is O(F^2) per placement in pure Python: plans over a few hundred pieces may be slow; mitigated by a 300-piece sync limit, a worker job for larger plans, a hard cap of 5,000 pieces, and a performance budget test.
- Actual saw constraints (stage limits, trim cuts, blade kerf varying by machine) are unknown; the guillotine mode is unlimited-stage and may still need operator adjustment.
- Legacy oversize semantics (+10 mm per side) are inferred from the spec; if the business meant something else (e.g. pieces cut oversize), the setting's meaning needs confirmation before release workflows depend on it.
- Taking row locks on the summary row of busy products may cause contention or deadlocks during bulk operations; mitigated by the documented lock order, sorted locking and bounded retries, but bulk imports of opening stock should run in batches.
- Projection drift between balances and the ledger would be a serious defect; the nightly verifier detects it but cannot prevent it if a code path bypasses the posting engine. Code review rule: only posting.py writes balances (enforced by a test that greps for writes outside it).
- Packaging data quality (missing carton weights or CBM, alias conflicts) will make many packing lists incomplete at first; flows must handle partial totals gracefully.
- Ownership transfer timing for Transporter handover and export Incoterms is simplified (ownership passes at challan issue); this may not match how the business accounts for it.
- Tax, e-invoice and accounting-system choices are unknown; live invoice issuance stays blocked until they are configured, which may surprise users who expect invoices on day one.
- Party-owned (customer-supplied) material is modelled but its consumption rules are minimal; real job-work-for-customer flows may need richer rules.
- Ageing depends on structured payment_due_days; legacy free-text payment terms will often leave due dates unknown until users fill them in.

## Open questions
- Which accounting system will hold the statutory books (for example Tally Prime, Zoho Books or something else), and will an e-invoice/e-way-bill provider be used? This blocks only the live accounting and e-invoice adapters and live tax-invoice issuance; the CSV export adapter, drafts, receipts, allocations and ageing go ahead without it.

## Acceptance tests
- [H / unit] backend/tests/unit/cutting/test_packer_properties.py::test_no_overlap_with_gap (hypothesis; nested and guillotine modes; every pair of real pieces is separated by at least gap_dmm on some axis)
- [H / unit] backend/tests/unit/cutting/test_packer_properties.py::test_within_usable_bounds (every placement lies inside [margin, raw-margin] for its board, oversize on and off)
- [H / unit] backend/tests/unit/cutting/test_packer_properties.py::test_grain_locked_never_rotated (locked decor or item rule, or blank decor, means rotated=false and along-length equals item length)
- [H / unit] backend/tests/unit/cutting/test_packer_properties.py::test_guillotine_mode_is_guillotine_separable (independent checker.is_guillotine on inflated rects; recorded cuts reproduce the partition)
- [H / unit] backend/tests/unit/cutting/test_packer_properties.py::test_counts_reconcile (per item required == placed_required + unfit and produced == placed_required + extra; group totals equal the sum of items)
- [H / unit] backend/tests/unit/cutting/test_packer_properties.py::test_area_identity_exact (raw == placed + scrap + trim in integer dmm^2; scrap_pct == 100 - efficiency_usable_pct)
- [H / unit] backend/tests/unit/cutting/test_packer_examples.py::test_unfit_reasons (piece 2500x100 gives exceeds_usable_board; locked 1300x2400 gives grain_lock_prevents_rotation; zero dimension gives 422 at schema validation)
- [H / unit] backend/tests/unit/cutting/test_packer_examples.py::test_oversize_effect (2435x1215 piece is unfit with defaults (usable 2430x1210) and fits with oversize (usable 2450x1230); the plan is flagged requires_physical_verification)
- [H / unit] backend/tests/unit/cutting/test_packer_examples.py::test_overproduction_bounded (disabled gives zero extra; enabled gives extra <= min(max_qty, floor(required*pct)) with the same board count; extra pieces are flagged)
- [H / unit] backend/tests/unit/cutting/test_packer_examples.py::test_grouping_decor_thickness (decors '0120', '120' and '120.0' form separate groups; thickness 0.8 and 0.80 form one group)
- [H / unit] backend/tests/unit/cutting/test_packer_examples.py::test_deterministic_result_hash (same input and algorithm_version twice give an identical result_hash)
- [H / unit] backend/tests/unit/cutting/test_remnants.py::test_predicted_offcuts_disjoint_and_clear_of_pieces (offcuts are disjoint, at least gap from pieces, and inside the usable area)
- [H / integration] backend/tests/integration/cutting/test_plan_persistence.py::test_save_reopen_preserves_inputs_and_results (reopen returns the stored calculation byte-identical with no recompute; editing inputs marks it stale)
- [H / integration] backend/tests/integration/cutting/test_plan_persistence.py::test_duplicate_copies_inputs_not_results_and_exports_escape_formulas (CSV cells starting with =+-@ are inert; SVG and PDF render per board)
- [H / integration] backend/tests/integration/cutting/test_plan_release.py::test_release_blocked_until_oversize_verified_and_links_work_order (measured smaller than assumed gives needs_recalc; on release, WO materials use requirement_source=cut_plan)
- [H / integration] backend/tests/integration/cutting/test_grain_settings.py::test_grain_lock_writes_admin_only
- [H / e2e] apps/web/e2e/cutting.spec.ts::plan_calculate_save_reopen_svg (enter items via autocomplete, calculate, see the true-scale board SVG and table, save, reload, see the same result; keyboard operable)
- [I / integration] backend/tests/integration/orders/test_quote_conversion.py::test_concurrent_and_retried_conversion_creates_one_order (2 threads plus a retry give one order; the others get created=false with the same id; total EUR 5,760.0000 matches the snapshot)
- [I / integration] backend/tests/integration/orders/test_quote_conversion.py::test_conversion_requires_won_quote_and_linked_party_and_snapshot_survives_catalogue_change
- [I / integration] backend/tests/integration/inventory/test_reservation_concurrency.py::test_no_oversell_under_concurrency (on-hand 10, 8 threads reserve 3 each with a barrier; sum reserved <= 10; shortfall events emitted; ledger consistent)
- [I / integration] backend/tests/integration/inventory/test_posting_engine.py::test_no_silent_negative_stock_and_reserved_stock_conflict (an outbound posting beyond on-hand raises NegativeStockError and the ledger is unchanged; an unreserved outbound posting that would eat into reservations raises ReservedStockConflict)
- [I / integration] backend/tests/integration/inventory/test_ledger_immutability.py::test_update_delete_on_movements_and_postings_rejected_by_trigger
- [I / integration] backend/tests/integration/inventory/test_ledger_stateful.py::LedgerMachine (hypothesis stateful: random reserve, release, post, reverse, count and adjust steps keep balances == SUM(ledger), available == on_hand - active reservations, and stock-bearing balances >= 0)
- [I / integration] backend/tests/integration/challans/test_issue_return_cancel.py::test_issue_posts_exactly_one_movement (issue twice with the same key and with a new key, plus dispatch through logistics, gives exactly one posting; on-hand decremented once; SO line delivered 100, remaining 140)
- [I / integration] backend/tests/integration/challans/test_issue_return_cancel.py::test_partial_return_linked_to_original_line (returnable sample of 10: return 4 leaves outstanding 6 and the pending-return summary shows 6; a further 7 is rejected as excess_return; the same return issued twice creates one link; a line from another party's challan is rejected)
- [I / integration] backend/tests/integration/challans/test_issue_return_cancel.py::test_cancel_issued_creates_reversal (a reversal posting with reverses_posting_id; the original is kept; on-hand and SO delivered are restored; a second cancel or a cancel with returns linked is rejected; status history records actor and reason)
- [I / integration] backend/tests/integration/orders/test_cancellation.py::test_line_cancellation_releases_reservation_and_is_audited
- [I / integration] backend/tests/integration/flows/test_duplicate_events.py::test_replayed_outbox_events_have_single_effect (re-deliver challans.challan.issued and goods_receipt.posted to every consumer; counters, suggestions and briefing items are not duplicated)
- [I / integration] backend/tests/integration/flows/test_scenario_i_quote_to_return.py::test_end_to_end (approved opening batch, won quote, convert, competing reservations, partial challan, shipment link without posting, customer return linked to the line, second challan cancelled, assert_ledger_consistent)
- [I / unit] backend/tests/unit/challans/test_movement_policy.py::test_policy_matrix_all_types_and_invalid_combinations (Job Work is forced returnable and stays company-owned at external_holding; Transfer requires a Warehouse destination; Transporter requires a consignee)
- [I / unit] backend/tests/unit/challans/test_status_machine.py::test_valid_and_invalid_transitions_table
- [I / e2e] apps/web/e2e/order-fulfilment.spec.ts::convert_reserve_dispatch_partial_return (UI path; failed save shows an inline error with retry; issued challan is read-only)
- [F / integration] backend/tests/integration/challans/test_challan_permissions.py::test_scope_enforced_on_read_edit_issue_export_and_admin_only_draft_delete (guessed IDs return 404/403; deleted draft numbers are never reused)
- [F / integration] backend/tests/integration/inventory/test_numbering_concurrency.py::test_concurrent_challan_so_po_numbers_unique
- [L / integration] backend/tests/integration/challans/test_challan_documents.py::test_pdf_unicode_rupee_euro_pagination_terms_signatures_omit_internal_notes_and_csv_escaped
- [M / integration] backend/tests/integration/inventory/test_opening_batch.py::test_opening_requires_approval_by_other_user_and_legacy_challans_create_no_stock
- [invariant / integration] backend/tests/integration/production/test_simulation_readonly.py::test_simulation_and_feasibility_write_nothing (counts of postings, reservations and outbox rows unchanged; the write guard raises if a write is attempted)
- [invariant / unit] backend/tests/unit/production/test_cost_rollup.py::test_deterministic_and_missing_inputs_listed_partial_total
- [invariant / unit] backend/tests/unit/production/test_feasibility.py::test_missing_lead_time_or_capacity_yields_estimate_with_evidence
- [invariant / integration] backend/tests/integration/procurement/test_receiving.py::test_partial_grn_qc_accept_reject_quantities_and_over_receipt_rejected
- [invariant / unit] backend/tests/unit/logistics/test_packing_math.py::test_cartons_cbm_weights_and_incomplete_flags; test_load_planner.py::test_respects_capacity_and_payload_and_labels_estimate
- [invariant / integration] backend/tests/integration/finance/test_issuance_gate.py::test_draft_allowed_issue_blocked_without_verified_tax_profile_and_number_assigned_only_at_issue
- [invariant / integration] backend/tests/integration/finance/test_allocations.py::test_allocations_bounded_and_ageing_per_currency
- [invariant / contract] backend/tests/contract/test_openapi_operations.py::test_ops_endpoints_schema_and_idempotency_header_present
