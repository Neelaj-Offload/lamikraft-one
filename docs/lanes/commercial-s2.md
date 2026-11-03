# Lane report: commercial-2 (Slice 2, wave 1) and the configurator follow-up

Branch `lane/s2w1-commercial`, worktree `D:\lk-wt\sales`, env slot 6 (API 8060 / web 3060, e2e 8160 / 3160,
databases `lk_wt6`, `lk_wt6_test`, `lk_wt6_e2e`). Branched from `main` at `00721da` (Checkpoint 1). Two sessions:

1. **commercial-2** (2026-10-30, commits `d2e7b72` … `8ff21bd`): pricing administration, FX, the full quote state
   machine, revisions compare/restore, duplicate, currency and owner change, CSV exports, custom products with
   promotion, samples, quote settings, their web screens and four Playwright specs. It ended without a report and
   left an uncommitted configurator on disk.
2. **configurator follow-up** (2026-11-03, brief `s2-commercial-configurator.md`, commits `e3f0ab3` onwards):
   committed and finished the configurator (API, packaging summary, HTTP tests, web drawer, vitest, e2e), the
   custom-product note test, the FG-QLN-05 snapshot dimensions, regenerated `openapi.json` / `schema.d.ts`, ran the
   branch's Playwright specs and wrote this report.

Status: **implemented**; gate results in §5. Nothing is pushed; the integrator merges onto `lane/s2-merge`.

## 1. What was built

### Pricing (`backend/app/modules/pricing/`)
- Price-list CRUD beyond Slice 1: edit (draft only), activate (target lock, overlap rejected), retire, duplicate
  (current prices copied into a new draft), item create / edit (draft) / supersede from a date / retire, item
  history (append-only), product costs (restricted, audited without values).
- `pricing.service.import_standard_price`: the `STD-{TYPE}-{CUR}` import contract the catalogue workbench calls
  (supersedes into the standard list instead of rewriting a row).
- FX (`fx.py`): `pricing_fx_rate` proposals approved by a second person through the approvals engine
  (`FX_RATE_HANDLER`), stale / rejected / withdrawn / disabled rates never convert; `pricing_fx_policy`
  (conversion enabled, source currency, maximum age). `resolve_price(allow_fx=True)` converts from the policy source
  currency at an approved dated rate and records the `fx` provenance; it never relabels a figure.
- Routes: 24 under `/api/v1/pricing` (price lists, items, history, costs, resolve, FX rates, decision, withdraw,
  FX policy).

### Sales (`backend/app/modules/sales/`)
- One transition table with dynamic targets: `revise` (editable working copy), `discard_revision`,
  `extend_validity`, `archive` / `unarchive`, `correct_status` (with reason), plus the Slice-1 actions; reviews
  reject back to the working copy (BUG-01 `allowed_transitions` on every 409).
- Revisions: issued revisions carry a restorable `working_copy`; compare two revisions; restore into a new draft
  version without rewriting history (a sent quote is revised first).
- Duplicate: real totals, customer reference cleared, owner per the `quote_defaults` policy, keep or refresh prices,
  from the current version or a revision (BUG-02).
- Currency change: resolves the list in the new currency or applies an approved dated FX rate; 409 with per-line
  reasons when neither exists; the DB `no_currency_relabel` CHECK and the deferred `(quote_id, currency)` FK on
  lines make a relabel impossible (AVOID-08).
- Owner change (`sales.quote.assign`), quote list and lines CSV bounded by the export scope (SEC-02, BUG-04),
  search providers for quotes and custom products (BUG-08).
- Custom products (`custom_products.py`): `CP-NNNN` atomic numbering (BR-09 / BUG-13), legacy fields, transition
  table with reasons, spec revisions linked to samples and quotes, protected costing (`pricing.cost.*`), duplicate
  (`X (Copy)`), archive rules, CSV export with costing guarded, auto-advance to `quoted` when a quote with the
  product is issued, and **promotion to a catalogue product**: requested by `sales.custom_product.promote`, approved
  by someone else holding `sales.custom_product.approve` + `catalogue.product.create`, executed idempotently through
  `catalogue.service.create_product` with lineage (origin `promotion`); a spec change after the request needs a new
  request. Internal notes go through the platform collab notes, authorised through the product.
