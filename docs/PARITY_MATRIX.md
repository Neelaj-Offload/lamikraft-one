# Legacy parity matrix

The legacy-parity contract for Lamikraft One. Every legacy module, field group, API capability, UI page and
behaviour, business rule, functional bug, security gap, engineering-debt item and reuse/redesign item from
`CURRENT_STATE_SPEC.md`, plus the build prompt's `legacy_parity_and_corrections` items 1–12 and acceptance scenarios
A–N, has a row here with its new home, target slice, status and verifying test. Completeness of the product is judged
against this file. A row may only move to **implemented** when the named test passes on `main` and the evidence is
recorded in `docs/BUILD_STATE.md`.

Checkpoint 0 (2026-10-12): every row is **planned**.

Checkpoint 1 (2026-10-30, integration lane `lane/s1-integration`, pending its merge): 40 slice-1 rows whose
named pytest tests all pass on that branch moved to **implemented**; 13 rows whose tests pass but whose scope is
larger (slice 1→2, or a persisted part owned by a lane not yet merged: FG-QUO-10, FG-QLN-10, SEC-05) moved to
**in progress**. Rows named by Playwright or vitest, and rows whose named test does not exist yet or fails (the
briefings scenario tests, see `docs/lanes/integration.md`), stay **planned**.

Checkpoint 3 (2026-11-04, Slice-2 merge `lane/s2-merge`, pending its merge to `main`): 396 rows whose named tests
pass on that branch moved to **implemented** — pytest from the full `npm run test:api` (1313 passed), vitest from
`npm run check` (611 passed), Playwright only for spec files whose every test passed in the final `npm run test:e2e`
(193 passed, 0 failed). Rows the lane reports map to differently named tests were repointed to those tests; rows
whose scope continues in Slice 4 (`2→4`), or whose matrix names a Playwright spec that was not written or not run,
are **in progress** (18). Renamed tests repointed at the merge: FG-PRC-05/06, FG-QRV-01/05, LM-68, FG-CP-17, and the
`e2e/scenarios/l-legacy-parity.spec.ts` rows → `e2e/challans.spec.ts`. Totals: 436 implemented, 18 in progress,
246 planned (Slices 3–6), 1 deferred.

Checkpoint 4a (2026-11-04, Slice-3 stage-1 merge `lane/s3-merge`: agents runtime + WhatsApp; an intermediate state,
CP4 follows in stage 2): rows moved only where the named tests passed on that branch — pytest from the full
`npm run test:api` (1479 passed, 7 live-only skips), Playwright from `npm run test:e2e`. The scenario-K rows were
repointed to the WhatsApp lane's tests (`docs/lanes/whatsapp-s3.md` §2): **implemented** SCN-K1, SCN-K2, SCN-K3, and
SCN-C5 (`e2e/scenario-c.spec.ts`, desktop and phone, now also asserting SSE progress); **in progress** SCN-C4 (text
and WhatsApp done, web voice is the voice lane's) and SCN-J2 (ambiguous customer done, ambiguous number/line/field
not yet). Net: +4 implemented, +2 in progress, −6 planned.

Checkpoint 4 (2026-11-04, Slice-3 stage-2 merge `lane/s3-merge`: voice/vision and briefings onto Checkpoint 4a):
rows moved only where the named tests passed on the final tree — pytest from the full `npm run test:api`, Playwright
from `npm run test:e2e`. **Implemented**: SCN-B3, SCN-B4, SCN-B6 (briefings lane §2), SCN-C4 (text, voice and WhatsApp
Demo all drafting the same quote), SCN-J1 (repointed to `tests/integration/voice/test_voice_api.py`; the planned
`test_transcript_idempotency.py` was not used). **In progress**: SCN-J3 (`j-voice.spec.ts` passes; its offline
stock-movement part waits for Slice 4, so the row is `3→4`). SCN-J2 stays in progress (ambiguous customer by text and
voice done; ambiguous number/line/field not yet). Net: +5 implemented, −5 planned (SCN-J3 planned → in progress, SCN-C4
in progress → implemented).

Checkpoint 5 (2026-11-05, Slice-4 merge `lane/s4-merge`: orders/inventory, production, procurement/quality/logistics):
rows moved only where the named tests passed on the merged branch — pytest from the full `npm run test:api` (1688
passed, 7 live-only skips). **Implemented**: SCN-I1, SCN-I2, SCN-I3, SCN-I4, LP-10.5, LP-10.6, REUSE-06, GAP-10
(repointed to `test_ledger_machine`, the `LedgerMachine` runner), GAP-11 (repointed to the lane's procure-to-pay
test; `test_receiving.py` was not written), GAP-14, and the `2→4` rows whose Slice-4 part landed: LM-78 (cut plans
link to work orders), LM-94 (movement policy and postings; e-way bill future scope), FG-REL-04 (challan → order
links), REUSE-05 (repointed to the production cut-plan link tests). **In progress**: GAP-12 (BOM, routing, work orders,
issue/consumption, scrap, costing done; job work through challans not built). UI-44 (product Operations tab) and
SCN-J3 (offline stock-movement card) stay as they were. Net: +14 implemented, −12 planned, −2 in progress
(LM-78, LM-94, FG-REL-04 in progress → implemented; GAP-12 planned → in progress). Totals: 459 implemented, 18 in
progress, 223 planned.

**Legend**
- *New home*: backend path under `backend/app/` (`platform/<name>` kernel, `modules/<name>` domain) and web route under
  `apps/web/src/app/(app)` (detail routes use UUIDs; `/go/[type]/[key]` resolves business keys).
- *Slice*: the slice in which the row must pass (`1→2` = partial in 1, complete in 2).
- *Status*: planned · in progress · implemented · verified · deferred (with reason).
- *Verifying test*: pytest paths are relative to `backend/` (`tests/...`); Playwright paths are relative to `apps/web/`
  (`e2e/...`); vitest paths relative to `apps/web/src/`.
- Permission keys: `docs/architecture/permissions.md`. Events: `docs/architecture/events.md`. Fixtures:
  `docs/architecture/fixtures.md`.

