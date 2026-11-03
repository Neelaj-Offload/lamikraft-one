# Lane report: catalogue-imports (Slice 2, wave 1)

Branch `lane/s2w1-catalogue`, worktree `D:\lk-wt\catalogue`, env slot 3. Scope: `modules/catalogue`, `modules/parties`,
the new `modules/imports`, and their web screens. Status: **DONE_WITH_CONCERNS** (see §7).

## 1. What was built

### Backend
- **Migration `0010_catalogue_slice2`** (down_revision `0009`): `catalogue_product_media`, `catalogue_taxonomy_alias`,
  `parties_customer_type` (+ FK `parties_party(company_id, customer_type)` replacing the enum CHECK, built-in rows
  backfilled per company under its own RLS GUC), `imports_job`, `imports_staged_row`, `imports_row_issue`,
  `imports_change` (one committing job per company: partial unique index). Forced RLS on every new table; enum CHECKs.
  Upgrade → downgrade → upgrade verified on `lk_wt3`; `alembic check` clean.
- **Catalogue** (`products.py`, `media.py`, `taxonomy.py`, `lookups.py`, plus `service.py`/`router.py` changes):
  - product forms API: `POST /products` (Idempotency-Key), `PATCH /products/{id}` (version, 409), `PUT
    .../specification`, `PUT .../packaging` (alias reconciliation, `alias_conflict` 422), archive/restore (no delete
    route), `GET .../history` (audit trail), `GET /products/recent`, `GET /products/export.csv` (import-compatible,
    `core.csv_safe`), `GET /completeness`;
  - detail capabilities `update/archive/restore/manage_media`; sections add `media` and `history`; list rows and
    detail carry `primary_image`; filters `has_image`, `has_price`; stats `without_active_price`;
  - completeness rules `no_image`, `no_primary_image`, `media_ingest_failed`, `no_active_price` (the last only with
    `pricing.price.read` and the price bridge; otherwise listed as not evaluated); rules are computed per actor;
  - media through `platform/files`: upload to `/api/v1/files`, attach by file id; sniffed kinds, images only as
    images, duplicate bytes → 409 `media_duplicate`, first image auto-primary, single live primary (partial unique),
    soft delete with reason + promotion of the next image, restore, own-scope `catalogue.media.manage` limited to own
    uploads (`not_owner`), downloads authorised by a registered file-access checker (product visibility; 404 across
    companies). Originals only (image variants are Platform-2);
  - taxonomy: create/update/rename (old name kept as alias; product search text refreshed), reorder, activation,
    FK-introspected reference counts, delete refused while referenced (`taxonomy_referenced`) or reassigned with the
    confirmed counts (`references_changed` on drift; `reassign_unsupported` for tables without a handler), validation
    report (`/taxonomy/validation`); reads now carry `version`;
  - lookups: browser (`/lookups`, `/lookups/types`) and safe CSV export.
- **Parties**: `parties_customer_type` table (SC-13) with `GET/POST/PATCH /parties/customer-types`
  (`parties.customer_type.manage`), built-in types provisioned on first use for new companies, inactive types cannot
  be newly assigned; party archive/restore (`parties.party.archive`, `parties.party.archived` event).
  `CustomerType` is now a validated code (`str` subclass with `.value`, wire format unchanged) so the sales lane's
  `detail.customer_type.value` keeps working.