- Samples (`samples.py`): `SMP` numbering, lifecycle (dispatch with courier reference or challan, delivered with
  evidence, feedback, closed), lineage to custom products; a `challans.challan.issued` subscription dispatches a
  sample automatically.
- Quote settings (`quote_settings.py`): defaults and numbering previews that never allocate a number.
- **Configurator** (`configurator.py`, follow-up): `POST /api/v1/sales/quotes/configurator/resolve`
  (`sales.quote.read`, internally also `catalogue.product.read`). Filters (text incl. numeric thickness, category,
  subcategory, family, size, thickness, decor, finish) apply in SQL before paging through
  `catalogue.list_products`; facets are narrowed over the whole filtered set (`catalogue.product_facets`);
  `exact_match` names the product when exactly one remains; each row carries the price the quote would get
  (agreement → customer type → standard, approved FX when no list exists in the currency; unpriced rows say why and
  never show another currency), the engine's order-value recommendation for that price (never labelled MOQ), and the
  packaging summary (`450g · 24/ctn · Poly bag`) from the canonical packaging columns in one query per page
  (`catalogue.service.packaging_summaries`, new public helper). Rows without `pricing.price.read` keep `price: null`.
- Line product snapshots now also keep `length_mm` / `width_mm` / `height_mm` / `diameter_mm` next to `size_text`
  (FG-QLN-05; optional, so pre-existing snapshots still parse).

### Web (`apps/web/src/`)
- Screens: price lists and detail (`/products/price-lists`), FX rates (`/settings/fx-rates`), quote settings
  (`/settings/quotes`), custom products list / new / detail, samples list / detail; in the quote workspace
  revise / extend / archive / correct, duplicate, currency change dialog, revision compare / restore, CSV links and
  custom-product lines. `useResourceCommand` (Idempotency-Key per command, 409 reload with a conflict toast, 422 to
  fields). Vitest server-render tests for every screen.
- **Configurator drawer** (follow-up, UI-60): "Browse the catalogue" in the quote workspace's *Add a product*
  section opens a drawer with type-ahead search (Enter takes the exact match), the six cascading filters (category,
  family, size, thickness, decor, finish) whose options and counts come from the narrowed facets (a selection that
  drops out stays visible), priced rows with size / thickness / decor / finish, packaging summary, recommendation
  and an "Exact match" badge, real paging (20 per page, Previous / Next with the range), then a pick form with the
  packaging summary, the default price, quantity, the price (editable only with `sales.quote_price.override`), a
  reason when the price differs, and amber advisories (quantity below the order-value recommendation; price differs
  from the default; no price for this customer). Files: `features/sales/configurator.ts` (typed client on the
  generated schema, request/advisory/line model), `configurator-drawer.tsx`, `configurator.test.tsx`.

## 2. Parity rows and tests

All rows below were `planned` in `docs/PARITY_MATRIX.md` and now have the named test passing on this branch
(integration tests under `backend/tests/integration/`, e2e under `apps/web/e2e/`).