Sections: [1 Roles and permissions (§3)](#1-roles-and-permissions-spec-3) · [2 Modules (§5)](#2-legacy-modules-spec-5) ·
[3 Field groups (§4)](#3-field-groups-spec-4) · [4 API (§7)](#4-api-capabilities-spec-7) ·
[5 UI (§8)](#5-ui-pages-and-behaviour-spec-8) · [6 Business rules (§6)](#6-business-rules-and-constants-spec-6) ·
[7 Bugs (§10.1)](#7-functional-bugs-spec-101) · [8 Security (§10.2)](#8-security-gaps-spec-102) ·
[9 Debt (§10.3)](#9-engineering-debt-spec-103) · [10 Reuse vs redesign (§11)](#10-reuse-vs-redesign-spec-11) ·
[11 PRD discrepancies (§12)](#11-prd-vs-code-discrepancies-spec-12) · [12 ERP gap list (§9)](#12-erp-gap-list-spec-9) ·
[13 Build-prompt items 1–12](#13-build-prompt-legacy_parity_and_corrections-112) ·
[14 Acceptance scenarios A–N](#14-acceptance-scenarios-an)

---

## 1. Roles and permissions (spec §3)

| ID | Legacy item | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| PERM-01 | `view_all_quotes` (admin, management, operations) | `sales.quote.read@company`; `modules/sales/policies.py` | 1 | planned | `tests/contract/test_legacy_permission_parity.py::test_legacy_templates_reproduce_spec_3_2` |
| PERM-02 | `view_own_quotes` (sales) | `sales.quote.read@own` | 1 | planned | `tests/contract/test_legacy_permission_parity.py::test_legacy_templates_reproduce_spec_3_2` |
| PERM-03 | `create_quotes` (admin, management, sales) | `sales.quote.create` | 1 | planned | `tests/contract/test_legacy_permission_parity.py::test_legacy_templates_reproduce_spec_3_2` |
| PERM-04 | `edit_all_quotes` (admin, management) | `sales.quote.{update,transition,issue,archive}@company` | 1 | planned | `tests/contract/test_legacy_permission_parity.py::test_legacy_templates_reproduce_spec_3_2` |
| PERM-05 | `edit_own_quotes` (sales) | `sales.quote.{update,transition,issue,archive}@own` | 1 | planned | `tests/contract/test_legacy_permission_parity.py::test_legacy_templates_reproduce_spec_3_2` |
| PERM-06 | `delete_quotes` (admin) | `sales.quote.delete` (never-issued drafts only) | 1 | implemented | `tests/integration/sales/test_quote_delete.py::test_delete_requires_permission_and_draft_never_issued` |
| PERM-07 | `override_price` (admin, management, sales) | `sales.quote_price.override`; reason waiver via `sales.quote_price.approve` | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_override_requires_permission_and_reason_for_sales` |
| PERM-08 | `export_quotes` (admin, management, sales) | `sales.quote.export` (rows bounded by read scope) | 1 | implemented | `tests/integration/sales/test_quote_idor.py::test_exports_bounded_by_read_scope` |
| PERM-09 | `view_products` (all four roles) | `catalogue.product.read` + `pricing.price.read` | 1 | planned | `tests/contract/test_legacy_permission_parity.py::test_legacy_templates_reproduce_spec_3_2` |
| PERM-10 | `edit_products` (admin) | `catalogue.product.{create,update,archive}`, `catalogue.media.manage`, `pricing.price_list.manage` | 1→2 | planned | `tests/integration/catalogue/test_product_crud.py::test_writes_require_catalogue_keys` |
| PERM-11 | `manage_users` (admin) | `identity.{user.read,user.manage,role.read,role.manage,permission.manage}` | 1→2 | implemented | `tests/integration/identity/test_user_admin.py::test_user_admin_requires_manage_keys` |
| PERM-12 | `import_data` (admin) | `imports.job.{read,run}` | 2 | planned | `tests/integration/imports/test_import_permissions.py::test_import_requires_imports_job_run` |
| PERM-13 | `view_costing` (admin, management) | `pricing.cost.read` + `pricing.price_list.read` (field guards) | 1→2 | implemented | `tests/integration/security/test_costing_redaction.py::test_costing_absent_without_pricing_cost_read` |
| PERM-14 | `manage_categories` (admin) | `catalogue.taxonomy.manage` | 2 | planned | `tests/integration/catalogue/test_taxonomy.py::test_taxonomy_writes_require_manage_key` |
| PERM-15 | Fixed roles `admin`, `management`, `sales`, `operations` | system role templates (+ employee base, finance, production, procurement, warehouse, catalogue) | 1 | planned | `tests/contract/test_legacy_permission_parity.py::test_management_has_no_destructive_or_identity_keys` |
| PERM-16 | Role is an unvalidated string | `role` rows with key CHECK; membership needs ≥1 role; unknown keys rejected | 1→2 | implemented | `tests/integration/authz/test_role_validation.py::test_unknown_key_scope_cycle_and_escalation_rejected` |
| PERM-17 | Effective permissions = role defaults ∪ grant − revoke | resolution with revoke always winning; `user_permission_override` | 1 | implemented | `tests/unit/authz/test_permission_resolution.py::test_revoke_wins_and_scope_is_max` |
| PERM-18 | `/auth/me` returns resolved permissions for UI hiding | `GET /api/v1/session/bootstrap` permissions + per-record `capabilities` | 1 | planned | `tests/integration/ui/test_session_bootstrap.py::test_permissions_and_capabilities_match_server_rules` |
| PERM-19 | §3.3 admin-only areas enforced by role check | permission keys per area, enforced in services | 1→2 | implemented | `tests/contract/test_route_authz_matrix.py::test_every_route_denies_unauthorised_personas` |
| PERM-20 | §3.3 quote create/update/lines/revise/status/duplicate for admin/sales/management | `sales.quote.*` with scope via `ScopedRepository` | 1→2 | implemented | `tests/integration/sales/test_quote_idor.py::test_quote_idor_matrix` |
| PERM-21 | §3.3 quote read/update/add-line ownership checks | own scope on `owner_user_id` | 1 | implemented | `tests/integration/sales/test_quote_idor.py::test_quote_idor_matrix` |
| PERM-22 | §3.3 quote delete: admin + delete_quotes + draft | `sales.quote.delete` + never-issued draft rule | 1 | implemented | `tests/integration/sales/test_quote_delete.py::test_delete_requires_permission_and_draft_never_issued` |
| PERM-23 | §3.3 challans, search, activity, notes, optimiser open to any login | `challans.*`, `search.global.use`, `collab` parent rules, `cutting.*` | 2 | implemented | `tests/contract/test_route_authz_matrix.py::test_every_route_denies_unauthorised_personas` |
| PERM-24 | §3.3 override/export/costing/edit/manage enforced in the UI only | server enforcement for every key | 1→2 | implemented | `tests/contract/test_route_authz_matrix.py::test_every_route_denies_unauthorised_personas` |
| PERM-25 | §3.4 JWT login, 24 h, `Authorization: Bearer` | opaque server sessions in HttpOnly cookie | 1 | implemented | `tests/integration/identity/test_login.py::test_successful_sign_in_sets_session_cookies`, `tests/integration/identity/test_sessions.py::test_sign_in_rotates_the_browser_session`, `tests/integration/identity/test_sessions.py::test_revocation_and_deactivation_apply_on_the_next_request` |
| PERM-26 | §3.4 `?auth=` query token for downloads | cookie-authenticated downloads; query tokens ignored | 1 | implemented | `tests/integration/identity/test_sessions.py::test_tokens_never_come_from_the_url` |
| PERM-27 | §3.4 change-password; admin reset returns a 12-char temporary password | self-service change (S1); one-time reset link, never a password (S2) | 1→2 | implemented | `tests/integration/identity/test_invitation_and_reset.py::test_admin_reset_never_returns_password` |
| PERM-28 | §3.4 fixed bootstrap admin re-synced from env on every boot | no bootstrap; `lk admin create-first` once | 1 | implemented | `tests/integration/identity/test_cli.py::test_create_first_refuses_when_an_admin_exists_anywhere`, `tests/integration/identity/test_access_sync.py::test_api_startup_repairs_template_drift_without_the_cli` |
| PERM-29 | §3.4 no lockout, rate limit, password policy, MFA, refresh, revocation, login audit | rate limits + lockout (S1), password policy (S1), TOTP MFA for admins (S2), revocation (S1), auth audit (S1) | 1→2 | implemented | `tests/integration/identity/test_login_security.py::test_generic_errors_lockout_and_rate_limits` |

## 2. Legacy modules (spec §5)

### 2.1 Authentication and user management (§5.1)

| ID | Legacy item | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| LM-01 | Login | `platform/identity` login service · `/login` | 1 | implemented | `tests/integration/identity/test_login.py::test_successful_sign_in_sets_session_cookies` |
| LM-02 | `me`: profile, resolved permissions, overrides | `GET /api/v1/identity/me` + session bootstrap · `/settings/profile` | 1 | implemented | `tests/integration/identity/test_profile.py::test_me_returns_profile_and_effective_permissions` |
| LM-03 | Change own password | `POST /api/v1/identity/me/password` (current password required; other sessions revoked) | 1 | implemented | `tests/integration/identity/test_profile.py::test_change_password_revokes_other_sessions` |
| LM-04 | Admin list/create/update (name, role, active) users | `platform/identity` admin API · `/settings/users` (S1: CLI and seed only) | 2 | implemented | `tests/integration/identity/test_user_admin.py::test_list_create_update_users` |
| LM-05 | Admin reset password (temporary password) | admin-issued one-time reset link (24 h, shown once) | 2 | implemented | `tests/integration/identity/test_invitation_and_reset.py::test_admin_reset_never_returns_password` |
| LM-06 | Cannot delete self | deactivation; last-admin guard; no self-escalation | 2 | implemented | `tests/integration/identity/test_deactivation.py::test_last_admin_guard_and_no_self_deactivation` |
| LM-07 | Hard delete of users; ids remain on records, names denormalised | users never hard-deleted; deactivation keeps attribution ("Name (inactive)") | 2 | implemented | `tests/integration/identity/test_deactivation.py::test_deactivation_keeps_attribution_and_revokes_sessions` |
| LM-08 | Per-user permission overrides | `user_permission_override` API (S1) · `/settings/users/[userId]` overrides UI (S2) | 1→2 | implemented | `tests/integration/authz/test_overrides.py::test_grant_and_revoke_with_reason_and_epoch_bump` |
| LM-09 | Read-only role matrix | role simulator `GET /api/v1/identity/access/effective` · `/settings/roles/simulate` | 2 | implemented | `tests/integration/authz/test_role_simulator.py::test_effective_permissions_with_sources` |

### 2.2 Product catalogue (§5.2)

| ID | Legacy item | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| LM-10 | Product listing: free-text search across key, SKU, name, category, subcategory, decor, finish; filters category, subcategory, status, brand, decor, thickness; limit/skip | `modules/catalogue/search.py` `search_products` · `/products` | 1 | implemented | `tests/integration/catalogue/test_product_list.py::test_search_and_filters_apply_before_pagination` |
| LM-11 | List enrichment: specs, EUR price, computed MOQ, primary image, decor fallback | catalogue list DTO + `pricing.display_prices` + engine recommendation | 1→2 | implemented | `tests/integration/catalogue/test_product_list.py::test_price_columns_require_pricing_price_read`, `tests/integration/catalogue/test_product_list.py::test_rows_enriched_without_n_plus_one` |
| LM-12 | Every search logged to `search_history` | `platform/search` `search_recent` (last 10 per user) | 2 | planned | `tests/integration/search/test_recent_searches.py::test_last_ten_kept_per_user` |
| LM-13 | Product detail: product, pricing rows, packaging, specs, media, EUR price, MOQ, primary image | `GET /api/v1/catalogue/products/{id}` · `/products/[productId]` | 1→2 | implemented | `tests/integration/catalogue/test_product_detail.py::test_detail_returns_all_field_groups_with_section_guards` |
| LM-14 | Product stats (by status, without pricing, updated 7 days, per category) | `GET /api/v1/catalogue/products/stats` · `/products` home | 2 | implemented | `tests/integration/catalogue/test_product_stats.py::test_stats_count_distinct_products` |
| LM-15 | Recent products (latest updated, with domestic price) | `GET /api/v1/catalogue/products/recent` · `/products` home | 2 | implemented | `tests/integration/catalogue/test_product_stats.py::test_recent_products_with_origin_and_actor` |
| LM-16 | Admin create product | `catalogue.create_product` · `/products/new` | 2 | implemented | `tests/integration/catalogue/test_product_crud.py::test_create_with_all_sections` |
| LM-17 | Admin update product with nested specification/packaging upsert | `PATCH /products/{id}`, `PUT .../specification`, `PUT .../packaging` (versioned) | 2 | implemented | `tests/integration/catalogue/test_product_crud.py::test_update_sections_with_version_conflict_409` |
| LM-18 | Admin delete product (hard-deletes pricing/packaging/specs, soft-deletes media) | archive/restore; hard delete only via import rollback or demo reset with FK RESTRICT | 2 | implemented | `tests/integration/catalogue/test_product_crud.py::test_archive_restore_and_no_hard_delete_via_ui` |
| LM-19 | Add a pricing row | price-list item create/supersede (`modules/pricing`) · `/products/price-lists/[id]` | 2 | implemented | `tests/integration/pricing/test_price_lists.py::test_item_create_and_supersede_with_history` |
| LM-20 | Replace packaging | `PUT /api/v1/catalogue/products/{id}/packaging` with alias provenance | 2 | implemented | `tests/integration/catalogue/test_product_crud.py::test_packaging_put_canonicalises_aliases` |
| LM-21 | Replace specifications | `PUT /api/v1/catalogue/products/{id}/specification` with dimension parsing | 2 | implemented | `tests/integration/catalogue/test_product_crud.py::test_specification_put_parses_dimensions` |
| LM-22 | Facets: categories, hierarchy, validate, brands, decors, thicknesses | `GET /api/v1/catalogue/products/facets`, `/categories`, `/taxonomy/validation` | 2 | planned | `tests/integration/catalogue/test_facets.py::test_facets_exclude_self_and_count_scoped_rows` |
| LM-23 | Media upload (image, document, packaging_photo; `is_primary` un-primaries siblings) | `POST /api/v1/catalogue/products/{id}/media` via `platform/files` | 2 | implemented | `tests/integration/catalogue/test_media.py::test_upload_sniffs_dedupes_and_single_primary` |
| LM-24 | Media list | `GET /api/v1/catalogue/products/{id}/media` · `/products/[productId]/media` | 2 | implemented | `tests/integration/catalogue/test_media.py::test_list_grouped_by_type` |
| LM-25 | Authenticated download proxy | `GET /api/v1/files/{id}/content` (cookie auth, streamed) | 2 | implemented | `tests/integration/files/test_file_download_authz.py::test_download_requires_parent_read_and_headers` |
| LM-26 | Media soft delete | `DELETE /api/v1/catalogue/media/{id}` (soft, reason) + restore | 2 | implemented | `tests/integration/catalogue/test_media.py::test_soft_delete_restore_and_primary_promotion` |
| LM-27 | Allowed file types by extension map | magic-byte sniffing (JPEG, PNG, GIF, WebP, PDF, OOXML, OLE); SVG/HTML/macros rejected | 2 | planned | `tests/unit/files/test_sniffing.py::test_accepts_allowed_and_rejects_svg_html_macros_mismatch` |

### 2.3 Bulk data import (§5.3)

| ID | Legacy item | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| LM-28 | `category_taxonomy` importer (must be first) | `modules/imports/definitions/category_taxonomy.py` | 2 | implemented | `tests/integration/imports/test_products_import.py::test_categories_before_subcategories` |
| LM-29 | `products_master` importer (category must exist; status normalised; display_sku/product_name default to key) | `definitions/products_master.py` | 2 | implemented | `tests/integration/imports/test_products_import.py::test_requires_taxonomy_and_applies_defaults` |
| LM-30 | `pricing_master` importer (`final_price` or `price`; orphans imported anyway) | `definitions/pricing_master.py` + pricing import contract `STD-{TYPE}-{CUR}` | 2 | implemented | `tests/integration/imports/test_dependent_imports.py::test_orphans_quarantined_and_price_alias_conflict` |
| LM-31 | `packaging_master` importer (wide alias mapping; orphans imported) | `definitions/packaging_master.py` | 2 | planned | `tests/integration/imports/test_packaging_import.py::test_alias_conflict_quarantined_with_row_numbers` |
| LM-32 | `specifications_master` importer | `definitions/specifications_master.py` | 2 | planned | `tests/integration/imports/test_specifications_import.py::test_orphans_quarantined_and_dimensions_parsed` |
| LM-33 | `media_master` importer (always inserts) | `definitions/media_master.py` (dedupe by product, type, URL key, then sha256) | 2 | planned | `tests/integration/imports/test_media_import.py::test_reimport_creates_no_duplicate_media` |
| LM-34 | `lookup_reference` importer (stored, never used) | `definitions/lookup_reference.py` + lookup browser/export | 2 | planned | `tests/integration/imports/test_lookup_import.py::test_upsert_idempotent_browse_and_export` |
| LM-35 | Preview (first 10 rows, columns, duplicate keys) | parse job preview (first 20 rows, header map, duplicate keys with row numbers, same-hash warning) | 2 | planned | `tests/integration/imports/test_preview.py::test_preview_lists_duplicates_with_row_numbers` |
| LM-36 | Validate (counts, orphan lists, products without pricing) | validate job + taxonomy validation report | 2 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_validation_report` |
| LM-37 | Clear sample data (wipes catalogue) | demo-only reset (`system.demo_data.delete`, `is_demo`, preview token, typed phrase, MFA) · `/settings/imports` demo panel | 2 | implemented | ; vitest `features/imports/imports.test.tsx` |
| LM-38 | Errors capped at 100 with row numbers and severity | uncapped `imports_row_issue` + downloadable `report.csv` | 2 | planned | `tests/integration/imports/test_report_csv.py::test_all_errors_reported_uncapped` |
| LM-39 | Headers lower-cased and underscored; documented aliases | header normaliser (BOM, NFKC, casefold, `_`) + alias registry | 2 | implemented | `tests/unit/imports/test_header_normalisation.py::test_normalisation_aliases_and_collisions` |

### 2.4 Category taxonomy (§5.4)

| ID | Legacy item | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| LM-40 | Admin CRUD of (category, subcategory) with display_order | `catalogue_category`, `catalogue_subcategory` · `/products/taxonomy` | 2 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_crud_reorder_and_activation` |
| LM-41 | Product import validates against taxonomy | `CATEGORY_NOT_FOUND` quarantine; unknown subcategory warning | 2 | implemented | `tests/integration/imports/test_products_import.py::test_unknown_category_quarantined` |
| LM-42 | Renames and deletes do not cascade | rename keeps aliases and updates search text; delete blocked by references or explicit reassign | 2 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_rename_alias_and_delete_or_reassign` |

### 2.5 Quotation engine (§5.5)

| ID | Legacy item | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| LM-43 | Catalogue configurator: selected filters, search text incl. numeric thickness, paging, narrowed options, enriched matches, `exact_match` | `POST /api/v1/sales/quotes/configurator/resolve` · configurator drawer in `/sales/quotes/[quoteId]` | 1→2 | implemented | `tests/integration/sales/test_configurator.py::test_filters_narrow_options_page_and_exact_match` |
| LM-44 | Quote header fields | `sales_quote` header · quote workspace header form | 1 | implemented | `tests/integration/sales/test_quote_header.py::test_header_fields_round_trip_with_party_snapshot` |
| LM-45 | Numbering `LK-QT-<year>-<0000>` (non-atomic) | `platform/numbering` sequence `sales.quote` (never reset by default) | 1 | implemented | `tests/integration/sales/test_quote_numbering.py::test_concurrent_quote_numbers_unique_gapless` |
| LM-46 | Catalog lines (configurator, full snapshot) | `sales_quote_line` type catalog with product/media/packaging/commercial snapshots | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_catalog_line_snapshot_immune_to_catalogue_change` |
| LM-47 | Custom lines (from custom-product library) | line type custom | 2 | implemented | `tests/integration/sales/test_quote_lines.py::test_custom_line_from_custom_product` |
| LM-48 | Manual lines (free text) | line type manual with presets | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_manual_line_presets` |
| LM-49 | `line_total = quoted_price × quantity`; totals recomputed after every change; remaining lines renumbered | engine persisted result in the same transaction; deferrable line_no constraint | 1 | implemented | `tests/integration/sales/test_quote_totals.py::test_totals_persisted_and_lines_renumbered_atomically` |
| LM-50 | `default_price` vs `quoted_price` + `override_reason` | override with permission and reason; default kept for audit | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_override_requires_permission_and_reason_for_sales` |
| LM-51 | Status workflow draft → internal_review → sent → revised → won/lost (no rules) | table-driven state machine `POST /api/v1/sales/quotes/{id}/transitions` | 1→2 | implemented | `tests/integration/sales/test_quote_status.py::test_quote_status_machine_table` |
| LM-52 | Every status change writes a revision snapshot | `sales_quote_status_history` (append-only) + issued revisions at issue | 1 | implemented | `tests/integration/sales/test_quote_status.py::test_status_history_append_only` |
| LM-53 | Revise: snapshot + version bump | `revise` transition (sent → revised), revision_no + 1 | 2 | implemented | `tests/integration/sales/test_quote_revisions.py::test_revise_creates_working_copy` |
| LM-54 | Revisions listed; no restore or diff | compare (header, lines by line_key, totals) and restore into a new draft version | 2 | implemented | `tests/integration/sales/test_quote_revisions.py::test_compare_and_restore_keep_history` |
| LM-55 | Duplicate quote (new number, draft, lines copied, customer reference cleared) | `POST .../duplicate` with real totals and owner policy | 2 | implemented | `tests/integration/sales/test_quote_duplicate.py::test_duplicate_real_totals_reference_cleared_owner_policy` |
| LM-56 | PDF export (A4, logo, terms block, 6-column table, totals, surcharge, threshold note, remarks, footer) | `core/documents` quote PDF from the issued snapshot | 1 | implemented | `tests/integration/documents/test_quote_pdf.py::test_layout_unicode_pagination_and_totals` |
| LM-57 | Quote list CSV export | `GET /api/v1/sales/quotes/export.csv` via `core/csv_safe` | 2 | implemented | `tests/integration/sales/test_quote_csv.py::test_line_counts_names_totals_and_escaping` |
| LM-58 | List search by number/customer/country, status filter, scope mine/all, pagination | `GET /api/v1/sales/quotes` · `/sales/quotes` | 1 | implemented | `tests/integration/sales/test_quote_list.py::test_filters_scope_and_paging_totals` |
| LM-59 | Admin delete of draft quotes (removes lines and revisions) | soft delete of never-issued drafts; number never reused | 1 | implemented | `tests/integration/sales/test_quote_delete.py::test_soft_delete_keeps_number_reserved` |
| LM-60 | Internal notes on quotes | `platform/collab` note on `sales.quote` | 2 | implemented | `tests/integration/collab/test_internal_notes.py::test_autosave_conflict_409_and_parent_update_required` |
| LM-61 | Dynamic MOQ (advisory) | engine order-value recommendation, labelled separately from product MOQ | 1 | implemented | `tests/unit/commercial/test_engine.py::test_recommended_quantity` |

### 2.6 Custom products (§5.6)

| ID | Legacy item | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| LM-62 | Library with auto code `CP-NNNN` | `sales_custom_product` + sequence `sales.custom_product` · `/sales/custom-products` | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_codes_unique_never_reused` |
| LM-63 | List, search, filter | `GET /api/v1/sales/custom-products` (search by `product_name`) | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_list_search_filter_paging` |
| LM-64 | Create, edit | create/update with all legacy fields · `/sales/custom-products/new`, `/[id]` | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |
| LM-65 | Admin delete | archive rules (rejected, dormant, converted or never quoted) | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_archive_rules` |
| LM-66 | Duplicate (API only) | `POST .../duplicate` with a UI action; name "X (Copy)" in `product_name` | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_duplicate_new_code_and_product_name_copy` |
| LM-67 | CSV export | `GET .../custom-products/export.csv` (costing only with `pricing.cost.read`) | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_csv_export_escaped_and_costing_guarded` |
| LM-68 | Internal notes | collab note on `sales.custom_product` | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_internal_notes_on_custom_products` |
| LM-69 | Selectable as a quote line | custom line type with snapshot | 2 | implemented | `tests/integration/sales/test_quote_lines.py::test_custom_line_from_custom_product` |
| LM-70 | `is_promoted_to_master` without a promote action | promotion with lineage and approval → master product | 2 | implemented | `tests/integration/sales/test_custom_product_promotion.py::test_request_approve_execute_idempotent` |

### 2.7 Sheet optimiser (§5.7)

| ID | Legacy item | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| LM-71 | Input items `{sku, decor, thickness, length, width, quantity}` + `allow_oversize` | `cutting_plan_item` + settings snapshot · `/operations/cutting/[planId]` | 2 | implemented | `tests/integration/cutting/test_plan_persistence.py::test_save_reopen_preserves_inputs_and_results` |
| LM-72 | Board 2440 × 1220, margin 5, gap 6, +10 oversize (code constants) | `cutting_settings` defaults + machine profiles | 2 | implemented | `tests/unit/cutting/test_packer_examples.py::test_defaults_and_oversize_effect` |
| LM-73 | Group by (decor, thickness); largest area first; rotation unless grain-locked | packer groups on canonical decor + normalised thickness; grain rule per item | 2 | implemented | `tests/unit/cutting/test_packer_examples.py::test_grouping_decor_thickness` |
| LM-74 | Grain-locked decors list (add, remove, replace) | `cutting_grain_lock` keyed on canonical decor · `/operations/cutting/grain-locks` | 2 | implemented | `tests/integration/cutting/test_grain_settings.py::test_grain_lock_writes_require_manage_and_canonical_key` |
| LM-75 | Outputs per group (boards, placed vs required, efficiency, scrap, used/sheet area, per-SKU produced, unfit, placements, leftovers) | `cutting_calculation` + groups, boards, placements, item results, offcuts | 2 | implemented | `tests/unit/cutting/test_packer_properties.py::test_counts_reconcile` |
| LM-76 | Per-board SVG + placement table | true-scale SVG canvas + accessible placement table; per-board SVG/PDF export | 2 | implemented | `e2e/scenarios/h-cutting-canvas.spec.ts::plan_calculate_save_reopen_svg` |
| LM-77 | `allow_overproduction` accepted but unused | bounded explicit overproduction into open boards only | 2 | implemented | `tests/unit/cutting/test_packer_examples.py::test_overproduction_bounded` |
| LM-78 | No save, export, print or links | save/reopen/duplicate/export (CSV, PDF, SVG); WO links in S4 | 2→4 | implemented | `tests/integration/cutting/test_plan_persistence.py::test_duplicate_copies_inputs_and_exports_escape_formulas`; WO link `tests/integration/production/test_cut_plans_capacity.py::test_cut_plan_link_sets_board_requirement_and_release_releases_the_plan` |
| LM-79 | Catalogue product search for autocomplete | `GET /api/v1/cutting/products?search=` (scoped catalogue search) | 2 | implemented | `tests/integration/cutting/test_calculate_endpoint.py::test_product_autocomplete_fills_decor_thickness_dimensions` |

### 2.8 Delivery challans (§5.8)

| ID | Legacy item | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| LM-80 | Types Outward, Inward, Return, Job Work, Transfer, Sample | `challans_challan.challan_type` | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_all_types_return_types_destinations` |
| LM-81 | Return type returnable / non-returnable | `return_type` (Job Work forced returnable when posting) | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_all_types_return_types_destinations` |
| LM-82 | Destination types Fabricator, Customer, Warehouse, Vendor, Office, Transporter | `destination_type` + party roles / office locations | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_all_types_return_types_destinations` |
| LM-83 | Statuses draft, issued, closed, cancelled | validated state machine | 2 | implemented | `tests/unit/challans/test_status_machine.py::test_valid_and_invalid_transitions_table` |
| LM-84 | Header fields | all legacy header fields + structured party/warehouse links | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_header_fields_round_trip` |
| LM-85 | Auto number `DC-<year>-<0001>` (restarts yearly) | sequence `challans.challan` yearly | 2 | implemented | `tests/integration/challans/test_challan_numbering.py::test_concurrent_dc_numbers_unique_yearly_reset` |
| LM-86 | Lines: item code, name, HSN/SAC, quantity, unit, remarks, line type | `challans_challan_line` with optional product/custom link and UOM rules | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_lines_with_product_lookup_and_uom_rules` |
| LM-87 | List filters (search, status, type, destination type/party, week, month, range) | `GET /api/v1/challans/challans` · `/operations/challans` | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_list_filters_before_paging` |
| LM-88 | Summary cards (total, week, month, pending returnable, by type/destination/status) | `GET /api/v1/challans/challans/summary` (same filters and scope) | 2 | implemented | `tests/integration/challans/test_challan_summary.py::test_summary_counts_scoped` |
| LM-89 | Duplicate with lines | `POST .../duplicate` | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_duplicate_with_lines_new_number` |
| LM-90 | CSV export | `GET .../export.csv` via `core/csv_safe` | 2 | implemented | `tests/integration/challans/test_challan_documents.py::test_csv_escaped_and_scoped` |
| LM-91 | Branded PDF (FROM/TO, line table, total qty, T&C, signature boxes) | `core/documents` challan PDF with configured identity and terms | 2 | implemented | `tests/integration/challans/test_challan_documents.py::test_pdf_unicode_pagination_terms_signatures_no_internal_notes` |
| LM-92 | Browser print view | `/print/challans/[id]` | 2 | implemented | `e2e/challans.spec.ts::challan_print_preview` |
| LM-93 | Delete: admin only, draft only | `challans.challan.delete` (admin), soft delete, number never reused | 2 | implemented | `tests/integration/challans/test_challan_permissions.py::test_admin_only_draft_delete_number_not_reused` |
| LM-94 | No stock effect, no return reconciliation, no e-way bill / GST value | document links for returns (S2); movement policy and postings (S4); e-way bill future scope | 2→4 | implemented | `tests/integration/challans/test_issue_return_cancel.py::test_partial_return_linked_to_original_line` |
| LM-95 | Internal notes on challans | collab note on `challans.challan` (never printed) | 2 | planned | `tests/integration/collab/test_internal_notes.py::test_notes_never_printed` |

### 2.9 Cross-module utilities (§5.9)

| ID | Legacy item | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| LM-96 | Global search (products, custom products, quotes, challans, categories; grouped; deep links; min 2 chars) | `platform/search` providers · search dialog (`/`) and `/search` | 2 | implemented | `tests/integration/search/test_global_search.py::test_grouped_scoped_results_with_deep_links` |
| LM-97 | Data completeness (missing images/decor/price/MOQ; custom products missing description/dimensions) | `modules/catalogue/completeness.py` per-product metrics · `/products/completeness` | 2 | planned | `tests/integration/catalogue/test_completeness.py::test_metrics_count_distinct_products_real_fields` |
| LM-98 | Recent activity (latest quotes, challans, custom products) | `platform/collab` activity projector · `/activity` | 2 | implemented | `tests/integration/collab/test_activity.py::test_feed_filtered_by_parent_visibility` |
| LM-99 | Internal notes `PUT /internal-notes/{type}/{id}` (auto-saved) | `PUT /api/v1/collab/notes/{resource_type}/{resource_id}` with `expected_version` | 2 | implemented | `tests/integration/collab/test_internal_notes.py::test_autosave_conflict_409_and_parent_update_required` |
| LM-100 | Light audit trail (`updated_by/at`, quote revisions) | `platform/audit` append-only log + record history | 1→2 | implemented | `tests/integration/audit/test_audit_append_only.py::test_update_delete_rejected_and_security_events_recorded` |
| LM-101 | `GET /` version and `GET /health` | `/api/v1/health/live`, `/api/v1/health/ready` | 0 | planned | `tests/integration/system/test_health_readiness.py::test_live_and_ready` |

## 3. Field groups (spec §4)

Rule for every field group: each legacy field has a column (or a documented canonical replacement with the original kept
as provenance), is editable where legacy allowed it, round-trips through API, CSV export and re-import, and is covered by
`tests/integration/catalogue/test_product_fields_round_trip.py` (catalogue) or the module tests named below.

### 3.1 `users` (§4.1)

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-USR-01 | `id`, `email` (unique), `name` | `app_user` (`email_normalized` unique, `display_name`, `full_name`) | 1 | implemented | `tests/integration/identity/test_user_admin.py::test_email_normalised_unique` |
| FG-USR-02 | `role` (unvalidated string) | `membership_role` → `role` (validated) | 1 | implemented | `tests/integration/authz/test_role_validation.py::test_unknown_key_scope_cycle_and_escalation_rejected` |
| FG-USR-03 | `password_hash` (bcrypt) | argon2id `password_hash`; legacy hashes never migrated | 1→5 | planned | `tests/integration/migration/test_users.py::test_no_password_hash_persisted_users_pending_invitation` |
| FG-USR-04 | `is_active` | `membership.status` (invited, active, suspended, deactivated) + `app_user.status` incl. historical | 1→2 | implemented | `tests/integration/identity/test_deactivation.py::test_deactivation_keeps_attribution_and_revokes_sessions` |
| FG-USR-05 | `created_at`, `last_login` | `created_at`, `last_login_at` + `auth_attempt` history | 1 | implemented | `tests/integration/identity/test_login_security.py::test_attempts_and_last_login_recorded` |
| FG-USR-06 | `permission_overrides{grant[], revoke[]}` | `user_permission_override` rows (reason, expiry, revoke wins); legacy names expanded via alias table | 1→5 | planned | `tests/integration/authz/test_overrides.py::test_legacy_overrides_expand_through_alias_table` |

### 3.2 `products_master` (§4.2)

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-PRD-01 | `product_key` (PK, unique) | `catalogue_product.product_key` unique per company, immutable (trigger), UUID `id` for URLs | 1 | implemented | `tests/integration/catalogue/test_product_crud.py::test_product_key_immutable_api_and_db_trigger` |
| FG-PRD-02 | `display_sku` (non-unique) | `display_sku` NOT NULL, non-unique; completeness flags shared SKUs (info) | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_display_sku_non_unique_preserved` |
| FG-PRD-03 | `product_name` | `product_name` NOT NULL (defaults to key on import) | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_master_fields_round_trip` |
| FG-PRD-04 | `brand` | `brand` text (brand registry is future scope) | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_master_fields_round_trip` |
| FG-PRD-05 | `category`, `subcategory` (free text) | FKs `category_id`, `subcategory_id` (composite FK) + `*_source` text | 1 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_composite_fk_rejects_foreign_subcategory` |
| FG-PRD-06 | `product_type`, `variant_group` | same columns; configurator "family" filter uses `variant_group` | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_master_fields_round_trip` |
| FG-PRD-07 | `unit_of_sale` | UOM code via `uom_alias` (source text kept) | 1 | planned | `tests/unit/catalogue/test_uom_aliases.py::test_unit_text_maps_or_flags_uom_unknown` |
| FG-PRD-08 | `size_mm` | `catalogue_product_dimension(kind=master_size)` + effective size columns NUMERIC(12,3) | 1 | planned | `tests/unit/catalogue/test_parse_dimension.py::test_parse_dimension_cases` |
| FG-PRD-09 | `decor_no`, `decor_name` | text `decor_no` (+ `decor_no_source`), `decor_name`; leading zeros kept | 1 | implemented | `tests/unit/catalogue/test_normalise_identifier.py::test_normalise_identifier`, `tests/unit/catalogue/test_normalise_identifier.py::test_120_0_becomes_120_and_0120_stays_distinct` |
| FG-PRD-10 | `decor_primary`, `decor_options` | `decor_primary`, `decor_options` text[] + `decor_options_text`; form inputs exist | 1→2 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_decor_fields_round_trip` |
| FG-PRD-11 | `finish`, `shape` | same columns | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_master_fields_round_trip` |
| FG-PRD-12 | `status` (active, inactive, under_development) | enum CHECK + label aliases on import | 1 | planned | `tests/unit/imports/test_value_rules.py::test_status_aliases` |
| FG-PRD-13 | `description`, `internal_remarks` | same; `internal_remarks` never printed | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_master_fields_round_trip` |
| FG-PRD-14 | `source_design_no`, `source_shape_no` | same columns (provenance) | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_provenance_fields_round_trip` |
| FG-PRD-15 | `source_sheet`, `source_row`, `source_catalog_page`, `source_notes` | same columns (text) + `source_extra` jsonb for unknown import columns | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_provenance_fields_round_trip` |
| FG-PRD-16 | `created_at`, `updated_at` | timestamps from the Clock; legacy values kept on migration | 1→5 | planned | `tests/integration/migration/test_dry_run.py::test_legacy_timestamps_preserved` |
| FG-PRD-17 | Indexes: unique key; SKU, category, decor; unused text index | indexes per catalogue design + pg_trgm on `search_text` | 1 | planned | `tests/integration/catalogue/test_product_list.py::test_search_uses_escaped_ilike_and_trigram` |
| FG-PRD-18 | (new) stock attributes | nullable `hsn_sac`, `stock_uom_code`, `is_stock_tracked`, `track_lots`, `qc_required` (required at inventory go-live) | 1→4 | planned | `tests/integration/catalogue/test_stock_attributes.py::test_required_when_inventory_live` |

### 3.3 `pricing` (§4.3)

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-PRC-01 | `id`, `product_key` | `pricing_price_list_item.product_id` + `product_key` | 1 | implemented | `tests/integration/pricing/test_price_lists.py::test_item_fields_round_trip` |
| FG-PRC-02 | `price_type` (domestic, export, sample, distributor) | `pricing_price_list.price_type` | 1 | planned | `tests/integration/pricing/test_price_resolution.py::test_price_type_selects_list_deterministically` |
| FG-PRC-03 | `currency` (default INR; logic reads EUR) | list currency; enabled INR, EUR, USD, GBP | 1 | planned | `tests/integration/pricing/test_price_resolution.py::test_currency_unit_and_date_filters` |
| FG-PRC-04 | `price`, `final_price` (alias pair) | `final_price` NUMERIC(18,4); import conflict `PRICE_AMBIGUOUS` | 1→2 | implemented | `tests/integration/imports/test_dependent_imports.py::test_orphans_quarantined_and_price_alias_conflict` |
| FG-PRC-05 | `base_price` (+label) | `base_price` + label (guard `pricing.price_list.read`) | 1 | implemented | `tests/integration/pricing/test_price_lists.py::test_breakdown_fields_need_price_list_read` |
| FG-PRC-06 | `addon_price` (+label) | `addon_price` + label (same guard) | 1 | implemented | `tests/integration/pricing/test_price_lists.py::test_breakdown_fields_need_price_list_read` |
| FG-PRC-07 | `price_basis` | `price_basis` (legacy text) | 1 | implemented | `tests/integration/pricing/test_price_lists.py::test_item_fields_round_trip` |
| FG-PRC-08 | `yield_qty_per_board` | same (guarded) | 1 | implemented | `tests/integration/pricing/test_price_lists.py::test_item_fields_round_trip` |
| FG-PRC-09 | `thickness_mm` | same NUMERIC(8,3) | 1 | implemented | `tests/integration/pricing/test_price_lists.py::test_item_fields_round_trip` |
| FG-PRC-10 | `moq` | `moq` + `moq_unit_code` (product MOQ, distinct from order-value recommendation) | 1 | implemented | `tests/unit/commercial/test_engine.py::test_product_moq_distinct_from_recommendation` |
| FG-PRC-11 | `unit_of_sale` | `unit_code` (no automatic unit conversion of prices) | 1 | planned | `tests/integration/pricing/test_price_resolution.py::test_unit_mismatch_unavailable_with_hint` |
| FG-PRC-12 | `price_notes` | `notes` | 1 | implemented | `tests/integration/pricing/test_price_lists.py::test_item_fields_round_trip` |
| FG-PRC-13 | `valid_from`, `valid_to` | item and list validity; no overlap (btree_gist EXCLUDE + service check) | 1→2 | implemented | `tests/integration/pricing/test_price_lists.py::test_overlap_rejected_at_activation` |
| FG-PRC-14 | `display_sku`, `source_sheet`, `source_row` | same provenance columns + `import_job_id` | 1→2 | implemented | `tests/integration/pricing/test_price_lists.py::test_item_fields_round_trip` |
| FG-PRC-15 | `created_at`, `updated_at` | timestamps + append-only `pricing_price_list_item_history` | 2 | implemented | `tests/integration/pricing/test_price_lists.py::test_active_items_immutable_and_history_append_only` |
| FG-PRC-16 | Import upsert key (product_key, price_type, currency) | maps to list `STD-{TYPE}-{CUR}`; supersede with valid_from | 2 | implemented | `tests/integration/pricing/test_pricing_import_contract.py::test_import_supersedes_into_standard_list` |

### 3.4 `packaging` (§4.4) — every alias pair

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-PKG-01 | `carton_qty` / `master_carton_qty` | canonical `carton_qty` int; conflict quarantined `ALIAS_CONFLICT`; provenance in `alias_provenance` | 1→2 | planned | `tests/unit/catalogue/test_packaging_aliases.py::test_carton_qty_alias_pair` |
| FG-PKG-02 | `unit_weight_g` / `unit_weight_kg` | canonical `unit_weight_g` (g = kg × 1000 exactly, 0.001 g scale) | 1→2 | planned | `tests/unit/catalogue/test_packaging_aliases.py::test_unit_weight_alias_pair` |
| FG-PKG-03 | `packing_type` / `unit_packing_type` | canonical `packing_type` (case/whitespace-insensitive compare) | 1→2 | planned | `tests/unit/catalogue/test_packaging_aliases.py::test_packing_type_alias_pair` |
| FG-PKG-04 | `inner_qty` / `inner_pack_qty` | canonical `inner_qty` int | 1→2 | planned | `tests/unit/catalogue/test_packaging_aliases.py::test_inner_qty_alias_pair` |
| FG-PKG-05 | `carton_length_cm`, `carton_width_cm`, `carton_height_cm` | same NUMERIC(10,2) cm (form inputs exist) | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_packaging_fields_round_trip` |
| FG-PKG-06 | `net_weight_kg`, `gross_weight_kg` | same NUMERIC(12,4), per master carton; gross < net warns | 1 | planned | `tests/unit/catalogue/test_packaging_aliases.py::test_cross_checks_warn` |
| FG-PKG-07 | `cbm` | NUMERIC(12,6); > 2 % difference from L×W×H warns | 1 | planned | `tests/unit/catalogue/test_packaging_aliases.py::test_cross_checks_warn` |
| FG-PKG-08 | `packaging_notes`, `fragile_notes` | same | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_packaging_fields_round_trip` |
| FG-PKG-09 | `packaging_status`, `notes` | same | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_packaging_fields_round_trip` |
| FG-PKG-10 | One row per product (unique `product_key`) | `catalogue_product_packaging` PK `product_id` | 1 | implemented | `tests/integration/catalogue/test_product_crud.py::test_packaging_one_row_per_product` |
| FG-PKG-11 | MOQ, configurator and summary read only `carton_qty`/`unit_weight_g`/`packing_type` | all readers use canonical columns; packaging summary "450g · 24/ctn · Poly bag" | 1 | implemented | `tests/integration/catalogue/test_seed_world.py::test_oak_tray_fixture_fields` |

### 3.5 `specifications` (§4.5)

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-SPC-01 | `length_mm`, `width_mm` | NUMERIC(12,3) + `*_source` | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_specification_fields_round_trip` |
| FG-SPC-02 | `thickness_mm`, `thickness_text` | `thickness_mm` NUMERIC(8,3) + `thickness_text` | 1 | planned | `tests/integration/catalogue/test_product_list.py::test_thickness_filter_paginates_before_limit` |
| FG-SPC-03 | `size_mm`, `size_label` | dimension row `spec_size` + `size_label` | 1 | planned | `tests/unit/catalogue/test_parse_dimension.py::test_parse_dimension_cases` |
| FG-SPC-04 | `finish`, `material_type`, `type`, `top_sheet` | `spec_finish`, `material_type`, `spec_type`, `top_sheet` | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_specification_fields_round_trip` |
| FG-SPC-05 | `groove_count`, `bowl_count`, `bowl_type` | same (non-negative CHECK) | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_specification_fields_round_trip` |
| FG-SPC-06 | `stand_material`, `stand_size_mm` | `stand_material` + dimension row `stand_size` | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_specification_fields_round_trip` |
| FG-SPC-07 | `board_size_mm`, `working_size_mm` | dimension rows `board_size`, `working_size` (form inputs exist) | 1→2 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_dimension_rows_round_trip` |
| FG-SPC-08 | `plate1_size_mm`, `plate2_size_mm`, `plate3_size_mm` | dimension rows `plate_1/2/3_size` (header alias `plate_1_size_mm`) | 1→2 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_dimension_rows_round_trip` |
| FG-SPC-09 | `no_of_boards` | same | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_specification_fields_round_trip` |
| FG-SPC-10 | `handle_type` | same | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_specification_fields_round_trip` |
| FG-SPC-11 | `special_features`, `care_instructions`, `usage_notes` | same | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_specification_fields_round_trip` |
| FG-SPC-12 | One row per product | `catalogue_product_specification` PK `product_id` | 1 | implemented | `tests/integration/catalogue/test_product_crud.py::test_specification_one_row_per_product` |

### 3.6 `media` (§4.6)

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-MED-01 | `id`, `product_key`, `media_type` (image, document, packaging_photo) | `catalogue_product_media` (`product_id`, `media_type`, `legacy_media_id`) | 2 | implemented | `tests/integration/catalogue/test_media.py::test_media_fields_round_trip` |
| FG-MED-02 | `storage_path` (object-store key) | `file_object` via `platform/files` (content-addressed key) | 2 | planned | `tests/integration/files/test_file_dedupe.py::test_identical_bytes_reuse_file_object` |
| FG-MED-03 | `file_url` / `drive_link` / `file_path` (location alias group) | `source_kind`, `source_url_key` (Drive canonicalised), `source_path`; differing values quarantined | 2 | planned | `tests/integration/imports/test_media_import.py::test_location_alias_group_conflict_quarantined` |
| FG-MED-04 | `file_name` / `original_filename` | both kept; `file_name` displayed; difference warns | 2 | planned | `tests/integration/imports/test_media_import.py::test_filename_pair_kept` |
| FG-MED-05 | `content_type`, `size` | sniffed `content_type`, `size_bytes`, `sha256` | 2 | planned | `tests/unit/files/test_sniffing.py::test_accepts_allowed_and_rejects_svg_html_macros_mismatch` |
| FG-MED-06 | `is_primary` | single primary per product (partial unique), images only | 2 | implemented | `tests/integration/catalogue/test_media.py::test_upload_sniffs_dedupes_and_single_primary` |
| FG-MED-07 | `is_deleted` (soft) | `deleted_at/by`, `delete_reason`, restore | 2 | implemented | `tests/integration/catalogue/test_media.py::test_soft_delete_restore_and_primary_promotion` |
| FG-MED-08 | `alt_text` | same | 2 | implemented | `tests/integration/catalogue/test_media.py::test_media_fields_round_trip` |
| FG-MED-09 | `uploaded_at`, `uploaded_by` | same (own-scope media management uses uploader) | 2 | implemented | `tests/integration/catalogue/test_media.py::test_own_scope_cannot_delete_others_uploads` |

### 3.7 `category_taxonomy` (§4.7)

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-TAX-01 | `id`, `category`, `subcategory` (unique pair) | `catalogue_category` + `catalogue_subcategory` (unique name keys) | 1 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_duplicate_name_keys_conflict` |
| FG-TAX-02 | `display_order` | same; ties by name | 1 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_tree_follows_display_order` |
| FG-TAX-03 | `is_active` | NOT NULL DEFAULT true; inactive parent hides children | 1 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_created_category_active_by_default`, `tests/integration/catalogue/test_taxonomy.py::test_inactive_parent_hides_its_children` |
| FG-TAX-04 | `product_count` | `legacy_product_count` provenance; live counts computed | 2 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_live_counts_computed` |
| FG-TAX-05 | `description` | same | 1 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_crud_reorder_and_activation` |
| FG-TAX-06 | `source_catalog_page_start/end` | same text columns | 1 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_crud_reorder_and_activation` |

### 3.8 `lookup_reference` (§4.8)

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-LKP-01 | `lookup_type`, `key_1`, `key_2` | `catalogue_lookup_reference` unique (type, key_1, key_2 default '') | 2 | planned | `tests/integration/imports/test_lookup_import.py::test_upsert_idempotent_browse_and_export` |
| FG-LKP-02 | `value_1`, `value_2`, `notes` | same + `source_extra` | 2 | planned | `tests/integration/imports/test_lookup_import.py::test_upsert_idempotent_browse_and_export` |
| FG-LKP-03 | Imported but never read | read-only browser, safe CSV export, agent read tool; documented as reference-only | 2→3 | planned | `e2e/catalogue/lookups.spec.ts::browse_filter_export` |

### 3.9 `quote_settings` (§4.9)

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-QST-01 | `brand_prefix` "LK" | brand token in sequence tokens (`^[A-Z]{2,4}$`) + quote default brand | 1 | implemented | `tests/integration/sales/test_quote_numbering.py::test_brand_token_and_shared_counter` |
| FG-QST-02 | `quote_prefix` "QT" | `document_sequence.format_template` `{brand}-QT-{yyyy}-{seq:04}` | 1 | planned | `tests/unit/numbering/test_sequence_settings_validation.py::test_template_rules` |
| FG-QST-03 | `year_format` | `{yyyy}`/`{yy}` tokens (local year in Asia/Kolkata) | 1 | planned | `tests/integration/numbering/test_concurrent_numbering.py::test_local_year_boundary` |
| FG-QST-04 | `next_sequence` (non-atomic) | `document_sequence_counter` (atomic upsert, only increases) | 1 | planned | `tests/integration/numbering/test_concurrent_numbering.py::test_unique_gapless_rollback_consumes_none` |
| FG-QST-05 | `format_template` (stored, ignored) | honoured and validated; preview without allocation | 1→2 | planned | `tests/unit/numbering/test_sequence_settings_validation.py::test_preview_does_not_allocate` |

### 3.10 `quotes` (§4.10)

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-QUO-01 | `id`, `quote_number` (unique) | `sales_quote` UUID + immutable `quote_number` unique per company | 1 | implemented | `tests/integration/sales/test_quote_numbering.py::test_concurrent_quote_numbers_unique_gapless` |
| FG-QUO-02 | `version` | `revision_no` (legacy version) + optimistic `version` | 1 | implemented | `tests/integration/sales/test_quote_header.py::test_optimistic_version_409` |
| FG-QUO-03 | `status` | eight statuses with validated transitions | 1→2 | implemented | `tests/integration/sales/test_quote_status.py::test_cancelled_and_archived_transitions` |
| FG-QUO-04 | `customer_name`, `customer_country`, `customer_reference` | `party_id` + `customer_snapshot` + flattened columns; `party_link_status` | 1 | implemented | `tests/integration/sales/test_quote_header.py::test_header_fields_round_trip_with_party_snapshot` |
| FG-QUO-05 | `customer_type` (standard, dealer, distributor) | `customer_type_id/code` driving price tiers | 1 | planned | `tests/integration/pricing/test_price_resolution.py::test_tier_order_agreement_type_standard` |
| FG-QUO-06 | `currency` (EUR), `incoterm` (FOB) | same + `incoterm_place`; currency change only via list or approved FX | 1→2 | implemented | `tests/integration/sales/test_currency_change.py::test_db_rejects_currency_relabel` |
| FG-QUO-07 | `payment_terms`, `validity_days` (30) | same; `quote_date`, `valid_until` | 1 | implemented | `tests/integration/sales/test_quote_header.py::test_valid_until_from_issue_date` |
| FG-QUO-08 | `remarks`, `min_invoice_note` | same (printed); min-invoice note from rule template | 1 | implemented | `tests/integration/documents/test_quote_pdf.py::test_layout_unicode_pagination_and_totals` |
| FG-QUO-09 | `brand` ("LK") | same | 1 | implemented | `tests/integration/sales/test_quote_header.py::test_header_fields_round_trip_with_party_snapshot` |
| FG-QUO-10 | `surcharge_applied` (toggle; not persisted in totals) | `surcharge_requested` toggle + persisted `surcharge_applied`, `surcharge_amount` | 1 | implemented | `tests/unit/commercial/test_engine.py::test_surcharge_table` |
| FG-QUO-11 | `created_by`, `created_by_name` | `created_by` FK (names from users, historical people on migration) | 1→5 | planned | `tests/integration/sales/test_quote_csv.py::test_line_counts_names_totals_and_escaping` |
| FG-QUO-12 | `assigned_to`, `assigned_to_name` | `owner_user_id` (migration: owner = assigned_to else created_by) | 1→5 | planned | `tests/integration/migration/test_quotes.py::test_owner_from_assigned_to_else_created_by` |
| FG-QUO-13 | `updated_by` | `updated_by` + audit log | 1 | implemented | `tests/integration/audit/test_audit_append_only.py::test_update_delete_rejected_and_security_events_recorded` |
| FG-QUO-14 | `internal_notes` | collab note (never printed) | 2 | planned | `tests/integration/collab/test_internal_notes.py::test_notes_never_printed` |
| FG-QUO-15 | `total_amount`, `total_lines` | persisted `line_count`, gross/discount/net/applicable subtotals, surcharge, tax status, `grand_total`, engine version, input hash | 1 | implemented | `tests/integration/documents/test_output_channels_agree.py::test_api_pdf_csv_print_totals_identical` |
| FG-QUO-16 | `created_at`, `updated_at` | Clock timestamps; legacy preserved on migration | 1→5 | planned | `tests/integration/migration/test_dry_run.py::test_legacy_timestamps_preserved` |
| FG-QUO-17 | No customer id (free text) | party link required to issue; legacy rows `legacy_unlinked` with candidate review | 1→5 | planned | `tests/integration/migration/test_party_candidates.py::test_never_auto_merge_decision_reused` |

### 3.11 `quote_lines` (§4.11)

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-QLN-01 | `id`, `quote_id`, `line_number`, `sort_order` | `sales_quote_line` (`line_no` deferrable unique, `sort_order`, stable `line_key`) | 1 | implemented | `tests/integration/sales/test_quote_totals.py::test_totals_persisted_and_lines_renumbered_atomically` |
| FG-QLN-02 | `line_type` (catalog, custom, manual) | same + CHECK on required references; `manual_preset` | 1→2 | implemented | `tests/integration/sales/test_quote_lines.py::test_line_type_reference_checks` |
| FG-QLN-03 | `product_key`, `custom_product_id` | `product_id` + `product_key`, `custom_product_id` (FK RESTRICT) | 1→2 | planned | `tests/integration/imports/test_rollback.py::test_rollback_blocked_when_referenced_or_later_edited` |
| FG-QLN-04 | `display_code`, `display_sku`, `product_name` | snapshot columns | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_catalog_line_snapshot_immune_to_catalogue_change` |
| FG-QLN-05 | `dimensions`, `thickness` (free text) | `dimensions_text` + `length_mm`, `width_mm`, `thickness_mm` | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_dimensions_text_and_canonical_numbers` |
| FG-QLN-06 | `decor_no`, `decor_name`, `finish` | snapshot columns (decor text) | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_catalog_line_snapshot_immune_to_catalogue_change` |
| FG-QLN-07 | `unit_of_sale` | `unit_code` with integer-UOM quantity rule | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_integer_uom_rejects_fractions` |
| FG-QLN-08 | `default_price`, `quoted_price`, `override_reason` | `default_unit_price`, `unit_price`, `override_reason` + by/at; discounts | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_override_requires_permission_and_reason_for_sales` |
| FG-QLN-09 | `currency` | line currency with deferred FK `(quote_id, currency)` + anti-relabel CHECK | 1 | implemented | `tests/integration/sales/test_currency_change.py::test_db_rejects_currency_relabel` |
| FG-QLN-10 | `moq` | `product_moq` + `recommended_qty` + advisories | 1 | implemented | `tests/unit/commercial/test_engine.py::test_product_moq_distinct_from_recommendation` |
| FG-QLN-11 | `quantity`, `line_total` | `quantity` NUMERIC(18,6); `line_gross`, `line_discount`, `line_net` | 1 | planned | `tests/unit/commercial/test_engine.py::test_engine_properties` |
| FG-QLN-12 | `packaging_summary` | `packaging_snapshot` + derived summary | 1 | implemented | `tests/integration/sales/test_configurator.py::test_packaging_summary_from_canonical_fields` |
| FG-QLN-13 | `image_url`, `image_id` | `media_snapshot` referencing `file_object` ids | 1→2 | planned | `tests/integration/sales/test_quote_lines.py::test_media_snapshot_survives_media_soft_delete` |
| FG-QLN-14 | `description`, `notes` | `description`, customer-visible `remarks`, `internal_note` (redacted from documents) | 1 | planned | `tests/integration/documents/test_quote_pdf.py::test_internal_notes_and_costs_absent` |
| FG-QLN-15 | `created_at` | Clock timestamps | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_catalog_line_snapshot_immune_to_catalogue_change` |
| FG-QLN-16 | Lines are snapshots (later changes do not alter lines) | snapshots + `price_list_item_id` provenance; explicit refresh only | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_catalog_line_snapshot_immune_to_catalogue_change` |

### 3.12 `quote_revisions` (§4.12)

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-QRV-01 | `id`, `quote_id`, `version` | `sales_quote_revision` (`revision_no`, `kind` issued/review/checkpoint/legacy) | 1 | implemented | `tests/integration/sales/test_quote_status.py::test_issued_revision_immutable_by_trigger` |
| FG-QRV-02 | `status_from`, `status_to` | `sales_quote_status_history` (append-only) | 1 | implemented | `tests/integration/sales/test_quote_status.py::test_status_history_append_only` |
| FG-QRV-03 | `changes_summary` | compare output + history reason text | 2 | implemented | `tests/integration/sales/test_quote_revisions.py::test_compare_and_restore_keep_history` |
| FG-QRV-04 | `snapshot` (full quote + lines) | canonical content JSON + `content_hash`; legacy snapshots kept verbatim | 1→5 | planned | `tests/integration/migration/test_quotes.py::test_legacy_revisions_stored_verbatim` |
| FG-QRV-05 | `created_by(_name)`, `created_at` | actor + Clock | 1 | implemented | `tests/integration/sales/test_quote_status.py::test_issued_revision_immutable_by_trigger` |

### 3.13 `custom_products` (§4.13)

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-CP-01 | `id`, `custom_code` (CP-NNNN unique) | `sales_custom_product.custom_code` (allocator, never reused) | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_codes_unique_never_reused` |
| FG-CP-02 | `custom_type` (modified_catalog, fully_new, quote_only) | same enum | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |
| FG-CP-03 | `base_product_key` | `base_product_id` + `base_product_key` | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |
| FG-CP-04 | `customer_specific_flag` | same | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |
| FG-CP-05 | `is_promoted_to_master` | `promoted_product_id` + promotion record with lineage | 2 | implemented | `tests/integration/sales/test_custom_product_promotion.py::test_request_approve_execute_idempotent` |
| FG-CP-06 | `category` | category/subcategory FKs | 2 | planned | `tests/integration/catalogue/test_taxonomy.py::test_reassign_covers_custom_products` |
| FG-CP-07 | `customer_name`, `inquiry_reference` | `party_id` (+ `legacy_customer_name`), `inquiry_reference` | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |
| FG-CP-08 | `product_name` | `product_name` NOT NULL (used consistently by search, activity, duplicate) | 2 | implemented | `tests/integration/search/test_custom_product_name.py::test_global_search_finds_custom_product_name` |
| FG-CP-09 | `dimensions`, `thickness` | `dimensions_text` + canonical mm, `thickness_mm`, `thickness_text` | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |
| FG-CP-10 | `decor_no`, `decor_name`, `finish`, `shape` | same (decor text) | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |
| FG-CP-11 | `groove_count`, `bowl_count`, `handle_type` | same | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |
| FG-CP-12 | `packaging_notes` | `packaging_notes` + structured `packaging` | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |
| FG-CP-13 | `costing` | `sales_custom_product_costing` (protected, versioned, `pricing.cost.read`) | 2 | implemented | `tests/integration/security/test_costing_redaction.py::test_costing_absent_without_pricing_cost_read` |
| FG-CP-14 | `quoted_price` | `quoted_price` + `quoted_currency` | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |
| FG-CP-15 | `remarks` | same | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |
| FG-CP-16 | `status` (inquiry … dormant) | state machine with reasons and history | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_transition_table_and_reasons` |
| FG-CP-17 | `internal_notes` | collab note | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_internal_notes_on_custom_products` |
| FG-CP-18 | `created_by`, `created_at`, `updated_at` | actor stamps + Clock | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |

### 3.14 `grain_locked_decors` (§4.14)

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-GRN-01 | `decor` (unique) | `cutting_grain_lock.decor_key` (canonical decor; unique per company) | 2 | implemented | `tests/unit/cutting/test_packer_examples.py::test_lock_on_120_blocks_rotation_of_120_0` |
| FG-GRN-02 | `label` | same | 2 | implemented | `tests/integration/cutting/test_grain_settings.py::test_grain_lock_writes_require_manage_and_canonical_key` |
| FG-GRN-03 | `updated_by`, `updated_at` | actor stamps + audit | 2 | implemented | `tests/integration/cutting/test_grain_settings.py::test_grain_lock_writes_require_manage_and_canonical_key` |

### 3.15 `delivery_challans` and lines (§4.15)

| ID | Legacy fields | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-DC-01 | `id`, `challan_number` (DC-YYYY-NNNN unique) | `challans_challan.challan_number` (allocator, yearly) | 2 | implemented | `tests/integration/challans/test_challan_numbering.py::test_concurrent_dc_numbers_unique_yearly_reset` |
| FG-DC-02 | `challan_date` | local `date` | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_header_fields_round_trip` |
| FG-DC-03 | `challan_type`, `return_type` | enums + movement policy | 2 | implemented | `tests/unit/challans/test_movement_policy.py::test_policy_matrix_all_types_and_invalid_combinations` |
| FG-DC-04 | `source_location` (default "Crown / Lamikraft Office") | display text + `source_warehouse_id`; default from settings | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_header_fields_round_trip` |
| FG-DC-05 | `destination_type`, `destination_party` | same + `party_id`, `consignee_party_id`, `destination_warehouse_id`, `office_location_id` | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_all_types_return_types_destinations` |
| FG-DC-06 | `shipping_name` | same | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_header_fields_round_trip` |
| FG-DC-07 | `gstin` | same (format check only, never "verified") | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_gstin_format_checked_not_verified` |
| FG-DC-08 | `phone`, `email`, `address` | same | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_header_fields_round_trip` |
| FG-DC-09 | `reference_no` | same | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_header_fields_round_trip` |
| FG-DC-10 | `remarks` (printed) | same | 2 | implemented | `tests/integration/challans/test_challan_documents.py::test_pdf_unicode_pagination_terms_signatures_no_internal_notes` |
| FG-DC-11 | `internal_notes` | collab note (never printed) | 2 | planned | `tests/integration/collab/test_internal_notes.py::test_notes_never_printed` |
| FG-DC-12 | `status` | validated statuses; issued immutable except notes | 2 | implemented | `tests/unit/challans/test_status_machine.py::test_valid_and_invalid_transitions_table` |
| FG-DC-13 | `created_by(_name)`, `updated_by`, `created_at`, `updated_at` | actor stamps, Clock, `owner_user_id` | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_header_fields_round_trip` |
| FG-DCL-01 | Line `id`, `challan_id` | `challans_challan_line` (child via parent policy) | 2 | implemented | `tests/integration/challans/test_challan_permissions.py::test_scope_enforced_on_read_edit_issue_export_and_admin_only_draft_delete` |
| FG-DCL-02 | `line_type` (label only) | catalog/custom/manual with product/custom-product lookup | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_lines_with_product_lookup_and_uom_rules` |
| FG-DCL-03 | `item_code`, `item_name` | same | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_lines_with_product_lookup_and_uom_rules` |
| FG-DCL-04 | `hsn_code` | `hsn_sac` | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_lines_with_product_lookup_and_uom_rules` |
| FG-DCL-05 | `quantity` (float) | NUMERIC(18,6) > 0 with UOM integer rule | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_lines_with_product_lookup_and_uom_rules` |
| FG-DCL-06 | `unit` (default pcs) | `uom_code` (seeded legacy units) | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_lines_with_product_lookup_and_uom_rules` |
| FG-DCL-07 | `remarks`, `sort_order` | same | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_lines_with_product_lookup_and_uom_rules` |

### 3.16 Miscellaneous and relationships (§4.16, §4.17)

| ID | Legacy item | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| FG-SRH-01 | `search_history` (user_id, query, results_count, searched_at; last 10) | `search_recent` (last 10 per user, clear control) | 2 | planned | `tests/integration/search/test_recent_searches.py::test_last_ten_kept_per_user` |
| FG-MSC-01 | `revision_history` (cleared, never written) | not migrated; reported as skipped | 5 | planned | `tests/integration/migration/test_dry_run.py::test_skipped_collections_reported` |
| FG-MSC-02 | Legacy `products` collection (cleared only) | not migrated; reported as skipped | 5 | planned | `tests/integration/migration/test_dry_run.py::test_skipped_collections_reported` |
| FG-REL-01 | taxonomy 1–* products (by text) | FK category/subcategory, composite FK | 1 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_composite_fk_rejects_foreign_subcategory` |
| FG-REL-02 | product 1–* pricing, 1–1 packaging, 1–1 specs, 1–* media | FKs with RESTRICT; price items by list | 1→2 | implemented | `tests/integration/catalogue/test_product_detail.py::test_detail_returns_all_field_groups_with_section_guards` |
| FG-REL-03 | quote lines snapshot-reference products or custom products | snapshot + FK RESTRICT (blocks unsafe rollback) | 1→2 | planned | `tests/integration/imports/test_rollback.py::test_rollback_blocked_when_referenced_or_later_edited` |
| FG-REL-04 | challans have no FK to products or quotes | optional product/custom/SO links; document-only for legacy | 2→4 | implemented | `tests/integration/challans/test_challan_crud.py::test_lines_with_product_lookup_and_uom_rules`; SO links `tests/integration/challans/test_issue_return_cancel.py::test_issue_posts_exactly_one_movement` |

## 4. API capabilities (spec §7)

Legacy paths were under `/api`; new paths are under `/api/v1/<module>`. ★ = legacy accepted `?auth=`; every new
download is cookie-authenticated and ignores query tokens.

| ID | Legacy endpoint (access) | New endpoint | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| API-01 | `POST /auth/login` (public) | `POST /api/v1/identity/login` | 1 | implemented | `tests/integration/identity/test_login.py::test_successful_sign_in_sets_session_cookies` |
| API-02 | `GET /auth/me` | `GET /api/v1/identity/me` + `GET /api/v1/session/bootstrap` | 1 | planned | `tests/integration/ui/test_session_bootstrap.py::test_permissions_and_capabilities_match_server_rules` |
| API-03 | `POST /auth/change-password` | `POST /api/v1/identity/me/password` | 1 | implemented | `tests/integration/identity/test_profile.py::test_change_password_revokes_other_sessions` |
| API-04 | `GET/POST /users` (admin) | `GET /api/v1/identity/users`, `POST /api/v1/identity/invitations` | 2 | implemented | `tests/integration/identity/test_user_admin.py::test_list_create_update_users` |
| API-05 | `PUT/DELETE /users/{id}` (admin) | `PATCH /api/v1/identity/users/{id}`, `POST .../deactivate`, `.../reactivate` | 2 | implemented | `tests/integration/identity/test_deactivation.py::test_deactivation_keeps_attribution_and_revokes_sessions` |
| API-06 | `POST /users/{id}/reset-password` | `POST /api/v1/identity/users/{id}/password-reset` (link, never a password) | 2 | implemented | `tests/integration/identity/test_invitation_and_reset.py::test_admin_reset_never_returns_password` |
| API-07 | `GET /admin/permissions/defaults` | `GET /api/v1/identity/roles`, `GET /api/v1/identity/permissions` | 1→2 | implemented | `tests/integration/authz/test_role_simulator.py::test_effective_permissions_with_sources` |
| API-08 | `GET /admin/permissions/users` | `GET /api/v1/identity/users/{id}/permission-overrides` | 1 | implemented | `tests/integration/authz/test_overrides.py::test_grant_and_revoke_with_reason_and_epoch_bump` |
| API-09 | `PUT /admin/permissions/users/{id}` | `PUT/DELETE /api/v1/identity/users/{id}/permission-overrides/{key}` | 1 | implemented | `tests/integration/authz/test_overrides.py::test_grant_and_revoke_with_reason_and_epoch_bump` |
| API-10 | `GET /products` (search, filters, limit, skip) | `GET /api/v1/catalogue/products` (Page; filters before paging) | 1 | implemented | `tests/integration/catalogue/test_product_list.py::test_search_and_filters_apply_before_pagination` |
| API-11 | `GET /products/stats` | `GET /api/v1/catalogue/products/stats` | 2 | implemented | `tests/integration/catalogue/test_product_stats.py::test_stats_count_distinct_products` |
| API-12 | `GET /products/recent` | `GET /api/v1/catalogue/products/recent` | 2 | implemented | `tests/integration/catalogue/test_product_stats.py::test_recent_products_with_origin_and_actor` |
| API-13 | `GET /products/{key}` | `GET /api/v1/catalogue/products/{id}`; `GET /api/v1/catalogue/products/lookup?key=` | 1 | implemented | `tests/integration/catalogue/test_product_detail.py::test_lookup_by_key_with_special_characters` |
| API-14 | `POST /products` (admin) | `POST /api/v1/catalogue/products` | 2 | implemented | `tests/integration/catalogue/test_product_crud.py::test_create_with_all_sections` |
| API-15 | `PUT /products/{key}` (admin) | `PATCH /api/v1/catalogue/products/{id}` | 2 | implemented | `tests/integration/catalogue/test_product_crud.py::test_update_sections_with_version_conflict_409` |
| API-16 | `DELETE /products/{key}` (admin) | `POST /api/v1/catalogue/products/{id}/archive` / `restore` | 2 | implemented | `tests/integration/catalogue/test_product_crud.py::test_archive_restore_and_no_hard_delete_via_ui` |
| API-17 | `GET/POST /products/{key}/pricing` | `GET /api/v1/pricing/products/{id}/prices`; price-list item endpoints | 1→2 | implemented | `tests/integration/pricing/test_price_lists.py::test_item_create_and_supersede_with_history` |
| API-18 | `GET/PUT /products/{key}/packaging` | `PUT /api/v1/catalogue/products/{id}/packaging` (GET via detail) | 2 | implemented | `tests/integration/catalogue/test_product_crud.py::test_packaging_put_canonicalises_aliases` |
| API-19 | `GET/PUT /products/{key}/specifications` | `PUT /api/v1/catalogue/products/{id}/specification` | 2 | implemented | `tests/integration/catalogue/test_product_crud.py::test_specification_put_parses_dimensions` |
| API-20 | `GET /categories` | `GET /api/v1/catalogue/categories?include_inactive=` | 1→2 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_created_category_active_by_default` |
| API-21 | `GET /categories/hierarchy` | `GET /api/v1/catalogue/categories` (nested subcategories) | 2 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_hierarchy_respects_inactive_parent` |
| API-22 | `GET /categories/validate` | `GET /api/v1/catalogue/taxonomy/validation` | 2 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_validation_report` |
| API-23 | `GET /brands`, `/decors`, `/thicknesses` | `GET /api/v1/catalogue/products/facets?dims=brand,decor_no,thickness_mm` | 2 | planned | `tests/integration/catalogue/test_facets.py::test_facets_exclude_self_and_count_scoped_rows` |
| API-24 | `GET /search/recent` | `GET/POST/DELETE /api/v1/search/recent` | 2 | implemented | `tests/integration/search/test_global_search.py::test_last_ten_kept_per_user` |
| API-25 | `POST /products/{key}/files` (admin, multipart) | `POST /api/v1/catalogue/products/{id}/media` | 2 | implemented | `tests/integration/catalogue/test_media.py::test_upload_sniffs_dedupes_and_single_primary` |
| API-26 | `GET /products/{key}/files` | `GET /api/v1/catalogue/products/{id}/media` | 2 | implemented | `tests/integration/catalogue/test_media.py::test_list_grouped_by_type` |
| API-27 | `GET /files/{id}/download` ★ | `GET /api/v1/files/{id}/content[?variant=]` | 1→2 | implemented | `tests/integration/files/test_file_download_authz.py::test_download_requires_parent_read_and_headers` |
| API-28 | `DELETE /files/{id}` (admin) | `DELETE /api/v1/catalogue/media/{id}` (soft) | 2 | implemented | `tests/integration/catalogue/test_media.py::test_soft_delete_restore_and_primary_promotion` |
| API-29 | `GET/POST/PUT/DELETE /admin/categories[/{id}]` | `POST/PATCH /api/v1/catalogue/categories`, `/subcategories`, `/references`, `/delete`, `/reorder` | 2 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_rename_alias_and_delete_or_reassign` |
| API-30 | `POST /import/preview` | `POST /api/v1/imports/jobs` + `GET .../preview` | 2 | planned | `tests/integration/imports/test_preview.py::test_preview_lists_duplicates_with_row_numbers` |
| API-31 | `POST /import/{seven types}` | `PUT .../mapping`, `POST .../validate`, `POST .../commit` per job type | 2 | implemented | `tests/integration/imports/test_imports_http.py::test_workbench_flow_over_http` |
| API-32 | `POST /import/validate` | `POST /api/v1/imports/jobs/{id}/validate` + `GET /api/v1/catalogue/taxonomy/validation` | 2 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_validation_report` |
| API-33 | `DELETE /import/clear-sample-data` | `GET .../demo-reset/preview` + `POST /api/v1/system/demo-reset` (is_demo only) | 2 | implemented | ; vitest `features/imports/imports.test.tsx` |
| API-34 | `POST /configurator/resolve` | `POST /api/v1/sales/quotes/configurator/resolve` | 1→2 | implemented | `tests/integration/sales/test_configurator.py::test_filters_narrow_options_page_and_exact_match` |
| API-35 | `GET/PUT /quote-settings` (admin) | `GET/PUT /api/v1/sales/quote-settings` + `GET/PATCH /api/v1/numbering/sequences` | 1→2 | implemented | `tests/integration/sales/test_quote_settings.py::test_defaults_and_numbering_settings_validated` |
| API-36 | `POST /quotes` | `POST /api/v1/sales/quotes` | 1 | implemented | `tests/integration/sales/test_quote_header.py::test_header_fields_round_trip_with_party_snapshot` |
| API-37 | `GET /quotes` (status, search, scope, limit, skip) | `GET /api/v1/sales/quotes` | 1 | implemented | `tests/integration/sales/test_quote_list.py::test_filters_scope_and_paging_totals` |
| API-38 | `GET /quotes/export-csv` ★ (any token) | `GET /api/v1/sales/quotes/export.csv` (`sales.quote.export`, scoped) | 2 | implemented | `tests/integration/sales/test_quote_csv.py::test_line_counts_names_totals_and_escaping` |
| API-39 | `GET /quotes/{id}` (quote + lines + revisions) | `GET /api/v1/sales/quotes/{id}` (+ `capabilities`, `allowed_transitions`) | 1 | implemented | `tests/integration/sales/test_quote_idor.py::test_quote_idor_matrix` |
| API-40 | `PUT /quotes/{id}` | `PATCH /api/v1/sales/quotes/{id}` (`expected_version`) | 1 | implemented | `tests/integration/sales/test_quote_header.py::test_optimistic_version_409` |
| API-41 | `DELETE /quotes/{id}` (admin, draft) | `DELETE /api/v1/sales/quotes/{id}` (soft) | 1 | implemented | `tests/integration/sales/test_quote_delete.py::test_delete_requires_permission_and_draft_never_issued` |
| API-42 | `POST/PUT/DELETE /quotes/{id}/lines[/{line_id}]` (no ownership on edit/delete) | `POST/PATCH/DELETE /api/v1/sales/quotes/{id}/lines[/{line_id}]`, `.../lines/reorder` | 1 | implemented | `tests/integration/sales/test_quote_idor.py::test_quote_idor_matrix` |
| API-43 | `POST /quotes/{id}/revise` | transition `revise` | 2 | implemented | `tests/integration/sales/test_quote_revisions.py::test_revise_creates_working_copy` |
| API-44 | `PUT /quotes/{id}/status` (any status, rejects cancelled/archived) | `POST /api/v1/sales/quotes/{id}/transitions` | 1→2 | implemented | `tests/integration/sales/test_quote_status.py::test_cancelled_and_archived_transitions` |
| API-45 | `POST /quotes/{id}/duplicate` | `POST /api/v1/sales/quotes/{id}/duplicate` | 2 | implemented | `tests/integration/sales/test_quote_duplicate.py::test_duplicate_real_totals_reference_cleared_owner_policy` |
| API-46 | `GET /quotes/{id}/export-pdf` ★ | `GET /api/v1/sales/quotes/{id}/pdf` | 1 | implemented | `tests/integration/documents/test_quote_pdf.py::test_layout_unicode_pagination_and_totals` |
| API-47 | `POST/GET /custom-products` | `POST/GET /api/v1/sales/custom-products` | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_list_search_filter_paging` |
| API-48 | `GET /custom-products/export` ★ | `GET /api/v1/sales/custom-products/export.csv` | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_csv_export_escaped_and_costing_guarded` |
| API-49 | `GET/PUT/DELETE /custom-products/{id}` | `GET/PATCH /api/v1/sales/custom-products/{id}`, `POST .../archive`, `.../transitions` | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |
| API-50 | `POST /custom-products/{id}/duplicate` (any login) | `POST /api/v1/sales/custom-products/{id}/duplicate` (scoped) | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_duplicate_new_code_and_product_name_copy` |
| API-51 | `POST /sheet-optimizer/calculate` (any login) | `POST /api/v1/cutting/calculate` (stateless, `cutting.calculation.run`) + plan `.../calculate` | 2 | implemented | `tests/integration/cutting/test_calculate_endpoint.py::test_stateless_calculate_parity` |
| API-52 | `GET /sheet-optimizer/products?search=` | `GET /api/v1/cutting/products?search=` | 2 | implemented | `tests/integration/cutting/test_calculate_endpoint.py::test_product_autocomplete_fills_decor_thickness_dimensions` |
| API-53 | `GET /sheet-optimizer/grain-settings` | `GET /api/v1/cutting/grain-locks` | 2 | implemented | `tests/integration/cutting/test_grain_settings.py::test_grain_lock_writes_require_manage_and_canonical_key` |
| API-54 | `PUT /sheet-optimizer/grain-settings` (bulk replace) | `PUT /api/v1/cutting/grain-locks` | 2 | implemented | `tests/integration/cutting/test_grain_settings.py::test_bulk_replace_and_add_remove` |
| API-55 | `POST /sheet-optimizer/grain-settings/add` | `POST /api/v1/cutting/grain-locks` | 2 | implemented | `tests/integration/cutting/test_grain_settings.py::test_bulk_replace_and_add_remove` |
| API-56 | `DELETE /sheet-optimizer/grain-settings/{decor}` | `DELETE /api/v1/cutting/grain-locks/{decor_key}` | 2 | implemented | `tests/integration/cutting/test_grain_settings.py::test_bulk_replace_and_add_remove` |
| API-57 | `POST/GET /challans` (any login) | `POST/GET /api/v1/challans/challans` | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_list_filters_before_paging` |
| API-58 | `GET /challans/summary` | `GET /api/v1/challans/challans/summary` | 2 | implemented | `tests/integration/challans/test_challan_summary.py::test_summary_counts_scoped` |
| API-59 | `GET /challans/export-csv` ★ | `GET /api/v1/challans/challans/export.csv` | 2 | implemented | `tests/integration/challans/test_challan_documents.py::test_csv_escaped_and_scoped` |
| API-60 | `GET/PUT /challans/{id}` | `GET/PATCH /api/v1/challans/challans/{id}` + `POST .../issue|close|cancel` | 2 | implemented | `tests/integration/challans/test_challan_status.py::test_transitions_validated_and_issued_immutable` |
| API-61 | `DELETE /challans/{id}` (admin, draft) | `DELETE /api/v1/challans/challans/{id}` (soft) | 2 | implemented | `tests/integration/challans/test_challan_permissions.py::test_admin_only_draft_delete_number_not_reused` |
| API-62 | `POST /challans/{id}/lines` | `POST /api/v1/challans/challans/{id}/lines` | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_lines_with_product_lookup_and_uom_rules` |
| API-63 | `PUT/DELETE /challans/{id}/lines/{line_id}` | `PATCH/DELETE .../lines/{line_id}` (`expected_version`) | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_line_edit_version_conflict_and_validation` |
| API-64 | `GET /challans/{id}/export-pdf` ★ | `GET /api/v1/challans/challans/{id}/document.pdf` | 2 | implemented | `tests/integration/challans/test_challan_documents.py::test_pdf_unicode_pagination_terms_signatures_no_internal_notes` |
| API-65 | `POST /challans/{id}/duplicate` | `POST /api/v1/challans/challans/{id}/duplicate` | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_duplicate_with_lines_new_number` |
| API-66 | `GET /global-search?q=` (any login) | `GET /api/v1/search?q=&types=&per_group=` | 2 | implemented | `tests/integration/search/test_global_search.py::test_grouped_scoped_results_with_deep_links` |
| API-67 | `GET /data-completeness` | `GET /api/v1/catalogue/completeness` | 2 | planned | `tests/integration/catalogue/test_completeness.py::test_metrics_count_distinct_products_real_fields` |
| API-68 | `GET /activity/recent` (any login) | `GET /api/v1/collab/activity` (parent-filtered, keyset) | 2 | implemented | `tests/integration/collab/test_activity.py::test_feed_filtered_by_parent_visibility` |
| API-69 | `PUT /internal-notes/{entity_type}/{id}` (any login, any record) | `GET/PUT /api/v1/collab/notes/{resource_type}/{resource_id}` | 2 | implemented | `tests/integration/collab/test_internal_notes.py::test_autosave_conflict_409_and_parent_update_required` |
| API-70 | `GET /` (version "2.0.0") | OpenAPI info version + `GET /api/v1/system/status` (admin) | 1 | planned | `tests/integration/system/test_health_readiness.py::test_status_admin_only_without_secrets` |
| API-71 | `GET /health` | `GET /api/v1/health/live`, `/ready` | 0 | planned | `tests/integration/system/test_health_readiness.py::test_live_and_ready` |
| API-72 | Static logo at `/static` | company branding logo as `file_object` (purpose company_logo) from settings | 2 | planned | `tests/integration/org/test_company_identity.py::test_logo_and_identity_from_settings` |

## 5. UI pages and behaviour (spec §8)

### 5.1 Shell, routing and client auth (§8.1)

| ID | Legacy behaviour | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| UI-01 | `ProtectedRoute` checks only "logged in"; no route gating | route manifest with required permission; server bootstrap renders only authorised, implemented areas; PermissionDenied view | 1 | planned | `e2e/scenarios/a-today-scope.spec.ts::restricted_user_navigation_and_direct_urls` |
| UI-02 | Sidebar filtered by role (cosmetic) | sidebar Today, Inbox, Sales, Products, Operations, Finance, Settings from effective permissions | 1 | planned | `src/lib/nav.test.ts::nav_filters_by_permission_and_slice` |
| UI-03 | Token in `localStorage`, axios Bearer | HttpOnly session cookie; no token in JS | 1 | implemented | `tests/integration/identity/test_login.py::test_successful_sign_in_sets_session_cookies`, `tests/integration/identity/test_sessions.py::test_sign_in_rotates_the_browser_session` |
| UI-04 | Any 401 hard-redirects to `/login` | `session_expired` → `/login?next=` (relative paths only) | 1 | planned | `e2e/auth/auth-flows.spec.ts::expired_session_redirects_with_safe_next` |
| UI-05 | Session restore via `/auth/me` | `GET /api/v1/session/bootstrap` in the `(app)` layout | 1 | implemented | `tests/integration/ui/test_bootstrap.py::test_sales_persona_bootstrap` |
| UI-06 | Logout client-only | server logout revokes the session | 1 | implemented | `tests/integration/identity/test_sessions.py::test_logout_revokes_and_clears_cookies` |
| UI-07 | Fixed sidebar, collapsible, not persisted | 208 px sidebar, 64 px icon rail, state persisted in preferences; phone bottom nav Today/Inbox/Work/More | 1 | planned | `e2e/responsive/n-shell.spec.ts::shell_at_three_viewports` |
| UI-08 | Header global search (`/`, 300 ms debounce, grouped, Enter → product search) | search dialog (`/`, Ctrl/Cmd+K, 250 ms, grouped, recent, Enter → canonical URL, "See all") | 2 | in progress | ; vitest `features/search/search-page.test.tsx`, `features/search/search-page.test.tsx`, `features/search/search.test.ts` |
| UI-09 | Dark-mode toggle persisted | light/dark/system theme via preferences + `lk_ui` cookie (no flash) | 1 | planned | `src/lib/ui-preferences.test.ts` |
| UI-10 | User menu (Settings, Sign out) | user menu (Profile, Preferences, Sign out) | 1 | planned | `e2e/auth/auth-flows.spec.ts::user_menu_profile_and_sign_out` |
| UI-11 | `can`, `isAdmin`, `canViewAllQuotes`, `canEditQuote`, `canViewSection` helpers | server `capabilities` + `allowed_transitions`; nav-only permission keys | 1 | planned | `tests/integration/sales/test_quote_capabilities.py::test_capabilities_reflect_scope_and_state` |

### 5.2 Routes (§8.2)

| ID | Legacy route | New route | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| UI-12 | `/login` | `/login` (+ `/forgot-password`, `/reset-password#t=`, `/invite#t=` from S2) | 1 | in progress | ; vitest `app/(auth)/auth-links.test.tsx`, `app/(auth)/auth-links.test.tsx` |
| UI-13 | `/` Dashboard | `/today` (briefing) + `/products` home (stats, recent, completeness link, categories) + challan summary + `/activity` | 1→2 | implemented | `e2e/challans.spec.ts::dashboard_capabilities_relocated` |
| UI-14 | `/products`, `/products/:key` | `/products`, `/products/[productId]/{overview,specifications,packaging,pricing,media,history}`, `/go/product/[key]` | 1→2 | implemented | `e2e/catalogue/product-list.spec.ts::filters_paging_and_deep_links_survive_reload` |
| UI-15 | `/products/new`, `/products/:key/edit` | `/products/new`, inline section edits on detail tabs | 2 | planned | `e2e/catalogue/product-form.spec.ts::create_with_all_sections_and_server_errors` |
| UI-16 | `/quotes`, `/quotes/new`, `/quotes/:id`, `/quotes/:id/preview` | `/sales/quotes`, `/sales/quotes/new`, `/sales/quotes/[quoteId]`, `.../review`, `.../revisions`, `/print/quotes/[id]` | 1→2 | planned | `e2e/scenarios/c-nordhaus-quote.spec.ts::prepare_review_and_preview` |
| UI-17 | `/custom-products`, `/new`, `/:id/edit` | `/sales/custom-products`, `/new`, `/[id]` (+ costing tab when permitted) | 2 | planned | `e2e/sales/custom-products.spec.ts::create_edit_duplicate_export` |
| UI-18 | `/sheet-optimizer` | `/operations/cutting`, `/operations/cutting/[planId]`, `/operations/cutting/grain-locks` | 2 | implemented | `e2e/scenarios/h-cutting-canvas.spec.ts::plan_calculate_save_reopen_svg` |
| UI-19 | `/challans`, `/new`, `/:id`, `/:id/preview` | `/operations/challans`, `/new`, `/[challanId]`, `/print/challans/[id]` | 2 | implemented | `e2e/challans.spec.ts::challan_create_duplicate_print_csv` |
| UI-20 | `/admin/categories` | `/products/taxonomy` | 2 | planned | `e2e/catalogue/taxonomy.spec.ts::crud_rename_reassign_delete` |
| UI-21 | `/admin/roles` (static matrix) | `/settings/roles`, `/settings/roles/simulate` | 2 | in progress | ; vitest `app/(app)/settings/_lib/settings.test.tsx`, `app/(app)/settings/_lib/settings.test.tsx` |
| UI-22 | `/admin/permissions` | `/settings/users/[userId]` overrides panel | 2 | in progress | ; vitest `settings.test.tsx` |
| UI-23 | `/users` | `/settings/users`, `/settings/users/invite` | 2 | in progress | ; vitest `settings.test.tsx` |
| UI-24 | `/import` | `/settings/imports`, `/settings/imports/new`, `/settings/imports/[jobId]` | 2 | implemented | `e2e/imports/workbench.spec.ts::taxonomy_products_packaging_conflict_commit_reimport_rollback` |
| UI-25 | `/settings` (profile + password) | `/settings/profile` (password, sessions, MFA, preferences, shortcuts) | 1→2 | in progress | ; vitest `settings.test.tsx` |

### 5.3 Page-by-page behaviour (§8.3)

| ID | Legacy behaviour | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| UI-26 | Login: email + password (show/hide), error, "Internal use only", no forgot password | login with show/hide, generic error, rate-limit state; forgot-password from S2 | 1→2 | in progress | ; vitest `app/(auth)/auth-links.test.tsx`, `app/(auth)/auth-links.test.tsx` |
| UI-27 | Dashboard stat cards (Total SKUs, Active, Missing Pricing, Updated 7d) | `/products` home stats as a compact summary (no KPI-card wall) | 2 | in progress | `tests/integration/catalogue/test_product_stats.py::test_stats_count_distinct_products` |
| UI-28 | Dashboard challan strip (Total, Week, Month, Pending Returns, Issued) | `/operations/challans` summary | 2 | implemented | `tests/integration/challans/test_challan_summary.py::test_summary_counts_scoped` |
| UI-29 | Recent activity feed | `/activity` + record activity tabs | 2 | implemented | `tests/integration/collab/test_activity.py::test_feed_filtered_by_parent_visibility` |
| UI-30 | 6 recently updated products | `/products` home recent list | 2 | implemented | `tests/integration/catalogue/test_product_stats.py::test_recent_products_with_origin_and_actor` |
| UI-31 | Data completeness card | `/products/completeness` with links to `issue=` filters | 2 | planned | `tests/integration/catalogue/test_completeness.py::test_metrics_count_distinct_products_real_fields` |
| UI-32 | First 8 categories as quick filters | category chips on `/products` home | 2 | implemented | `e2e/catalogue/product-list.spec.ts::category_chips_filter` |
| UI-33 | No charts; no pipeline KPIs | no chart library; no fabricated metrics | 1 | planned | `e2e/responsive/n-no-fabricated-metrics.spec.ts::empty_tenant_shows_no_figures` |
| UI-34 | Product list filters URL-synced (search debounce, category, thickness, status) | URL-synced filters incl. size, finish, decor, has_image, has_price | 1→2 | implemented | `e2e/catalogue/product-list.spec.ts::filters_paging_and_deep_links_survive_reload` |
| UI-35 | Product list columns (thumbnail, SKU, name, category, decor, dims, thickness, EUR price, MOQ, status) | same columns; price and recommendation only with `pricing.price.read` | 1 | implemented | `tests/integration/catalogue/test_product_list.py::test_price_columns_require_pricing_price_read`, `tests/integration/catalogue/test_product_list.py::test_rows_enriched_without_n_plus_one` |
| UI-36 | No pagination (limit 100) | server pagination 25/50/100 with real totals; mobile card view | 1 | planned | `tests/integration/catalogue/test_product_list.py::test_thickness_filter_paginates_before_limit` |
| UI-37 | "Add Product" for admins | shown only with `catalogue.product.create` | 2 | planned | `e2e/catalogue/product-form.spec.ts::create_button_requires_capability` |
| UI-38 | Detail header with admin Edit/Delete (confirm) | `RecordHeader` with capability-driven actions; archive with confirm dialog | 2 | planned | `e2e/catalogue/product-form.spec.ts::archive_restore_with_confirm` |
| UI-39 | Overview tab (EUR price, MOQ, dims, thickness, info, key specs, primary image, EUR/USD export price summary, classification) | overview tab with resolved prices per currency list (no relabelled conversions) | 1 | implemented | `tests/integration/catalogue/test_product_detail.py::test_overview_prices_only_from_real_lists` |
| UI-40 | Pricing tab (needs `view_costing`) | pricing tab needs `pricing.price_list.read` | 1→2 | implemented | `tests/integration/catalogue/test_product_detail.py::test_detail_returns_all_field_groups_with_section_guards` |
| UI-41 | Packaging tab (hidden from sales) | packaging tab with `catalogue.product.read` (deliberate change: sales see packaging) | 1 | implemented | `tests/integration/catalogue/test_product_detail.py::test_detail_returns_all_field_groups_with_section_guards` |
| UI-42 | Specifications tab (hidden from sales) | specifications tab with `catalogue.product.read` | 1 | implemented | `tests/integration/catalogue/test_product_detail.py::test_detail_returns_all_field_groups_with_section_guards` |
| UI-43 | Documents tab (grouped; admin upload/delete; preview; download) | media tab (drop zone + button, primary toggle, preview, download, delete with reason, restore) | 2 | planned | `e2e/catalogue/media.spec.ts::upload_preview_download_delete_restore` |
| UI-44 | Costing, Operations, History tabs (design brief, not built) | History tab (S2), Material 3D view (S2), costing via `pricing.cost.read` (S2), Operations tab (S4) | 2→4 | planned | `e2e/catalogue/product-form.spec.ts::history_tab_shows_versions` |
| UI-45 | Product form: all master/spec/packaging fields | full form with sections Master, Taxonomy, Decor, Specifications, Packaging | 2 | in progress | `tests/integration/catalogue/test_product_crud.py::test_create_with_all_sections`; vitest `features/catalogue/catalogue.test.tsx` |
| UI-46 | Only `product_key` validated; immutable on edit | server validation for all fields (422 mapped to fields); key immutable | 2 | implemented | `tests/integration/catalogue/test_product_crud.py::test_product_key_immutable_api_and_db_trigger` |
| UI-47 | Pricing not editable in UI | price-list editor (`/products/price-lists/[id]`) with supersede and history | 2 | planned | `e2e/pricing/price-lists.spec.ts::create_activate_supersede_retire` |
| UI-48 | Category, subcategory, brand free text | taxonomy pickers (active only); brand text | 2 | planned | `e2e/catalogue/product-form.spec.ts::taxonomy_pickers_only_active` |
| UI-49 | Fields without inputs (decor_primary, decor_options, source_sheet, stand/board/working sizes, plate sizes, carton dims) | every field has an input; provenance disclosure | 2 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_every_field_writable_through_api` |
| UI-50 | Quote list tabs All, Draft, Review, Sent, Won, Lost | tabs incl. Revised, Cancelled, Archived with server counts | 1→2 | implemented | `tests/integration/sales/test_quote_list.py::test_status_tabs_include_revised_cancelled_archived` |
| UI-51 | Quote search (not debounced) | debounced search; LIKE/regex metacharacters literal | 1 | implemented | `tests/integration/sales/test_quote_list.py::test_search_metacharacters_literal` |
| UI-52 | My / All toggle with `view_all_quotes` | Mine/All shown only when scope is wider than own | 1 | implemented | `e2e/sales/quotes.spec.ts::mine_all_toggle_by_scope` |
| UI-53 | Columns (number + version, customer + country, status, lines, total + currency, creator, date) | same columns from persisted totals | 1 | implemented | `tests/integration/sales/test_quote_list.py::test_filters_scope_and_paging_totals` |
| UI-54 | Open; delete (draft + permission, confirm) | open; delete via capability with confirm dialog | 1 | implemented | `e2e/sales/quotes.spec.ts::delete_draft_with_confirm` |
| UI-55 | New Quote; Export CSV shown to everyone | New Quote with `sales.quote.create`; Export with `sales.quote.export` | 1→2 | implemented | `e2e/sales/quotes.spec.ts::export_requires_capability` |
| UI-56 | Limit 100, no paging | server paging | 1 | implemented | `tests/integration/sales/test_quote_list.py::test_filters_scope_and_paging_totals` |
| UI-57 | Builder header: customer name/country/reference, type (standard, dealer, distributor), currency (EUR, USD, GBP, INR), incoterm (FOB, CIF, CFR, EXW, DDP, DAP, FCA), validity (30), payment terms, brand (LK), min-invoice note, remarks | quote header form with party picker (inline prospect), same option sets | 1 | implemented | `e2e/sales/quotes.spec.ts::header_fields_and_options` |
| UI-58 | Top bar: Preview, Export PDF, status select, Revise, Duplicate, Delete | action bar from `allowed_transitions` and capabilities | 1→2 | implemented | `e2e/sales/quotes.spec.ts::action_bar_matches_allowed_transitions` |
| UI-59 | Lines addable only after the quote is created | header first, then lines (draft created on first save) | 1 | implemented | `e2e/sales/quotes.spec.ts::create_header_then_lines` |
| UI-60 | Catalog configurator dialog (type-ahead, 6 cascading filters, results with image/SKU/name/dims/thickness/decor/finish/EUR price/recommended MOQ, packaging summary, price default, qty, override reason, amber warnings, only page 0) | configurator drawer with paging and narrowed facets; advisories from the engine | 1→2 | implemented | `e2e/sales/quotes.spec.ts::configurator_keyboard_filters_paging_and_advisories` |
| UI-61 | Custom product dialog (qty starts 0) | custom line dialog with quantity validation | 2 | implemented | `e2e/sales/quotes.spec.ts::add_custom_line` |
| UI-62 | Manual line dialog with preset chips (Development, Tooling, Special Packaging, Freight, Sample, Miscellaneous) | manual line dialog with the same presets | 1 | implemented | `e2e/sales/quotes.spec.ts::manual_line_presets` |
| UI-63 | Line table (image, details + override reason, rec MOQ, click-to-edit price with `override_price`, struck default, optimistic qty, total, delete without confirm) | line grid with inline edits (versioned), capability-gated price edit, confirm or undo for delete | 1 | implemented | `e2e/sales/quotes.spec.ts::line_grid_inline_edit_and_delete_confirm` |
| UI-64 | Whole quote re-fetched after each change so the server owns `line_total` | server returns the recalculated document; "Recalculating…" until then; no client totals | 1 | planned | `src/lib/money.test.ts::no_client_arithmetic` |
| UI-65 | Commercial summary (subtotal, below-MOQ banner, meets/below EUR 5,000 panel, surcharge toggle saved immediately, non-EUR text "EUR 5,000 equivalent") | summary panel from engine explanations; toggle disabled outside EUR with reason; no fabricated equivalents | 1 | planned | `e2e/scenarios/d-commercial-rules.spec.ts::surcharge_toggle_and_non_eur_explanation` |
| UI-66 | Internal notes textarea autosaves after 1 s | autosaved collab note with status line, conflict panel, local mirror | 2 | implemented | `e2e/challans.spec.ts::note_conflict_across_two_contexts` |
| UI-67 | Catalogue prices always EUR even when currency is USD/GBP/INR | currency change dialog: reprice from list or convert at approved rate; no relabel | 2 | planned | `e2e/scenarios/e-currency-costing.spec.ts::currency_dialog_reprice_or_convert_only` |
| UI-68 | Quote preview (Back, Edit, Export PDF, Print; seller "Lamikraft" only; no address/tax/bank/terms; revision history on screen) | `/print/quotes/[id]` from the document view model with configured company identity | 1 | implemented | `e2e/challans.spec.ts::quote_print_preview_repeated_headers` |
| UI-69 | Custom product list (columns, search, status filter, CSV, `window.confirm` delete, no detail page) | list + detail page; RAC dialogs | 2 | planned | `e2e/sales/custom-products.spec.ts::create_edit_duplicate_export` |
| UI-70 | Custom product form (all fields; costing visible to anyone) | form with all fields; costing tab only with `pricing.cost.read` | 2 | planned | `e2e/scenarios/e-currency-costing.spec.ts::sales_user_sees_no_costing_tab_or_sentinel` |
| UI-71 | Duplicate API without a button | Duplicate action | 2 | planned | `e2e/sales/custom-products.spec.ts::create_edit_duplicate_export` |
| UI-72 | Optimiser cut-list table (3 blank rows, autocomplete fills dimensions) | cut-list editor with catalogue autocomplete | 2 | implemented | `e2e/scenarios/h-cutting-canvas.spec.ts::plan_calculate_save_reopen_svg` |
| UI-73 | Switches "+10 mm oversize" and "allow overproduction" (ignored) | oversize switch with "verify before release"; bounded overproduction controls | 2 | implemented | `e2e/scenarios/h-cutting-canvas.spec.ts::oversize_and_overproduction_have_effects` |
| UI-74 | Admin Grain Settings dialog | `/operations/cutting/grain-locks` with `cutting.grain_lock.manage` | 2 | implemented | `tests/integration/cutting/test_grain_settings.py::test_grain_lock_writes_require_manage_and_canonical_key` |
| UI-75 | Results per group: SVG diagram, placement table, leftover areas | true-scale canvas (zoom/pan/keyboard), placement table, unfit list, predicted offcuts, optional nesting playback | 2 | implemented | `e2e/scenarios/h-cutting-canvas.spec.ts::svg_no_overlap_inside_boundary_counts_match` |
| UI-76 | No save, export, print or link | save, reopen, duplicate, CSV/PDF/SVG export, print | 2 | implemented | `tests/integration/cutting/test_plan_persistence.py::test_duplicate_copies_inputs_and_exports_escape_formulas` |
| UI-77 | Challan list with summary cards and filters + CSV | `/operations/challans` list + summary + CSV | 2 | implemented | `e2e/challans.spec.ts::challan_create_duplicate_print_csv` |
| UI-78 | Builder header fields (source default "Crown / Lamikraft Office"; only destination party required) | builder with validated fields; default source from settings | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_header_fields_round_trip` |
| UI-79 | Status select any → any | action bar from allowed transitions | 2 | implemented | `tests/unit/challans/test_status_machine.py::test_valid_and_invalid_transitions_table` |
| UI-80 | Duplicate, PDF, preview, internal notes autosave | same, capability-gated | 2 | implemented | `e2e/challans.spec.ts::challan_create_duplicate_print_csv` |
| UI-81 | Line dialog type toggle changes only a label (no product lookup) | catalog/custom lookup fills code, name, HSN/SAC, unit | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_lines_with_product_lookup_and_uom_rules` |
| UI-82 | Units pcs, nos, sheets, kg, m, sqm, sqft, box, set, roll, bundle | UOM master incl. these codes | 1→2 | planned | `tests/integration/org/test_uom.py::test_seeded_legacy_units_and_integer_rules` |
| UI-83 | Quantity saves on every keystroke, errors swallowed | 600 ms debounced versioned PATCH; failures inline with retry | 2 | implemented | `e2e/challans.spec.ts::challan_failed_save_shows_inline_retry` |
| UI-84 | No delete-challan button | draft delete for admin with confirm | 2 | implemented | `e2e/challans.spec.ts::challan_admin_draft_delete` |
| UI-85 | Preview/PDF hard-coded identity, 3–4 fixed terms, signature blocks (Delivered By, Received By, Authorised Signatory) | configurable identity and terms; same three signature blocks | 2 | implemented | `tests/integration/challans/test_challan_documents.py::test_pdf_unicode_pagination_terms_signatures_no_internal_notes` |
| UI-86 | Import flow: type → upload (click only) → preview → import → counts, first 20 errors, orphans, unescaped error CSV | stepper: type → upload (button and drag-and-drop) → preview → mapping → validate → review → commit → result; escaped full report | 2 | implemented | `e2e/imports/workbench.spec.ts::taxonomy_products_packaging_conflict_commit_reimport_rollback` |
| UI-87 | Session-only import history | durable history with filters | 2 | planned | `tests/integration/imports/test_history.py::test_jobs_mappings_hashes_durable` |
| UI-88 | Validate Data and Clear All Data (confirm) | validation report; demo-only reset panel | 2 | implemented | ; vitest `features/imports/imports.test.tsx` |
| UI-89 | Recommended order shown (taxonomy → products → pricing/packaging/specs/media → lookup) | type picker shows dependency status | 2 | implemented | `e2e/imports/workbench.spec.ts::dependency_status_shown` |
| UI-90 | User management (table; create with password ≥ 8; edit name + role; no deactivate UI; reset shows temp password; delete) | users table; invite; edit roles/branches/teams; deactivate/reactivate; reset link | 2 | in progress | ; vitest `settings.test.tsx` |
| UI-91 | Settings: read-only profile; change password | profile, password, sessions, MFA, preferences | 1→2 | in progress | ; vitest `settings.test.tsx` |
| UI-92 | Quote-settings API has no UI | `/settings/sequences` and quote defaults in `/settings` | 2 | planned | `e2e/settings/sequences.spec.ts::preview_next_number_without_allocation` |
| UI-93 | Category management (flat list, display order, `window.confirm`) | taxonomy screen with reorder, activation, rename, delete-or-reassign dialog | 2 | planned | `e2e/catalogue/taxonomy.spec.ts::crud_rename_reassign_delete` |
| UI-94 | Role permissions static matrix | role simulator (effective permissions with sources) | 2 | in progress | ; vitest `app/(app)/settings/_lib/settings.test.tsx`, `app/(app)/settings/_lib/settings.test.tsx` |
| UI-95 | Access control (role defaults, override editor, effective preview; 14 permissions only) | overrides over the full catalogue with scope, reason and expiry | 2 | in progress | ; vitest `settings.test.tsx` |

### 5.4 Styling and conventions (§8.4)

| ID | Legacy item | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| UI-96 | Brand #C8A064 primary, #8BC34A leaf green, #333; Chivo/IBM Plex fonts | tokens: canvas #F6F5F0, ink #202723, forest #214C3C, sand #C8A064 (accent only), border #E0E4DC; Manrope Variable; tabular numerals | 1 | planned | `src/styles/tokens.contrast.test.ts::text_and_ui_contrast_thresholds` |
| UI-97 | Light default + dark mode; desktop-first | light and dark themes; responsive desktop/tablet/phone | 1 | planned | `e2e/a11y/n-axe-sweep.spec.ts::every_manifest_route_three_viewports_both_themes` |
| UI-98 | `data-testid` on every interactive element | accessible names everywhere; test ids where a name is not unique | 1 | planned | `e2e/responsive/n-no-dead-controls.spec.ts::every_control_named_and_effective` |
| UI-99 | Emergent title, `emergent-main.js`, PostHog snippet | none; nonce CSP; no third-party scripts | 1 | planned | `e2e/security/no-third-party-scripts.spec.ts::no_external_scripts_and_csp_present` |
| UI-100 | Unused libraries, no TypeScript, no frontend tests, no i18n, no pagination, `window.confirm` | TypeScript, vitest + Playwright, copy in `messages/en.ts`, pagination, RAC dialogs | 1 | planned | `src/lib/design-lint.test.ts::banned_patterns_absent` |
| UI-101 | Many API client functions unused | generated `openapi-fetch` client; `api:check` drift gate | 0→1 | planned | `npm run api:check` (scripts/dev.mjs api-check) |

## 6. Business rules and constants (spec §6)

| ID | Legacy rule | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| BR-01 | Minimum order value EUR 5,000 at quote level | rule set `quote_commercial` v1 threshold (EUR only) | 1 | implemented | `tests/unit/commercial/test_engine.py::test_minimum_order_meets_below_not_evaluated` |
| BR-02 | Surcharge EUR 400 when EUR, 0 < subtotal < 5,000 and toggled; render-time, not persisted | engine surcharge persisted with reason codes | 1 | implemented | `tests/unit/commercial/test_engine.py::test_surcharge_table` |
| BR-03 | Dynamic MOQ `ceil(5000 / EUR price)` rounded up to `carton_qty`; advisory | order-value recommendation (216 at EUR 24, carton 24), advisory only | 1 | implemented | `tests/unit/commercial/test_engine.py::test_recommended_quantity` |
| BR-04 | Price = first/last EUR row (price_type ignored) | deterministic tier/currency/unit/date resolution | 1 | implemented | `tests/integration/pricing/test_price_resolution.py::test_legacy_multi_eur_rows_resolved_by_price_type` |
| BR-05 | Override: admin/management free, sales must note, operations none | `sales.quote_price.override` + reason waiver via `sales.quote_price.approve`; operations lacks the key | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_override_requires_permission_and_reason_for_sales` |
| BR-06 | Customer type stored, does not change prices | customer-type price-list tier | 1→2 | planned | `tests/integration/pricing/test_price_resolution.py::test_tier_order_agreement_type_standard` |
| BR-07 | Quote number `{brand}-{quote}-{YYYY}-{seq:04}` → LK-QT-2026-0001 | sequence `sales.quote`, never reset by default | 1 | implemented | `tests/integration/sales/test_quote_numbering.py::test_concurrent_quote_numbers_unique_gapless` |
| BR-08 | Challan number `DC-{YYYY}-{seq:04}` (max + 1, yearly) | sequence `challans.challan` yearly (atomic) | 2 | implemented | `tests/integration/challans/test_challan_numbering.py::test_concurrent_dc_numbers_unique_yearly_reset` |
| BR-09 | Custom code `CP-{count+1:04}` | sequence `sales.custom_product` never reset (atomic) | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_codes_unique_never_reused` |
| BR-10 | Defaults EUR, FOB, 30 days, brand LK, note "Minimum invoice value: EUR 5,000" | quote settings defaults + rule-set note template | 1 | implemented | `tests/integration/sales/test_quote_header.py::test_defaults_applied` |
| BR-11 | Sheet 2440 × 1220, margin 5, gap 6, oversize 10 | cutting settings defaults | 2 | implemented | `tests/unit/cutting/test_packer_examples.py::test_defaults_and_oversize_effect` |
| BR-12 | JWT HS256, 24 h | opaque sessions (idle 12 h, absolute 7 days) | 1 | planned | `tests/integration/identity/test_session_cookie_csrf.py::test_cookie_flags_rotation_and_revocation` |
| BR-13 | Company identity in PDFs hard-coded (logo, "Crown Decor Pvt. Ltd.", source text, challan T&Cs) | settings `company.profile`, `company.branding`, `documents.terms.*` (permission-protected, versioned) | 1→2 | implemented | `tests/integration/challans/test_challan_documents.py::test_pdf_unicode_pagination_terms_signatures_no_internal_notes` |
| BR-14 | Brand tokens wood brown #C8A064, leaf green #8BC34A | design tokens (sand accent, forest primary) | 1 | planned | `src/styles/tokens.contrast.test.ts::text_and_ui_contrast_thresholds` |

## 7. Functional bugs (spec §10.1)

Each bug has a named regression test (PLAN legacy-parity rule 4).

| ID | Legacy bug | Correction | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| BUG-01 | Cancelled and Archived quote statuses fail (400) | full state machine incl. cancel (S1) and archive/unarchive (S2) | 1→2 | implemented | `tests/integration/sales/test_quote_status.py::test_cancelled_and_archived_transitions` |
| BUG-02 | Duplicated quotes show total 0; `assigned_to` not set | duplicate computes real totals in the same transaction; owner per policy | 2 | implemented | `tests/integration/sales/test_quote_duplicate.py::test_duplicate_real_totals_reference_cleared_owner_policy` |
| BUG-03 | Surcharge totals disagree between UI and PDF; PDF note printed with flag off | one persisted engine result read by UI, API, PDF, print, CSV | 1 | implemented | `tests/integration/documents/test_output_channels_agree.py::test_api_pdf_csv_print_totals_identical` |
| BUG-04 | Quote CSV "Total Lines" always 0; "Created By" exports an id; no totals | CSV from persisted `line_count`, names from users, totals columns | 2 | implemented | `tests/integration/sales/test_quote_csv.py::test_line_counts_names_totals_and_escaping` |
| BUG-05 | Decor fallback `"120.0".rstrip('.0')` → `"12"` | `normalise_identifier` (`^\d+\.0+$` rule with warning; `0120` distinct) | 1→2 | implemented | `tests/unit/catalogue/test_normalise_identifier.py::test_normalise_identifier`, `tests/unit/catalogue/test_normalise_identifier.py::test_120_0_becomes_120_and_0120_stays_distinct` |
| BUG-06 | Thickness filter applied after skip/limit; products without specs pass | one WHERE for items and count; thickness requires a spec row | 1 | planned | `tests/integration/catalogue/test_product_list.py::test_thickness_filter_paginates_before_limit` |
| BUG-07 | Categories created in admin UI invisible (`is_active` never set) | `is_active NOT NULL DEFAULT true` | 1→2 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_created_category_active_by_default` |
| BUG-08 | Custom-product search/activity/duplicate use non-existent `name`; completeness checks `description` | `product_name` everywhere; completeness checks real fields | 2 | implemented | `tests/integration/search/test_custom_product_name.py::test_global_search_finds_custom_product_name` |
| BUG-09 | MOQ ignores `master_carton_qty` (and other alias names) | canonical packaging columns with alias reconciliation | 1→2 | planned | `tests/unit/catalogue/test_packaging_aliases.py::test_carton_qty_alias_pair` |
| BUG-10 | EUR price selection ambiguous (last EUR row wins regardless of price_type) | deterministic resolution; ambiguity reported, never guessed | 1 | implemented | `tests/integration/pricing/test_price_resolution.py::test_legacy_multi_eur_rows_resolved_by_price_type` |
| BUG-11 | Optimiser: overproduction unused; "MaxRects" is guillotine without pruning; rough leftovers; wasted packer call; constants in code | own MaxRects with pruning + guillotine with cut tree; bounded overproduction; predicted offcuts; settings | 2 | implemented | `tests/unit/cutting/test_packer_properties.py::test_no_overlap_with_gap` |
| BUG-12 | Media import always inserts; orphan pricing/packaging/spec rows written | media dedupe; orphans quarantined then released by recheck | 2 | planned | `tests/integration/imports/test_quarantine.py::test_orphan_rows_quarantined_then_released_by_recheck` |
| BUG-13 | Numbering racy: quote read-then-increment, challan max + 1, custom count + 1 | atomic allocator with issued-number registry | 1→2 | implemented | `tests/integration/challans/test_challan_regressions.py::test_bug_13_deleted_draft_number_is_never_reused` |
| BUG-14 | Challan status accepts any string; quantity saved every keystroke | validated transitions; debounced versioned edits with surfaced failures | 2 | implemented | `tests/integration/challans/test_challan_status.py::test_transitions_validated_and_issued_immutable` |
| BUG-15 | Pricing has no edit/delete path; duplicate (product, type, currency) rows possible | price-list CRUD with effective-dated supersede, retire and history; overlap rejected | 2 | implemented | `tests/integration/pricing/test_price_lists.py::test_active_items_immutable_and_history_append_only` |
| BUG-16 | Category rename/delete do not cascade; category free text | FKs, safe rename with aliases, delete blocked or explicit reassign | 2 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_rename_alias_and_delete_or_reassign` |

## 8. Security gaps (spec §10.2)

Each gap has an IDOR or permission test (PLAN legacy-parity rule 5).

| ID | Legacy gap | Correction | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| SEC-01 | Permissions mostly cosmetic (override, export, costing, edit products, manage users, import not enforced) | service-enforced keys; route declarations; route matrix | 1→2 | implemented | `tests/contract/test_route_authz_matrix.py::test_every_route_denies_unauthorised_personas` |
| SEC-02 | Quote IDOR on line edit/delete, revise, status, duplicate, PDF, CSV; CSV dumps all quotes | parent-scoped children; scoped exports; 404 outside scope | 1→2 | implemented | `tests/integration/sales/test_quote_idor.py::test_quote_idor_matrix` |
| SEC-03 | Challans, search, activity, notes, optimiser need only a login; notes overwritable by anyone | module keys; notes need parent `update`; search/activity parent-filtered | 2 | implemented | `tests/integration/security/test_isolation_matrix.py::test_restricted_user_sees_no_sentinel_anywhere` |
| SEC-04 | JWT in query strings (`?auth=`); 24 h, no revocation | cookie sessions; query tokens ignored; immediate revocation; fragment tokens for links | 1 | implemented | `tests/integration/identity/test_sessions.py::test_tokens_never_come_from_the_url`, `tests/integration/identity/test_sessions.py::test_revocation_and_deactivation_apply_on_the_next_request` |
| SEC-05 | Hard-coded bootstrap admin re-applied on restart; default JWT secret; CORS `*` with credentials; no rate limit/lockout/password policy; demo credentials published | no bootstrap; first-admin CLI; startup refuses placeholders and wildcard origins; same-origin, no CORS; rate limits, lockout, password policy; passwordless demo links | 1 | implemented | `tests/integration/identity/test_cli.py::test_create_first_refuses_when_an_admin_exists_anywhere`, `tests/integration/identity/test_cli.py::test_create_first_enforces_the_password_policy`, `tests/integration/identity/test_login.py::test_lockout_after_five_failures_with_backoff`, `tests/integration/identity/test_login.py::test_ip_rate_limit_thirty_per_ten_minutes` |
| SEC-06 | Unescaped user input into `$regex` (ReDoS, injection) | `escape_like` ILIKE + pg_trgm; architecture test bans regex operators | 1→2 | implemented | `tests/unit/core/test_escape_like.py::test_metacharacters_match_literally` |
| SEC-07 | Role strings unvalidated; users hard-deleted; no audit of price/role/permission changes | validated roles; deactivation; append-only audit with diffs | 1→2 | implemented | `tests/integration/audit/test_audit_append_only.py::test_update_delete_rejected_and_security_events_recorded` |
| SEC-08 | Third-party scripts (Emergent loader, PostHog) on every page | none; nonce CSP; e2e check | 1 | planned | `e2e/security/no-third-party-scripts.spec.ts::no_external_scripts_and_csp_present` |

## 9. Engineering debt (spec §10.3)

| ID | Legacy debt | Correction | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| DEBT-01 | One 4.3k-line `server.py`; no routers/services/repositories; `Dict[str, Any]` bodies | modular monolith; typed Pydantic schemas (`extra="forbid"` on writes); layering test | 0→1 | planned | `tests/contract/test_architecture_rules.py::test_layering_and_decorated_services` |
| DEBT-02 | N+1 queries (configurator enrichment, challan counts, summary, recent products) | batched queries; query-count assertions | 1→2 | implemented | `tests/integration/catalogue/test_product_list.py::test_rows_enriched_without_n_plus_one` |
| DEBT-03 | No transactions; totals recomputation can drift | one UoW per command; totals in the same transaction | 0→1 | planned | `tests/integration/sales/test_quote_totals.py::test_totals_persisted_and_lines_renumbered_atomically` |
| DEBT-04 | Overlapping packaging names; free-text dimensions/thickness on lines and custom products | canonical packaging; numeric mm with source text | 1→2 | planned | `tests/unit/catalogue/test_parse_dimension.py::test_parse_dimension_cases` |
| DEBT-05 | PDFs in core Helvetica (Latin-1): € ₹ and non-Latin names fail; fixed rows truncate text | ReportLab + embedded Noto; wrapping cells; repeated headers | 0→1 | planned | `tests/integration/documents/test_pdf_unicode_pagination.py::test_long_document_paginates_with_glyphs` |
| DEBT-06 | Emergent-specific storage and `EMERGENT_LLM_KEY` | `platform/files` (local_fs + S3); provider keys only for chosen providers | 1→2 | implemented | `tests/contract/files/test_storage_adapters.py::test_local_fs_and_s3_moto_same_contract` |
| DEBT-07 | Tests hit a live URL with real credentials; no unit tests, CI or frontend tests | hermetic unit/integration/contract suites on local Postgres; vitest; Playwright | 0→1 | planned | `npm run check` and `npm run test:api` (scripts/dev.mjs) |
| DEBT-08 | Unused dependencies on both sides | locked, minimal dependency sets; `npm ls`, `pip-audit`, `npm audit` in Slice 6 | 0→6 | planned | `tests/contract/test_dependencies.py::test_no_unused_backend_dependencies` |

## 10. Reuse vs redesign (spec §11)

### 10.1 Carry over

| ID | Legacy asset | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| REUSE-01 | Product data model: immutable `product_key` vs non-unique display SKU; master + pricing (many) + packaging (1) + specs (1) + media (many); taxonomy; decor/thickness/size/finish variant dimensions | `modules/catalogue` + `modules/pricing` | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_master_fields_round_trip` |
| REUSE-02 | Import discipline: taxonomy first, category validation, orphan detection, preview → import → validate, row-numbered errors, column aliases | `modules/imports` workbench | 2 | implemented | `tests/integration/imports/test_products_import.py::test_requires_taxonomy_and_applies_defaults` |
| REUSE-03 | Quotation behaviour: search-first configurator, snapshot lines, override with reason, advisory MOQ, EUR 5,000 / EUR 400, revisions with status history, duplicate, PDF, three line types, customer type, incoterm | `modules/sales` quotes + `modules/commercial` engine | 1→2 | implemented | `e2e/challans.spec.ts::quote_full_legacy_journey` |
| REUSE-04 | Custom-product lifecycle and promotion idea | `modules/sales` custom products with promotion | 2 | implemented | `tests/integration/sales/test_custom_product_promotion.py::test_request_approve_execute_idempotent` |
| REUSE-05 | Optimiser inputs/outputs (groups, grain locks, margin/gap/oversize, efficiency and scrap, per-board layout); proper packer; persisted against production orders | `modules/cutting` (S2) + WO links (S4) | 2→4 | implemented | `tests/integration/production/test_cut_plans_capacity.py::test_cut_plan_link_sets_board_requirement_and_release_releases_the_plan` (repointed at the Slice-4 merge; `test_plan_release.py` was not written), `::test_stale_cut_plan_refuses_the_release` |
| REUSE-06 | Challan semantics (types, returnable, destinations, GSTIN/HSN, DC numbering, terms, signatures) modelled as inventory movements with reconciled returns | `modules/challans` (S2) + `modules/inventory` (S4) | 2→4 | implemented | `tests/integration/challans/test_issue_return_cancel.py::test_issue_posts_exactly_one_movement` |
| REUSE-07 | Role intent (4 roles, 14 permissions) made real, server-enforced, extensible | role templates + legacy alias table | 1 | planned | `tests/contract/test_legacy_permission_parity.py::test_legacy_templates_reproduce_spec_3_2` |
| REUSE-08 | Validated UX patterns: global `/` search, completeness dashboard, activity feed, autosaving notes, duplicates, CSV exports, print-friendly documents | platform search, catalogue completeness, collab, documents | 2 | implemented | `e2e/challans.spec.ts::shared_utilities_journey` |

### 10.2 Do not carry over

| ID | Legacy pattern | Replacement | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| AVOID-01 | Single-file backend | modular monolith with layering test | 0 | planned | `tests/contract/test_architecture_rules.py::test_layering_and_decorated_services` |
| AVOID-02 | Schemaless `Dict` writes | typed schemas; JSONB only through validated models | 0→1 | planned | `tests/contract/test_architecture_rules.py::test_no_untyped_write_bodies` |
| AVOID-03 | Query-string tokens | cookie sessions; fragment tokens | 1 | planned | `tests/integration/identity/test_session_cookie_csrf.py::test_query_tokens_ignored` |
| AVOID-04 | Hard-coded admin, credentials, secrets | first-admin CLI; env secrets; startup validation | 1 | planned | `tests/integration/identity/test_no_bootstrap_credentials.py::test_production_config_rejects_placeholders_and_wildcards` |
| AVOID-05 | Emergent storage, scripts, analytics | platform files; no third-party scripts | 1→2 | planned | `e2e/security/no-third-party-scripts.spec.ts::no_external_scripts_and_csp_present` |
| AVOID-06 | Free-text customer fields | party master with snapshots | 1 | implemented | `tests/integration/sales/test_quote_header.py::test_issue_requires_linked_party` |
| AVOID-07 | Cosmetic-only permissions | server-enforced keys | 1 | implemented | `tests/contract/test_route_authz_matrix.py::test_every_route_denies_unauthorised_personas` |
| AVOID-08 | Currency as a label without FX | anti-relabel constraint; list or approved FX | 2 | implemented | `tests/integration/sales/test_currency_change.py::test_db_rejects_currency_relabel` |
| AVOID-09 | Count-based document numbering | atomic allocator | 1 | planned | `tests/integration/numbering/test_concurrent_numbering.py::test_unique_gapless_rollback_consumes_none` |

### 10.3 Open questions from §11 (tracked as owner decisions)

| ID | Question | Where recorded | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| OQ-01 | Single company or multi-entity; GST/e-way-bill and export documentation both required? | BUILD_STATE §5 #4, #8 | 5 | planned (owner input) | — (business decision; company/branch boundaries built from Slice 1) |
| OQ-02 | Domestic vs export price-list rules per customer type | BUILD_STATE §5 #15; tier resolution | 2 | planned (owner input) | `tests/integration/pricing/test_price_resolution.py::test_tier_order_agreement_type_standard` |
| OQ-03 | Optimiser feeding purchasing and production vs calculator | answered by plan: links to WOs and board lots (S4), offcut reuse (S5) | 4→5 | planned | `tests/integration/cutting/test_plan_release.py::test_release_blocked_until_oversize_verified_and_links_work_order` |
| OQ-04 | Historical data migration form | migration dry-run tooling for every legacy entity | 5 | planned | `tests/integration/migration/test_dry_run.py::test_counts_reconcile_and_hashes_verified` |
| OQ-05 | Approval rules for price overrides, below-MOQ and below-minimum orders | BUILD_STATE §5 #2; approvals policy | 1→3 | planned (owner input) | `tests/integration/approvals/test_quote_review_policy.py::test_demo_rule_requires_review_for_overrides` |

## 11. PRD vs code discrepancies (spec §12)

| ID | Discrepancy | Resolution | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| PRD-01 | Cancelled/Archived "added" but rejected by backend | BUG-01 | 1→2 | implemented | `tests/integration/sales/test_quote_status.py::test_cancelled_and_archived_transitions` |
| PRD-02 | Analytics, margin calculator, bulk price export, customer master, approval workflow, quote-to-order listed as backlog | parties (S1), approvals (S1), price-list export (S2), orders (S4), margin (S5); analytics only as factual views | 1→5 | planned | `tests/integration/orders/test_quote_conversion.py::test_concurrent_and_retried_conversion_creates_one_order` |
| PRD-03 | "Operations = no override" enforced only in UI | operations template lacks `sales.quote_price.override` | 1 | planned | `tests/contract/test_legacy_permission_parity.py::test_legacy_templates_reproduce_spec_3_2` |
| PRD-04 | "Sales get 403 on others' quotes" only partly true | SEC-02 | 1→2 | implemented | `tests/integration/sales/test_quote_idor.py::test_quote_idor_matrix` |
| PRD-05 | Dynamic permission resolution used for only three backend checks | every key enforced | 1→2 | implemented | `tests/contract/test_route_authz_matrix.py::test_every_route_denies_unauthorised_personas` |
| PRD-06 | Completeness "missing EUR price / MOQ" miscounted | per-product metrics | 2 | planned | `tests/integration/catalogue/test_completeness.py::test_metrics_count_distinct_products_real_fields` |
| PRD-07 | 7 imports; lookup_reference never used | LM-34, FG-LKP-03 | 2 | planned | `tests/integration/imports/test_lookup_import.py::test_upsert_idempotent_browse_and_export` |
| PRD-08 | Admin credentials in PRD differ from code bootstrap; password reset each restart | SEC-05 | 1 | planned | `tests/integration/identity/test_no_bootstrap_credentials.py::test_startup_creates_no_users_and_cli_refuses_second_admin` |
| PRD-09 | `design_guidelines.json` navy palette and 8 product tabs vs warm theme and 5 tabs | new tokens (UI-96); product tabs overview, specifications, packaging, pricing, media, history (+ material view, operations S4) | 1→4 | planned | `e2e/catalogue/product-form.spec.ts::history_tab_shows_versions` |

## 12. ERP gap list (spec §9)

New scope beyond parity, tracked so nothing in §9 is silently dropped.

| ID | Gap | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| GAP-01 | Customer/vendor master, contacts, addresses | `modules/parties` | 1→2 | implemented | `tests/integration/parties/test_parties.py::test_create_allocates_the_next_number_and_emits_created`, `tests/integration/parties/test_parties.py::test_update_reports_changed_field_names_and_checks_versions`, `tests/integration/parties/test_parties.py::test_sales_users_see_only_their_own_parties`, `tests/integration/parties/test_parties.py::test_company_scope_and_visible_but_forbidden` |
| GAP-02 | Price lists per customer / customer type | `modules/pricing` tiers | 2 | planned | `tests/integration/pricing/test_price_resolution.py::test_tier_order_agreement_type_standard` |
| GAP-03 | Multi-currency with FX rates | `pricing_fx_rate` with approval | 2 | implemented | `tests/integration/sales/test_currency_change.py::test_currency_change_with_approved_fx` |
| GAP-04 | Tax codes, HSN master | HSN/SAC on products and lines; tax profiles (S5); no fabricated GST rules | 1→5 | planned | `tests/integration/finance/test_issuance_gate.py::test_draft_allowed_issue_blocked_without_verified_tax_profile` |
| GAP-05 | UOM master, warehouses/locations, employee master | `platform/org` UOM (S1), `inventory` warehouses (S4), memberships/teams (S1) | 1→4 | planned | `tests/integration/org/test_uom.py::test_seeded_legacy_units_and_integer_rules` |
| GAP-06 | Quote approval workflow | `platform/approvals` | 1 | planned | `tests/integration/approvals/test_decide.py::test_sod_hash_and_version_bound_decision` |
| GAP-07 | Quote → order → delivery → invoice chain | orders (S4), challans/inventory (S4), finance (S5) | 4→5 | planned | `tests/integration/flows/test_scenario_i_quote_to_return.py::test_end_to_end` |
| GAP-08 | Discounts, taxes, freight, payment schedule | line discounts (S1 engine), freight manual line (S1), payment due days (S5) | 1→5 | planned | `tests/unit/commercial/test_engine.py::test_discount_applicable_subtotal` |
| GAP-09 | CRM, leads, follow-ups, customer-wise quote history | enquiries + customer messages (S1), follow-up drafts (S3), party quote tab (S2) | 1→3 | planned | `tests/integration/sales/test_enquiries.py::test_enquiry_lifecycle_and_events` |
| GAP-10 | Stock ledger, lots, stock by location, reorder levels, stock take | `modules/inventory` | 4 | implemented | `tests/integration/inventory/test_ledger_stateful.py::test_ledger_machine` (`LedgerMachine`) |
| GAP-11 | Purchasing (requisitions, POs, GRN, vendor bills, vendor price lists) | `modules/procurement` | 4 | implemented | `tests/integration/procurement/test_procure_to_pay.py::test_requisition_to_bill_handoff` |
| GAP-12 | Manufacturing (BOM, routing, work orders, job work, issue/consumption, planning, scrap, costing) | `modules/production` | 4 | in progress | `tests/integration/production/test_costing_feasibility.py::test_rollup_is_deterministic_and_lists_missing_inputs`; job-work operations through challans not built (production report) |
| GAP-13 | Finance (invoicing, receipts, ledgers, GST returns, e-invoice, bank reconciliation, budgets, P&L) | invoices, receipts, allocations, ageing, accounting adapter (S5); native GL, GST returns, budgets, P&L are future scope | 5 | planned | `tests/integration/finance/test_allocations.py::test_allocations_bounded_and_ageing_per_currency` |
| GAP-14 | Logistics (packing lists, shipping docs, CBM planning, LCs, tracking) | `modules/logistics` (LCs future scope) | 4 | implemented | `tests/unit/logistics/test_packing_math.py::test_cartons_cbm_weights_and_incomplete_flags` |
| GAP-15 | HR, payroll, attendance | future scope (leave/delegation context only) | — | deferred (out of scope unless owner adds) | — |
| GAP-16 | Platform: configurable roles, field-level permissions, approval engine, audit log, notifications/email, document templates/settings, multi-branch, localisation, reporting, webhooks, backups, migration tooling, automated tests | identity/authz (S1–S2), field guards (S1), approvals (S1), audit (S1), email adapter (S2–S3), settings (S1), branches (S1), backups (S5), migration (S5), tests (S0+) | 1→5 | planned | `tests/integration/system/test_backup_restore_rehearsal.py::test_restore_rehearsal_roundtrip` |

## 13. Build prompt `legacy_parity_and_corrections` 1–12

| ID | Requirement | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| LP-01.1 | Retain admin, management, sales, operations as initial role templates | identity templates | 1 | planned | `tests/contract/test_legacy_permission_parity.py::test_legacy_templates_reproduce_spec_3_2` |
| LP-01.2 | Retain all 14 legacy permission intentions plus module/action/scope permissions | permissions catalogue + alias table | 1 | planned | `tests/contract/test_legacy_permission_parity.py::test_alias_table_matches_registry` |
| LP-01.3 | Per-user grants/revokes with revoke precedence | resolution | 1 | implemented | `tests/unit/authz/test_permission_resolution.py::test_revoke_wins_and_scope_is_max` |
| LP-01.4 | Enforce on every read/write, child line, revision, duplicate, export, media download, note, activity item, search result and agent tool | ScopedRepository, parent policies, tool matrix | 1→3 | planned | `tests/integration/security/test_isolation_matrix.py::test_restricted_user_sees_no_sentinel_anywhere` |
| LP-01.5 | Validate roles | role validation | 1→2 | implemented | `tests/integration/authz/test_role_validation.py::test_unknown_key_scope_cycle_and_escalation_rejected` |
| LP-01.6 | User creation/invitation, updates, deactivation, secure reset, profile, password/session management; historical attribution via soft deletion | identity S1–S2 | 1→2 | planned | `tests/integration/identity/test_invitation_and_reset.py::test_tokens_single_use_hashed_fragment_only` |
| LP-01.7 | No fixed bootstrap credential or startup password reset | first-admin CLI | 1 | planned | `tests/integration/identity/test_no_bootstrap_credentials.py::test_startup_creates_no_users_and_cli_refuses_second_admin` |
| LP-01.8 | Maintained auth, rate limits, revocation, administrator MFA | argon2id, Postgres rate limits, sessions, TOTP | 1→2 | implemented | `tests/integration/identity/test_mfa.py::test_admin_enrolment_replay_rejected_recovery_once` |
| LP-01.9 | Never put tokens in download query strings | cookie downloads | 1 | planned | `tests/integration/identity/test_session_cookie_csrf.py::test_query_tokens_ignored` |
| LP-02.1 | Immutable product_key distinct from non-unique display_sku | catalogue | 1 | implemented | `tests/integration/catalogue/test_product_crud.py::test_product_key_immutable_api_and_db_trigger` |
| LP-02.2 | Product master fields (brand, status, taxonomy, variant group, unit, decor identity/options, finish/shape, source provenance, remarks) | catalogue tables | 1→2 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_master_fields_round_trip` |
| LP-02.3 | All specification and packaging fields | FG-SPC, FG-PKG | 1→2 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_specification_fields_round_trip` |
| LP-02.4 | Canonical numeric dimensions and units; original strings as provenance | dimension rows | 1 | planned | `tests/unit/catalogue/test_parse_dimension.py::test_parse_dimension_cases` |
| LP-02.5 | Text decor identifiers with leading zeros | normalise_identifier | 1 | implemented | `tests/unit/catalogue/test_normalise_identifier.py::test_normalise_identifier` |
| LP-02.6 | Search/filter by all dimensions, filtering before pagination | search_products | 1 | implemented | `tests/integration/catalogue/test_product_list.py::test_search_and_filters_apply_before_pagination` |
| LP-02.7 | Stats, recently changed, facets, taxonomy validation, deep-linked tabs | LM-14, LM-15, LM-22, UI-14 | 2 | implemented | `e2e/catalogue/product-list.spec.ts::filters_paging_and_deep_links_survive_reload` |
| LP-02.8 | Validated forms, editable price lists, actual paging in lists and configurator | UI-45, UI-47, UI-36, UI-60 | 2 | planned | `e2e/catalogue/product-form.spec.ts::create_with_all_sections_and_server_errors` |
| LP-03.1 | Images, documents, packaging photos; primary image, preview, upload, authenticated download, soft delete | catalogue media + platform files | 2 | planned | `e2e/catalogue/media.spec.ts::upload_preview_download_delete_restore` |
| LP-03.2 | Replace Emergent storage with S3-compatible storage | local_fs + S3 adapter | 1→2 | implemented | `tests/contract/files/test_storage_adapters.py::test_local_fs_and_s3_moto_same_contract` |
| LP-03.3 | Validate content type, size and upload ownership | sniffing, limits, uploader-only unattached files | 2 | planned | `tests/integration/files/test_file_dedupe.py::test_unattached_visible_only_to_uploader` |
| LP-03.4 | Categories/subcategories with FKs and active/order settings; safe rename; block or reassign deletion | taxonomy | 2 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_rename_alias_and_delete_or_reassign` |
| LP-03.5 | Retain catalogue-page/source metadata | provenance columns | 1 | planned | `tests/integration/catalogue/test_product_fields_round_trip.py::test_provenance_fields_round_trip` |
| LP-03.6 | Remove platform branding/scripts and unrequested analytics | SEC-08 | 1 | planned | `e2e/security/no-third-party-scripts.spec.ts::no_external_scripts_and_csp_present` |
| LP-04.1 | All seven import types, CSV and XLSX, header normalisation, documented aliases | imports | 2 | implemented | `tests/unit/imports/test_header_normalisation.py::test_normalisation_aliases_and_collisions` |
| LP-04.2 | Stage taxonomy first, then products and dependents | dependency order | 2 | implemented | `tests/integration/imports/test_products_import.py::test_requires_taxonomy_and_applies_defaults` |
| LP-04.3 | Preview, map, validate, all row-numbered errors in a downloadable report | workbench | 2 | planned | `tests/integration/imports/test_report_csv.py::test_all_errors_reported_uncapped` |
| LP-04.4 | Commit transactionally in bounded batches | 500-row batches, resumable | 2 | implemented | `tests/integration/imports/test_imports_http.py::test_workbench_flow_over_http` |
| LP-04.5 | Quarantine orphans; re-import must not duplicate media | quarantine + dedupe | 2 | planned | `tests/integration/imports/test_reimport_idempotent.py::test_second_identical_import_is_noop` |
| LP-04.6 | Durable history, mappings, hashes, source rows; before/after review; rollback of unreferenced imports without erasing later work | history + rollback plan | 2 | planned | `tests/integration/imports/test_rollback.py::test_rollback_blocked_when_referenced_or_later_edited` |
| LP-04.7 | Lookup data with a documented use or export path | lookup browser/export | 2 | planned | `tests/integration/imports/test_lookup_import.py::test_upsert_idempotent_browse_and_export` |
| LP-04.8 | Escape spreadsheet formula injection on all CSV outputs | `core/csv_safe` single writer | 1 | planned | `tests/contract/test_single_csv_writer.py::test_no_csv_writer_outside_csv_safe` |
| LP-04.9 | Clear-sample-data only in an isolated demo dataset with scoped admin confirmation | demo reset | 2 | implemented | ; vitest `features/imports/imports.test.tsx` |
| LP-05.1 | Price types, currencies, unit/basis, base/addon/final prices and labels, yield, thickness, MOQ, validity, notes, provenance | pricing tables | 1→2 | implemented | `tests/integration/pricing/test_price_lists.py::test_item_fields_round_trip` |
| LP-05.2 | Deterministic selection agreement → customer type → standard, then currency, unit, date; reject ambiguous overlaps unless priority explicit | resolution | 1→2 | planned | `tests/integration/pricing/test_price_resolution.py::test_ambiguous_same_tier_does_not_fall_through` |
| LP-05.3 | Price history and protected costing | item history + product_cost | 2 | implemented | `tests/integration/pricing/test_price_lists.py::test_active_items_immutable_and_history_append_only` |
| LP-05.4 | Selected currency's list or sourced, dated FX snapshot; never relabel; unknown FX blocks only conversion | FX second pass + anti-relabel | 2 | implemented | `tests/integration/sales/test_currency_change.py::test_currency_change_blocked_without_fx` |
| LP-05.5 | Price create/edit/retire UI | price-list editor | 2 | planned | `e2e/pricing/price-lists.spec.ts::create_activate_supersede_retire` |
| LP-06.1 | Search-first configurator with category, family, size, thickness, decor, finish filters, narrowed options and exact match | configurator | 1→2 | implemented | `tests/integration/sales/test_configurator.py::test_filters_narrow_options_page_and_exact_match` |
| LP-06.2 | Catalog/custom/manual lines with product/media/packaging/commercial snapshots | quote lines | 1→2 | implemented | `tests/integration/sales/test_quote_lines.py::test_catalog_line_snapshot_immune_to_catalogue_change` |
| LP-06.3 | Customer via party link + historical snapshot; type, incoterm, currency, terms, validity, brand, owner, surcharge toggle, remarks, internal notes | quote header | 1→2 | implemented | `tests/integration/sales/test_quote_header.py::test_header_fields_round_trip_with_party_snapshot` |
| LP-06.4 | Manual presets development, tooling, special packaging, freight, samples, miscellaneous; defaults EUR/FOB/30/LK | manual lines + defaults | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_manual_line_presets` |
| LP-06.5 | Override with reason and permission (sales reason required); quantity/MOQ warnings advisory | override rules + advisories | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_override_requires_permission_and_reason_for_sales` |
| LP-06.6 | Filters, mine/all scope, duplication, revision snapshots, status history, PDF, print, CSV, draft-only deletion | quotes | 1→2 | implemented | `e2e/challans.spec.ts::quote_full_legacy_journey` |
| LP-06.7 | Duplicate computes real totals, copies assignee under policy, clears customer reference | duplicate | 2 | implemented | `tests/integration/sales/test_quote_duplicate.py::test_duplicate_real_totals_reference_cleared_owner_policy` |
| LP-06.8 | Eight statuses with validated transitions, terminal/archive rules, lawful correction paths | state machine | 1→2 | implemented | `tests/integration/sales/test_quote_status.py::test_quote_status_machine_table` |
| LP-06.9 | Internal review can request approval; marked sent and provider delivery distinct | approvals + dispatch records | 1→3 | planned | `tests/integration/sales/test_quote_dispatch.py::test_marked_sent_distinct_from_delivery_status` |
| LP-06.10 | Immutable issued revisions; compare; restore into a new draft version | revisions | 1→2 | implemented | `tests/integration/sales/test_quote_revisions.py::test_compare_and_restore_keep_history` |
| LP-07.1 | Decimal arithmetic, explicit rounding, single server-side result for UI, API, PDF, CSV | engine | 1 | planned | `tests/unit/commercial/test_engine.py::test_engine_properties` |
| LP-07.2 | Recommended units `ceil(5000 / positive EUR price)` rounded up to carton multiple; distinct from product MOQ | engine | 1 | implemented | `tests/unit/commercial/test_engine.py::test_recommended_quantity` |
| LP-07.3 | Zero/missing price → unavailable advisory, no division by zero; no invented FX thresholds | engine | 1 | implemented | `tests/unit/commercial/test_engine.py::test_missing_zero_price_and_non_eur` |
| LP-07.4 | EUR 400 surcharge rule; EUR 5,000 exactly has none | engine | 1 | implemented | `tests/unit/commercial/test_engine.py::test_surcharge_table` |
| LP-07.5 | Persist subtotal, adjustments, surcharge, tax where applicable, final total with rule/version inputs | persisted calculation | 1 | implemented | `tests/integration/sales/test_quote_totals.py::test_calc_input_hash_matches_recomputation` |
| LP-07.6 | Discounts: applicable subtotal = merchandise after line discounts, excluding tax and surcharge; undiscounted legacy cases match | engine rule set v1 | 1 | planned | `tests/unit/commercial/test_engine.py::test_discount_applicable_subtotal` |
| LP-07.7 | Quote, PDF and CSV agree | output agreement | 1→2 | implemented | `tests/integration/documents/test_output_channels_agree.py::test_api_pdf_csv_print_totals_identical` |
| LP-07.8 | Atomic unique counters for LK-QT, DC, CP; documented reset settings; never reuse numbers | numbering | 1→2 | planned | `tests/integration/numbering/test_concurrent_numbering.py::test_unique_gapless_rollback_consumes_none` |
| LP-08.1 | Custom product types, base product, customer-specific flag, customer/inquiry, specification fields, packaging, protected costing, quote price, remarks, notes | custom products | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_custom_product_lifecycle_and_fields` |
| LP-08.2 | Eight states with valid transitions | custom product state machine | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_transition_table_and_reasons` |
| LP-08.3 | List/search/filter/detail/create/edit/duplicate/export/archive; `product_name` consistently | custom products | 2 | implemented | `tests/integration/search/test_custom_product_name.py::test_global_search_finds_custom_product_name` |
| LP-08.4 | Promotion creates a validated master record with lineage and approval | promotion | 2 | implemented | `tests/integration/sales/test_custom_product_promotion.py::test_request_approve_execute_idempotent` |
| LP-08.5 | Keep approved sample/spec history; attach the product to quotes | spec revisions + custom lines | 2 | implemented | `tests/integration/sales/test_custom_products.py::test_spec_revisions_and_quote_link` |
| LP-09.1 | Inputs SKU/decor/thickness/length/width/qty with autocomplete, grain locks, rotation rules, sheet size, margins, gap, oversize, bounded overproduction | cutting | 2 | implemented | `tests/integration/cutting/test_calculate_endpoint.py::test_product_autocomplete_fills_decor_thickness_dimensions` |
| LP-09.2 | Defaults 2440 × 1220, 5 mm margin, 6 mm gap, separately enabled +10 mm oversize marked for physical verification | cutting settings | 2 | implemented | `tests/unit/cutting/test_packer_examples.py::test_defaults_and_oversize_effect` |
| LP-09.3 | Group by decor + thickness; proven non-overlapping packer; guillotine vs nesting distinguished | packer modes | 2 | implemented | `tests/unit/cutting/test_packer_properties.py::test_guillotine_mode_is_guillotine_separable` |
| LP-09.4 | Boards, placements, required/produced, unfit reasons, usable/raw areas, scrap, efficiency, rotation, per-board SVG/table; no optimality claim | calculation outputs | 2 | implemented | `tests/unit/cutting/test_packer_properties.py::test_area_identity_exact` |
| LP-09.5 | Implement or hide overproduction; target bounded explicit overproduction | bounded overproduction | 2 | implemented | `tests/unit/cutting/test_packer_examples.py::test_overproduction_bounded` |
| LP-09.6 | Save/reopen/duplicate/export plans; later link to work orders, board lots and measured offcuts | plans (S2), links (S4), offcut reuse (S5) | 2→5 | in progress | `tests/integration/cutting/test_plan_persistence.py::test_save_reopen_preserves_inputs_and_results` |
| LP-10.1 | Six types; returnable/non-returnable; six destinations | challans | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_all_types_return_types_destinations` |
| LP-10.2 | Header and line fields incl. HSN/SAC, UOM, product link | challans | 2 | implemented | `tests/integration/challans/test_challan_crud.py::test_lines_with_product_lookup_and_uom_rules` |
| LP-10.3 | draft/issued/closed/cancelled with valid transitions; duplicate; filters; summaries; CSV, PDF, print, terms, signatures | challans | 2 | implemented | `tests/unit/challans/test_status_machine.py::test_valid_and_invalid_transitions_table` |
| LP-10.4 | Draft deletion admin-only; debounced edits, validated quantities, surfaced failed saves | challans | 2 | implemented | `tests/integration/challans/test_challan_permissions.py::test_admin_only_draft_delete_number_not_reused` |
| LP-10.5 | Movement policy per type; dispatch and challan reference one posting | movement policy + ledger | 4 | implemented | `tests/integration/challans/test_issue_return_cancel.py::test_issue_posts_exactly_one_movement` |
| LP-10.6 | Job-work material company-owned at external location; partial returns reconcile; excess/duplicate receipts rejected; cancellation by reversal | inventory + returns | 4 | implemented | `tests/integration/challans/test_issue_return_cancel.py::test_cancel_issued_creates_reversal` |
| LP-11.1 | Grouped global search with deep links and slash shortcut; recent searches; all old and new entities under permissions | platform search | 2 | implemented | `tests/integration/search/test_global_search.py::test_grouped_scoped_results_with_deep_links` |
| LP-11.2 | Accurate per-product completeness for products and custom products | completeness | 2 | planned | `tests/integration/catalogue/test_completeness.py::test_metrics_count_distinct_products_real_fields` |
| LP-11.3 | Recent activity; conflict-aware autosaved internal notes | collab | 2 | implemented | `tests/integration/collab/test_internal_notes.py::test_autosave_conflict_409_and_parent_update_required` |
| LP-11.4 | Duplicates, exports, printed documents | quotes, custom products, challans, cut plans | 2 | implemented | `e2e/challans.spec.ts::shared_utilities_journey` |
| LP-11.5 | Persistent sidebar/theme preferences; light and dark themes; pagination | preferences, tokens | 1 | planned | `src/lib/ui-preferences.test.ts` |
| LP-11.6 | PDFs wrap across pages, repeat headers, Unicode names and currency glyphs | core documents | 1→2 | planned | `tests/integration/documents/test_pdf_unicode_pagination.py::test_long_document_paginates_with_glyphs` |
| LP-11.7 | Company logos, addresses, GSTIN, bank details, terms are configurable, permission-protected settings | org settings | 1→2 | planned | `tests/integration/org/test_settings_versioning.py::test_identity_and_bank_settings_masked_and_versioned` |
| LP-12.1 | Explicit regressions (all §10.1 items) | §7 BUG rows | 1→2 | planned | see BUG-01…BUG-16 |
| LP-12.2 | Fix ownership/field-leak vulnerabilities; remove regex injection | §8 SEC rows | 1→2 | planned | see SEC-01…SEC-08 |
| LP-12.3 | Focused tests rather than screen-render assertions | test strategy | 0→6 | planned | `npm run test:api` and `npm run test:e2e` coverage per scenario |

## 14. Acceptance scenarios A–N

| ID | Scenario clause | New home | Slice | Status | Verifying test |
|---|---|---|---|---|---|
| SCN-A1 | Sales user opens Today in their local morning: only authorised due tasks, real updates, source-linked suggestions, correct dates | briefings | 1 | implemented | `tests/integration/briefings/test_sales_overview_computed.py::test_meera_sentence_and_sections` |
| SCN-A2 | Management sees authorised cross-team decisions | briefings + approvals | 1→4 | planned | `tests/integration/briefings/test_management_three_decisions.py::test_sahil_three_decisions_sentence` |
| SCN-A3 | Restricted employee cannot obtain others' sensitive information through summaries, search, tools, exports or direct URLs | isolation matrix | 1→6 | planned | `tests/integration/briefings/test_restricted_briefing_contents.py::test_kabir_sees_only_his_task` |
| SCN-A4 | No aggregate leakage | visibility before counting | 1 | implemented | `tests/integration/briefings/test_no_aggregate_leak_property.py::test_overview_numbers_equal_visible_counts` |
| SCN-A5 | E2E Today scope and isolation (desktop + mobile) | web Today | 1 | planned | `e2e/scenarios/a-today-scope.spec.ts::meera_today_and_restricted_user` |
| SCN-B1 | Source change invalidates/refreshes recommendation; stable issue id | briefings | 1→2 | implemented | `tests/integration/briefings/test_source_change_invalidates_recommendation.py::test_stable_issue_id_and_stale_recommendation` |
| SCN-B2 | No manufactured versions; replay and out-of-order handled | tasks + briefings | 1 | implemented | `tests/integration/briefings/test_no_manufactured_versions.py::test_replay_and_immaterial_change_create_no_version` |
| SCN-B3 | Active spoken briefing never reorders | pins | 3 | implemented | `tests/integration/briefings/test_voice_pin_no_reorder.py::test_pinned_order_and_ordinal_resolution`, `tests/integration/briefings/test_listen_and_phrasing.py::test_listen_script_keeps_the_pinned_order_and_reads_back_values`; `e2e/scenarios/b-briefing-stability.spec.ts` |
| SCN-B4 | Snoozed/handled state survives reload and channel switching | item states | 1→3 | implemented | `tests/integration/briefings/test_snooze_persists_across_reload_and_whatsapp.py::test_snooze_reload_and_whatsapp_sync`, `::test_web_acknowledgement_marks_the_summary_and_voids_its_buttons` |
| SCN-B5 | Midnight, weekend and shift boundaries explicit | workcal | 1→2 | implemented | `tests/integration/briefings/test_versions_and_actions.py::test_midnight_rollover` |
| SCN-B6 | AI outage behaves explicitly | fallback | 1→3 | implemented | `tests/integration/briefings/test_ai_outage_template_text.py::test_standard_wording_label`, `tests/integration/briefings/test_listen_and_phrasing.py::test_listen_after_an_outage_speaks_the_template_wording` |
| SCN-C1 | "Prepare Nordhaus's usual oak tray quote" resolves customer/product from fixtures, current EUR export price snapshotted, 240 × 24 = 5,760, reviewable draft | sales tools + Demo orchestrator | 1 | implemented | `tests/integration/sales/test_nordhaus_quote_path.py::test_scenario_c_nordhaus_repeat_quote` |
| SCN-C2 | Correctly scoped next-action item | tasks | 1 | implemented | `tests/integration/tasks/test_agent_quote_draft_creates_scoped_next_action.py::test_review_task_for_meera_only` |
| SCN-C3 | Catalogue changes cannot mutate the draft's snapshot | snapshots | 1 | implemented | `tests/integration/sales/test_quote_lines.py::test_catalog_line_snapshot_immune_to_catalogue_change` |
| SCN-C4 | Same path via text, voice and WhatsApp demo | agents, voice, channels | 3 | implemented | `tests/integration/channels/test_scenario_c_whatsapp.py::test_c_whatsapp_text_drafts_the_quote_and_review_link_redirects`, `::test_c_whatsapp_voice_note_echoes_the_transcript_and_drafts`, `tests/integration/voice/test_voice_api.py::test_agent_c_voice_path_same_result`; `e2e/scenarios/k-whatsapp.spec.ts`, `e2e/scenarios/j-voice.spec.ts` |
| SCN-C5 | E2E desktop and phone | web | 1 | implemented | `e2e/scenario-c.spec.ts` (desktop and phone; run progress over SSE) |
| SCN-D1 | EUR 24, carton 24 → recommended 216 | engine | 1 | implemented | `tests/unit/commercial/test_engine.py::test_recommended_quantity` |
| SCN-D2 | EUR 4,800: off → 4,800; on → 5,200; 5,000 → no surcharge | engine | 1 | implemented | `tests/unit/commercial/test_engine.py::test_surcharge_table` |
| SCN-D3 | All output channels agree | documents | 1→2 | implemented | `tests/integration/documents/test_output_channels_agree.py::test_api_pdf_csv_print_totals_identical` |
| SCN-D4 | Missing/zero price and non-EUR cases do not fabricate results | engine | 1 | implemented | `tests/unit/commercial/test_engine.py::test_missing_zero_price_and_non_eur` |
| SCN-E1 | Currency switch resolves the right list or performs an approved dated conversion; relabel impossible | currency change | 2 | implemented | `tests/integration/sales/test_currency_change.py::test_currency_change_with_approved_fx` |
| SCN-E2 | Restricted costing redacted from custom products, model context and exports | field guards | 2→3 | in progress | `tests/integration/security/test_costing_redaction.py::test_costing_absent_without_pricing_cost_read` |
| SCN-F1 | Sales user cannot alter another owner's line, revision, status, notes, PDF, CSV or duplicate via guessed ids | IDOR matrix | 1→2 | implemented | `tests/integration/sales/test_quote_idor.py::test_quote_idor_matrix` |
| SCN-F2 | Revoking permission after proposal creation prevents execution | approvals | 1→3 | planned | `tests/integration/approvals/test_proposal_authority.py::test_revoked_permission_blocks_execution` |
| SCN-F3 | Altering an approved proposal requires fresh approval | approvals | 1 | planned | `tests/integration/approvals/test_proposal_authority.py::test_changed_content_invalidates_approval` |
| SCN-F4 | Concurrent numbering creates unique references | numbering | 1 | planned | `tests/integration/numbering/test_concurrent_numbering.py::test_unique_gapless_rollback_consumes_none` |
| SCN-G1 | Repeated import makes no unintended duplicates | imports | 2 | planned | `tests/integration/imports/test_reimport_idempotent.py::test_second_identical_import_is_noop` |
| SCN-G2 | Alias conflicts and orphans quarantined with row references | imports | 2 | planned | `tests/integration/imports/test_packaging_import.py::test_alias_conflict_quarantined_with_row_numbers` |
| SCN-G3 | Categories stay referentially valid | taxonomy | 2 | implemented | `tests/integration/catalogue/test_taxonomy.py::test_rename_alias_and_delete_or_reassign` |
| SCN-G4 | Search and thickness filters paginate correctly | catalogue search | 1→2 | planned | `tests/integration/catalogue/test_product_list.py::test_thickness_filter_paginates_before_limit` |
| SCN-G5 | Global search finds custom `product_name` | search | 2 | implemented | `tests/integration/search/test_custom_product_name.py::test_global_search_finds_custom_product_name` |
| SCN-G6 | Formula-like CSV text is inert | csv_safe | 1→2 | planned | `tests/unit/core/test_csv_safe.py::test_formula_cells_neutralised_numbers_kept` |
| SCN-H1 | Never overlaps, violates usable boundary or rotates grain-locked material | packer | 2 | implemented | `tests/unit/cutting/test_packer_properties.py::test_grain_locked_never_rotated` |
| SCN-H2 | Unfit pieces explicit; required/produced and area metrics reconcile | packer | 2 | implemented | `tests/unit/cutting/test_packer_properties.py::test_counts_reconcile` |
| SCN-H3 | Saved/reopened plans preserve inputs and results; oversize and overproduction have tested effects | plans | 2 | implemented | `tests/integration/cutting/test_plan_persistence.py::test_save_reopen_preserves_inputs_and_results` |
| SCN-I1 | Accept a quote once (idempotent conversion) | orders | 4 | implemented | `tests/integration/orders/test_quote_conversion.py::test_concurrent_and_retried_conversion_creates_one_order` |
| SCN-I2 | Reserve without overselling under concurrency | inventory | 4 | implemented | `tests/integration/inventory/test_reservation_concurrency.py::test_no_oversell_under_concurrency` |
| SCN-I3 | Fulfil partially; challan issue with exactly one movement | challans + inventory | 4 | implemented | `tests/integration/challans/test_issue_return_cancel.py::test_issue_posts_exactly_one_movement` |
| SCN-I4 | Partial return linked to its original line; duplicate events cannot post again; cancellation auditable | returns, replay | 4 | implemented | `tests/integration/flows/test_duplicate_events.py::test_replayed_outbox_events_have_single_effect` |
| SCN-J1 | Corrected voice transcript does not submit twice | voice | 3 | implemented | `tests/integration/voice/test_voice_api.py::test_same_utterance_id_one_turn`, `::test_correction_after_submission_is_a_new_turn_that_revises_the_draft` |
| SCN-J2 | Ambiguous customer/number prompts clarification | agents | 3 | in progress | `tests/integration/agents/test_scenario_c.py::test_agent_c_ambiguous_customer_asks_one_question`, `tests/evals/test_golden.py::test_golden_demo` (ambiguous customer; ambiguous number/line/field not yet) |
| SCN-J3 | Interrupt stops speech; mic denial and network loss keep text/draft paths; no offline stock commit shown as success | web voice | 3→4 | in progress | `e2e/scenarios/j-voice.spec.ts` (interrupt, mic denial, offline "Queued draft — not sent"); the offline stock-movement card waits for Slice 4 |
| SCN-K1 | Webhook signature rejection, replay, out-of-order status | channels | 3 | implemented | `tests/integration/channels/test_webhook.py::test_k_signature_rejection_writes_a_rejection_row_without_the_payload`, `::test_k_replay_of_a_delivery_has_one_business_effect`, `::test_previous_secret_is_accepted_during_rotation`, `tests/integration/channels/test_scenario_k.py::test_k_out_of_order_status_never_lowers_the_rank_and_failed_does_not_override_delivered`, `::test_status_before_the_send_response_matches_by_biz_opaque` |
| SCN-K2 | Employee unlink, expired approval, opt-out, closed messaging window | channels | 3 | implemented | `tests/integration/channels/test_scenario_k.py::test_k_employee_unlink_revokes_the_session_and_voids_armed_buttons`, `::test_k_button_for_an_expired_approval_does_nothing`, `::test_k_opt_out_confirms_and_blocks_proactive_messages_but_not_replies`, `::test_k_closed_window_blocks_with_a_reason`; `e2e/scenarios/k-whatsapp.spec.ts` |
| SCN-K3 | Duplicate delivery → one business effect; simulated delivery labelled; real status from provider evidence | channels | 3 | implemented | `tests/integration/channels/test_webhook.py::test_k_replay_of_a_delivery_has_one_business_effect`, `tests/integration/channels/test_scenario_k.py::test_k_simulated_statuses_are_labelled_and_reach_read_through_the_webhook`, `tests/integration/channels/test_live_mode.py::test_live_outbound_needs_the_flag_and_the_allowlist_and_statuses_are_real` |
| SCN-L1 | Quote/custom/challan duplication, notes, filters, histories, PDF/CSV/print, all field groups | legacy parity | 2 | implemented | `e2e/challans.spec.ts::quote_full_legacy_journey` |
| SCN-L2 | Unicode names and € ₹ export correctly; long documents paginate; PDFs omit internal notes and costs | documents | 1→2 | planned | `tests/integration/documents/test_pdf_unicode_pagination.py::test_long_document_paginates_with_glyphs` |
| SCN-M1 | Migration dry-run reconciles source counts and historical totals | migration | 5 | planned | `tests/integration/migration/test_dry_run.py::test_counts_reconcile_and_hashes_verified` |
| SCN-M2 | Rerun without duplication; no stock from legacy challans | migration | 5 | planned | `tests/integration/migration/test_rerun.py::test_verify_rerun_zero_inserts_zero_updates` |
| SCN-M3 | Restore rehearsal proves the backup path locally | backup | 5 | planned | `tests/integration/system/test_backup_restore_rehearsal.py::test_restore_rehearsal_roundtrip` |
| SCN-N1 | Desktop/tablet/mobile workflows support keyboard and touch | web | 1→6 | planned | `e2e/responsive/n-keyboard.spec.ts::today_search_quote_review_approve` |
| SCN-N2 | Understandable loading/empty/error states | web | 1→6 | planned | `e2e/responsive/n-states.spec.ts::states_render_real_copy_and_actions` |
| SCN-N3 | No dead buttons or fabricated operational metrics | web | 1→6 | planned | `e2e/responsive/n-no-dead-controls.spec.ts::every_control_named_and_effective` |
| SCN-N4 | Reduced motion honoured; showcase motion within budget | web motion system | 1→6 | planned | `e2e/responsive/n-reduced-motion.spec.ts::no_running_animations_when_reduced` |

---

Row counts (checkpoint 0): permissions 29 · modules 101 · field groups 151 · API 72 · UI 101 · business rules 14 ·
bugs 16 · security 8 · debt 8 · reuse/avoid/open questions 22 · PRD 9 · ERP gaps 16 · build-prompt items 74 ·
scenarios 56.