- **Imports** (`modules/imports`): readers (CSV encoding/delimiter detection; XLSX via openpyxl read-only with zip-bomb
  and macro guard; identifiers as text, zero-pattern formats padded), header normaliser and alias registry, seven
  definitions (`category_taxonomy`, `products_master`, `pricing`, `packaging`, `specifications`, `media`,
  `lookup_reference`), engine (staging, preview with duplicate keys and same-hash jobs, validation with uncapped
  issues and duplicate handling, 500-row batched commits re-planned under lock with `DEPENDENCY_CHANGED` /
  `TARGET_CHANGED_SINCE_REVIEW` / `KEY_CREATED_CONCURRENTLY`, resumable after `commit_failed`, quarantine recheck into
  a child job, rollback plan with hash, `all` / `reversible_only`), jobs `imports.validate` / `imports.commit` on
  `platform/jobs` (writes run as the requesting user via `actor_for_member`), issue report CSV, history, demo-only
  reset (`is_demo`, `system.demo_data.delete`, recent sign-in, 5-minute HMAC token binding the counts, typed phrase,
  refused while non-catalogue rows reference the demo catalogue). Pricing rows go through `pricing.service` public
  functions only (create draft `STD-{TYPE}-{CUR}` list + `add_item`, or `supersede_item` on an active list).
  Imports also installs the catalogue's price-presence bridge (catalogue cannot import pricing).

### Web (`features/catalogue`, `features/imports`, `features/parties`)
- `/products`: summary line from stats, category chips, URL-synced filters (search, status, subcategory, thickness,
  finish, size, decor, image, sort, page size 25/50/100), server pagination with real totals, phone card list,
  capability-gated Add product / Export CSV / Taxonomy.
- `/products/[productId]` and `/products/[productId]/[section]`: deep-linked tabs; overview (facts, primary image,
  prices, missing data) + inline master/decor/provenance edit; specifications and packaging inline section editors
  (422 field errors, 409 conflict view), packaging warnings and alias provenance disclosure; media (button and
  drop upload, groups, primary, preview/download, delete with reason, restore, deleted view); history; archive with
  confirm and restore.
- `/products/new` (all sections, active-only taxonomy pickers, server errors on fields), `/products/taxonomy`
  (reorder, activation, rename, delete-or-reassign dialog with reference counts), `/products/completeness`.
- `/settings/imports` (history + demo reset panel), `/settings/imports/new` (types in dependency order with status
  and templates, button or drop upload), `/settings/imports/[jobId]` (stepper: mapping with preview, duplicate keys and
  same-file warning → validation polling → review with counts, issues filter, row diffs, full report link,
  acknowledgement → commit polling → recheck / rollback plan dialog).
- `/settings/lookups`, `/settings/customer-types`, `/sales/parties`, `/sales/parties/[partyId]` (contacts and
  addresses editor, archive/restore by capability).
- Route manifest entries and query keys added in one `// catalogue lane` block each. Playwright specs written (not
  run): `e2e/catalogue/product-list.spec.ts`, `e2e/imports/workbench.spec.ts`.

## 2. Tests (new in this lane)

| File | Tests |
|---|---|
| `tests/integration/catalogue/test_product_crud.py` (+7) | create with all sections, update 409, spec PUT parsing, packaging PUT aliases, one row per product (x2), archive/restore and no delete route |
| `tests/integration/catalogue/test_media.py` | 7: sniff/dedupe/single primary, groups, fields, soft delete/restore/promotion, own scope, download visibility, completeness + `has_image` |
| `tests/integration/catalogue/test_product_stats.py` | 5: stats distinct counts, price figures hidden without pricing read, recent products, exclude-self facets, completeness counts = filter totals |
| `tests/integration/catalogue/test_taxonomy.py` (+5) | CRUD/reorder/activation, inactive parent, live counts, rename alias + delete-or-reassign, validation report |
| `tests/integration/catalogue/test_catalogue_http.py` | 6: route declarations, create/patch/409/replay, CSV export formula-safe, taxonomy 409, media 403/404, lookup permission |
| `tests/integration/parties/test_customer_types.py` | 6: built-ins, FK enforcement, inactive types, provisioning, archive/restore, GAP-01 contacts/addresses/scope |
| `tests/unit/imports/test_header_normalisation.py` | 15: header normalisation, collisions, CSV/XLSX readers, zip guard, status aliases, dates, media location keys |
| `tests/integration/imports/test_products_import.py` | 4 |
| `tests/integration/imports/test_dependent_imports.py` | 8 |
| `tests/integration/imports/test_workbench.py` | 11 |
| `tests/integration/imports/test_imports_http.py` | 2 |
| `apps/web/src/features/catalogue/catalogue.test.tsx` | 19 |
| `apps/web/src/features/imports/imports.test.tsx` | 6 |
| `apps/web/src/features/parties/parties.test.tsx` | 5 |