| Rows | Test |
|---|---|
| LM-43, API-34, LP-06.1 | `sales/test_configurator.py::test_filters_narrow_options_page_and_exact_match` (+ `::test_configurator_over_http`) |
| FG-QLN-12 | `sales/test_configurator.py::test_packaging_summary_from_canonical_fields` |
| UI-60 | `e2e/sales/quotes.spec.ts::configurator_keyboard_filters_paging_and_advisories`; vitest `features/sales/configurator.test.tsx` |
| FG-QLN-05 | `sales/test_quote_lines.py::test_dimensions_text_and_canonical_numbers` |
| LM-19, API-17 | `pricing/test_price_lists.py::test_item_create_and_supersede_with_history` |
| FG-PRC-01, -07, -08, -09, -12, -14, LP-05.1 | `pricing/test_price_lists.py::test_item_fields_round_trip` |
| FG-PRC-13 | `pricing/test_price_lists.py::test_overlap_rejected_at_activation` |
| FG-PRC-15, BUG-15, LP-05.3 | `pricing/test_price_lists.py::test_active_items_immutable_and_history_append_only` |
| FG-PRC-16 | `pricing/test_pricing_import_contract.py::test_import_supersedes_into_standard_list` |
| PERM-07, LM-50, FG-QLN-08, BR-05, LP-06.5 | `sales/test_quote_lines.py::test_override_requires_permission_and_reason_for_sales` |
| LM-46, FG-QLN-04, -06, -15, -16, LP-06.2, SCN-C3 | `sales/test_quote_lines.py::test_catalog_line_snapshot_immune_to_catalogue_change` |
| LM-47, LM-69 | `sales/test_quote_lines.py::test_custom_line_from_custom_product` |
| LM-48, LP-06.4 | `sales/test_quote_lines.py::test_manual_line_presets` |
| FG-QLN-02 | `sales/test_quote_lines.py::test_line_type_reference_checks` |
| FG-QLN-07 | `sales/test_quote_lines.py::test_integer_uom_rejects_fractions` |
| LM-51, LP-06.8 | `sales/test_quote_status.py::test_quote_status_machine_table` |
| LM-52, FG-QRV-02 | `sales/test_quote_status.py::test_status_history_append_only` |
| FG-QUO-03, API-44, BUG-01, PRD-01 | `sales/test_quote_status.py::test_cancelled_and_archived_transitions` |
| LM-53, API-43 | `sales/test_quote_revisions.py::test_revise_creates_working_copy` |
| LM-54, FG-QRV-03, LP-06.10 | `sales/test_quote_revisions.py::test_compare_and_restore_keep_history` |
| LM-55, API-45, BUG-02, LP-06.7 | `sales/test_quote_duplicate.py::test_duplicate_real_totals_reference_cleared_owner_policy` |
| LM-57, FG-QUO-11, API-38, BUG-04 | `sales/test_quote_csv.py::test_line_counts_names_totals_and_escaping` |
| LM-58, API-37, UI-53, UI-56 | `sales/test_quote_list.py::test_filters_scope_and_paging_totals` |
| UI-50 | `sales/test_quote_list.py::test_status_tabs_include_revised_cancelled_archived` |
| UI-51 | `sales/test_quote_list.py::test_search_metacharacters_literal` |
| PERM-08 | `sales/test_quote_idor.py::test_exports_bounded_by_read_scope` |
| PERM-20, PERM-21, API-39, API-42, SEC-02, PRD-04, SCN-F1 | `sales/test_quote_idor.py::test_quote_idor_matrix` |
| FG-QUO-06, FG-QLN-09, AVOID-08 | `sales/test_currency_change.py::test_db_rejects_currency_relabel` |
| GAP-03, SCN-E1 | `sales/test_currency_change.py::test_currency_change_with_approved_fx` |
| LP-05.4 | `sales/test_currency_change.py::test_currency_change_blocked_without_fx` |
| API-35 | `sales/test_quote_settings.py::test_defaults_and_numbering_settings_validated` |
| LM-62, FG-CP-01, BR-09 | `sales/test_custom_products.py::test_codes_unique_never_reused` |
| LM-63, API-47 | `sales/test_custom_products.py::test_list_search_filter_paging` |
| LM-64, API-49, FG-CP-02, -03, -04, -07, -09 … -12, -14, -15, -18, LP-08.1 | `sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |
| LM-65 | `sales/test_custom_products.py::test_archive_rules` |
| LM-66, API-50 | `sales/test_custom_products.py::test_duplicate_new_code_and_product_name_copy` |
| LM-67, API-48 | `sales/test_custom_products.py::test_csv_export_escaped_and_costing_guarded` |
| FG-CP-16, LP-08.2 | `sales/test_custom_products.py::test_transition_table_and_reasons` |
| LP-08.5 | `sales/test_custom_products.py::test_spec_revisions_and_quote_link` |
| LM-68, FG-CP-17 | `sales/test_custom_products.py::test_internal_notes_on_custom_products` (rows not yet pointing at it) |
| LM-70, FG-CP-05, REUSE-04, LP-08.4 | `sales/test_custom_product_promotion.py::test_request_approve_execute_idempotent` |
| FG-CP-08, BUG-08, LP-08.3, SCN-G5 | `search/test_custom_product_name.py::test_global_search_finds_custom_product_name` |
| PERM-13, FG-CP-13, SCN-E2 | `security/test_costing_redaction.py::test_costing_absent_without_pricing_cost_read` |

Also tested without a matrix row of their own: FX approval and staleness (`pricing/test_fx_rates.py`, 3 tests),
samples lifecycle and challan dispatch (`sales/test_samples.py`, 2), promotion invalidated by a spec change
(`test_custom_product_promotion.py::test_spec_change_after_request_needs_a_fresh_request`), the route declarations
and operationIds of every sales route (`sales/test_lane_api.py::test_operation_ids_and_route_declarations`, the
configurator route added).

Matrix rows whose named test does not exist under that name (for the integrator to repoint, see §4):
FG-PRC-05 / FG-PRC-06 name `test_breakdown_requires_price_list_read` — the test is
`pricing/test_price_lists.py::test_breakdown_fields_need_price_list_read`; FG-QRV-01 / FG-QRV-05 name
`test_quote_revisions.py::test_issued_revision_immutable_by_trigger` — it lives in `sales/test_quote_status.py`.
FG-QLN-13 (`test_media_snapshot_survives_media_soft_delete`) is **not done**: the line `media_snapshot` has only a
hint until the catalogue lane's `catalogue_product_media` merges (§6).

## 3. Migrations, events, keys

- Migration **`0010_commercial_slice2.py`** (`down_revision = "0009"`; numbered before the placeholder rule —
  renumber into the linear chain at merge): `pricing_fx_rate`, `pricing_fx_policy`, quote lifecycle columns
  (archive, lineage, restore, corrections), the `no_currency_relabel` CHECK and the deferred
  `(quote_id, currency)` FK on lines, `sales_custom_product`, `sales_custom_product_costing`,
  `sales_custom_product_spec_revision`, `sales_custom_product_promotion`, `sales_custom_product_status_history`,
  `sales_sample`, and `sales_quote_line.custom_product_id` → `sales_custom_product.id`. The follow-up adds **no
  migration** (snapshot dimensions are JSONB fields).
- Events (`sales/events.py`, `pricing/events.py`): `sales.quote.revised`, `.validity_extended`, `.archived`,
  `.unarchived`, `.status_corrected`, `.owner_changed`, `.duplicated`, `.restored`, `.currency_changed`;
  `sales.custom_product.created`, `.updated`, `.status_changed`, `.spec_revision_recorded`,
  `.promotion_requested`, `.promoted`, `.promotion_rejected`, `.duplicated`, `.archived`; `sales.sample.created`,
  `.dispatched`, `.delivered`, `.feedback_recorded`, `.closed`; `pricing.price_list.retired`,
  `pricing.price_list_item.retired`, `pricing.fx_rate.proposed`, `.approved`, `.rejected`. The configurator emits
  nothing (read only).
- Subscriptions (`sales/manifest.py`): `sales.quote.issued` → `sales.custom_product_autoadvance`;
  `challans.challan.issued` → `sales.sample_dispatch`. Approval handlers: custom-product promotion, FX rate.
  Sequences: `sales.custom_product` (`CP-NNNN`, never reset), samples.
- `keys.py`: no additions (the configurator tests use the Slice-1 fixtures `OAK_TRAY`, `NORDHAUS`,
  `CATEGORIES.SERVEWARE`, `PRICE_LISTS.EXP_EUR`).

## 4. Integrator requests

1. **Challans FK** (asked by `lane/s2w2-challans`): `challans_challan_line.custom_product_id` → table
   **`sales_custom_product`**, column **`id`** (uuid PK; use `ondelete="RESTRICT"` like
   `fk_sales_quote_line_custom_product_id`).
2. **Challans event payload**: `sales.sample_dispatch` reads `sample_id` and `challan_id` from the
   `challans.challan.issued` payload; the challans lane must include `sample_id` (nullable) for sample challans.
   After challans merge, add the FK `sales_sample.challan_id` → `challans_challan.id` (today a plain uuid).
3. Renumber migration `0010_commercial_slice2` into the merged chain.
4. After the catalogue lane merges, `ProductSummary.primary_image` appears in configurator rows automatically
   (`catalogue.list_products`); show it in `ResultRow` (`configurator-drawer.tsx`) and record media `file_id`s in
   the line `media_snapshot` (then FG-QLN-13 can be tested).
5. Repoint FG-PRC-05 / -06 and FG-QRV-01 / -05 to the existing test names (§2), and LM-68 / FG-CP-17 to
   `test_internal_notes_on_custom_products`; mark the rows of §2 implemented.
6. `catalogue/service.py` gained one public helper (`packaging_summaries`) right after `_packaging_summary`;
   expect a trivial hunk if the catalogue lane edited that region.
7. Re-run `npm run api:generate` on the merged branch (this branch's `openapi.json` was stale since the
   commercial-2 commits and is now regenerated: 158 operations).

## 5. Gates

Run on this branch in slot 6, 2026-11-03/04, one suite at a time (logs in the session scratchpad):

| Gate | Command | Result |
|---|---|---|
| API suite | `npm run test:api` | **1103 passed**, 1 warning (PIL decompression-bomb test), 37 min 49 s |
| check | `npm run check -- --keep-going` | **7/7 PASS**: ruff; pytest unit + contract 481 passed; alembic heads 1; api:check (`openapi.json` matches); web lint; typecheck; vitest 33 files / 442 tests |
| api:generate | `npm run api:generate` | committed (`20999e2`, `49476d2`); `api:check` passes |
| e2e (branch specs) | `npm run test:e2e -- e2e/commercial e2e/sales --project=desktop --workers=1` | **5 passed, 1 skipped** (`price-lists.spec.ts` management half needs `LK_E2E_ADMIN`) |

The first e2e run of the 8ff21bd specs failed 4 of 4 runnable specs plus the new one, and were fixed in this lane's
code: (a) `/sales/custom-products`, `/products/price-lists` and `/sales/samples` crashed on server render because
the pages called `customListStateFrom` / `priceListStateFrom` / `sampleListStateFrom` exported from `"use client"`
modules — moved to server-safe `list-state.ts` modules (`9482f81`); (b) the currency spec opened the seeded Nordhaus
draft, which is in review at D0 and so offers no "Change currency" — it now creates its own draft with a line
(`e2e/support/quotes.ts`); (c) the new configurator spec needed the combobox / decimal-field interactions of the
shared helper. Note: `next build` on this branch's Next **16.4.0** intermittently stops after a successful compile
with a `SecurityFatalError` upgrade notice (2 of 4 builds); a plain retry built. `main` already pins 16.4.4, so the
merge removes it; the notice's suggested upgrade command was not run.

## 6. Not done, with reasons

- **FG-QLN-13** media snapshot with `file_object` ids — needs `catalogue_product_media` from the catalogue lane.
- **DEBT-02 for the configurator**: the packaging summary is one query per page, but prices are still resolved per
  row through `pricing.resolve_price` (a page is at most 50 rows, 20 in the UI). A batched resolver is a pricing
  refactor left for later; the catalogue list itself is covered by
  `catalogue/test_product_list.py::test_rows_enriched_without_n_plus_one`.
- `price-lists.spec.ts` skips its management half unless `LK_E2E_ADMIN` is set (admin sign-in is not a fixture
  persona); only the read half runs.
