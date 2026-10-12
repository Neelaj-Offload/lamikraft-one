> Design-workflow output (2026-10-12), kept as source material. Where it conflicts with docs/architecture/*, the architecture docs win.

# Catalogue, taxonomy, media, imports and legacy migration

# Catalogue, Taxonomy, Media, Imports and Legacy Migration: Subsystem Design

## 0. Scope and interfaces
**This subsystem owns:**
- the product master, with specification, packaging and dimension tables;
- taxonomy;
- product media, plus the shared object-storage core;
- catalogue search, facets, stats and completeness;
- lookup_reference;
- the import workbench for all 7 types;
- the shared CSV/XLSX safety utility;
- the demo catalogue reset;
- the migration framework, its catalogue adapters, and orchestration of the other modules' adapters.

**This subsystem consumes, but does not own:**
- **Pricing:**
  - `pricing.imports.preview_legacy_row / apply_legacy_row / revert_change`
  - `pricing.queries.active_price_exists(company)`, which returns a selectable
  - `pricing.service.display_prices(product_ids, actor)`
- **Identity:**
  - permission resolution
  - step-up re-auth
  - `ensure_historical_person`
  - `create_pending_invitation_user`
- **Platform:**
  - outbox, `jobs.enqueue`, audit log
  - the `company.is_demo` flag
  - UOM codes and aliases
  - the same-origin httpOnly session cookie
- **Parties:** `find_candidates(name, country, gstin)`.
- **Quotes, custom products, challans and optimiser:** each provides `legacy_import_*` functions with the semantics given in §11.

## 1. Layout
```
backend/app/core/storage/{protocol,s3,local_fs,sniff,models,service,gc}.py   # StoredObject, content-addressed
backend/app/core/exports/csv_safe.py      # write_csv, safe_text, xlsx_safe_cell (ONLY CSV writer)
backend/app/core/formatting/decimal.py    # format_decimal (no exponent)
backend/app/core/net/safe_fetch.py        # SSRF-safe allowlisted fetch (media ingest, migration)
backend/app/core/db/references.py         # FK-introspection reference counts
backend/app/modules/catalogue/{models,schemas,service,products,taxonomy,media,search,completeness,lookups,normalise,demo_reset,router,events,tools,policies}.py
backend/app/modules/imports/{models,schemas,service,engine,readers,headers,report,jobs,router,events,policies,tools}.py
backend/app/modules/imports/definitions/{category_taxonomy,products_master,pricing_master,packaging_master,specifications_master,media_master,lookup_reference}.py
backend/app/modules/migration/{__main__,cli,manifest,ejson,runner,models,parties,reconcile,report,router,policies}.py
backend/app/modules/migration/adapters/{users,taxonomy,products,specifications,packaging,pricing,media,lookups,grain_locks,custom_products,quotes,quote_lines,quote_revisions,challans,challan_lines,counters}.py
backend/tests/fixtures/legacy_export/      # fictional EJSON + CSV + manifest + media
apps/web/app/(app)/products/{page,new/page,[productKey]/[tab]/page,categories/page,completeness/page}.tsx
apps/web/app/(app)/settings/imports/{page,new/page,[jobId]/page,lookups/page}.tsx, settings/migration/..., settings/demo/page.tsx
apps/web/components/{catalogue,imports}/*; apps/web/e2e/{catalogue,imports}/*.spec.ts
docs/IMPORTS.md, docs/CATALOGUE_FIELDS.md (legacy field -> column map), docs/MIGRATION_RUNBOOK.md
```
Dependencies added: `pillow` (image verification and thumbnails) and `defusedxml`, which openpyxl recommends for untrusted XLSX. Readers do not use pandas, because its type inference is the source of the "120.0" corruption.

## 2. Legacy field inventory (all preserved; full map in docs/CATALOGUE_FIELDS.md)
- **Master** (`catalogue_product`): product_key, display_sku, product_name, brand, category, subcategory, product_type, variant_group, unit_of_sale, size_mm, decor_no, decor_name, decor_primary, decor_options, finish, shape, status, description, internal_remarks, source_design_no, source_shape_no, source_sheet, source_row, source_catalog_page, source_notes, created_at, updated_at.
- **Specifications** (`catalogue_product_specification` and `_dimension`): length_mm, width_mm, thickness_mm, thickness_text, size_mm, size_label, finish, material_type, groove_count, bowl_count, bowl_type, top_sheet, stand_material, stand_size_mm, board_size_mm, working_size_mm, type, plate1/2/3_size_mm, no_of_boards, handle_type, special_features, care_instructions, usage_notes.
- **Packaging:**
  - Alias pairs: carton_qty/master_carton_qty, unit_weight_g/unit_weight_kg, packing_type/unit_packing_type, inner_qty/inner_pack_qty.
  - Other fields: carton_length_cm, carton_width_cm, carton_height_cm, net_weight_kg, gross_weight_kg, cbm, packaging_notes, fragile_notes, packaging_status, notes.
- **Media:**
  - id, product_key, media_type (image|document|packaging_photo)
  - location fields: storage_path, file_url, drive_link, file_path
  - file_name/original_filename, content_type, size, is_primary, is_deleted, alt_text, uploaded_at, uploaded_by.
- **Taxonomy:** id, category, subcategory, display_order, is_active, product_count, description, source_catalog_page_start/end.
- **Lookup:** lookup_type, key_1, key_2, value_1, value_2, notes.
- **Pricing** (staged here; stored by pricing): product_key, price_type, currency, price, final_price, base_price(+label), addon_price(+label), price_basis, yield_qty_per_board, thickness_mm, moq, unit_of_sale, price_notes, valid_from, valid_to, display_sku, source_sheet, source_row.
- **Unknown or extra legacy columns** go to `source_extra jsonb` on the owning row. They are never dropped silently.

## 3. Tables
Every table has the standard columns (company_id, created/updated_at/by, version). Archival is used where noted.

- **catalogue_category**
  - Columns: id, name, name_key (casefold+trim), display_order int default 0, is_active bool NOT NULL DEFAULT true (fixes bug #7), description, source_catalog_page_start/end text, legacy_product_count int (provenance only; live counts are computed), origin enum(seed|ui|import|migration|migration_inferred).
  - Constraint: UNIQUE(company_id, name_key).
- **catalogue_subcategory**
  - Same columns, plus category_id FK RESTRICT.
  - Constraints: UNIQUE(category_id, name_key) and UNIQUE(id, category_id), which supports the composite FK.
- **catalogue_taxonomy_alias**
  - Columns: id, category_id, subcategory_id null, alias_key.
  - Former names are written on rename, so old spreadsheets still resolve, with a warning.
  - Constraint: unique per scope. The service rejects an alias that equals a live name.
- **catalogue_product**
  - Identity, text and status columns:
    - id, product_key text NOT NULL, display_sku NOT NULL, product_name NOT NULL, brand text
    - category_id FK NOT NULL; subcategory_id with composite FK (subcategory_id, category_id) → subcategory(id, category_id)
    - category_source, subcategory_source (original text), product_type, variant_group, unit_of_sale (UOM code; source kept in alias provenance)
    - decor_no text, decor_no_source text, decor_name, decor_primary, decor_options_text, decor_options text[]
    - finish, shape, status enum(active|inactive|under_development), description, internal_remarks
    - source_design_no, source_shape_no, source_sheet, source_row (text), source_catalog_page (text), source_notes, source_extra jsonb
    - origin enum(ui|import|migration|promotion|seed), origin_ref, search_text, archived_at/by.
  - Effective size: size_length_mm, size_width_mm, size_height_mm, size_diameter_mm NUMERIC(12,3), plus size_basis enum(master_size|spec_size|spec_length_width). These are denormalised from the dimension rows for filtering.
  - Constraints:
    - UNIQUE(company_id, product_key)
    - CHECK on trimmed non-empty product_key of ≤120 chars with no control characters
    - BEFORE UPDATE trigger that rejects changes to product_key.
  - Indexes:
    - (company_id, display_sku), (company_id, category_id, subcategory_id), (company_id, decor_no), (company_id, brand), (company_id, variant_group), (company_id, finish)
    - (company_id, updated_at DESC), partial (company_id, status) WHERE archived_at IS NULL
    - GIN trigram index on search_text, created only if `pg_trgm` is available (probed in the migration).
- **catalogue_product_dimension**
  - Columns: product_id FK CASCADE, kind enum(master_size, spec_size, board_size, working_size, stand_size, plate_1_size, plate_2_size, plate_3_size), source_field, source_text NOT NULL, length_mm/width_mm/height_mm/diameter_mm NUMERIC(12,3), source_unit, unit_inferred bool, parse_status enum(parsed|ambiguous|unparsed), parse_warnings text[].
  - Constraint: UNIQUE(product_id, kind).
- **catalogue_product_specification** (PK product_id, 1:1)
  - Columns: length_mm, width_mm NUMERIC(12,3) with *_source text; thickness_mm NUMERIC(8,3) with thickness_mm_source; thickness_text, size_label, spec_finish, material_type, groove_count, bowl_count, bowl_type, top_sheet, stand_material, spec_type (legacy `type`), no_of_boards, handle_type, special_features, care_instructions, usage_notes, source_extra.
  - Constraints: CHECK on positive dimensions and non-negative counts.
  - Index: (company_id, thickness_mm).
- **catalogue_product_packaging** (PK product_id)
  - Columns: carton_qty int, inner_qty int, unit_weight_g NUMERIC(14,3), packing_type text, carton_length/width/height_cm NUMERIC(10,2), net_weight_kg and gross_weight_kg NUMERIC(12,4), cbm NUMERIC(12,6), packaging_notes, fragile_notes, packaging_status, notes, alias_provenance jsonb, source_extra.
  - alias_provenance records, per canonical field, which source field won and the original raw values, e.g. `{"carton_qty":{"carton_qty":"24","master_carton_qty":"24.0"}}`.
  - Constraint: CHECK on positive quantities.
- **core_stored_object**
  - Columns: id, sha256 char(64), size_bytes, content_type (sniffed), backend, storage_key `c/{company}/sha256/{ab}/{sha}`, original_filename, purpose, has_thumbnail, created_by_run_id.
  - Constraint: UNIQUE(company_id, sha256).
- **catalogue_product_media**
  - Columns:
    - id, product_id FK, stored_object_id FK null, media_type enum, file_name, original_filename, content_type, size_bytes, alt_text, is_primary, sort_order
    - source_kind enum(upload|import_url|import_reference|migration), source_url_key (normalised), source_path
    - ingest_status enum(stored|pending|failed|external_only), ingest_error, source_catalog_page, legacy_media_id, uploaded_by/at, deleted_at/by, delete_reason.
  - Constraints and partial unique indexes:
    - UNIQUE(product_id) WHERE is_primary AND deleted_at IS NULL
    - CHECK(NOT is_primary OR media_type='image')
    - UNIQUE(product_id, stored_object_id) WHERE deleted_at IS NULL AND stored_object_id IS NOT NULL
    - UNIQUE(product_id, media_type, source_url_key) WHERE deleted_at IS NULL AND source_url_key IS NOT NULL.
- **catalogue_lookup_reference**
  - Columns: lookup_type, key_1, key_2 NOT NULL DEFAULT '', value_1, value_2, notes, source_extra.
  - Constraint: UNIQUE(company_id, lookup_type, key_1, key_2).
- **import_job**
  - Columns:
    - import_type enum(7), status, dataset enum(production|demo)
    - source_object_id, file_name, file_sha256, file_size, format, sheet_name, header_row, encoding, delimiter
    - mapping jsonb, options jsonb, validation_digest, counts jsonb, progress jsonb, parent_job_id
    - committed_at/by, rolled_back_at/by, rollback_mode, report_object_id.
  - Partial UNIQUE(company_id) WHERE status IN ('committing','rolling_back'), so a company runs one write job at a time.
- **import_staged_row**
  - Columns: job_id, row_number (physical sheet row), raw jsonb (`{col:{v,t,fmt}}`), raw_hash, normalized jsonb, natural_key, status enum(pending|valid|warning|rejected|quarantined|duplicate_identical|committed|unchanged|released), action enum(insert|update|unchanged), diff jsonb, target_id, target_version_seen, released_to_job_id.
  - Constraint: UNIQUE(job_id, row_number).
  - Indexes: (job_id, status) and (job_id, natural_key).
- **import_row_issue**
  - Columns: job_id, staged_row_id, row_number, column_original, field, code, severity enum(error|quarantine|warning|info), message, raw_value (truncated to 500 chars).
  - Issues are never capped.
  - Index: (job_id, severity, code).
- **import_change**
  - Columns: job_id, seq, entity_table, entity_id, op enum(insert|update), before jsonb, after jsonb, changed_fields text[], version_after.
  - Index: (entity_table, entity_id).
- **import_mapping_preset**
  - Columns: import_type, name, header_signature, mapping, options.
- **Migration tables:**
  - `migration_run`: mode dry_run|apply, target_label, manifest_sha256, code_version, options, status, summary jsonb, report_object_ids.
  - `migration_source_file`: collection, file, format, sha256, declared_count, parsed_count.
  - `migration_id_map`: source_system, collection, source_id, business_key, target_table, target_id, source_hash, version_after, status, first_run_id, last_run_id; UNIQUE(company_id, source_system, collection, source_id).
  - `migration_issue`: run_id, collection, source_id, severity, code, detail, source_doc jsonb. This is the quarantine.
  - `migration_party_candidate`: cluster_key, source refs, raw_name, raw_country, gstin, candidate_party_id, score, reason.
  - `migration_party_decision`: cluster_key, action link|create|leave_unlinked, party_id, decided_by/at. Decisions are reused on every rerun.

## 4. Normalisation (`catalogue/normalise.py`; pure and exhaustively unit-tested)
**4.1 Identifiers** (`normalise_identifier(cell, field_policy)`):
- XLSX string cells and JSON strings: trim outer whitespace only. Leading zeros are never touched.
- XLSX numeric cells and JSON numbers:
  - an integral value becomes an integer string;
  - if number_format is a pure zero pattern (e.g. `0000`), the value is zero-padded to that width, so `120` with `0000` gives "0120".
- Float artefact rule: text exactly matching `^\d+\.0+$` has the `.0+` suffix stripped. This means "120.0" becomes "120", "120" stays "120", and "12.50" is unchanged. The rule never uses `rstrip`.
  - It is on by default for decor_no, decor_primary and decor_options, and off for product_key. The setting is a toggle per mapping.
  - It emits a warning `DECOR_FLOAT_ARTEFACT_NORMALISED` and keeps `*_source`.
- Optional zero-pad width is set explicitly by an admin and is never inferred.
- product_key keys that differ only by case raise the warning `PRODUCT_KEY_CASE_VARIANT`.
- `format_decimal` uses `format(d.normalize(),'f')`, which avoids output like `1.2E+2`.

**4.2 Dimensions** (`parse_dimension(text, default_unit)` returns `{status, length, width, height, diameter, source_unit, unit_inferred, warnings}`):
1. Apply NFKC, lowercase, and convert ×, ✕, `*` and `X` to `x`.
2. Commas: if every comma group has exactly 3 digits, the commas are thousands separators. A single comma followed by 1–2 digits is a decimal point and raises a warning. Anything else is unparsed.
3. Units: mm, cm, m, in/inch/`"`, ft/`'`. A unit can be per number or trailing. With no unit, the field default applies (`*_mm` gives mm, `carton_*_cm` gives cm) and `unit_inferred=true`.
4. Patterns:
   - `N x N [x N]` gives L, W and H.
   - `ø|⌀|dia N` or `N dia` gives a diameter.
   - A single N is a thickness for thickness fields and **ambiguous** for size fields.
   - Ranges such as `300-350` are unparsed.
5. Convert exactly with Decimal: cm ×10, m ×1000, in ×25.4, ft ×304.8. L and W order is preserved.

The original text is always stored. Effective product size is taken from the parsed master_size, else the parsed spec_size, else spec length/width; `size_basis` records which was used.

**4.3 Packaging aliases** (`resolve_alias_group`):
- Pairs:
  - carton_qty ⇄ master_carton_qty (int)
  - inner_qty ⇄ inner_pack_qty (int)
  - packing_type ⇄ unit_packing_type (text, compared case- and whitespace-insensitively)
  - unit_weight_g ⇄ unit_weight_kg, where g = kg × 1000 exactly and the canonical value is unit_weight_g
- Integers: "24" and "24.0" are accepted as 24. "24.5" raises `NOT_INTEGER`.
- If one side is present, it is used.
- If both are present and equal after conversion and quantising to the canonical scale (0.001 g), the value is accepted.
- If both are present and they differ, the row is quarantined with `ALIAS_CONFLICT` and both raw values are listed. The system never guesses.
- Provenance is written to `alias_provenance`.
- Cross-checks that only produce warnings:
  - CBM differs by more than 2% from L×W×H/1e6
  - gross weight < net weight
  - inner_qty > carton_qty.

**4.4 Other value rules:**
- status: snake_case with label aliases ("In Dev" and "Under Development" both become under_development).
- bool: true/false/yes/no/y/n/1/0/active/inactive.
- Dates: ISO dates and Excel date cells are accepted directly. Slash dates follow the company date order (DMY default), which is shown at mapping. A column containing both D>12 and M>12 patterns raises `DATE_ORDER_INCONSISTENT`.
- unit_of_sale maps through UOM aliases. An unknown unit raises `UOM_UNKNOWN`.
- Currency symbols (€, ₹, $, £) map to ISO codes with a warning.
- MongoDB NaN is treated as blank, with an info note.

## 5. Services and invariants
- **Product writes** (`products.py`): `create_product`, `update_master`, `put_specification`, `put_packaging`, `archive`, `restore`, `apply_import_row`, `revert_change`.
  - The import handler and the UI handler share this code.
  - Every write:
    - checks `version` and returns 409 with the current state on mismatch;
    - normalises and validates;
    - recomputes dimension rows, effective size and search_text;
    - writes the audit diff and the outbox event in the same transaction.
- **Defaults on insert:** display_sku and product_name default to product_key. A category is required, and it must be active on create.
- **Subcategory:** it must belong to the category; the DB also enforces this.
- **Deletion:**
  - Products are archived, never deleted, through the UI.
  - Hard delete is possible only through import rollback or demo reset, and FK RESTRICT protects referenced rows in both cases.
- **Blank import cells:** `ignore` by default, meaning existing values are kept; `clear` is opt-in per mapping.

## 6. List, search, facets, stats, completeness (`search.py`, `completeness.py`)
- **List query:** `search_products(actor, filters, sort, page, page_size≤100)`.
  - It builds one WHERE clause shared by the items query and the `COUNT(*)` query.
  - Specification is LEFT JOINed. A thickness filter requires a spec row (fixes bug #6).
  - LIMIT/OFFSET is applied last.
  - Ordering is stable, with id as the final tie-break.
- **Filters:**
  - q, category_id, subcategory_id, status, brand, decor_no
  - thickness_mm, or a thickness min/max range
  - size (L×W canonical), finish, shape, variant_group, product_type, unit_of_sale
  - has_image, has_price, issue, updated_since, include_archived.
- **Search text:**
  - q is split into tokens; each token must match search_text (key, SKU, product_name, decor no/name, finish, variant, category/subcategory names, thickness variants such as "18"/"18mm", and size such as "300x200").
  - Matching is ILIKE with `\ % _` escaped and `ESCAPE '\'`. Regex is never used.
  - Ranking: exact key first, then exact SKU, then name prefix, then updated_at.
- **Facets:** each requested dimension is counted with all filters except its own (`facet_mode=exclude_self|narrow`; the configurator in quotes may choose narrow).
- **Stats:** counts by status, number without an active price (pricing subquery), number updated in the last 7 days, and per-category counts. **Recent:** the latest updated products, with change origin and actor.
- **Completeness:** each metric counts distinct non-archived products and links to `issue=` filters:
  - no_image
  - image_not_stored
  - no_primary_image
  - no_decor (decor_no and decor_primary both blank)
  - no_active_price
  - no_standard_export_eur_price (the MOQ basis)
  - no_carton_qty
  - no_specification
  - no_thickness
  - unparsed_dimensions
  - taxonomy_unresolved or category_inactive
  - media_ingest_failed
  - shared_display_sku (info).

## 7. Media (`media.py`, `core/storage`)
- **Storage adapters:** `ObjectStorage` protocol with `s3` (boto3, any S3-compatible endpoint) and `local_fs`. local_fs is explicitly dev-only; it is the default because the Docker daemon is off. The same contract suite runs against both, with S3 tested through moto.
- **Upload:** multipart `POST /products/{id}/media`.
  1. Check authorisation and company ownership of the product.
  2. Stream to a spool file, counting bytes. Exceeding the limit returns 413. Limits are configurable: images 15 MB, documents 25 MB.
  3. Compute SHA-256.
  4. Sniff magic bytes. Allowed formats:
     - JPEG, PNG, GIF, WEBP for image and packaging_photo
     - PDF, OOXML docx/xlsx (ZIP containing `[Content_Types].xml`; `vbaProject.bin` is rejected)
     - OLE2 doc/xls.
     The declared type and extension must agree with the sniffed family, or the upload is rejected with 415. SVG and HTML are never accepted.
  5. Images are checked with Pillow `verify()` under a pixel cap.
  6. Reuse an existing object with the same (company, sha256), or PUT a new one.
  7. Insert the link. The partial unique index blocks duplicates on the same product.
  8. Enqueue a thumbnail job (320px WEBP, EXIF stripped).
- **Primary image:** the first stored image becomes primary automatically. Deleting the primary promotes the next image by (sort_order, uploaded_at). Making an image primary is one transaction.
- **Downloads:** `GET /media/{id}/content` (attachment), `/preview` (inline; images and PDF only), and `/thumbnail`.
  - The server streams through `get_object`. Authentication is by session cookie only; `?auth=` and any query token are ignored.
  - Response headers: `X-Content-Type-Options: nosniff`, `Cache-Control: private`, ETag = sha256, RFC 5987 filename.
  - Requests for another company's media return 404 (no existence leak).
- **Soft delete and restore:** soft delete sets deleted_at and the reason. Objects are retained. Quote snapshots reference stored_object_id, so they remain renderable.
- **Ownership:** with `catalogue.media_manage` at scope own, a user can edit or delete only media they uploaded. At scope company, they can edit or delete any.
- **URL ingest** (`safe_fetch`):
  - https only, admin host allowlist
  - DNS-resolved IPs must not be private, loopback, link-local or multicast; this is rechecked on each of at most 3 redirects
  - timeouts, size limits, and the same sniffing as uploads
  - Drive share URLs are canonicalised to `gdrive:<id>` and a direct-download URL
  - an HTML response means `failed` with reason "not a direct file".
- **GC job:** deletes only storage keys that have no core_stored_object row and are older than 24 h. These are orphans from rolled-back transactions.

## 8. Taxonomy (`taxonomy.py`)
- **CRUD:** create defaults to active. Reorder sets display_order; ties sort by name. Activate/deactivate: an inactive category is hidden from pickers and filters, while existing products are unchanged. An inactive parent makes its children effectively inactive.
- **Rename:**
  - checks the version and name_key uniqueness (live names and aliases);
  - stores the old name as an alias;
  - recomputes search_text for affected products in the same transaction;
  - leaves quote and line snapshots untouched;
  - emits `catalogue.category.renamed`.
- **Delete:**
  1. `GET references` counts every FK pointing at the row via `core/db/references.py` introspection, giving per-table counts.
  2. If the count is non-zero and no target is given, the delete is refused with 409.
  3. With `reassign_to` and `expected_reference_counts`, one transaction:
     - locks the rows;
     - rechecks the counts and returns 409 if they changed;
     - runs registered reassign handlers (catalogue products and custom products);
     - verifies zero references, deletes, and writes audit and events.
  4. A referencing table without a handler blocks reassignment. That is the safe default.
- **Validation report:** products with an unresolved subcategory_source, products in inactive categories, and migration_inferred categories.
- **Legacy pair rows:** a row with a blank subcategory supplies the category's attributes. Otherwise the category is derived: display_order = min of its rows, is_active = any active. The derivation is reported.

## 9. Import workbench (`modules/imports`)
**9.1 Type definitions.** Each type declares FieldSpecs (type, required flag, aliases, normaliser), a natural key, dependencies and handlers. `*` marks a required field.
- **category_taxonomy:**
  - Key: (category, subcategory).
  - Fields: category*, subcategory, display_order, is_active, description, source_catalog_page_start/end, product_count (provenance).
  - No dependencies.
- **products_master:**
  - Key: product_key.
  - Fields: the §2 master fields; product_key* and category* are required.
  - Depends on taxonomy. An unknown category is quarantined as `CATEGORY_NOT_FOUND`. An unknown subcategory gives a warning, keeps subcategory_source, and flags the row for the taxonomy report.
- **pricing_master:**
  - Key: (product_key, price_type, currency).
  - Fields: the §2 pricing fields. The `price`/`final_price` alias pair: if they differ, the row is quarantined as `PRICE_AMBIGUOUS`.
  - A blank price_type or currency is quarantined unless the admin explicitly sets a default in the mapping. The legacy defaults (domestic/INR) are pre-filled but must be confirmed.
  - display_sku that does not match the product gives a warning.
  - Depends on products. Storage and history are handled through the pricing interface.
- **packaging_master:**
  - Key: product_key.
  - Fields: the four alias pairs (§4.3) plus the remaining packaging fields.
- **specifications_master:**
  - Key: product_key.
  - Fields: all spec fields. `type` maps to spec_type. Header normalisation produces plate_1_size_mm, which is aliased to plate1_size_mm.
- **media_master:**
  - Key: (product_key, media_type, normalised location).
  - Location aliases file_url | drive_link | file_path | storage_path: exactly one distinct value is allowed. Differing values are quarantined with `ALIAS_CONFLICT`.
  - file_name/original_filename: both are kept and file_name is displayed. A difference gives a warning.
  - A blank media_type is inferred from the file extension (image, else document) with a warning.
  - URL rows become `pending` media and are ingested by a job. Reference-only rows become `external_only` and are clearly labelled.
- **lookup_reference:**
  - Key: (lookup_type, key_1, key_2).

Documented legacy aliases are the four packaging pairs, price/final_price, the media location and filename groups, the defaults that set display_sku and product_name from product_key, and status snake_case. The only additions are aliases produced by the header normaliser, such as sub_category and plate_1_size_mm; docs/IMPORTS.md labels them separately.

**9.2 Header normalisation:** strip the BOM, NFKC, casefold, collapse every run of non-alphanumeric characters to `_`, then trim `_`. For example "Unit Weight (g)" becomes unit_weight_g. Headers that collide after normalisation raise `HEADER_COLLISION` and need explicit mapping.

**9.3 Parse job:**
1. Re-verify the file hash.
2. XLSX: zip-bomb guard (uncompressed size ≤200 MB, compression ratio ≤100), then openpyxl `read_only=True, data_only=True`. Choose the sheet and header row. A formula with no cached value raises `FORMULA_NO_VALUE`.
3. CSV: encoding is detected as utf-8-sig, then strict utf-8, then cp1252 with a warning, and can be overridden. Delimiter is sniffed from `, ; \t |`. All values are read as strings.
4. Limits: 50k rows, 200 columns, 10k characters per cell.
5. Persist the raw typed cells in bulk.
6. Return auto-mapping suggestions and a preview: first 20 rows, all columns, the original→normalised header table, natural keys that occur more than once with their row numbers, blank required columns, and any earlier job with the same sha256.

**9.4 Validate job** (all rows; every issue is kept):
1. Map the columns. Strip our own formula-guard prefix `'` when it precedes a dangerous character (round-trip), recording an info issue.
2. Normalise each field type (§4).
3. Resolve alias groups.
4. Apply required, range and cross-field rules.
5. Duplicate keys within the file:
   - identical normalised payloads: the first row is kept and the rest become `duplicate_identical`;
   - differing payloads: every occurrence is quarantined with `DUPLICATE_KEY_CONFLICT`.
6. Resolve dependencies against committed data, bulk-loaded. Missing references are quarantined as `ORPHAN_PRODUCT` or `CATEGORY_NOT_FOUND`.
7. Compute a field diff against the current entity, and record the action, target_id and target_version_seen.
8. Compute validation_digest.

Rows with errors are `rejected` and must be fixed in the source. Quarantined rows can be rechecked.

**9.5 Review:** counts of insert, update, unchanged, rejected and quarantined, plus paginated before/after diffs and the issues table (filter by severity, code and column). `report.csv` lists every issue: row number, original column, field, code, severity, message and value. Commit requires the job version and an explicit acknowledgement when rows are excluded. `strict` mode requires zero errors.

**9.6 Commit job** (batches of ≤500 rows in row order; taxonomy commits categories before subcategories). For each batch, in one transaction:
1. Lock the job.
2. Re-resolve dependencies. Failures are quarantined as `DEPENDENCY_CHANGED`.
3. Lock target rows. If the version is not target_version_seen, the row is quarantined as `TARGET_CHANGED_SINCE_REVIEW`. If an expected insert now exists, it is quarantined as `KEY_CREATED_CONCURRENTLY`.
4. Call the domain handler.
5. Write import_change, the staged-row status, outbox events (origin=import, job id) and audit.
6. Checkpoint progress.

A failing batch is retried up to 3 times, after which the job becomes `commit_failed`. It can be resumed; committed batches are idempotent because staged rows are marked inside the batch transaction. On completion the job emits `catalogue.import.committed` and enqueues media ingests. Unchanged rows produce no write, no version bump and no event.

**9.7 Re-import idempotency:** upsert by natural key with no-op on equal values; media is deduplicated by (product, type, URL key) and then by sha256. A same-file hash produces a warning, not a block.

**9.8 Quarantine recheck:** `POST /imports/{id}/quarantine/recheck` creates a child job from the quarantined rows' raw data and revalidates it against current data. For example, pricing orphans are released after products are imported. The parent rows are marked `released`.

**9.9 Rollback:**
- **Plan**, walking import_change in reverse:
  - entity gone: `already_removed`;
  - version ≠ version_after: `blocked: LATER_EDIT` (who and when, from audit);
  - an insert with FK references from anywhere: `blocked: REFERENCED` (per-table counts).
  The plan hash is computed over the items.
- **Execute**, in a single transaction:
  - recompute the plan, returning 409 if the hash differs;
  - `all` mode needs zero blocked items; `reversible_only` applies the safe subset;
  - updates restore only the import-changed fields and bump the version;
  - inserts are hard-deleted (dimension rows cascade; media links are removed and objects are left for GC);
  - the job becomes `rolled_back` or `partially_rolled_back`.
- Later business work is protected three ways: version checks, FK RESTRICT, and field-scoped restore.

**9.10 History:** jobs, mappings, options, file sha256, source objects (retention configurable, default kept), staged source rows, issues and changes are all durable. The list can be filtered by type, status and user.

**9.11 Demo reset:**
- Only for `company.is_demo=true`. The flag is set at seed and cannot be changed through any API.
- Requires `catalogue.demo_reset`, step-up re-authentication, and a preview that returns counts and a 5-minute token.
- The user must type a phrase containing the company name.
- Every delete SQL also asserts `is_demo`.
- The reset is refused if non-catalogue modules reference demo products, unless the platform's whole-workspace demo reset (per-module purge hooks) is used.
- The reset is audited.

**9.12 lookup_reference:** a read-only browser (filter by type and key), a safe CSV export, and an agent read tool. docs/IMPORTS.md documents it as reference-only data. It is not used in business rules until its semantics are confirmed.

## 10. CSV safety (`core/exports/csv_safe.py`)
- `safe_text`: if the first character, or the first character after leading spaces, is in `= + - @ \t \r \n ＝ ＋ － ＠`, prefix it with `'`. This follows OWASP guidance.
- `write_csv`: `QUOTE_ALL`, embedded quotes doubled, CRLF, UTF-8 BOM (for € and ₹ in Excel). Decimal and int are written through format_decimal without a prefix, so numeric negatives stay numeric. None is written as empty and dates as ISO.
- `xlsx_safe_cell` forces `data_type='s'`, so text is never written as a formula.
- A contract test fails if `csv.writer` or `csv.DictWriter` is used outside this module, or if the frontend creates `text/csv` blobs. Every CSV export in every module, including import reports and migration reports, goes through this utility.

## 11. Migration tooling (`modules/migration`; slice 5)
**Input:**
- An authorised export directory: `manifest.json` (exported_at, exporter, legacy commit; per collection: file, format, sha256, declared count) plus per-collection JSON, JSONL or CSV, and an optional `media/` folder.
- `ejson.py` decodes $oid, $date, $numberDouble/Int/Long/Decimal and NaN, without pymongo.
- A legacy media API token, if used, comes from an env var and is sent only as an Authorization header. It is never written to logs or query strings.

**CLI** (`python -m app.modules.migration`):
- `verify-export`: hashes, parse counts, duplicate source ids, schema drift (unknown fields go to source_extra and the report).
- `dry-run [--fresh] [--verify-rerun]`: loads into a scratch database (`MIGRATION_SCRATCH_DATABASE_URL`, created, Alembic head, platform seed without demo data).
  - Control tables (`migration_run`, issues, party candidates and decisions) live in the main DB, so reports and reviews are visible in the app.
  - With `--verify-rerun` the whole run is executed a second time and must produce 0 inserts and 0 updates.
- `apply --backup-id <verified backup>`: requires `migration.execute`. It uses the same code path against the main DB.
- `report`, `party-review export|import`, `media-ingest`.

**Runner:** topological adapter order:
1. users
2. taxonomy
3. products
4. specifications
5. packaging
6. pricing
7. media
8. lookups
9. grain_locks
10. custom_products
11. quotes
12. quote_lines
13. quote_revisions
14. challans
15. challan_lines
16. counters
17. party candidates

Each adapter implements `source_id`, `validate`, `transform` (resolving references through id_map), `upsert` (owning module service in migration mode: `origin=migration`, notifications suppressed, events flagged so briefings ignore bulk loads), and `reconcile`. Work runs in batches of 500.

**Rerun rules:**
- mapped and source_hash unchanged: `unchanged`;
- source changed and target version == version_after: update;
- source changed and target edited: quarantined as `TARGET_MODIFIED_AFTER_MIGRATION`;
- no mapping but the business key already exists: quarantined as `BUSINESS_KEY_EXISTS_UNMAPPED`. It is never merged silently.

**Entity rules:**
- **Taxonomy/products:** categories that products reference but that are missing from the taxonomy (bug #16) are created as `migration_inferred`, inactive, and listed for review. Decor and dimension provenance is kept. Numeric decor identifiers that may have lost leading zeros are listed; they are never auto-padded.
- **Pricing:**
  - duplicate (product, type, currency) rows: identical rows are collapsed and reported; differing rows are quarantined as `PRICE_AMBIGUOUS` (bug #15);
  - unknown or missing currency, or price ≤ 0, is quarantined.
- **Media:**
  - storage_path objects come from the export folder or from the legacy API with a header token;
  - URLs go through `safe_fetch` under a dry-run storage prefix;
  - every object gets a sha256 and is deduplicated;
  - deleted legacy media is migrated as soft-deleted metadata;
  - inaccessible items keep `failed` with a reason and are reported.
- **Users:**
  - password_hash is never read;
  - active users become `pending_invitation`, and invitations are sent only by an explicit post-cutover admin action;
  - inactive users are preserved as inactive;
  - creators referenced in records but missing from the export become `historical` people with no login, named from created_by_name;
  - an invalid role is quarantined, and the person is still kept for attribution;
  - the 14 legacy overrides map to new grants and revokes;
  - emails that differ only by case are quarantined as `DUPLICATE_IDENTITY`.
- **Quotes:**
  - quote_number, versions, status history, created_by_name, assigned user and internal notes are preserved;
  - issued quotes (sent, revised, won, lost) are stored with their legacy lines and totals exactly (Decimal from `repr(float)`);
  - revision snapshots are kept verbatim;
  - the new engine recomputes totals for the report only;
  - discrepancy classes, reported at half a minor unit: `LINE_TOTAL_MISMATCH`, `HEADER_TOTAL_MISMATCH`, `DUPLICATE_TOTAL_FIELD` (bug #2), `SURCHARGE_RULE_DIVERGENCE` (bug #3), `TOTAL_LINES_MISMATCH`;
  - new revisions use the corrected engine.
- **Custom products:** the CP code is preserved. Costing goes to protected costing with EUR currency and provenance "legacy form label".
- **Challans:** challans and their lines are preserved with `document_only=true`. They post no inventory movements; the inventory module excludes document-only challans.
- **Grain locks:** decor text goes through the identifier rules.
- **Counters:** LK-QT, DC and CP counters are set above the maximum migrated number, per policy (per year, or global). Numbers are never reused.
- **Party candidates:**
  - names are casefolded, punctuation and legal suffixes (gmbh, ltd, pvt, llc, bv, srl, sa, co) are removed, and names are clustered by (normalised name, country); an exact GSTIN match is a strong signal;
  - trigram or difflib similarity of at least 0.85 marks a possible match;
  - the review UI offers link, create or leave unlinked;
  - nothing is ever merged automatically; `party_id` stays null until a decision is made, and the text snapshot is kept.
- **Skipped (reported):** search_history, revision_history, and the legacy `products` collection.

**Reconciliation report** (JSON, safe CSV and Markdown; costing figures appear only in a restricted section):
- **Per collection:** declared count = parsed count = migrated (insert, update, unchanged) + quarantined + skipped.
- **Totals by currency:**
  - quote total_amount and line_total: legacy vs stored, which must be equal, and vs recomputed, where differences are listed;
  - prices by (type, currency).
- **Links:** lines→quotes, lines→products/custom products, pricing/specs/packaging/media→products, revisions→quotes, challan lines→challans, every created_by/assigned_to→user or historical person, products→categories.
- **Files:** manifest hashes, media counts by status, total bytes, collapsed duplicates, and the list of inaccessible items.
- **Stock:** inventory movement delta = 0.
- **Numbering:** maximum legacy number vs counter value.

**Cutover and rollback** (docs/MIGRATION_RUNBOOK.md):
1. **T-14d:** iterate dry-runs until no blocking issues remain. Complete the party review and the media rehearsal.
2. **Restore rehearsal:** pg_dump -Fc plus a storage manifest, then pg_restore into a scratch database, then verify counts, checksums and object hashes.
3. **T-1:** freeze legacy writes (operator procedure). Take the final authorised export and manifest.
4. **Cutover:** verified backup, `apply`, reconciliation gate (zero unexplained differences), smoke tests, set counters, then send invitations explicitly.
5. **Rollback before go-live:** restore the pre-cutover dump, delete objects whose `created_by_run_id` matches this run, and unfreeze legacy, which remains the source of truth.
6. **After go-live:** forward-fix only. A disaster restore requires re-entering post-cutover transactions, listed from the audit log.

## 12. API (prefix `/api`; responses are typed Pydantic models, which generate the OpenAPI spec and the TS client)
- **Catalogue (`/catalogue`):**
  - Products:
    - `GET /products` (filters §6, page, page_size, sort)
    - `GET /products/facets`
    - `GET /products/stats`
    - `GET /products/recent`
    - `GET /products/lookup?key=`
    - `GET /products/{id}`, which returns master, spec, packaging, dimensions, media, taxonomy, completeness and the price summary from pricing
    - `POST /products`, `PATCH /products/{id}`
    - `PUT /products/{id}/specification`, `PUT /products/{id}/packaging`
    - `POST /products/{id}/archive|restore`
    - `GET /products/{id}/history`
    - `GET /products/export.csv`, which is import-compatible
    - `POST /dimensions/parse`
  - Media:
    - `GET|POST /products/{id}/media`
    - `PATCH /media/{id}`
    - `POST /media/{id}/make-primary|restore`
    - `DELETE /media/{id}` (soft)
    - `GET /media/{id}/content|preview|thumbnail`
  - Taxonomy:
    - `GET /categories?include_inactive`
    - `POST /categories`, `PATCH /categories/{id}`
    - `POST /categories/{id}/subcategories`, `PATCH /subcategories/{id}`
    - `GET /categories/{id}/references`, `POST /categories/{id}/delete`
    - the same references and delete endpoints for subcategories
    - `POST /categories/reorder`
    - `GET /taxonomy/validation`
  - Completeness and lookups:
    - `GET /completeness`
    - `GET /lookups`, `GET /lookups/types`, `GET /lookups/export.csv`
- **Imports (`/imports`):**
  - `GET /imports/types`, `GET /imports/types/{t}/template.csv|.xlsx`
  - `POST /imports` (multipart), `GET /imports`, `GET /imports/{id}`
  - `GET /imports/{id}/preview`, `PUT /imports/{id}/settings`, `PUT /imports/{id}/mapping`
  - `POST /imports/{id}/validate`
  - `GET /imports/{id}/issues`, `GET /imports/{id}/issues/report.csv`
  - `GET /imports/{id}/changes`
  - `POST /imports/{id}/commit|cancel`
  - `GET /imports/{id}/quarantine`, `POST /imports/{id}/quarantine/recheck`
  - `POST /imports/{id}/rollback-plan`, `POST /imports/{id}/rollback`
  - `GET /imports/{id}/source`
  - `GET|POST|DELETE /imports/mapping-presets`
  - `GET /imports/demo-reset/preview`, `POST /imports/demo-reset`
- **Migration (`/migration`):**
  - `GET /migration/runs`, `GET /migration/runs/{id}`
  - `GET /migration/runs/{id}/issues`, `GET /migration/runs/{id}/report.csv`
  - `GET /migration/party-candidates`, `POST /migration/party-candidates/{cluster}/decision`
- **Global search provider:** product results come from the same `search_products` with a limit.

## 13. Events (outbox; payloads carry id, business key, version, origin, actor, and import_job_id/run_id)
- **Emitted:**
  - `catalogue.product.created|updated|archived|restored|deleted`; `updated` lists changed_groups (master, specification, packaging, dimensions)
  - `catalogue.media.uploaded|deleted|restored|primary_changed|ingest_failed`
  - `catalogue.category.created|renamed|updated|deleted`, `catalogue.subcategory.*`, `catalogue.taxonomy.reassigned`
  - `catalogue.import.uploaded|validated|committed|failed|rolled_back`; committed includes the quarantine count
  - `catalogue.demo.reset`
  - `migration.run.completed|failed`
- **Consumed:** none required. The tasks/briefing module consumes the import, ingest and migration events for the admin briefing.

## 14. Permissions
- **Catalogue:**
  - `catalogue.view`, the legacy view_products
  - `catalogue.edit`, the legacy edit_products
  - `catalogue.archive`
  - `catalogue.media_manage`, with scope own or company
  - `catalogue.taxonomy_manage`, the legacy manage_categories
  - `catalogue.export`
  - `catalogue.lookup_view`
  - `catalogue.demo_reset`
- **Imports:**
  - `catalogue.import`, the legacy import_data, with scope own or company
  - `catalogue.import_rollback`
- **Migration:**
  - `migration.dry_run`
  - `migration.execute`, which requires admin MFA
- Prices and costing remain governed by pricing permissions. Catalogue never returns costing.

## 15. Frontend
- **Product pages:**
  - The Products subnav has Catalogue, Taxonomy, Price lists (pricing) and Completeness.
  - The list has URL-synced filters, facet sidebar/drawer, server pagination with page sizes 25/50/100, totals, and a mobile card view.
  - Detail tabs are deep-linked at `/products/{key}/{overview|specifications|packaging|pricing|media|history}`.
  - Forms:
    - the create form is a full page with sections (Master, Taxonomy, Decor, Specifications, Packaging);
    - each tab has an inline edit form;
    - field errors come from the server's 422 response; 409 shows a conflict view;
    - `DimensionInput` shows the parsed preview;
    - the packaging form has a g/kg selector with recorded provenance;
    - a read-only Provenance disclosure shows alias and source values.
  - Media gallery: a drop zone with a keyboard button alternative, primary toggle, preview dialog, download, delete with a reason, and restore.
- **Imports (Settings > Imports):**
  - The stepper runs: type (with dependency status) → upload → preview → mapping → validate → review changes → commit progress → result.
  - Other screens: history, rollback plan dialog, lookups browser, migration runs and party review, and demo reset (demo company only).

## 16. Build-order slices
- **Slice 1:**
  - all catalogue, taxonomy and dimension tables with full columns
  - normalise.py, search service, read-only list and detail, `resolve_product`
  - fictional seed (oak tray, carton qty 24)
  - csv_safe and format_decimal
  - `catalogue.view`
- **Slice 2:**
  - forms and archive
  - taxonomy operations
  - storage and media
  - facets, stats, recent and completeness
  - lookups and product export
  - the full import workbench including rollback and quarantine recheck
  - templates, demo reset, search provider
  - e2e tests
- **Slice 3:** agent read tools (`search_products`, `resolve_product`, `get_product`, `get_catalogue_completeness`, `get_import_job_summary`) and channel reuse.
- **Slice 4:**
  - UOM FK hardening
  - reference counting automatically covers new inventory and production FKs
  - `get_packaging_snapshot` for logistics
- **Slice 5:** migration tooling, party review, media ingest, runbook and restore rehearsal.
- **Slice 6:** G/M/L acceptance runs, isolation checks on every catalogue, media and import endpoint, and visual QA.

## 17. Future scope (explicit)
- A decor master with swatches and a grain registry. Decor identifiers stay as text for now.
- A brand FK to the company brand registry.
- ZIP media bundles for reference-only media rows.
- A malware-scanning adapter.
- A retention purge for soft-deleted media.
- Multi-file import bundles with cross-file staged dependencies.
- lookup_reference as value dictionaries, once its semantics are confirmed.
- Agent write tools through proposals.
- Per-category attribute schemas.
- XLSX issue reports.
- tsvector ranking.
- Delta sync during long freezes.


## Decisions
- **Product media downloads are streamed through the backend and authenticated only by the same-origin httpOnly session cookie; there are no presigned URLs and no query tokens.** — Requirement 1 forbids tokens in download query strings, and a presigned S3 URL is a bearer capability in the query string. Streaming through the backend also enforces per-request permission, company isolation and the ETag/nosniff headers. The cost is backend bandwidth, which is acceptable for catalogue-sized files.
- **Storage is content-addressed: core_stored_object is UNIQUE(company_id, sha256), and catalogue_product_media is a separate link table with partial unique indexes.** — This gives checksum deduplication and idempotent re-import and migration for free. Quote snapshots can reference immutable objects, so soft-deleting a product image never breaks historical documents.
- **Local development uses a local_fs storage adapter, labelled as dev-only. The s3 adapter (boto3) targets any S3-compatible endpoint, and one contract suite runs against both, using moto for S3.** — The Docker daemon is not running and no S3 server is installed. A shared contract suite keeps the two adapters behaviourally identical without depending on an unavailable service.
- **Composite dimension strings are kept verbatim in a catalogue_product_dimension child table with parsed canonical mm values. An effective size (with its basis) is denormalised onto the product; thickness stays canonical on the specification table.** — This preserves every legacy string as provenance and gives explicit numeric units. Size and thickness filtering is SQL-indexable before pagination, without adding dozens of columns to the product table.
- **Identifier normalisation is type-aware. Text keeps leading zeros. Numeric cells become integer strings, or are zero-padded from the XLSX number_format. The '^\d+\.0+$' artefact rule is a per-field toggle that is on for decor fields, warns, and keeps the *_source value.** — This fixes bug #5 (rstrip corruption) without corrupting '120'. It handles legacy pandas float artefacts explicitly and stays reversible, rather than silently guessing.
- **Packaging alias pairs resolve to one canonical column. When both sides are present and disagree after exact Decimal conversion, the row is quarantined. Original values are kept in alias_provenance.** — The migration section says not to guess when aliases disagree. Fixing bug #9 needs a single source of truth for carton_qty, which MOQ, the configurator and logistics read.
- **Taxonomy uses separate category and subcategory tables. Products reference both through FKs, with a composite FK guaranteeing that the subcategory belongs to the category. Renames keep the old name as an import alias. Deletion is blocked by FK-introspected reference counts unless the admin chooses an explicit reassignment with expected counts.** — This fixes bugs #7 and #16. Referential validity is enforced in the database, not only in the UI. Renames are safe for legacy spreadsheets, and accidental mass reassignment is prevented.
- **Import rows end as either rejected (a data error; fix the source) or quarantined (orphan, alias conflict, duplicate key conflict, ambiguous price, changed dependency or target). Quarantined rows can be rechecked into a child job.** — Orphans and conflicts are often resolved by later imports or decisions. Separating the two avoids forcing a full re-upload while keeping invalid data out.
- **Commits run in batches of 500 rows. Each batch transaction marks its staged rows, so the commit can resume and is idempotent. Rollback runs in one transaction with a plan hash, and supports an explicit 'all' or 'reversible_only' mode.** — The prompt requires bounded batches. A single-transaction rollback makes 'all' truly all-or-nothing within the bounded import size of 50k rows.
- **Rollback never erases later work. Three guards enforce this: entity version must equal version_after, FK RESTRICT (counted through introspection) must find no references, and only the fields the import changed are restored.** — Using database FKs plus versions as the authority avoids a registry that a future module could forget to update. New inventory, production and quote references are covered automatically.
- **Blank import cells default to 'ignore' (keep the existing value). Pricing rows with a blank currency or price_type are quarantined unless the admin explicitly confirms a default in the mapping.** — Legacy defaulted pricing silently to INR/domestic, which is the kind of ambiguous pricing the prompt says to quarantine. Treating blank as ignore prevents accidental data wipes.
- **Readers use the csv module (all values as strings) and openpyxl read_only/data_only with defusedxml, plus a zip-bomb guard. pandas is not used.** — pandas type inference caused the '120.0' artefacts and leading-zero loss. openpyxl exposes data_type and number_format in read-only mode, and its docs recommend defusedxml for untrusted files.
- **There is one shared CSV writer (core/exports/csv_safe.py) using the OWASP prefix-quote rule (= + - @ TAB CR LF and full-width variants), QUOTE_ALL, CRLF and a UTF-8 BOM. A contract test forbids any other CSV writer. Imports strip our own guard prefix on round-trip.** — This satisfies 'all CSV outputs' structurally rather than by convention. Exported € and ₹ render in Excel, and an export can be re-imported without accumulating apostrophes.
- **Migration dry-runs load into a dedicated scratch database migrated to Alembic head, using the same adapters and services as apply. Control tables (runs, issues, party decisions) live in the main database.** — This gives full-fidelity constraint checking and proves reruns (the second pass must produce 0 inserts and 0 updates) without touching production. Admins review reports and party links in the app, and decisions persist across reruns.
- **Migration keeps legacy created_at/updated_at in the standard columns. id_map records migrated_at, source_hash and version_after. A business key that exists without a mapping is quarantined, never merged.** — Historical dates stay truthful (for example, quote dates). Rerun and update semantics are deterministic, and duplicate identities are surfaced as the prompt requires.
- **Products referenced by legacy data whose category is missing from the taxonomy are migrated under inactive 'migration_inferred' categories listed for review, while the workbench import quarantines CATEGORY_NOT_FOUND.** — Migration must preserve every existing product, and the bug #16 non-cascade made such orphans possible. Day-to-day imports still enforce taxonomy-first discipline.
- **Demo reset is allowed only for companies with is_demo=true, which is set at seed and immutable through the API. It requires a permission, step-up re-authentication, a preview token and a typed phrase, and every delete statement also asserts is_demo.** — This meets 'isolated demo dataset with scoped admin confirmation' with defence in depth, so the reset can never become a production wipe.
- **lookup_reference is preserved in its own table, with a read-only browser, a safe CSV export and an agent read tool. It is documented as reference-only.** — The legacy semantics are unknown. A documented export and use path satisfies the requirement without inventing business rules that consume it.
- **Search uses tokenised ILIKE over a maintained search_text, with escaped wildcards, ordered by exact key, then exact SKU, then name prefix. The trigram GIN index is created only if pg_trgm is available.** — This removes the regex injection and ReDoS risks. It works on pgserver even if contrib is missing, and catalogue size makes a sequential fallback acceptable.

## Risks
- The real shape of the legacy data is unknown, because the spec is not a dump. Unexpected fields, types or NaN patterns may appear. Mitigations: source_extra preservation, a schema-drift report in verify-export, and tolerant EJSON decoding. Real migration is blocked until authorised exports are supplied.
- Media downloads depend on the platform providing same-origin httpOnly session-cookie auth, because <img> and <iframe> cannot send bearer headers. If the platform chooses in-memory bearer tokens, previews need a fetch-then-blob approach, and thumbnails in lists become costlier.
- pgserver (PostgreSQL 16.2, Python ≤3.12) documents pgvector but not pg_trgm or pg_dump/pg_restore. The trigram index is guarded by an availability probe. If pg_dump is missing, the restore-rehearsal test needs PATH binaries; in CI it must fail loudly rather than skip.
- Legacy Google Drive or external media links may require sign-in or virus-scan confirmation pages. The expected outcome is a non-trivial number of 'failed' ingests that need manual export. The report lists them, and nothing is silently dropped.
- The float-artefact rule could normalise a decor identifier that is legitimately '120.0'. Mitigations: a per-field toggle, a warning on every normalisation, and the *_source column, which allows audit and reversal.
- Rollback safety relies on every module referencing products, categories and media through real FKs with ON DELETE RESTRICT. A module that stores product references only inside JSON snapshots without an FK would not block rollback. A contract test must assert that snapshot-bearing tables (for example quote lines) also carry the FK.
- Product keys containing '/', '%', '#' or other special characters may break Next.js dynamic segments. The API addresses products by UUID and looks up keys through a query parameter. An e2e test with such keys must pass, or the frontend falls back to an id-based route.
- Import scale: 50k rows with jsonb staging and per-row diffs on Windows with pgserver may be slow. Mitigations: bulk loads, chunked IN queries, batch commits and progress reporting. The limits are configurable.
- There are cross-subsystem contract dependencies: the pricing import, preview and revert functions; identity's historical-person and invitation functions; parties' candidate search; and the quotes, custom products and challans legacy_import adapters. Divergent interpretations would break migration reconciliation. These need contract tests owned jointly.
- Date-order and decimal-comma ambiguity in legacy spreadsheets. The defaults (DMY dates, and comma rules that warn) may misread unusual files. Mixed-order columns are rejected rather than guessed.
- Pillow image decoding is an attack surface. Mitigations: keep Pillow updated, enforce a pixel cap, verify() before thumbnailing, and never serve thumbnails generated from unverified files.

## Acceptance tests
- [G / integration] test_import_products_master_twice_is_noop: second identical import yields 0 inserts/0 updates, all rows 'unchanged', no version bumps, no outbox events
- [G / integration] test_import_media_master_twice_no_duplicate_media: same URLs re-imported create no new catalogue_product_media rows; ingest of identical bytes reuses one core_stored_object (sha256) and partial unique index holds
- [G / integration] test_packaging_alias_conflict_quarantined_with_row_numbers: carton_qty=24 vs master_carton_qty=12 and unit_weight_g=450 vs unit_weight_kg=0.5 produce ALIAS_CONFLICT issues with correct sheet row numbers and both raw values; consistent pairs (450 g / 0.45 kg) commit with alias_provenance
- [G / integration] test_orphan_rows_quarantined_then_released_by_recheck: pricing/packaging/spec rows for unknown product_key are quarantined (not written); after products import, quarantine/recheck child job commits them exactly once
- [G / integration] test_products_require_taxonomy_first: products with unknown category quarantined CATEGORY_NOT_FOUND; unknown subcategory imports with warning and appears in taxonomy validation
- [G / integration] test_in_file_duplicate_keys: identical duplicates -> first kept, others duplicate_identical; differing duplicates -> all DUPLICATE_KEY_CONFLICT; preview lists duplicate keys with row numbers
- [G / integration] test_all_errors_reported_uncapped_and_report_csv: 250 invalid rows produce >=250 issues and report.csv contains every row number, column and code
- [G / integration] test_commit_batches_resume_after_failure: injected failure in batch 3 leaves batches 1-2 committed, job commit_failed; resume completes without duplicates
- [G / integration] test_target_changed_since_review_not_overwritten: product edited in UI between validate and commit is quarantined TARGET_CHANGED_SINCE_REVIEW and keeps the UI edit
- [G / integration] test_rollback_unreferenced_import_restores_before_state and test_rollback_blocked_when_referenced_or_later_edited: quote line FK reference or later version blocks 'all'; 'reversible_only' leaves later work intact
- [G / integration] test_blank_cells_ignore_vs_clear_policy
- [G / integration] test_taxonomy_referential_integrity: created category active by default (bug #7); delete blocked with per-table reference counts; reassign with expected counts then delete; rename updates product search and old name resolves via alias on import; composite FK rejects subcategory of another category
- [G / integration] test_thickness_filter_paginates_before_limit: 120 products, 30 with thickness 18 interleaved, page_size 10 -> total=30, 3 full pages, no product without specs included (bug #6)
- [G / integration] test_search_escapes_wildcards_and_regex: q in ['.*', '%', '_', '(a+)+$'] matches literally, no error, no ReDoS; product_name tokens match
- [G / contract] test_global_search_finds_custom_product_name: catalogue and custom-product search providers return a custom product by product_name (contract with custom products module)
- [G / unit] test_csv_safe_cells: '=1+1', '+1', '-1+2', '@SUM(A1)', '\t=1', '\r=1', '\n=1', ' =1', fullwidth '＝1' are prefixed with an apostrophe; Decimal(-5) stays numeric; embedded quotes doubled; BOM present
- [G / unit] test_xlsx_safe_cell_never_formula: openpyxl read-back of exported '=HYPERLINK(...)' has data_type 's'
- [G / contract] test_no_csv_writer_outside_csv_safe: static scan of backend/app forbids csv.writer/DictWriter outside core/exports/csv_safe.py and apps/web forbids text/csv Blob creation
- [G / integration] test_formula_guard_round_trip: exported product named '=Tray' re-imports as '=Tray' (guard prefix stripped with info issue), not "'=Tray"
- [G / unit] test_header_normalisation_and_aliases: 'Product Key', ' PRODUCT-KEY ', 'Unit Weight (g)', 'Plate 1 Size (mm)', BOM; collisions raise HEADER_COLLISION
- [G / integration] test_lookup_reference_import_browse_export: upsert by (lookup_type,key_1,key_2) idempotent; export CSV safe
- [G / integration] test_demo_reset_guarded: refused for non-demo company even with permission; requires preview token, typed phrase and step-up; only demo company rows removed
- [G / e2e] e2e imports/workbench.spec.ts: taxonomy -> products -> packaging with alias conflict; preview, mapping, issues filter, report download, commit; re-import shows all unchanged; rollback plan dialog
- [G / e2e] e2e catalogue/product-list.spec.ts: thickness + category filters with paging and URL deep links survive reload; keyboard operable; mobile card view
- [L / unit] test_normalise_identifier: '120'->'120', '120.0'->'120' (+warning, toggle off keeps), numeric 120.0->'120', '0120' kept, XLSX 120 with format '0000'->'0120', '12.50' unchanged, format_decimal never emits exponent
- [L / unit] test_parse_dimension: '300 x 200 mm', '300X200', '30 x 20 cm', '12" x 8"'->304.8x203.2, 'Ø 300', '2440*1220*18', '2,440 x 1,220', '2,5 mm' (warning), '300-350' unparsed, single value ambiguous for size
- [L / integration] test_product_all_field_groups_round_trip: every legacy master/spec/packaging/media/taxonomy field survives create -> read -> CSV export -> import with provenance columns intact
- [L / integration] test_product_key_immutable_api_and_db_trigger and test_optimistic_version_conflict_returns_409
- [L / integration] test_completeness_metrics_per_product: each metric counts distinct non-archived products per documented definition (no per-row MOQ counting)
- [L / unit] test_media_upload_validation: magic-byte sniffing accepts jpg/png/gif/webp/pdf/docx/xlsx/ole; rejects svg, html, extension mismatch, docm with vbaProject, oversize (413), decompression bomb
- [L / integration] test_media_download_authz: cross-company id -> 404, no permission -> 403, ?auth= query ignored, Content-Disposition RFC 5987 Unicode filename, nosniff, ETag=sha256
- [L / integration] test_media_primary_rules_and_soft_delete_restore: single primary per product enforced; auto-primary first image; deleting primary promotes next; restore works; own-scope user cannot delete others' uploads
- [L / integration] test_product_export_csv_unicode: names with Devanagari/umlauts and € ₹ in remarks export intact with BOM
- [L / e2e] e2e catalogue/product-form.spec.ts and media.spec.ts: create product with all sections, server field errors shown, dimension parse preview, packaging g/kg provenance, upload via button and drop, preview, download, delete/restore, deep-linked tabs incl. product_key with '/', space and unicode
- [M / integration] test_migration_dry_run_reconciles_counts: for every fixture collection declared=parsed=migrated+quarantined+skipped and manifest hashes verified
- [M / integration] test_migration_totals_by_currency_and_discrepancies: stored legacy quote/line totals equal source sums per currency exactly; fixture quotes trigger DUPLICATE_TOTAL_FIELD, LINE_TOTAL_MISMATCH and SURCHARGE_RULE_DIVERGENCE without altering stored snapshots
- [M / integration] test_migration_rerun_no_duplication: --verify-rerun second pass yields 0 inserts/0 updates; changed source updates untouched target; edited target quarantined TARGET_MODIFIED_AFTER_MIGRATION; unmapped existing business key quarantined
- [M / integration] test_migration_challans_document_only_no_stock: all challans document_only, inventory movement count delta = 0, DC counters above max per year
- [M / integration] test_migration_users_invitation_and_attribution: no password_hash persisted, active users pending_invitation, inactive preserved, deleted creators become historical people, invalid role quarantined but person kept
- [M / integration] test_migration_party_candidates_never_auto_merge: 'Nordhaus GmbH' and 'NORDHAUS gmbh.' cluster into one candidate; quote.party_id stays null until decision; decision reused on rerun
- [M / integration] test_migration_media_checksums_and_inaccessible: httpx MockTransport serves files and a 403/HTML page; sha256 recorded, duplicates collapsed, inaccessible listed, private-IP redirect blocked
- [M / integration] test_migration_pricing_ambiguity_quarantined and test_inferred_categories_listed: conflicting duplicate price rows quarantined PRICE_AMBIGUOUS; missing taxonomy categories created inactive migration_inferred and reported
- [M / unit] test_ejson_decode: $oid, $date (ISO and numberLong), $numberDecimal, $numberDouble NaN->None with note
- [M / integration] test_restore_rehearsal_roundtrip: pg_dump -Fc of migrated fixture DB restored into fresh DB; row counts, product_key hash list, quote totals by currency and stored object hashes match
- [A / integration] test_catalogue_endpoints_company_isolation: product, media, import job, issues report and migration report ids from another company return 404; own-scope importer cannot read another user's job or source file