Changed existing tests: `test_product_detail.py` (sections now include media/history; completeness includes the media
and price rules), `tests/contract/catalogue/test_lane_schema.py` (party customer type is an FK now).

## 3. PARITY_MATRIX row → test

Backend paths are relative to `backend/`; vitest to `apps/web/src/`; Playwright to `apps/web/` (written, not run).

| Row | Test |
|---|---|
| LM-11 | `tests/integration/catalogue/test_media.py::test_media_completeness_rules_and_has_image_filter` (primary image on rows) + existing price-column tests |
| LM-13 | `tests/integration/catalogue/test_media.py::test_upload_sniffs_dedupes_and_single_primary` (detail primary image, media count) + `test_product_detail.py::test_detail_returns_all_field_groups_with_section_guards` |
| LM-14, API-11, UI-27 | `tests/integration/catalogue/test_product_stats.py::test_stats_count_distinct_products` |
| LM-15, API-12, UI-30 | `test_product_stats.py::test_recent_products_with_origin_and_actor` |
| LM-16, API-14, UI-45 | `tests/integration/catalogue/test_product_crud.py::test_create_with_all_sections`; `features/catalogue/catalogue.test.tsx` "renders the create form sections" |
| LM-17, API-15 | `test_product_crud.py::test_update_sections_with_version_conflict_409`; `test_catalogue_http.py::test_create_patch_conflict_and_replay` |
| LM-18, API-16 | `test_product_crud.py::test_archive_restore_and_no_hard_delete_via_ui` |
| LM-20, API-18 | `test_product_crud.py::test_packaging_put_canonicalises_aliases` |
| LM-21, API-19 | `test_product_crud.py::test_specification_put_parses_dimensions` |
| LM-22, API-23 | `test_product_stats.py::test_facets_exclude_self_and_count_scoped_rows` (matrix names `test_facets.py`) |
| LM-23, API-25, FG-MED-06 | `tests/integration/catalogue/test_media.py::test_upload_sniffs_dedupes_and_single_primary` |
| LM-24, API-26 | `test_media.py::test_list_grouped_by_type` |
| LM-26, API-28, FG-MED-07 | `test_media.py::test_soft_delete_restore_and_primary_promotion` |
| FG-MED-01, FG-MED-08 | `test_media.py::test_media_fields_round_trip` |
| FG-MED-09 | `test_media.py::test_own_scope_cannot_delete_others_uploads` |
| LM-25 (catalogue side) | `test_media.py::test_downloads_follow_product_visibility` (the platform route test is the platform lane's) |
| LM-28 | `tests/integration/imports/test_products_import.py::test_categories_before_subcategories` |
| LM-29, LP-04.2 | `test_products_import.py::test_requires_taxonomy_and_applies_defaults` |
| LM-30, FG-PRC-04 | `tests/integration/imports/test_dependent_imports.py::test_orphans_quarantined_and_price_alias_conflict` |
| FG-PRC-16 | `tests/integration/imports/test_workbench.py::test_pricing_supersedes_into_an_active_standard_list` (matrix names `tests/integration/pricing/test_pricing_import_contract.py`, the pricing lane's) |
| LM-31, SCN-G2, FG-PKG-01..04, BUG-09 | `test_dependent_imports.py::test_alias_conflict_quarantined_with_row_numbers` |
| LM-32 | `test_dependent_imports.py::test_orphans_quarantined_and_dimensions_parsed` |
| LM-33 | `test_dependent_imports.py::test_reimport_creates_no_duplicate_media` |
| FG-MED-03 | `test_dependent_imports.py::test_location_alias_group_conflict_quarantined` |
| FG-MED-04 | `test_dependent_imports.py::test_filename_pair_kept` |
| LM-34, FG-LKP-01/02, LP-04.7 | `test_dependent_imports.py::test_upsert_idempotent_browse_and_export` |
| FG-LKP-03 | `catalogue.test.tsx` "keeps lookup filters in the URL" + `test_catalogue_http.py::test_lookup_routes_need_the_lookup_key`; `e2e/catalogue/product-list.spec.ts::browse_filter_export` |
| LM-35, API-30 | `test_workbench.py::test_preview_lists_duplicates_with_row_numbers` |
| LM-36, API-32 | `test_workbench.py::test_all_issues_counts_and_orphans`; `tests/integration/catalogue/test_taxonomy.py::test_validation_report` |
| LM-37, API-33, UI-88, LP-04.9 | `test_workbench.py::test_refused_for_non_demo_and_guarded`; `features/imports/imports.test.tsx` demo reset |
| LM-38, LP-04.3 | `test_workbench.py::test_all_errors_reported_uncapped` |
| LM-39, LP-04.1 | `tests/unit/imports/test_header_normalisation.py::test_normalisation_aliases_and_collisions` |
| FG-PRD-12 | `test_header_normalisation.py::test_status_aliases` |
| API-31, LP-04.4 | `test_workbench.py::test_commit_batches_resume_after_failure`; `tests/integration/imports/test_imports_http.py::test_workbench_flow_over_http` |
| LP-04.5, SCN-G1 | `test_products_import.py::test_second_identical_import_is_noop` (matrix names `test_reimport_idempotent.py`) |
| BUG-12 | `test_dependent_imports.py::test_orphan_rows_quarantined_then_released_by_recheck` |
| LP-04.6 | `test_workbench.py::test_rollback_blocked_when_referenced_or_later_edited`, `::test_rollback_unreferenced_import_restores_before_state` |
| UI-87 | `test_workbench.py::test_jobs_mappings_hashes_durable`; `imports.test.tsx` history |
| LM-40, FG-TAX-05/06 | `test_taxonomy.py::test_crud_reorder_and_activation` |
| LM-41 | `test_products_import.py::test_unknown_category_quarantined` |
| LM-42, BUG-16, LP-03.4, SCN-G3, API-29 | `test_taxonomy.py::test_rename_alias_and_delete_or_reassign`; `test_catalogue_http.py::test_taxonomy_delete_refused_while_referenced` |
| FG-TAX-04 | `test_taxonomy.py::test_live_counts_computed` |
| API-21 | `test_taxonomy.py::test_hierarchy_respects_inactive_parent` |
| API-22 | `test_taxonomy.py::test_validation_report` |
| API-67, UI-31, LP-11.2 | `test_product_stats.py::test_metrics_count_distinct_products_real_fields` (matrix names `test_completeness.py`); `catalogue.test.tsx` completeness links |
| FG-PKG-10, FG-SPC-12 | `test_product_crud.py::test_packaging_one_row_per_product`, `::test_specification_one_row_per_product` |
| UI-14, UI-34, UI-36 | `catalogue.test.tsx` list state + catalogue screen; `e2e/catalogue/product-list.spec.ts::filters_paging_and_deep_links_survive_reload` |
| UI-15, UI-38, UI-46 | `catalogue.test.tsx` detail screen; `e2e/catalogue/product-list.spec.ts::archive_restore_with_confirm`, `::create_with_all_sections_and_server_errors` |
| UI-20, UI-93 | `catalogue.test.tsx` taxonomy delete plan; `e2e/catalogue/product-list.spec.ts::crud_rename_reassign_delete` |
| UI-24, UI-86, UI-89 | `imports.test.tsx`; `e2e/imports/workbench.spec.ts` |
| UI-32, UI-37 | `catalogue.test.tsx` "renders rows, summary figures and category chips; create and export only with their permissions" |
| UI-43 | `features/catalogue/media-panel.tsx` (rendered via detail); `e2e/catalogue/product-list.spec.ts::upload_preview_download_delete_restore` |
| UI-48 | `catalogue.test.tsx` "offers only active taxonomy in pickers" |
| UI-49 | `test_product_crud.py::test_create_with_all_sections` (every section writable) + `catalogue.test.tsx` create form |
| GAP-01 | `tests/integration/parties/test_customer_types.py::test_party_contacts_addresses_roles_scope`; `features/parties/parties.test.tsx` |
| SC-13 (customer-type table) | `test_customer_types.py::test_new_type_is_assignable_and_enforced_by_foreign_key`, `::test_inactive_type_cannot_be_newly_assigned_but_may_stay` |
| BUG-05, FG-PRD-09 (import path) | `test_products_import.py::test_requires_taxonomy_and_applies_defaults` (`120.0` → `120` with warning, `0120` kept) |

Rows assigned by path but not completed here: FG-GRN-* (3.14: the `cutting_grain_lock` table is the operations lane's;
the canonical decor key it needs is `catalogue.normalise.normalise_identifier`), LM-12 (platform search),
LM-19/API-17/BUG-15 (price-list editor, commercial lane), LM-27/FG-MED-02/05 (platform files tests).

## 4. Gates

See §8 (filled with the final run).

## 5. Requests for the integrator

1. Regenerate `backend/openapi.json` and `apps/web/src/lib/api/schema.d.ts` (31 catalogue, 18 imports, 5 parties
   routes). The web code uses `requestUntyped` adapters (marked `INTERIM(api-generate)`) until then.
2. `apps/web/e2e/support/world.ts`: add `"PRIYA"` to `PersonKey` (the catalogue/import specs sign in as the admin).
3. Pricing lane: (a) a public `active_price_exists(uow)` selectable to replace `imports/bridges.py`, which reads pricing
   tables read-only through `pricing.service.visible_lists`; (b) the `STD-{TYPE}-{CUR}` import service: today a new
   product on an active standard list is quarantined `PRICE_LIST_ACTIVE_NEW_ITEM`, a changed price on a draft list
   `PRICE_DRAFT_ITEM_EXISTS`, and price-list changes are never reversed by an import rollback (`NOT_REVERSIBLE`);
   (c) FK `pricing_price_list(company_id, customer_type)` → `parties_customer_type(company_id, code)` like parties.
4. Sales lane: `quotes.py` may drop `.value` on `detail.customer_type` (it is a code string now; `.value` still works).
5. Platform: image variants for media thumbnails (the UI uses originals); URL ingest (`safe_fetch`) for imported media
   locations (rows are stored as `external_only` reference media until then).

### keys.py requests
- Import fixture constants are inline in tests (CSV bodies); no new world seeds. Built-in customer-type codes
  (`standard`, `dealer`, `distributor`) live in `parties.models.SYSTEM_CUSTOMER_TYPES`.

## 6. Events and permissions used
- Events (all catalogued): `catalogue.product.archived/restored`, `catalogue.media.uploaded/deleted/restored/primary_changed`,
  `catalogue.category.renamed/updated/deleted`, `catalogue.subcategory.renamed/updated/deleted`,
  `catalogue.taxonomy.reassigned`, `imports.job.uploaded/validated/committed/failed/rolled_back`,
  `parties.party.archived`, `system.demo_data.deleted`.
- Permissions (all catalogued): `catalogue.product.{read,create,update,archive,export}`, `catalogue.media.manage`,
  `catalogue.taxonomy.manage`, `catalogue.lookup.read`, `imports.job.{read,run}`, `imports.rollback.execute`,
  `system.demo_data.delete`, `parties.customer_type.manage`, `parties.party.archive`.
- Jobs: `imports.validate`, `imports.commit`. File access checkers: `catalogue.product_media`, `imports.job`.

## 7. Concerns
- Media upload thumbnails use originals (no variants yet). Imported media rows are reference-only (no fetch).
- `catalogue.media.manage`/`imports.rollback.execute`/`system.demo_data.delete` recent-auth (`ra`) is enforced in
  this lane's services with the identity 10-minute window; MFA (`mfa` flag) is the Platform-2 lane's.
- Taxonomy delete of a category that still has subcategories is blocked (`reassign_unsupported`); delete or move the
  subcategories first.
