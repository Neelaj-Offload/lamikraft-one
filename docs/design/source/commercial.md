> Design-workflow output (2026-10-12), kept as source material. Where it conflicts with docs/architecture/*, the architecture docs win.

# Parties, pricing and FX, commercial calculation engine, quotations, and custom products

# Parties · Pricing/FX · Commercial Engine · Quotes · Custom Products

## 0. What this subsystem owns and what it depends on
**Owns:** the basic party master (customer and vendor flags, contacts, addresses, tax IDs, customer types, agreement price lists), price lists with items and history, protected product costs, currencies, FX snapshots and FX policy, versioned commercial rule sets and the calculation engine, quotes (lines, revisions, status history, dispatch records, documents), and custom products (spec and sample history, promotion).

**Consumes these contracts from other designers:**
- **Identity:** `Actor` (user, company, branches, teams, effective permissions with scope) and `policies.require(actor, key, record)`.
- **Platform:** `next_document_number()`, `outbox.emit()`, `escape_like()`, `csv_safe()`, idempotency keys, structlog redaction registry.
- **Approvals:** `request_approval(target_kind, target_id, content_hash, approver_permission)` plus a decision callback that runs inside the same transaction.
- **Catalogue:** product snapshot, `search_products(filters, text, page, facets)`, `validate_new_product` / `create_product(payload, lineage)`, and canonical packaging (`carton_qty` after alias normalisation).
- **Others:** media/files (immutable object refs, attachments); notes service (with a policy callback); settings `get_document_identity(company, brand, kind)`; tasks/briefing (consume my events); channels (slice 3).

## 1. File layout
- `backend/app/core/money.py`: `CurrencyCode`, `Money`, and `quantize(amount, currency)` using minor units and rounding mode. It rejects floats.
- `backend/app/core/documents/{pdf_base.py,fonts.py}` and `backend/app/assets/fonts/NotoSans-{Regular,Bold}.ttf` with `OFL.txt`. Shared with challans.
- `backend/app/modules/parties/{models,schemas,service,router,events,tools,policies}.py`
- `backend/app/modules/pricing/{models,schemas,service,resolution,fx,costing,router,events,tools,policies}.py`
- `backend/app/modules/commercial/{engine (pure, no I/O),rules,models,service,router,events}.py`
- `backend/app/modules/sales/quotes/{models,schemas,service,lifecycle,revisions,duplication,currency_change,configurator,handlers,router,events,tools,policies}.py` and `documents/{view_model,pdf,csv}.py`
- `backend/app/modules/sales/custom_products/{models,schemas,service,lifecycle,promotion,exports,handlers,router,events,tools,policies}.py`
- `backend/migrations/versions/`: `*_parties`, `*_pricing_fx`, `*_commercial_rules`, `*_quotes`, `*_custom_products`
- `backend/app/seed/demo_commercial.py`: fictional data only. Nordhaus, Maison Clair and Berg & Co; oak tray at EUR 24 with carton 24; a prior won Nordhaus quote for 240 pcs; an FX rate labelled "Demo rate".
- Web: `apps/web/src/features/{parties,pricing,quotes,custom-products}`. Routes: `app/(app)/sales/{parties,quotes,custom-products}`, `/products/price-lists`, `/settings/{commercial,quotes,fx,customer-types}`, `/sales/quotes/[id]/print`.
- Tests: `backend/tests/{unit,integration,contract}/{commercial,pricing,parties,quotes,custom_products}` and `apps/web/e2e/{quotes,custom-products,price-lists}.spec.ts`.

## 2. Tables
Standard columns on every table: `id uuid7`, `company_id`, timestamps, actors, `version`, and `archived_at` where noted. Money is always `NUMERIC(18,4)` plus `CHAR(3)`.

### 2.1 Parties
- **customer_type:** `code` (seed: standard, dealer, distributor), `name`, `default_price_type`, `is_active`, `sort_order`. UNIQUE(company_id, code).
- **party:** `party_number` (P-NNNNN, immutable), `display_name`, `legal_name`, `is_customer`, `is_vendor`, `status` (prospect, active, inactive, blocked), `customer_type_id`, `country_code`, default currency/incoterm/payment terms, `preferred_language`, `owner_user_id`, `branch_id`, `notes`, `archived_at`.
  - CHECK(is_customer OR is_vendor). UNIQUE(company_id, party_number).
  - Indexes: (company_id, lower(display_name)), (company_id, owner_user_id), (company_id, is_customer, status).
- **party_contact:** `name`, `job_title`, `email`, `phone`, `is_primary` (partial unique, one primary per party), `archived_at`.
- **party_address:** `kind` (billing, shipping, registered, other), address lines, city, region, postal code, country, default flags, `archived_at`.
- **party_tax_identifier:** `scheme` (GSTIN, VAT, EORI, PAN, IEC, OTHER), `value` (normalised), country, optional `address_id`, `verification_status='unverified'`.
  - Partial UNIQUE(company_id, scheme, value) on live rows.
  - GSTIN gets a format check only; it is never claimed as verified.
- **Customer agreements** are `price_list` rows with `scope_kind=customer_agreement`. There is no separate agreements table.

### 2.2 Pricing, FX and costing
- **currency** (global): `code`, `symbol`, `minor_units`, `rounding_mode` (HALF_UP), `is_enabled`. Seeded with INR, EUR, USD, GBP.
- **price_list:** `code` (business key), `name`, `scope_kind` (standard, customer_type, customer_agreement), `party_id`, `customer_type_id`, `price_type` (domestic, export, sample, distributor), `currency`, `priority INT NULL`, `status` (draft, active, retired), `valid_from`/`valid_to`, `notes`, provenance (`source_kind` manual/import/migration, `source_ref`, `import_job_id`), activated/retired by/at, `retire_reason`.
  - CHECKs: an agreement requires party_id (and only an agreement has one); a customer_type list requires customer_type_id; valid_to ≥ valid_from.
  - UNIQUE(company_id, code). Indexes: (company_id, status, scope_kind, price_type, currency), (company_id, party_id).
- **price_list_item:** `product_id`, `product_key`, `unit_code`, `price_basis` (legacy text), `final_price` (≥ 0), `base_price` and `addon_price` with labels, `yield_qty_per_board`, `thickness_mm`, `moq` with `moq_unit_code`, `valid_from`/`valid_to`, `notes`, `display_sku`, `source_sheet`, `source_row`, `status` (active, retired), `superseded_by_item_id`.
  - No overlapping validity for the same (list, product, unit). The service checks this while holding the list row lock; add an `EXCLUDE USING gist` constraint as well if btree_gist is available.
  - Trigger: once the parent list is active, price columns are immutable. Only shortening `valid_to`, retiring, or setting `superseded_by` is allowed.
- **price_list_item_history** (append-only): `change_kind` (created, edited_draft, superseded, retired, list_activated, list_retired), `before`/`after` JSONB, `reason`, `actor`.
- **product_cost** (protected): `product_id`, `cost_version`, `unit_cost` + currency, `unit_code`, `components` JSONB `[{label, amount}]`, `source_kind`, `effective_from`. UNIQUE(product_id, cost_version).
- **fx_rate:** `base_currency`, `quote_currency` (1 base = rate quote), `rate NUMERIC(20,10) > 0`, `rate_date`, `source_kind` (manual, bank, ecb_reference, other), `source_reference NOT NULL`, `status` (proposed, approved, rejected, withdrawn), proposer and decider with timestamps, `is_demo`.
  - Partial UNIQUE(company, base, quote, rate_date) WHERE approved.
- **fx_policy** (one per company): `conversion_enabled=false`, `conversion_source_currency='EUR'`, `max_rate_age_days=7`, `require_second_approver=true`.

### 2.3 Commercial rules
- **commercial_rule_set:** `code='quote_commercial'`, `version_no`, `status` (draft, active, retired), `effective_from`, `params` JSONB validated by `rules.QuoteCommercialRulesV1`, approver. One active rule set per code.
- **v1 params:**
  - `thresholds = {EUR: {minimum_order_value: 5000.00, surcharge_amount: 400.00}}`
  - `applicable_line_types = [catalog, custom, manual]`
  - `surcharge_label`
  - `min_invoice_note_template`

### 2.4 Quotes
- **quote_settings** (per company): defaults EUR / FOB / 30 days / brand LK / price_type export; `review_policy` (never, always, on_exceptions; default never); `duplicate_copy_assignee=true`.
  - Numbering config lives in the platform `document_sequence`: template `LK-QT-{YYYY}-{seq:04}`, reset never (default) or yearly.
- **quote** columns:
  - **Identity:** `quote_number` (immutable), `branch_id`, `revision_no` (legacy "version"), `status`.
  - **Customer:** `party_id NULL` (required except for migrated rows), `party_link_status` (linked, legacy_unlinked, candidate), `contact_id`, `customer_snapshot` JSONB, plus flattened `customer_name`, `customer_country`, `customer_reference`, `customer_type_id`/`customer_type_code`.
  - **Terms:** `price_type`, `currency`, `incoterm`, `incoterm_place`, `payment_terms`, `validity_days` (1–365), `quote_date`, `valid_until`, `brand`, `remarks`, `min_invoice_note`, `surcharge_requested` (the toggle), `owner_user_id`, `commercial_rule_set_id`.
  - **Persisted totals:** `line_count`, `gross_subtotal`, `discount_total`, `net_subtotal`, `applicable_subtotal`, `surcharge_applied`, `surcharge_amount`, `tax_status`, `tax_total`, `grand_total NULL` (null while any line is unpriced), `totals_complete`, `calc_engine_version`, `calc_input_hash`, `calculation` JSONB, `calculated_at`.
  - **Review:** `review_outcome` (none, pending, approved, rejected), `review_content_hash`, `approval_request_id`.
  - **Outcome:** `latest_issued_revision_no`, `accepted_revision_id`, sent_marked at/by, `won_at`, `lost_at` with `lost_reason_code`/`text`, `cancelled_at` with `cancel_reason`, `archived_at`, `archived_from_status`, `deleted_at`/`deleted_by`.
  - **Origin:** `duplicated_from_quote_id`, `origin_channel`, `legacy_id`, `legacy_total_amount`.
  - Constraints: UNIQUE(company_id, quote_number); UNIQUE(id, currency) as an FK target.
  - Indexes: (company_id, status, updated_at DESC) on non-deleted rows, (company_id, owner_user_id, status), (company_id, party_id, quote_date DESC), (company_id, valid_until) WHERE sent, (company_id, lower(customer_name)).
- **quote_line** columns:
  - **Identity and type:** `line_key` (stable across revisions), `line_no`, `sort_order`, `line_type` (catalog, custom, manual), `manual_preset` (development, tooling, special_packaging, freight, samples, miscellaneous), `product_id`, `product_key`, `custom_product_id`.
  - **Descriptive snapshot:** `display_code`, `display_sku`, `product_name`, `description`, `dimensions_text`, `length_mm`, `width_mm`, `thickness_mm`, `decor_no` (text), `decor_name`, `finish`, `unit_code`.
  - **Quantity and price:** `quantity` (≥ 0), `currency`, `default_unit_price NULL`, `unit_price NULL`, `override_reason` with by/at, `discount_percent` or `discount_amount` (never both), `line_gross`, `line_discount`, `line_net`, `price_status` (resolved, manual, unavailable, ambiguous, fx_unavailable).
  - **Price provenance:** `price_list_item_id`, `source_currency`, `source_unit_price`, `fx_rate_id`, `price_resolution` JSONB.
  - **Snapshots:** `product_snapshot`, `media_snapshot`, `packaging_snapshot`, `commercial_snapshot` (all JSONB).
  - **Advisory inputs:** `carton_qty`, `product_moq`, `recommended_qty`, `advisories` JSONB.
  - **Notes:** `remarks` (customer-visible), `internal_note`, `restored_from_revision_no`.
  - **FK (quote_id, currency) → quote(id, currency):** DEFERRABLE INITIALLY DEFERRED, with no cascade.
  - **Anti-relabel CHECK:** `source_currency IS NULL OR currency = source_currency OR fx_rate_id IS NOT NULL`.
  - **Other constraints:** a CHECK that each line type has its required reference; UNIQUE(quote_id, line_no) DEFERRABLE.
- **quote_revision** (immutable; a trigger blocks UPDATE and DELETE): `revision_no`, `kind` (issued, review, checkpoint, legacy), `snapshot` JSONB (header, customer snapshot, lines, calculation, rule version), `content_hash`. Partial UNIQUE(quote_id, revision_no) WHERE issued.
- **quote_document:** `revision_id`, `file_id`, `sha256`, `renderer_version`.
- **quote_status_history** (append-only): `action`, `from_status`, `to_status`, `revision_no`, `reason_code`/`text`, `actor`, `channel`, `proposal_id`, `correlation_id`.
- **quote_dispatch:** `revision_id`, `method` (manual_mark, email, whatsapp), `recipient_snapshot`, `outbound_message_id`, `provider_status` (null for manual; queued, sent, delivered, read, failed, unknown), `is_demo`, `status_evidence`.

### 2.5 Custom products
- **custom_product:**
  - **Identity and type:** `custom_code` (CP-NNNN, immutable), `custom_type` (modified_catalog, fully_new, quote_only), `base_product_id`/`base_product_key`, `customer_specific_flag`, `party_id`, `legacy_customer_name`, `inquiry_reference`.
  - **Specification:** `product_name NOT NULL`, `description`, category and subcategory FKs, `dimensions_text`, `length_mm`, `width_mm`, `height_mm`, `thickness_mm`, `thickness_text`, `decor_no` (text), `decor_name`, `finish`, `shape`, `groove_count`, `bowl_count`, `handle_type`.
  - **Packaging:** `packaging_notes` plus `packaging` JSONB (carton/inner qty, packing type, unit weight in g, carton dimensions, CBM).
  - **Commercial and state:** `quoted_price` + `quoted_currency` (both or neither), `remarks`, `status`, `dormant_from_status`, `status_reason`, `owner_user_id`, `promoted_product_id`, `duplicated_from_id`, `archived_at`, `legacy_id`.
  - UNIQUE(company_id, custom_code). Indexes on status, party, lower(product_name), category.
- **custom_product_costing** (protected, versioned): `cost_amount` + currency, `components`, `basis_note`.
- **custom_product_spec_revision:** `revision_no`, `spec_snapshot`, `sample_reference`, `sample_sent_on`, `challan_id NULL`, `feedback`, `outcome` (pending, approved, rejected, superseded), `decided_at`, attachments. Immutable once decided, except for moving to superseded.
- **custom_product_status_history** (append-only).
- **custom_product_promotion:** `spec_revision_id`, `payload` JSONB, `payload_hash`, `status` (pending_approval, approved, executed, rejected, failed), `approval_request_id`, `executed_product_id`, `idempotency_key`.

## 3. Algorithms

### 3.1 Price resolution (`pricing/resolution.py`)
Input: `PriceContext{product_ids[], party_id?, customer_type_id, price_type, currency, unit_code, price_date (company-local)}`.
1. **Authorise.** Requires `pricing.price.resolve`. If the party is outside the actor's party scope, return 404.
2. **Build the tier list.** Customer agreement (if a party is set), then customer type (if set), then standard.
3. **Pass A: direct currency.** For each tier, run one set-based query for all products: active list, active item, matching price_type, list currency = quote currency, item unit = unit, and both list and item validity contain price_date. Then:
   - **0 matches:** record the reason, plus hints if the product exists in another unit or currency. Go to the next tier.
   - **1 match:** FOUND.
   - **More than 1 match:** use the unique highest non-null priority. Otherwise the result is AMBIGUOUS with candidates, and resolution does not fall through to the next tier.
   - **FOUND but final_price = 0:** UNAVAILABLE(ZERO_PRICE), with no fallthrough.
4. **Pass B: FX conversion.** Runs only when Pass A found nothing, `fx_policy.conversion_enabled` is true, and the quote currency differs from the source currency.
   - Repeat Pass A in the source currency.
   - Find an approved rate (source → target) with rate_date ≤ price_date and age ≤ max_rate_age_days; take the latest.
   - No rate: FX_UNAVAILABLE. No converted figure is shown.
   - Rate found: `unit_price = quantize(source × rate)` using HALF_UP, with full provenance recorded.
5. **Nothing found:** UNAVAILABLE, with an explanation that lists every tier checked.

**Output:** status, unit_price, currency, tier, price list (id/code/name), item_id, price_basis, product_moq, valid_to, source currency and price, FX details, explanations and candidates. Costs and the base/addon breakdown are never included.

**Activation check:** an active item in another list with the same scope target, price_type, currency, product and unit, and overlapping dates, is a conflict. The only exception is when both lists carry explicit, different priorities. Conflicts return 409 with a report.

### 3.2 Commercial engine (`commercial/engine.py`: pure and deterministic)
**Inputs:** currency, lines `{line_key, line_type, quantity, unit_price|None, discount, carton_qty, product_moq}`, `surcharge_requested`, the rule set, currency metadata, and the `TaxProvider` result.
- A float anywhere raises TypeError.
- `q(x)` quantizes to the currency's minor units with ROUND_HALF_UP.

**Per line:**
1. If there is no price, mark the line PRICE_MISSING.
2. `gross = q(qty × price)`.
3. `discount = q(gross × pct / 100)` or a fixed amount, never more than gross.
4. `net = gross − discount`.

**Advisories (never block):**
- **Order-value recommendation** (catalog and custom lines):
  - T = threshold for the quote currency. If none exists: NOT_EVALUATED.
  - If the price is missing or ≤ 0: UNAVAILABLE ("no positive EUR unit price; recommendation cannot be calculated").
  - Otherwise `r = ceil(T / unit_price)`. If carton_qty > 0, round r up to a carton multiple.
  - If qty < r: BELOW_ORDER_VALUE_RECOMMENDATION.
  - The basis is the quoted unit price (after override, before discount). It is labelled "order-value recommendation", never "MOQ".
- **Product MOQ:** qty < product_moq gives BELOW_PRODUCT_MOQ. This is the supplier/product MOQ from the price item.
- **Carton multiple:** a quantity that isn't a carton multiple gives NOT_CARTON_MULTIPLE (info).

**Totals:**
- `gross_subtotal`, `discount_total` (the adjustments) and `net_subtotal`.
- `complete` = every line has a price.
- `applicable` = Σ net over `applicable_line_types`. In v1 that is all lines, which matches legacy. It excludes tax and surcharge.

**Minimum order:** NOT_EVALUATED (no threshold), MEETS (applicable ≥ T) or BELOW (with the shortfall).

**Surcharge:** applies only when complete ∧ a threshold exists ∧ toggle on ∧ 0 < applicable < T. Reason codes: APPLIED, TOGGLE_OFF, AT_OR_ABOVE_MINIMUM, ZERO_SUBTOTAL, CURRENCY_NOT_EVALUATED, TOTALS_INCOMPLETE.

**Tax:** the v1 `TaxProvider` returns `not_calculated` with total 0 and the label "Excludes taxes".

**Grand total:** `net + surcharge + tax` when complete; otherwise null.

**Result:** carries the rule set id and version, `ENGINE_VERSION`, `input_hash` and template explanations.

**Persistence rule:** every header or line mutation recalculates and persists the result in the same transaction. The UI, API, PDF, print view, CSV and agent tools read only the persisted result.

### 3.3 Quote status machine (`POST /quotes/{id}/transitions {action, expected_version, reason…}`)
"editable" means draft (never issued) or revised (has an issued revision).

| Action | From → To | Permission | Guards and effects |
|---|---|---|---|
| submit_review | draft, revised → internal_review | edit | Must pass issuability checks. Creates a review snapshot and an approval request bound to the content hash. Quote is locked. |
| withdraw_review | internal_review → editable | edit | Cancels the approval request. |
| approve_review | internal_review (outcome=approved) | approve | Approver is not the requester. Hash must equal current content. |
| reject_review | internal_review → editable | approve | Reason required. |
| mark_sent | draft, revised, or internal_review(approved) → sent | send | Issuable; review is required by policy only if configured; hash must match. Creates the issued revision, sets valid_until, creates a manual dispatch record, queues the PDF job, emits issued and marked_sent. |
| revise | sent → revised | edit | revision_no + 1. |
| discard_revision | revised → sent | edit | Saves a checkpoint, then resets the working copy to the latest issued revision. |
| mark_won | sent → won | edit | Records accepted_revision_id (the latest issued revision by default). |
| mark_lost | sent, revised → lost | edit | Reason code required. |
| cancel | draft, internal_review, sent, revised → cancelled | edit | Reason required. Cancels any pending approval. |
| archive / unarchive | won, lost, cancelled ↔ archived | archive | Stores and restores archived_from_status. |
| correct_status | won → sent; lost → sent; cancelled → draft (never issued) or sent | correct_status | Reason required. won → sent is blocked while an active sales order exists (slice 4). |
| delete | draft never issued, nothing pending | delete | Soft delete. The number is never reused. |

- Terminal states: won, lost and cancelled are content-terminal; archived is terminal.
- `is_expired` = sent and valid_until < today. This is computed, never a status.
- **Issuable** means: party linked; at least one line; quantities > 0 (integral for countable units); totals complete; no unavailable or ambiguous price left without a manual price.

### 3.4 Revisions
- **Issue:** build a canonical content JSON (customer-visible header, customer snapshot, lines with snapshots, persisted calculation, rule version) → sha256 → insert an immutable `quote_revision`.
- **Compare (from, to or working copy):**
  - header diffs over a fixed field list;
  - line diffs by `line_key` (added, removed, changed, moved);
  - totals diffs from persisted values;
  - price-source, FX and rule-version changes flagged.
- **Restore(rev):** allowed from draft, revised or sent (from sent it performs an implicit revise).
  1. Save a checkpoint of the working copy, unless it is identical to the latest snapshot.
  2. Replace working lines with the snapshot lines: new ids, same `line_key`, historical prices and provenance kept.
  3. Restore header fields, except party and owner.
  4. Recalculate with the pinned rule set.
  5. Write a history entry; flag an advisory if totals differ from the source revision.

### 3.5 Currency change
- **Preview** builds a new price per line:
  - catalog lines: resolve in the new currency (direct list or FX);
  - custom lines: the custom product's own price in that currency, or FX;
  - manual lines and overridden prices: FX, or a user-entered price (override permission and reason).
- **Apply** (with expected_version) runs only when every line has a new price. It updates the header and all lines atomically.
- The deferred FK plus the provenance CHECK make a pure relabel fail at commit.
- The surcharge toggle is kept, but outside EUR the engine returns CURRENCY_NOT_EVALUATED.

### 3.6 Duplicate
- **Needs:** view on the source quote (within scope) plus `create`.
- **Header:** new number, status draft, revision 1, current active rule set. Header is copied; the following are cleared: customer_reference, review, sent, outcome and dispatch fields. Internal notes are not copied; a history entry links the source.
- **Owner:** the source owner if `duplicate_copy_assignee` is on and the actor's edit scope covers that owner; otherwise the actor.
- **Price mode:**
  - `keep` (default, legacy parity): advisories show current list-price differences.
  - `refresh`: lines that fail to resolve keep the source price and are flagged PRICE_NOT_REFRESHED.
- **Totals:** computed by the engine in the same transaction.
- **Options:** `from_revision_no`, or a target `party_id` (which re-snapshots the customer).

### 3.7 Numbering
- `document_sequence` is incremented with `UPDATE … RETURNING` inside the transaction that creates the record. The row lock serialises writers.
- A rollback releases the number. A committed number is never reused, because deleted drafts are soft-deleted.
- Keys:
  - `sales.quote`: YYYY is the local creation year; no reset by default (legacy continuity), yearly reset is optional.
  - `sales.custom_product`: CP-{seq:04}.
- Migration seeds each sequence to the legacy maximum + 1. The UNIQUE constraints are the final guard.

### 3.8 Custom product lifecycle and promotion
**Transitions:**
- inquiry → under_development, sample_stage, quoted, rejected, dormant
- under_development → sample_stage, quoted, rejected, dormant
- sample_stage → under_development, quoted, approved, rejected, dormant
- quoted → under_development, sample_stage, approved, rejected, dormant
- approved → quoted or dormant; → converted_to_standard only through promotion
- rejected → inquiry (reopen); dormant → its previous state
- converted_to_standard is terminal

**Rules:**
- A reason is required for reject, dormant and reopen.
- `approved` requires an approved spec revision.
- When a quote containing the product is issued, a system transition moves it forward to quoted from inquiry, under_development or sample_stage. Forward moves only, with full history.
- Archive is allowed when the product is rejected, dormant, converted, or has never been quoted.

**Promotion:**
1. **Request** (product must be approved with an approved spec revision). Build the master payload from the spec plus user-entered fields: product_key, display_sku, brand, taxonomy FKs, unit, canonical dimensions and packaging. Dry-run catalogue validation.
2. **Approval** is bound to `payload_hash`. The approver needs `catalog.product.create` and cannot be the requester.
3. **Execute** (idempotent): revalidate; call `catalog.create_product` with lineage (custom product, promotion, base product); set `promoted_product_id`; set status converted_to_standard.
   - Price items are only suggested as drafts, never activated.
   - Costing is copied only if the executor holds `pricing.costing.edit`.
4. Any payload edit after approval needs a fresh approval.

## 4. Invariants
- **Scope:** every query adds company plus permission scope to the SQL. Out-of-scope records return 404. Child rows (lines, revisions, documents, history, dispatches, spec revisions, costing) are reached only through an authorised root.
- **Mutations:** each one takes a root `FOR UPDATE` lock, checks `expected_version` (409 on mismatch), recalculates, persists, bumps the version and writes the outbox event, all in one transaction.
- **Immutability:** issued revisions, status histories and price-item history are immutable, enforced by triggers.
- **Money format:** money in the API is decimal strings. A contract test asserts this.
- **Price override:** a unit price different from the default (or set where no default exists), or any discount, requires `sales.quote.override_price`. A reason is required unless the actor holds `override_price_without_reason` (initially admin and management).
- **AI and prices:** agent tools never infer prices. They only pass prices the user stated, under the same checks.
- **Costing:** costing never appears in quote or custom-product read models, search, events, tool output, logs, or CSV (unless the actor has costing permission and sets `include_costing`).
- **Search:** always `ILIKE` with `escape_like`; never regex.

## 5. API (`/api`)
File downloads use session or header auth only, never `?auth=`. Every detail response returns server-computed `allowed_actions`.

**Parties**
- `GET/POST /parties`; `GET/PATCH /parties/{id}`; `POST …/archive|unarchive`; `GET /parties/duplicate-check`
- Contacts, addresses and tax IDs: CRUD-with-archive under `/parties/{id}/{contacts|addresses|tax-identifiers}`
- `GET/POST/PATCH /customer-types`

**Pricing**
- `GET/POST /price-lists`; `GET/PATCH /price-lists/{id}`; `POST …/activate|retire|duplicate`
- `GET/POST …/items`; `PATCH …/items/{iid}` (draft lists only); `POST …/items/{iid}/supersede|retire`
- `GET /price-list-items/{iid}/history`; `GET /products/{pid}/prices?as_of=`
- `POST /pricing/resolve`, `POST /pricing/resolve-batch`
- `GET/POST /products/{pid}/costs`
- `GET /currencies`; `GET/POST /fx-rates`; `POST /fx-rates/{id}/approve|reject|withdraw`; `GET/PUT /fx-policy`

**Commercial rules**
- `GET/POST /commercial/rule-sets`; `POST /commercial/rule-sets/{id}/activate`

**Quotes**
- `GET /quotes` with filters: status[], q, scope=mine|all, owner, party, currency, brand, dates, expiring_before, include_archived, page, sort
- `GET /quotes/summary`; `POST /quotes`; `GET/PATCH/DELETE /quotes/{id}`
- Lines: `POST /quotes/{id}/lines` (catalog, custom or manual); `PATCH/DELETE …/lines/{lid}`; `POST …/lines/reorder`
- `POST …/prices/refresh`, `POST …/currency-change`, `POST …/calculate-preview`, `POST …/transitions`, `POST …/duplicate`
- `PUT …/owner`, `POST …/link-party`
- Revisions: `GET …/revisions[/{rev}]`, `GET …/revisions/compare`, `POST …/revisions/{rev}/restore`
- `GET …/status-history`, `GET …/dispatches`, `GET …/document-view`, `GET …/pdf`, `GET …/lines.csv`
- `GET /quotes/export.csv`; `POST /quotes/configurator/resolve`; `GET/PUT /quote-settings`

**Custom products**
- `GET/POST /custom-products`; `GET/PATCH /custom-products/{id}`; `POST …/transitions|duplicate|archive|unarchive`
- `GET/POST …/costing`; `GET/POST …/spec-revisions`; `POST …/spec-revisions/{rid}/outcome`
- `POST/GET …/promotion`; `GET …/quotes`; `GET …/status-history`; `GET /custom-products/export.csv`

**Configurator**
1. Catalogue search filters before paginating, and returns facets narrowed to the whole result set plus the total; `exact_match` when the total is 1.
2. Resolve prices for the page in one batch.
3. Engine computes the recommendation; the packaging summary comes from canonical fields.

## 6. Permissions
Scoped keys are marked *.
- **Parties:** `parties.party.{view*,create,edit*,archive*}`, `parties.customer_type.manage`
- **Pricing:** `pricing.price.resolve`, `pricing.price_list.{view,manage,activate}`, `pricing.costing.{view,edit}`, `pricing.fx.{view,propose,approve}`, `pricing.fx_policy.manage`, `commercial.rule_set.manage`
- **Quotes:** `sales.quote.{view*,create,edit*,send*,approve*,archive*,correct_status*,assign*,delete*,export*,override_price,override_price_without_reason}`, `sales.quote_settings.manage`
- **Custom products:** `sales.custom_product.{view*,create,edit*,archive*,export*,promote*}`
- **Scope meaning:** own = `owner_user_id`; team = owner is in the actor's teams; branch = record branch; company = all.

| Legacy permission | New permission |
|---|---|
| view_all_quotes / view_own_quotes | `sales.quote.view` at company / own |
| create_quotes | `sales.quote.create` and `sales.custom_product.create` |
| edit_all_quotes / edit_own_quotes | `edit`, `send` and `archive` at company / own |
| delete_quotes | `sales.quote.delete` |
| override_price | `sales.quote.override_price` |
| export_quotes | `sales.quote.export` and `sales.custom_product.export` |
| view_products | `pricing.price.resolve` |
| edit_products | `pricing.price_list.manage` |
| view_costing | `pricing.costing.view` and `pricing.price_list.view` |

**Role templates:**
- **sales:** quotes at own scope; override requires a reason; no costing.
- **management:** everything at company scope, including approve and correct_status.
- **operations:** view all quotes (legacy parity), read-only.
- **admin:** all.

## 7. Documents
**`QuoteDocumentView`** is built from an issued snapshot, or from the working copy with a "DRAFT – not issued" watermark, plus the configured company identity (logo, legal name, address, GSTIN/IEC, optional bank details, terms).
- It excludes internal notes, line internal notes, override reasons, default prices, provenance, recommendations and costs.

**PDF (ReportLab Platypus):**
- Embedded Noto Sans covers €, ₹, £, extended Latin, Greek and Cyrillic.
- A4; `LongTable(repeatRows=1)` with Paragraph cells and `splitInRow` so long text wraps across pages.
- Columns: #, Product (SKU + name), Details, Unit price, Qty + unit, Total.
- The totals block stays together; the surcharge line appears only when applied; "Page n of m" footer.
- Draft PDFs render synchronously. Issued PDFs are rendered by the worker and stored with a sha256.

**Print view:** the Next.js print route renders the same view JSON, with `@page` A4 and a repeated `thead`.

**CSV:**
- List CSV columns: number, revision, status, dates, customer, country, reference, customer type, owner_name, created_by_name, currency, line_count, net_subtotal, discount_total, surcharge, tax_status, grand_total.
- A per-quote lines CSV is also available.
- Encoding: UTF-8 with BOM. `csv_safe` prefixes `'` to text cells that start with `= + - @`, TAB or CR.
- Only rows visible to the actor are exported.

## 8. Events
**Emitted:**
- `parties.party.{created,updated,archived}`
- `pricing.price_list.{created,activated,retired}`, `pricing.price_list_item.{superseded,retired}`, `pricing.fx_rate.{proposed,approved,rejected}`
- `commercial.rule_set.activated`
- `sales.quote.{created,updated,review_requested,review_approved,review_rejected,review_withdrawn,issued,marked_sent,delivery_status_changed,revised,won,lost,cancelled,archived,unarchived,status_corrected,duplicated,restored,owner_changed,currency_changed,deleted}`
- `sales.custom_product.{created,updated,status_changed,spec_revision_recorded,promotion_requested,promoted,promotion_rejected,duplicated,archived}`

**Payload:** ids, business keys, owner, branch, party, status, revision, version, currency, `grand_total` (string), valid_until, actor, correlation id. Never costing or notes.

**Consumed:**
- approval decisions, as in-transaction callbacks (quote review, FX, promotion);
- `sales.quote.issued` (PDF job, custom product moves to quoted);
- `channels.message.status_changed` (slice 3);
- `sales.order.*` (slice 4, correction guard).

**Used by tasks and briefing:**
- `created` gives the owner a "Review draft…" next action; `review_requested` gives the approver a task.
- `quotes.service.list_expiring()` feeds quote-expiry items.
- `superseded` events flag affected open quotes.

## 9. Agent tools (slice 3)
Tools: `resolve_party`, `resolve_price`, `calculate_quote`, `find_repeat_quote_basis`, `draft_quote`, `revise_quote`, `request_quote_review`, `propose_quote_transition`, `search_custom_products`, `draft_custom_product`.
- `find_repeat_quote_basis` uses the latest won quote (falling back to the latest sent) matching the product hint. If several products match, it asks a clarifying question.
- `revise_quote` takes typed changes: set_quantity, add/remove line, set_currency.
- `propose_quote_transition` creates a proposal bound to the content hash and version. Permissions are rechecked at execution.
- The server injects identity, and tool outputs never include costing.

## 10. Frontend
- **Parties:** list and detail, with tabs for contacts, addresses, tax IDs, agreements, quotes, custom products, history and notes.
- **Quote list:**
  - Status tabs including Revised, Cancelled and Archived, with server counts.
  - Search; a Mine/All toggle shown only when the user's scope is wider than own; real paging; CSV export.
- **Quote workspace:**
  - Header form with a party picker that can create a prospect inline.
  - Line grid with debounced, versioned inline edits and a conflict banner.
  - Configurator drawer, plus custom-line and manual-line (preset chips) dialogs.
  - Summary panel showing the engine's values and explanations; the toggle is disabled outside EUR, with the reason shown.
  - Action bar driven by `allowed_actions`.
  - Tabs for revisions (compare and restore), history, notes, attachments and dispatches; print view.
- **Custom products:** list, detail (with a Costing tab only when permitted), and edit.
- **Price lists:** item grid; supersede, activate and retire, with a conflict report; history drawer.
- **Settings:** commercial rules, quote defaults and numbering, FX, customer types.
- **Money display:** formats server-provided decimal strings and never does arithmetic on them.

## 11. Worked examples
- **C:**
  - Fixtures: Nordhaus (standard customer type, DE); oak tray (pcs, carton 24); standard export EUR list item at 24.0000; a prior won quote for 240 pcs.
  - Draft: 240 × 24.0000 gives gross and net 5,760.00 and applicable 5,760.00 (minimum MEETS). Surcharge is AT_OR_ABOVE_MINIMUM. Grand total EUR 5,760.00, excluding taxes.
  - Recommendation 216 ≤ 240, and 240 is a carton multiple. Status draft; owner = requester; a review task goes to the owner.
  - Later the item is superseded at 26.00 and the product renamed. The quote still shows 24.0000 and 5,760.00 with the old name, plus a PRICE_CHANGED_SINCE_SNAPSHOT advisory. Only an explicit refresh changes it.
- **D:**
  - Recommendation: ceil(5000/24) = 209, rounded up to the carton multiple = 216.
  - 200 × 24 = 4,800.00: toggle off gives 4,800.00; toggle on gives 400.00 surcharge and 5,200.00.
  - 200 × 25.00 = 5,000.00: no surcharge.
  - Discount case: 250 × 24 = 6,000 less 20% = net 4,800.00, so the surcharge applies.
  - Price 0 or missing: recommendation UNAVAILABLE, grand total null, issuing blocked.
  - USD: no surcharge, minimum NOT_EVALUATED.
- **E:**
  - Approved EUR→USD rate 1.0850 dated 2026-10-09: 26.04 USD per unit, total 6,249.60.
  - With no approved rate, applying the change returns 409 and the quote stays unchanged.

## 12. Build order
1. **Slice 1:**
   - money/currency core, the engine with rule set v1, minimal parties, seeded price lists with Pass A resolution;
   - quote header and catalog/manual lines, snapshots, numbering and concurrency;
   - list (mine/all, status, search), plus review, mark_sent, cancel and draft delete with the issued revision;
   - PDF and print, scope enforcement, created/review/issued events; scenarios C and D.
2. **Slice 2:**
   - full parties; price list create/edit/activate/retire, supersede and history; product_cost;
   - FX with approval, Pass B and currency change;
   - the full status machine with corrections and archive; compare and restore; duplicate; custom lines; full configurator; CSVs; settings UIs; rule-set versioning;
   - all of custom products, including promotion; notes, search and completeness providers;
   - legacy bug regressions; scenarios E, F (without the proposal parts) and L.
3. **Slice 3:** agent tools; proposal hash binding; channel send (demo) and delivery reconciliation; the proposal parts of F.
4. **Slice 4:** won → order hand-off; correction guard; sample challan link on spec revisions.
5. **Slice 5:** legacy migration mappings (quotes, revisions, custom products, prices, party candidates, sequence seeding, discrepancy report); margin view; price-change what-if for open quotes.
6. **Slice 6:** isolation and acceptance sweep.

## 13. Future scope
- FX-derived threshold equivalents (needs an approved rule)
- automated ECB/bank FX feed adapter
- converting prices between units
- header-level discounts and tiered quantity pricing
- a GST/VAT engine via finance integrations
- party merge
- customer-portal acceptance and e-signature
- quote templates
- complex-script (Devanagari) PDF shaping, if not verified in slice 2


## Decisions
- **Generate PDFs with ReportLab Platypus and embedded Noto Sans TTF fonts (OFL), not WeasyPrint.** — ReportLab is pure Python and runs on the Windows dev machine without GTK/Pango. LongTable repeatRows repeats table headers, splitInRow (in-row splitting, since 3.6.10) breaks tall rows across pages, and Paragraph cells wrap text. Noto Sans covers the euro, rupee, pound, Latin-extended, Greek and Cyrillic glyphs that the legacy core Helvetica (Latin-1) could not.
- **Price resolution is tier-first (customer agreement, then customer type, then standard) using the quote currency directly; FX conversion is a second pass, only when policy enables it and an approved, dated rate exists.** — This follows the required order (tier, then currency, unit, date). It prefers a real list in the selected currency over a converted figure, and it is deterministic and explainable through provenance.
- **An ambiguous match at a higher tier returns AMBIGUOUS and does not fall through to a lower tier. Explicit, unique priority resolves ties. Overlaps are also rejected at list activation.** — Falling through would silently apply a less specific price. Checking at both write time and read time guards against overlaps that appear as validity dates shift.
- **Items on an active price list are immutable. A price change is an effective-dated supersede (the old row gets valid_to and a new row is inserted), with an append-only history table.** — This provides price history and exact provenance: a quote line's price_list_item_id always points to the exact price that was used. It also fixes the legacy gap of no edit path (bug #15) without in-place mutation.
- **Block relabelling at the database level: a deferred composite FK on quote_line (quote_id, currency) to quote(id, currency), plus a CHECK that currency = source_currency or fx_rate_id is set.** — Scenario E requires that relabelling be impossible, not merely discouraged. Changing only the header currency, or changing a line's currency without FX provenance, fails at commit.
- **One pure, Decimal-only commercial engine. Its result is persisted on the quote in the same transaction as every change, and the UI, API, PDF, print view, CSV and agent tools read only the persisted result.** — Removes the legacy disagreement over surcharges (bug #3) and over totals and CSV counts (#2, #4). It also gives a verifiable input hash and engine/rule versions for audit.
- **Rule set v1: applicable subtotal = net totals of all line types after line discounts, excluding tax and the surcharge. Thresholds exist only for explicitly configured currencies (EUR 5,000 minimum, EUR 400 surcharge). The included line types are a versioned rule parameter.** — Undiscounted legacy cases match exactly, as required (legacy summed all lines), and the requirement's discount rule is honoured. No foreign-currency threshold is invented.
- **The order-value recommendation uses the quoted unit price (after override, before discount): ceil(threshold / price), rounded up to a carton multiple. It is labelled separately from the product MOQ held on the price item.** — It reflects the actual order value after an override. It is identical to legacy for non-overridden lines (24 with carton 24 gives 216). Scenario D requires it to be distinct from supplier/product MOQ.
- **Tax is not calculated in v1. A TaxProvider interface returns not_calculated, and totals are labelled 'Excludes taxes'.** — The prompt forbids fabricating GST or VAT rules. Scenario D totals are stated before taxes.
- **Quote numbers are assigned at creation from an atomic per-company document sequence. Drafts are soft-deleted so numbers are never reused. The default is no yearly reset (legacy continuity); yearly reset is configurable.** — Preserves the LK-QT-YYYY-NNNN format and the legacy counter, fixes the race (bug #13), and lets migration seed the sequences safely.
- **Issued revisions are immutable snapshots, enforced by a DB trigger. They are created at issue time, plus review and checkpoint snapshots. Restore copies a snapshot into the working copy as a new draft version after checkpointing the current state.** — Satisfies 'immutable issued revisions, compare, restore without overwriting history'. A content hash binds approvals to exact content.
- **Review approval is tracked as review_outcome plus a content hash while the status stays internal_review. There is no extra 'approved' status.** — Keeps the eight required statuses. A content change after approval invalidates it (scenario F).
- **All status changes go through one transitions endpoint with an explicit table of allowed transitions. Correction paths (won/lost/cancelled back to an open status) require a management permission and a reason, and are guarded against existing sales orders.** — Fixes legacy bug #1 (cancelled and archived failing) and the absence of transition rules. The correction paths are lawful and audited.
- **Price overrides and discounts require sales.quote.override_price. A reason is required unless the actor also holds sales.quote.override_price_without_reason (granted initially to admin and management).** — Expresses the legacy role policy ('sales must give a note') as server-enforced permissions rather than role-string checks. Legacy enforced it only in the UI.
- **Protected costing lives in separate tables and endpoints (product_cost, custom_product_costing). Read models never contain costing fields.** — A missing field cannot leak. This makes the redaction required by scenario E structural across APIs, search, events, exports, logs and model context.
- **Out-of-scope records return 404 on every root and child endpoint, and all child rows are reached only through the authorised root.** — Closes the legacy IDOR on quotes (security 10.2 #2) without revealing whether a record exists (scenario F).
- **Customer agreements are price_list rows with scope_kind=customer_agreement and party_id. Customer types carry a default_price_type.** — One price-list model covers all three tiers, which is the simplest possible schema. price_type stays a list attribute (legacy) while the customer type drives defaults.
- **No automatic price conversion between units in v1. A unit mismatch gives UNAVAILABLE with a hint.** — Converting a per-sheet price to per-piece needs a verified yield or conversion. Guessing would be an invented price.
- **Custom products move automatically to 'quoted' (forward moves only) when a quote containing them is issued. Promotion creates a master product through the catalogue service, with an approval bound to a payload hash and recorded lineage.** — Deterministic, auditable lifecycle automation. Promotion becomes a real validated record instead of the legacy unused boolean.
- **Duplicating a quote keeps source prices by default, with advisories showing current list-price differences; a refresh mode is available and is what the agent's repeat-quote path uses. The source owner is copied only when the actor's scope covers that owner. customer_reference is cleared.** — Default duplicate behaviour matches legacy, fixes bug #2 (real totals, assignee), and lets scenario C use current prices.
- **CSV exports are UTF-8 with BOM and pass every text cell through csv_safe (formula escaping). Totals and line counts come from persisted fields, and creator and owner names come from the users table.** — Fixes bug #4. Euro and rupee signs open correctly in Excel. Formula-like text stays inert.

## Risks
- ReportLab complex-script shaping (for example Devanagari or Hindi customer names) is only preliminary in recent versions. Latin, Greek and Cyrillic plus the euro and rupee glyphs are safe. Devanagari output must be verified in slice 2 and documented as a limitation if it fails.
- The btree_gist exclusion constraint may not be available in the pgserver-bundled Postgres. The service-level overlap check under a list row lock is authoritative either way; the DB constraint is added only if the extension loads.
- Deferred composite FKs and DEFERRABLE unique constraints need careful SQLAlchemy and Alembic handling (renumbering lines, changing currency). They must be covered by integration tests against real Postgres, never SQLite.
- Price precedence is a business policy (an agreement in another currency versus a standard list in the quote currency). The implemented rule is tier-first with direct currency preferred. Owners may later want an agreement price converted instead; that would need a new policy version.
- Number continuity: if migration does not seed the sequences from legacy maximums before go-live, inserts collide with the unique constraints. This must be a migration checklist gate.
- Legacy totals were computed with floats and inconsistent surcharge logic, so historical quotes will show discrepancies. They are reported, never rewritten. Users may initially distrust differing numbers on new revisions.
- The slice 1 vertical path depends on minimal approvals, outbox and tasks primitives from other designers. If they slip, quote review and next-action items stall.
- Large quotes (hundreds of lines) make snapshot JSON and synchronous draft PDF rendering heavier. Monitor render time; if needed, move draft rendering to the worker with a progress state.
- Rounding policy (line-level HALF_UP to minor units, FX-converted unit prices rounded to 2 decimals) is an assumption the business accountant should confirm before live export quotes.
- Auto-transitioning custom products to 'quoted' on issue could surprise users if quotes are issued and then corrected. A status correction does not roll it back, and the transition is visible in history.

## Acceptance tests
- [C / integration] test_scenario_c_nordhaus_repeat_quote: the seeded fictional Nordhaus party, oak tray (pcs, carton 24) and standard export EUR list at 24.0000. find_repeat_quote_basis plus draft_quote (refresh mode) produce a draft with one line, 240 x 24.0000 = 5,760.00 EUR, minimum MEETS, surcharge AT_OR_ABOVE_MINIMUM, grand_total 5760.00, status draft, owner = actor, and a sales.quote.created outbox row whose payload has owner and branch.
- [C / integration] test_quote_snapshot_immune_to_catalog_change: after supersede_item to 26.00 and a catalogue rename, GET /quotes/{id} still shows 24.0000, 5,760.00 and the old product_name, with advisory PRICE_CHANGED_SINCE_SNAPSHOT. Only POST /prices/refresh changes it to 26.00 and 6,240.00.
- [C / integration] test_quote_created_event_yields_owner_scoped_next_action: a tasks consumer creates a 'Review draft quote' item for the owner only. Another sales user's briefing and search never show it.
- [C / e2e] quotes.spec.ts 'prepare Nordhaus usual oak tray quote': the Today command (demo adapter) opens the draft workspace showing 240, EUR 24.00 and EUR 5,760.00 with 'Draft', the review action is visible, and the briefing item links to the quote. Checked at desktop and mobile sizes.
- [D / unit] test_engine_recommended_quantity: (24, carton 24) gives 216; (24, carton 0 or None) gives 209; price 0 or None gives UNAVAILABLE with an explanation and no exception; a USD quote gives NOT_EVALUATED; a negative price is rejected; a float input raises TypeError.
- [D / unit] test_engine_surcharge_table: EUR 4,800 with toggle off gives 4,800.00 (TOGGLE_OFF); toggle on gives 400.00 and 5,200.00; 5,000.00 with toggle on gives no surcharge; 4,999.99 with toggle on gives 5,399.99; a zero subtotal gives no surcharge; USD 4,800 with toggle on gives none (CURRENCY_NOT_EVALUATED); an incomplete quote gives TOTALS_INCOMPLETE and a null grand total.
- [D / unit] test_engine_discount_applicable_subtotal: 250 x 24 = 6,000 gross less 20% = net 4,800, so the surcharge applies with the toggle on. Tax is never in the applicable subtotal. Undiscounted legacy fixture quotes match the legacy PDF formula exactly.
- [D / unit] test_engine_properties (hypothesis): grand = net + surcharge + tax; the surcharge is non-zero only when currency is EUR and 0 < applicable < 5000 with the toggle on; the recommendation x price >= 5000, is a carton multiple, and is minimal; results are deterministic for identical input hashes.
- [D / integration] test_all_outputs_agree: for EUR 4,800 quotes with the toggle on and off, the totals from the API JSON, PDF text extraction, list CSV and lines CSV, and the print view (Playwright DOM) are identical strings. Persisted calc_input_hash equals a recomputation.
- [E / integration] test_currency_change_direct_list: switching an EUR quote to USD when a USD export list exists uses the USD item, records provenance, and recalculates totals.
- [E / integration] test_currency_change_blocked_without_fx: with no USD list and no approved rate, the preview shows the line blocked and apply returns 409 with per-line reasons. The quote remains EUR with unchanged amounts and version, and other edits still work.
- [E / integration] test_currency_change_with_approved_fx: an approved EUR to USD rate of 1.0850 dated 2026-10-09 (proposer is not the approver) gives line 26.04 USD and total 6,249.60 with fx_rate_id. A stale rate beyond max age, or a self-approved rate, is rejected.
- [E / integration] test_db_rejects_currency_relabel: raw SQL that changes a line's currency without fx_rate_id violates the CHECK, and changing the header currency alone fails the deferred FK at commit.
- [E / integration] test_costing_redaction: a sales user's custom product detail, list, CSV (even with include_costing=true), global search, agent tool outputs, the model-context builder, outbox payloads and captured logs contain no costing keys or values. A management user gets costing only through the costing endpoints.
- [F / integration] test_quote_idor_matrix (parametrised): sales user B against user A's quote. GET, PATCH, lines POST/PATCH/DELETE, reorder, transitions, revise, restore, compare, duplicate, owner, pdf, lines.csv, document-view, status-history and notes PUT all return 404, and the database is unchanged. export.csv excludes A's quotes.
- [F / integration] test_custom_product_and_party_scope: an own-scope user cannot edit, transition, duplicate or export another owner's custom product, or read an out-of-scope party's agreement price through /pricing/resolve.
- [F / integration] test_proposal_revoked_permission_blocks_execution: a mark_sent proposal is created, sales.quote.send is then revoked, and executing it returns 403 with the quote still unsent.
- [F / integration] test_changed_content_invalidates_approval: after review approval, changing a quantity makes mark_sent fail with 'approval stale', and a new review is required.
- [F / integration] test_concurrent_quote_and_custom_numbering: 40 concurrent create_quote calls on separate connections produce 40 unique, gap-free LK-QT-2026-NNNN numbers, and likewise for CP-NNNN. A rolled-back transaction does not consume a number, and deleted drafts never reuse one.
- [F / integration] test_optimistic_concurrency: two line edits with the same expected_version give 200 then 409 carrying the current version, with no lost update.
- [L / integration] test_quote_status_machine_table: every allowed transition succeeds, every other pair returns 409 with allowed_actions, cancelled and archived work (legacy bug 1), and correction paths need a reason and permission. Status history is append-only (an UPDATE raises).
- [L / integration] test_quote_duplicate: real totals (not 0), new number, draft status, customer_reference cleared, owner per policy (manager keeps assignee, sales actor becomes owner), internal notes not copied, keep and refresh price modes.
- [L / integration] test_revisions_compare_restore: an issued revision is immutable, compare reports added/removed/changed lines by line_key and the total deltas, and restore creates a checkpoint plus a new draft version while leaving issued revisions intact.
- [L / integration] test_quote_list_filters: status tabs including revised, cancelled and archived; mine/all; owner, party, currency and expiring filters; paging totals; search with regex/LIKE metacharacters ('.*(a+)+$', '%_') treated literally.
- [L / integration] test_quote_csv: correct line_count, creator and owner names, net, surcharge and grand totals, UTF-8 BOM with euro and rupee signs intact, and cells such as '=HYPERLINK(...)', '+1', '-2', '@x' prefixed with an apostrophe.
- [L / integration] test_quote_pdf_unicode_and_pagination: customer names such as 'Nordhaus Møbler ÅB', 'Łódź', 'Ελλάδα' and 'Москва', plus euro and rupee prices, appear in the extracted text with fonts embedded. A 150-line quote with 3,000-character descriptions paginates with the header row on every page and every description present in full. Internal notes, line internal notes, override reasons, default prices and costing strings are absent.
- [L / integration] test_custom_product_lifecycle_and_fields: all legacy fields round-trip; the transition table is enforced, with reasons for reject, dormant and reopen and an approved spec revision required for approved; issuing a quote moves the product forward to quoted; duplicate gives a new CP code and product_name 'X (Copy)'; archive rules hold; CSV export.
- [L / integration] test_custom_product_promotion: approved product plus approved spec revision, then request, then approval (requester cannot approve), then execute creates a validated catalogue product with lineage and status converted_to_standard. Re-executing is idempotent, and editing the payload after approval requires fresh approval.
- [L / integration] test_global_search_and_completeness_custom_product: search finds custom products by product_name (legacy bug 8). Completeness checks real fields, so there is no phantom 'missing description'.
- [L / e2e] quotes.spec.ts and custom-products.spec.ts: create, edit, duplicate, autosaved notes with conflict handling, revision compare, print preview with repeated headers, PDF and CSV downloads without query-string tokens, and keyboard-only operation of the configurator and line grid at desktop, tablet and mobile sizes.
- [invariant / integration] test_price_resolution_determinism: agreement beats customer type beats standard; currency, unit and date filters; a same-tier overlap without priority gives AMBIGUOUS with no fall-through; a unique explicit priority wins; a zero price gives UNAVAILABLE; activation of an overlapping list is rejected with a conflict report; the legacy multi-EUR-row case (bug 10) is resolved by price_type.
- [invariant / integration] test_price_list_item_immutability_and_history: an UPDATE of the price on an active list's item raises; supersede writes history and closes the old validity; retire hides the item from resolution from its date onward.
- [invariant / contract] test_openapi_money_fields_are_strings: every money field in the OpenAPI schema is a string type, and the generated TypeScript types compile with no number-typed money fields.
