# Lamikraft / Crown "SKU Intelligence Portal" — Current-State Specification

> **Purpose:** an as-built description of what the existing application does today, written to be the starting point for designing a new ERP.
> **Method:** derived by reading the source (`backend/server.py`, all of `frontend/src`, tests and reports). Where the in-repo PRD (`memory/PRD.md`) and the code disagree, **the code wins** and the disagreement is called out (see [§12](#12-prd-vs-code-discrepancies)).
> **Snapshot:** repository state at commit `e2418db`, 2026-10-12.

---

## Table of contents

1. [What this system is](#1-what-this-system-is)
2. [Architecture & tech stack](#2-architecture--tech-stack)
3. [Users, roles & permissions](#3-users-roles--permissions)
4. [Data model (MongoDB collections)](#4-data-model-mongodb-collections)
5. [Feature modules (as built)](#5-feature-modules-as-built)
6. [Business rules & hard-coded constants](#6-business-rules--hard-coded-constants)
7. [API reference](#7-api-reference)
8. [Frontend: routes, pages & UI behaviour](#8-frontend-routes-pages--ui-behaviour)
9. [What is NOT built (ERP gap list)](#9-what-is-not-built-erp-gap-list)
10. [Verified bugs, inconsistencies & risks](#10-verified-bugs-inconsistencies--risks)
11. [What to reuse vs. redesign for the new ERP](#11-what-to-reuse-vs-redesign-for-the-new-erp)
12. [PRD vs. code discrepancies](#12-prd-vs-code-discrepancies)
13. [Testing & delivery history](#13-testing--delivery-history)

---

## 1. What this system is

An **internal web app for Crown / Lamikraft** (decorative laminate / wood-panel and kitchenware-style products; brand names "Crown", "Lamikraft", legal name hard-coded as *Crown Decor Pvt. Ltd.*) that acts as:

1. A **product information & commercial reference catalogue** ("SKU Intelligence"): product master, pricing, packaging/carton data, specifications, images/documents, category taxonomy.
2. A **quotation engine** for export quotes (default currency EUR): catalogue configurator, custom/non-catalogue products, manual lines, versioning, status workflow, PDF.
3. A **sheet-cutting optimiser** (nesting of cut pieces onto 8 ft × 4 ft boards, grouped by decor + thickness).
4. A **delivery-challan (material movement) module** with PDF/print.
5. Cross-cutting: role/permission control, bulk CSV/Excel import, global search, data-quality dashboard, activity feed, internal notes, CSV exports.

It is **not** an ERP yet: there is no customer master, no sales order, no inventory, no purchasing, no invoicing/accounting, no production/BOM and no HR. It is a catalogue + quoting + two small operational tools. Scale of the codebase: one 4,318-line FastAPI file, ~20 React pages, ~12 pytest files.

Origin note: the app was generated/iterated with the Emergent platform (`.emergent/`, `test_reports/iteration_*.json`, `emergentintegrations`, Emergent object storage). Its history is "auto-commit" snapshots — there is no meaningful git history to mine.

---

## 2. Architecture & tech stack

| Layer | Technology |
|---|---|
| Frontend | React 19 (Create React App + CRACO), React Router 7, Tailwind CSS + shadcn/ui (Radix), axios, react-hook-form + zod, recharts, sonner toasts, phosphor + lucide icons, `xlsx`, `papaparse` |
| Backend | Python FastAPI 0.110 + Uvicorn, **single file** `backend/server.py` (models, routes, PDF, algorithms, startup all together) |
| Database | MongoDB via Motor (async). No ORM/migrations; schemaless with a few Pydantic models. Indexes created at startup |
| Auth | Email + password, bcrypt, JWT (HS256, 24 h expiry, no refresh) |
| PDF | `fpdf2` (core Helvetica font, programmatic layout) for quotes and challans |
| File storage | Emergent object-storage HTTP API (`integrations.emergentagent.com/objstore`) — platform-specific, **must be replaced**. Media can alternatively be external URLs (e.g. Drive links via CSV import) |
| Data import | `pandas` (+ `openpyxl`) for CSV/XLSX |
| Other deps present but unused | `boto3`, `PyMuPDF`, `passlib`, `python-jose`, `numpy`, `typer`, `jq` |
| Tests | pytest *integration* tests that call a **live deployed URL** (`REACT_APP_BACKEND_URL`), plus Playwright-style reports in `test_reports/` |
| Hosting hints | Emergent preview + a production site `dashboard.lamikraft.com` (from commit messages) |

Backend structure (all in `server.py`, in file order): config/storage helpers → Pydantic models → permission constants → auth → users → products/pricing/packaging/specs → categories/lookups → file upload → data import (7 importers + validate + clear) → configurator → quote settings/CRUD/lines/revisions/status/duplicate → custom products → permission overrides → quote PDF → category admin → sheet optimiser → challans (+PDF) → global search / completeness / duplicates / notes / activity → health → startup (indexes + admin bootstrap).

All routes are mounted under `/api`. Static logo served at `/static`.

---

## 3. Users, roles & permissions

### 3.1 Roles (fixed, 4)

`admin`, `management`, `sales`, `operations`. Role is a string on the user; it is **not validated** on create/update.

### 3.2 Permission model

Two layers exist and they are **not consistently used**:

1. **Role gate on endpoints** (`require_roles(...)`): this is what the backend mostly enforces.
2. **Named permissions** resolved per user = role defaults ∪ `permission_overrides.grant` − `permission_overrides.revoke`. Returned by `/api/auth/me` and used by the frontend to show/hide UI; the backend only checks a handful (`view_all_quotes`, `edit_all_quotes`, `delete_quotes`).

| Permission | admin | management | sales | operations |
|---|:-:|:-:|:-:|:-:|
| `view_all_quotes` | ✔ | ✔ | | ✔ |
| `view_own_quotes` | | | ✔ | |
| `create_quotes` | ✔ | ✔ | ✔ | |
| `edit_all_quotes` | ✔ | ✔ | | |
| `edit_own_quotes` | | | ✔ | |
| `delete_quotes` | ✔ | | | |
| `override_price` | ✔ | ✔ | ✔ | |
| `export_quotes` | ✔ | ✔ | ✔ | |
| `view_products` | ✔ | ✔ | ✔ | ✔ |
| `edit_products` | ✔ | | | |
| `manage_users` | ✔ | | | |
| `import_data` | ✔ | | | |
| `view_costing` | ✔ | ✔ | | |
| `manage_categories` | ✔ | | | |

14 permissions total (`ALL_PERMISSIONS`). Per-user overrides are edited at `/admin/permissions`; `/admin/roles` is a read-only matrix.

### 3.3 What the backend actually enforces

| Area | Enforcement |
|---|---|
| User CRUD, reset password, import, product create/update/delete, pricing add, packaging/spec PUT, file upload/delete, category CRUD, grain-lock edits, quote settings, permission admin | `role == admin` |
| Quote create/update/lines/revise/status/duplicate, custom-product create/update | `role ∈ {admin, sales, management}` |
| Quote **read** (`GET /quotes/{id}`), quote **update**, add line | Ownership: users without `view_all_quotes` / `edit_all_quotes` only see/edit quotes where `created_by == self` |
| Quote **delete** | `role == admin` **and** `delete_quotes` permission **and** status is `draft` |
| Challans, global search, activity, notes, optimiser calc | **Any authenticated user** (no role/permission check) |
| `override_price`, `export_quotes`, `view_costing`, `edit_products`, `manage_*` | **Frontend only** (UI hiding) — no server-side check |

### 3.4 Authentication details

* Login → JWT `{user_id, email, role, exp=24h}`; token stored client-side and sent as `Authorization: Bearer`.
* File/PDF/CSV downloads also accept the token as a **query-string param `?auth=`** (so plain `<a href>` links work).
* `POST /auth/change-password`; admin `POST /users/{id}/reset-password` returns a 12-char temporary password in the response.
* Startup **bootstraps a fixed admin account** (`sahil@crownlam.com`) and **re-syncs its password from `ADMIN_INITIAL_PASSWORD` on every boot** (default value hard-coded in source). Any admin-initiated password change for that user is reverted on restart. The PRD also lists seed credentials for four demo users — treat all of these as compromised and do not carry over.
* No lockout / rate-limit, password policy, MFA, refresh tokens, token revocation, or audit log of logins (only `last_login`).

---

## 4. Data model (MongoDB collections)

Documents use a string UUID `id` (except products, keyed by `product_key`). `_id` is stripped in responses. Fields below are those actually written/read by the code; collections are schemaless so real documents may carry extra import-only columns.

### 4.1 `users`
`id, email (unique), name, role, password_hash, is_active, created_at, last_login, permission_overrides{grant[], revoke[]}`

### 4.2 `products_master` — catalogue core (PK = `product_key`, unique)
`product_key, display_sku (non-unique, for UI), product_name, brand, category, subcategory, product_type, variant_group, unit_of_sale, size_mm, decor_no, decor_name, decor_primary, decor_options, finish, shape, status (active|inactive|under_development), description, internal_remarks, source_design_no, source_shape_no, source_sheet, source_row, source_catalog_page, source_notes, created_at, updated_at`
Indexes: unique `product_key`; `display_sku`, `category`, `decor_no`; a text index (name/sku/category/decor) that is not actually used by the queries (regex is used instead).

### 4.3 `pricing` — many rows per product
`id, product_key, price_type (default "domestic"; values seen: domestic/export/sample/distributor), currency (default "INR" in the API model; imports default "INR"; the app logic reads **EUR** rows), price, final_price, base_price(+label), addon_price(+label), price_basis, yield_qty_per_board, thickness_mm, moq, unit_of_sale, price_notes, valid_from, valid_to, display_sku, source_sheet, source_row, created_at, updated_at`
Upsert key on import: `(product_key, price_type, currency)`.

### 4.4 `packaging` — one row per product (unique `product_key`)
Two overlapping naming schemes coexist (importer accepts both, API model uses the second):
`carton_qty` / `master_carton_qty`, `unit_weight_g` / `unit_weight_kg`, `packing_type` / `unit_packing_type`, `inner_qty` / `inner_pack_qty`, plus `carton_length_cm, carton_width_cm, carton_height_cm, net_weight_kg, gross_weight_kg, cbm, packaging_notes, fragile_notes, packaging_status, notes`.
**MOQ and the configurator read `carton_qty` / `unit_weight_g` / `packing_type` only.**

### 4.5 `specifications` — one row per product (unique `product_key`)
`length_mm, width_mm, thickness_mm, thickness_text, size_mm, size_label, finish, material_type, groove_count, bowl_count, bowl_type, top_sheet, stand_material, stand_size_mm, board_size_mm, working_size_mm, type, plate1/2/3_size_mm, no_of_boards, handle_type, special_features, care_instructions, usage_notes`

### 4.6 `media`
`id, product_key, media_type (image|document|packaging_photo), storage_path (object-store key) or file_url / drive_link / file_path, file_name / original_filename, content_type, size, is_primary, is_deleted (soft), alt_text, uploaded_at, uploaded_by`

### 4.7 `category_taxonomy`
`id, category, subcategory, display_order, is_active, product_count, description, source_catalog_page_start/end`. Unique on `(category, subcategory)`.

### 4.8 `lookup_reference` (import only)
`lookup_type, key_1, key_2, value_1, value_2, notes` — imported but **no endpoint or UI reads it**.

### 4.9 `quote_settings` (singleton)
`brand_prefix "LK", quote_prefix "QT", year_format, next_sequence, format_template` (template field is stored but ignored; number format is hard-coded).

### 4.10 `quotes`
`id, quote_number (unique), version, status, customer_name, customer_country, customer_reference, customer_type (standard|dealer|distributor), currency (default EUR), incoterm (default FOB), payment_terms, validity_days (30), remarks, min_invoice_note, brand ("LK"), surcharge_applied, created_by, created_by_name, assigned_to, assigned_to_name, updated_by, internal_notes, total_amount, total_lines, created_at, updated_at`
There is **no customer id** — the customer is free text.

### 4.11 `quote_lines`
`id, quote_id, line_number, sort_order, line_type (catalog|custom|manual), product_key, custom_product_id, display_code, display_sku, product_name, dimensions, thickness, decor_no, decor_name, finish, unit_of_sale, default_price, quoted_price, override_reason, currency, moq, quantity, line_total, packaging_summary, image_url, image_id, description, notes, created_at`
Lines are **snapshots**: later catalogue/price changes do not alter existing lines.

### 4.12 `quote_revisions`
`id, quote_id, version, status_from, status_to, changes_summary, snapshot{full quote + lines}, created_by(_name), created_at`

### 4.13 `custom_products` (non-catalogue / customer-specific library)
`id, custom_code (CP-NNNN, unique), custom_type (default "fully_new"), base_product_key, customer_specific_flag, is_promoted_to_master (always false — no promote flow), category, customer_name, inquiry_reference, product_name, dimensions, thickness, decor_no, decor_name, finish, shape, groove_count, bowl_count, handle_type, packaging_notes, costing, quoted_price, remarks, status (default "inquiry"), internal_notes, created_by, created_at, updated_at`

### 4.14 `grain_locked_decors`
`decor (unique), label, updated_by, updated_at` — decors whose pieces may not be rotated in nesting.

### 4.15 `delivery_challans` / `delivery_challan_lines`
Challan: `id, challan_number (DC-YYYY-NNNN, unique), challan_date, challan_type, return_type, source_location, destination_type, destination_party, shipping_name, gstin, phone, email, address, reference_no, remarks, internal_notes, status, created_by(_name), updated_by, created_at, updated_at`
Line: `id, challan_id, line_type (catalog|custom|manual), item_code, item_name, hsn_code, quantity (float), unit (default "pcs"), remarks, sort_order`

### 4.16 Misc
`search_history` (`user_id, query, results_count, searched_at`; last 10 per user exposed), `revision_history` (cleared by "clear sample data" but never written), legacy `products` (cleared only).

### 4.17 Entity relationships

```
category_taxonomy 1─* products_master 1─* pricing
                              │ 1─1 packaging
                              │ 1─1 specifications
                              │ 1─* media
quotes 1─* quote_lines ─(snapshot ref)→ products_master | custom_products
quotes 1─* quote_revisions (full JSON snapshots)
delivery_challans 1─* delivery_challan_lines   (no FK to products or quotes)
```

---

## 5. Feature modules (as built)

### 5.1 Authentication & user management
* Login, `me` (profile + resolved permissions + overrides), change own password.
* Admin: list/create/update (name, role, active)/delete users; reset password (returns temp password); cannot delete self.
* Hard delete of users; their `created_by` ids remain on quotes/challans (names are denormalised as `created_by_name`).

### 5.2 Product catalogue ("SKU Intelligence")
* **Listing** (`GET /products`): free-text search (regex across key, SKU, name, category, subcategory, decor no/name, finish), filters for category, subcategory, status, brand, decor number, thickness; `limit`/`skip`. Each row is enriched (batched) with specs, **EUR price**, **computed MOQ**, **primary image**, and a decor fallback from `decor_primary`. Every search is logged to `search_history`.
* **Detail** (`GET /products/{key}`): product + all pricing rows + packaging + specifications + media + EUR price + MOQ + primary image.
* **Stats** (`/products/stats`): totals by status, count with no pricing, updated in last 7 days, per-category counts. **Recent** (`/products/recent`): latest updated, with domestic price.
* **Admin CRUD**: create product; update product (+ nested `specifications` / `packaging` upsert in one PUT); delete product (hard-deletes pricing, packaging, specs; soft-deletes media); add a pricing row; replace packaging; replace specifications.
* **Facet endpoints**: categories, category hierarchy, categories/validate (products whose category is missing from taxonomy), brands, decors, thicknesses.
* **Media**: admin upload (multipart; image/document/packaging_photo; optional `is_primary` which un-primaries siblings), list, authenticated download proxy (streams from object storage), soft delete. Allowed file types by extension map: jpg/png/gif/webp/pdf/doc(x)/xls(x).

### 5.3 Bulk data import (admin)
Seven importers + preview + validate + wipe. CSV or XLSX; headers lower-cased and underscored.

| Endpoint | Upsert key | Notes |
|---|---|---|
| `category_taxonomy` | category + subcategory | **Must be imported first** |
| `products_master` | `product_key` | Category must exist in taxonomy (row fails otherwise); unknown subcategory = warning only; status normalised to snake_case; defaults `display_sku`/`product_name` to the key |
| `pricing_master` | product_key + price_type + currency | Accepts `final_price` or `price`; orphan rows (no product) are reported **but still imported** |
| `packaging_master` | product_key | Wide alias mapping (see §4.4); orphans reported but imported |
| `specifications_master` | product_key | Orphans reported but imported |
| `media_master` | none (always inserts) | Needs a URL/path/file name; re-importing duplicates media |
| `lookup_reference` | lookup_type + key_1 (+ key_2) | Stored, never used |

Also: `POST /import/preview` (first 10 rows, columns, duplicate keys), `POST /import/validate` (counts + orphan lists + products without pricing), `DELETE /import/clear-sample-data` (wipes products, pricing, packaging, specs, media, taxonomy, search history). Errors are capped at 100 per import and returned with row numbers and severity.

### 5.4 Category taxonomy management
Admin CRUD of `(category, subcategory)` with `display_order`. Product import validates against it. Renames/deletes **do not cascade** to products.

### 5.5 Quotation engine

**Catalogue configurator** (`POST /configurator/resolve`): search-first product picker. Input: `selected{category, variant_group, decor_no, thickness_mm, size_mm, finish}`, `search` text (matches SKU/name/key/decor/variant/category + size/thickness/finish text + numeric thickness), `page`, `page_size`. Output: **available filter options narrowed to the current result set**, a page of enriched matches (EUR price, MOQ, primary image, packaging summary like `450g | 24/ctn | Poly bag`), total count, and `exact_match` when exactly one product remains.

**Quote header**: customer name/country/reference, customer type, currency, incoterm, payment terms, validity days, remarks, min-invoice note, brand, surcharge toggle, assigned-to.

**Numbering**: `LK-QT-<year>-<0000>` from a counter in `quote_settings` (counter never resets per year; increment is not atomic).

**Lines** (3 types): *catalog* (from configurator, full snapshot), *custom* (from custom-product library), *manual* (free text). `line_total = quoted_price × quantity`. Quote `total_amount` / `total_lines` recomputed after every add/update/delete; remaining lines are renumbered after delete. `default_price` vs `quoted_price` + `override_reason` capture price overrides.

**Status workflow**: `draft → internal_review → sent → revised → won / lost` (the UI also offers `cancelled` and `archived` — see §10). Every status change writes a revision snapshot. No transition rules; any status can be set from any status; no approval step.

**Versioning**: `POST /quotes/{id}/revise` stores a full snapshot (quote + lines) in `quote_revisions` and bumps `version` (optionally changing status). Revisions are listed with the quote; there is no restore or diff.

**Duplicate quote**: new number, `draft`, copies header + all lines (customer reference cleared).

**PDF export**: A4, Lamikraft logo header, quote no./version/date, customer & terms block, 6-column line table (#, product SKU+name, details, price, qty, total), subtotal, optional EUR 400 surcharge, total, threshold note, remarks, min-invoice note, page footer. (The "Rec. MOQ" column was removed by request.)

**Other**: quote list CSV export, search by number/customer/country, status filter, scope (`mine`/`all`), pagination; admin-only delete of **draft** quotes (also removes lines and revisions); internal notes.

**Dynamic MOQ (advisory only)** — see §6.

### 5.6 Custom products
Library of non-catalogue / customer-specific items with auto code `CP-NNNN`, type, optional `base_product_key`, customer-specific flag, dimensions/thickness/decor/finish/shape/groove/bowl/handle, packaging notes, **costing** and quoted price, status (default `inquiry`), remarks. List/search/filter, create, edit, admin delete, duplicate, CSV export, internal notes; selectable as a quote line. `is_promoted_to_master` exists but there is **no promote-to-catalogue action**.

### 5.7 Sheet optimiser (cut-list nesting)
* Input: list of items `{sku, decor, thickness, length, width, quantity}` (UI autocompletes from the catalogue and fills dimensions), `allow_oversize` flag.
* Board: **2440 × 1220 mm**, 5 mm edge margin, 6 mm cutting gap, optional +10 mm per side oversize tolerance (constants in code).
* Pieces are **grouped by (decor, thickness)** and packed per group onto as many boards as needed, largest-area first, with 90° rotation unless the decor is **grain-locked** (admin-maintained list `grain_locked_decors`, add/remove/replace endpoints).
* Output per group: boards needed, pieces placed vs required, overall efficiency %, scrap %, used/sheet area, per-SKU required vs produced, unfit (too-large) pieces, and per-board placements `{sku, x, y, w, h, rotated}` plus approximate leftover areas. UI renders each board as colour-coded SVG with a placement table.
* Algorithm note: described as MaxRects Best-Short-Side-Fit, but the implementation splits free rectangles guillotine-style and does not prune/merge overlapping free rects — efficiency is therefore lower than a true MaxRects. `allow_overproduction` is accepted but unused.

### 5.8 Delivery challans (material movement)
* **Types**: Outward, Inward, Return, Job Work, Transfer, Sample. **Return type**: returnable / non-returnable. **Destination types**: Fabricator, Customer, Warehouse, Vendor, Office, Transporter. **Statuses**: draft, issued, closed, cancelled.
* Header: date, type, return type, source location, destination type/party, shipping name, GSTIN, phone, email, address, reference no., remarks, internal notes. Auto number `DC-<year>-<0001>` (restarts each year).
* Lines: item code, item name, HSN/SAC, quantity, unit (default pcs), remarks; line type catalog/custom/manual (but only free text is stored — no product link, no value/rate).
* List with filters (search on number/party, status, type, destination type/party, this-week/this-month/date range), summary cards (total, this week, this month, pending returnable, by type/destination/status), duplicate (with lines), CSV export, branded PDF (FROM/TO block, line table, total quantity, terms & conditions, signature boxes) and a browser print view.
* Delete: admin only, draft only. **No stock effect, no return reconciliation against original challan, no e-way bill/GST value handling.**

### 5.9 Cross-module utilities
* **Global search** (`/global-search?q=`): products, custom products, quotes, challans, categories — grouped results with deep links (min 2 chars).
* **Data completeness**: counts of products missing images / decor / price / MOQ and custom products missing description / dimensions.
* **Recent activity**: merged feed of latest quotes, challans, custom products.
* **Internal notes**: `PUT /internal-notes/{quote|challan|custom_product}/{id}` — free-text, auto-saved from the UI.
* **Audit trail (light)**: `updated_by`/`updated_at` on quotes and challans; revision snapshots on quotes. No general audit log.

---

## 6. Business rules & hard-coded constants

| Rule | Detail |
|---|---|
| **Minimum order value** | EUR **5,000** at quote level |
| **Shipping surcharge** | EUR **400**, only when currency = EUR, 0 < subtotal < 5,000 **and** the user toggled `surcharge_applied`; computed at render/PDF time, **not persisted in totals** |
| **Dynamic MOQ** | `ceil(5000 / EUR_unit_price)`, then rounded **up to a multiple of `carton_qty`** when known. Advisory: shown as a warning, never blocks a quote |
| **Which price is used** | the first/last `pricing` row with `currency == "EUR"` (price_type is ignored) |
| **Price override** | `quoted_price` vs `default_price` with `override_reason`; UI role rule: admin/management free, sales must give a note, operations none |
| **Customer type** | standard / dealer / distributor is stored on the quote but **does not change prices** |
| **Quote number** | `{brand_prefix}-{quote_prefix}-{YYYY}-{seq:04}` → `LK-QT-2026-0001` |
| **Challan number** | `DC-{YYYY}-{seq:04}` (max-existing + 1, yearly reset) |
| **Custom code** | `CP-{count+1:04}` |
| **Defaults** | currency EUR, incoterm FOB, validity 30 days, brand LK, min-invoice note "Minimum invoice value: EUR 5,000" |
| **Sheet** | 2440 × 1220 mm, margin 5, gap 6, oversize tolerance 10 |
| **JWT** | HS256, 24 h |
| **Company identity in PDFs** | Lamikraft logo, "Crown Decor Pvt. Ltd.", default source "Crown / Lamikraft Office", challan T&Cs — all hard-coded |
| **Brand tokens** | wood brown `#C8A064`, leaf green `#8BC34A` |

---

## 7. API reference

All paths are prefixed `/api`. "Auth" = valid JWT. Unless noted, response is JSON. ★ = token also accepted as `?auth=` query param.

### Auth & users
| Method | Path | Access |
|---|---|---|
| POST | `/auth/login` | public |
| GET | `/auth/me` | Auth |
| POST | `/auth/change-password` | Auth |
| GET / POST | `/users` | admin |
| PUT / DELETE | `/users/{id}` | admin |
| POST | `/users/{id}/reset-password` | admin |
| GET | `/admin/permissions/defaults` | admin |
| GET | `/admin/permissions/users` | admin |
| PUT | `/admin/permissions/users/{id}` | admin |

### Catalogue
| Method | Path | Access |
|---|---|---|
| GET | `/products` (search, category, subcategory, status, brand, decor_no, thickness, limit, skip) | Auth |
| GET | `/products/stats`, `/products/recent`, `/products/{key}` | Auth |
| POST | `/products` | admin |
| PUT / DELETE | `/products/{key}` | admin |
| GET | `/products/{key}/pricing` · POST `/products/{key}/pricing` | Auth · admin |
| GET / PUT | `/products/{key}/packaging` | Auth · admin |
| GET / PUT | `/products/{key}/specifications` | Auth · admin |
| GET | `/categories`, `/categories/hierarchy`, `/categories/validate`, `/brands`, `/decors`, `/thicknesses` | Auth |
| GET | `/search/recent` | Auth |
| POST | `/products/{key}/files?media_type=&is_primary=` (multipart) | admin |
| GET | `/products/{key}/files` | Auth |
| GET ★ | `/files/{id}/download` | Auth |
| DELETE | `/files/{id}` | admin |
| GET / POST / PUT / DELETE | `/admin/categories[/{id}]` (GET is any Auth) | admin for writes |

### Import (all admin)
`POST /import/preview`, `/import/{products_master | pricing_master | packaging_master | specifications_master | media_master | category_taxonomy | lookup_reference}`, `POST /import/validate`, `DELETE /import/clear-sample-data`.

### Quotation
| Method | Path | Access |
|---|---|---|
| POST | `/configurator/resolve` | Auth |
| GET / PUT | `/quote-settings` | admin |
| POST | `/quotes` | admin/sales/management |
| GET | `/quotes` (status, search, scope, limit, skip) → `{quotes,total}` | Auth (+ownership) |
| GET ★ | `/quotes/export-csv` | any valid token |
| GET | `/quotes/{id}` → quote + lines + revisions | Auth (+ownership) |
| PUT | `/quotes/{id}` | admin/sales/mgmt (+ownership) |
| DELETE | `/quotes/{id}` | admin (draft only) |
| POST / PUT / DELETE | `/quotes/{id}/lines[/{line_id}]` | admin/sales/mgmt |
| POST | `/quotes/{id}/revise` · PUT `/quotes/{id}/status` · POST `/quotes/{id}/duplicate` | admin/sales/mgmt |
| GET ★ | `/quotes/{id}/export-pdf` | any valid token |
| POST / GET | `/custom-products`; GET ★ `/custom-products/export` | create: admin/sales/mgmt |
| GET / PUT / DELETE | `/custom-products/{id}` | Auth · admin/sales/mgmt · admin |
| POST | `/custom-products/{id}/duplicate` | Auth |

### Sheet optimiser
`POST /sheet-optimizer/calculate`, `GET /sheet-optimizer/products?search=`, `GET /sheet-optimizer/grain-settings`, `PUT /sheet-optimizer/grain-settings` (bulk replace), `POST /sheet-optimizer/grain-settings/add`, `DELETE /sheet-optimizer/grain-settings/{decor}` (writes admin only).

### Challans (all: any Auth unless noted)
`POST/GET /challans`, `GET /challans/summary`, `GET ★ /challans/export-csv`, `GET/PUT /challans/{id}`, `DELETE /challans/{id}` (admin+draft), `POST /challans/{id}/lines`, `PUT/DELETE /challans/{id}/lines/{line_id}`, `GET ★ /challans/{id}/export-pdf`, `POST /challans/{id}/duplicate`.

### Cross-module / system
`GET /global-search`, `GET /data-completeness`, `GET /activity/recent`, `PUT /internal-notes/{entity_type}/{id}`, `GET /` (version "2.0.0"), `GET /health`.

---

## 8. Frontend: routes, pages & UI behaviour

### 8.1 Shell, routing & client auth
* `BrowserRouter` + `AuthProvider`. `ProtectedRoute` only checks "is logged in"; **no route has role/permission gating**. Gating is cosmetic: the sidebar filters by role, some buttons check `isAdmin()` or `can(perm)`, and two pages (`/users`, `/import`) redirect non-admins client-side. A sales/operations user can open `/admin/*`, `/products/new`, `/custom-products`, `/quotes`, `/challans` by typing the URL — only the API stops them.
* Token in `localStorage['token']`; axios adds `Bearer`; any 401 hard-redirects to `/login`. Session restore calls `/auth/me` (server-resolved permissions incl. overrides). Logout is client-only.
* Layout: fixed sidebar (collapsible, not persisted), sticky header with **global search** (`/` shortcut, 300 ms debounce, grouped results, Enter falls back to product search), dark-mode toggle (persisted), user menu (Settings, Sign out).
* Helpers in `useAuth()`: `can(perm)`, `isAdmin()` (role test), `canViewAllQuotes()`, `canEditQuote(quote)` (edit_all, or edit_own + owner), `canViewSection(pricing|packaging|specifications)` (pricing needs `view_costing`; packaging/specs hidden from `sales`).

### 8.2 Routes & navigation

| Path | Page | Sidebar roles |
|---|---|---|
| `/login` | Login | public |
| `/` | Dashboard | all |
| `/products`, `/products/:key` | Product list / detail | all |
| `/products/new`, `/products/:key/edit` | Product form | (button: admin) |
| `/quotes`, `/quotes/new`, `/quotes/:id`, `/quotes/:id/preview` | Quote list / builder / print preview | admin, sales, management |
| `/custom-products`, `/new`, `/:id/edit` | Custom product list / form | admin, sales |
| `/sheet-optimizer` | Sheet optimiser | all |
| `/challans`, `/new`, `/:id`, `/:id/preview` | Challan list / builder / print preview | all |
| `/admin/categories` | Category management | admin |
| `/admin/roles` | Role permission matrix (static) | admin |
| `/admin/permissions` | Per-user permission overrides | admin |
| `/users` | User management | admin |
| `/import` | Data import | admin |
| `/settings` | Own profile + change password (user menu only) | all |

### 8.3 Page-by-page behaviour

**Login** — email + password (show/hide), error message, "Internal use only" footer. No forgot-password, no registration.

**Dashboard** — stat cards (Total SKUs, Active, Missing Pricing, Updated 7d), a challan strip (Total, This Week, This Month, Pending Returns, Issued), recent-activity feed (quote/challan/custom badges), 6 recently updated products, a Data Completeness card (missing images / decor / EUR price / MOQ; custom products missing description / dimensions) and the first 8 categories as quick filters. **No charts** (recharts is installed but unused). No sales, quote-pipeline or revenue KPIs.

**Product list** — filters synced to URL: search (300 ms debounce), category, thickness, status (Active / Inactive / In Dev); columns: thumbnail, SKU, name, category, decor, dimensions, thickness, EUR price, MOQ, status. **No pagination** (API default limit 100). "Add Product" for admins.

**Product detail** — header (name, status, SKU, brand, category, decor, key) with admin Edit/Delete (confirm). Tabs: **Overview** (EUR export price, MOQ, dimensions, thickness, product info, key specs, primary image, pricing summary EUR/USD export, classification), **Pricing** (one card per price row: type, basis, currency, unit, base/add-on prices, yield per board, thickness, notes; needs `view_costing`), **Packaging** (weights, packing type, inner/carton qty, carton dimensions, CBM, notes, fragile), **Specifications** (size, L/W/T, finish, type, material, groove/bowl counts, plate/board/stand sizes, features, care, usage), **Documents** (grouped images / documents / packaging photos / catalogue references; admin upload & delete; preview dialog; download). The design brief also lists Costing, Operations and History tabs — **not built**.

**Product form** — create/edit all master, specification and packaging fields (see below). `product_key` is the only validated field and is immutable on edit. **Pricing cannot be created or edited in the UI** — price data enters only via CSV import. Category/subcategory/brand are **free text**, not tied to the taxonomy. Some fields exist in form state but have no input (`decor_primary`, `decor_options`, `source_sheet`, stand/board/working size, plate sizes, carton dimensions).

**Quote list** — status tabs (All, Draft, Review, Sent, Won, Lost — none for Revised/Cancelled/Archived), search (not debounced), "My / All quotes" toggle when `view_all_quotes`, columns (number + version, customer + country, status, lines, total + currency, creator, date), open, delete (draft + permission, confirm), New Quote, Export CSV (shown to everyone). Limit 100, no paging.

**Quote builder** *(the largest screen, 1,130 lines)*
* Header fields: customer name / country / reference, **customer type** (standard, dealer, distributor), **currency** (EUR, USD, GBP, INR), **incoterm** (FOB, CIF, CFR, EXW, DDP, DAP, FCA), validity days (30), payment terms, brand prefix (LK), min-invoice note, remarks.
* Top bar: Preview, Export PDF (`export_quotes`), status select (Draft, Internal Review, Sent to Customer, Revised, Won, Lost, **Cancelled, Archived**), Revise, Duplicate, Delete (draft only).
* Lines are only addable after the quote is created. Three add dialogs:
  * **Catalog configurator** — type-ahead + six cascading filters (category, family/variant group, size, thickness, decor, finish); results show image, SKU, name, dimensions, thickness, decor, finish, EUR price, recommended MOQ. Picking a product shows packaging summary and asks for price (defaults to EUR price), quantity, optional override reason. Amber warnings: qty below recommended MOQ; price differs from default. Only page 0 (30 rows) is ever fetched.
  * **Custom product** — search the custom library; quantity starts at 0 and is edited in the table.
  * **Manual line** — preset chips (Development Charges, Tooling Charges, Special Packaging, Freight, Sample Charges, Miscellaneous) + description, amount, quantity, notes.
* Line table: image, product details (+ override reason), recommended MOQ, price (click-to-edit only with `override_price`; default price struck through when overridden), quantity (always editable, optimistic), total, delete (no confirm). The whole quote is re-fetched after each change so the server owns `line_total`.
* **Commercial summary**: subtotal; per-line "below MOQ" banner; for EUR quotes a "meets / below EUR 5,000 minimum" panel with a toggle for the EUR 400 surcharge (saved immediately); for non-EUR quotes text only ("EUR 5,000 equivalent"), no conversion. Internal notes textarea auto-saves after 1 s.
* **Catalogue prices are always the EUR price, even when the quote currency is USD/GBP/INR** — currency is a label, there is no FX.

**Quote preview** — print-friendly document (Back, Edit, Export PDF, Print). Seller shown only as "Lamikraft"; no address, tax IDs, bank details or T&Cs. Shows line table, subtotal / surcharge / total, commercial-threshold banners, remarks, and (screen only) revision history.

**Custom product list / form** — list columns code, name, type, customer, category, decor, status, updated; search + status filter; CSV export; delete via `window.confirm`; no detail page. Form fields: code (auto if blank), type (`modified_catalog` / `fully_new` / `quote_only`), base product key, status (`inquiry`, `under_development`, `sample_stage`, `quoted`, `approved`, `converted_to_standard`, `rejected`, `dormant`), customer, inquiry ref, name, category (taxonomy dropdown), dimensions, thickness, decor no/name, finish, shape, groove/bowl counts, handle type, **costing (EUR)**, quoted price (EUR), packaging notes, remarks. Costing is visible to anyone who can open the page (no `view_costing` check). Duplicate API exists but has no button.

**Sheet optimiser** — editable cut-list table (SKU, decor, thickness, length, width, qty; starts with 3 blank rows) with catalogue product search that auto-fills dimensions; switches for "+10 mm oversize tolerance" and "allow overproduction" (the latter is ignored by the server); admin "Grain Settings" dialog (add/remove grain-locked decors with labels). Results per decor+thickness group: sheets required, pieces placed, efficiency %, scrap %, produced-vs-required per SKU, un-fittable pieces, and for each board a scaled **SVG nesting diagram** with a placement table (SKU, x/y, size, rotated) and leftover areas. No save, export, print, or link to quotes/production.

**Challan list / builder / preview** — list with summary cards and filters (search, status, type, destination, period) + CSV; builder with all header fields (source location defaults to "Crown / Lamikraft Office"; only destination party is required), status select (any→any), duplicate, PDF, preview, internal notes (auto-save); line dialog with type toggle (catalog/custom/manual — **toggle changes only a label; there is no product lookup**), item code, HSN/SAC, item name, quantity, unit (pcs, nos, sheets, kg, m, sqm, sqft, box, set, roll, bundle), remarks. Quantity saves on every keystroke with errors swallowed. No delete-challan button in the UI. Preview/PDF carry hard-coded "Crown Decor Pvt. Ltd." identity, 3–4 fixed terms and three signature blocks (Delivered By, Received By, Authorised Signatory).

**Data import** — pick table type → upload CSV/XLSX (click only; "drag and drop" text is not implemented) → server preview (columns, first rows, duplicate keys, missing `product_key` blocks) → import → result counts, first 20 errors, orphans, downloadable (unescaped) error CSV. Session-only import history; "Validate Data" and "Clear All Data" (confirm). Recommended order shown: taxonomy → products → pricing/packaging/specs/media → lookup.

**User management** — table (name, email, role, status, created); create (name, email, password ≥ 8, role), edit (name + role only — **no UI to deactivate a user** even though the API supports `is_active`), reset password (shows temp password), delete (confirm, not self).

**Settings** — read-only profile; change-password (≥ 8 chars, confirm). The quote-settings API (number prefixes) has **no UI**.

**Category management** — flat list of category/subcategory pairs with display order; add/edit/delete (`window.confirm`).

**Role permissions** — static hard-coded matrix (not wired to real permissions and contradicts the sidebar in places — indicative only).

**Access control** — role defaults summary + per-user override editor (grant/revoke per permission, effective set preview). Covers only the 14 quote/product/admin permissions; **challans, custom products, optimiser have no permission keys**.

### 8.4 Styling & front-end conventions
* Brand: warm gold/brown primary `#C8A064` (HSL 36 45% 58%), leaf green `#8BC34A`, dark `#333`; fonts Chivo (headings), IBM Plex Sans (body), IBM Plex Mono (SKUs, prices, dimensions). Light default + dark mode. Desktop-first (w-64 sidebar, h-16 header). `design_guidelines.json` describes a different slate-navy palette that was **not** followed.
* Every interactive element carries a `data-testid` (used by the Playwright-style test agent).
* `index.html` still contains **Emergent platform branding (title "Emergent | Fullstack App"), the `emergent-main.js` script and a PostHog analytics snippet with a project key** — remove for any new build.
* Unused installed libs: recharts, xlsx, papaparse, date-fns, react-hook-form, zod. No TypeScript, no frontend tests, no i18n, no pagination anywhere, several `window.confirm` dialogs.
* Many API client functions are unused (product pricing/packaging/specs sub-resources, `getBrands`, `getDecors`, `getCategoryHierarchy`, `getRecentSearches`, `updateGrainSettings`, `duplicateCustomProduct`, `deleteChallan`, quote-settings).

---

## 9. What is NOT built (ERP gap list)

Use this as the "greenfield" backlog. None of the following exists in code (not even partially) unless noted.

**Master data:** customer / party master (customers are free text on quotes and challans); vendor / supplier master; contacts & addresses; price lists per customer / customer-type (customer type is stored but changes nothing); multi-currency with FX rates; tax codes, HSN master, units-of-measure master, warehouses/locations master; employee master.

**Sales:** quote approval workflow; quote → sales order → delivery → invoice chain (the PRD lists "Quote-to-Order conversion" as upcoming); discounts, taxes (GST/VAT), freight, payment schedule; sales targets; CRM / leads / follow-ups; customer-wise quote history.

**Inventory & warehouse:** stock ledger, batches/lots, stock by location, reorder levels, stock take; challans have no stock effect and no return reconciliation. (A `getStockStatusColor` helper exists in the UI but nothing uses it.)

**Purchasing:** purchase requisitions, POs, GRN, vendor bills, vendor price lists.

**Manufacturing:** BOM, routing, work orders, job-work tracking (challan type "Job Work" is a label only), material issue/consumption, production planning, scrap/yield tracking (the optimiser result is not saved or linked to anything), costing/cost sheets (only a free "costing" number on custom products; pricing has base/add-on prices and yield-per-board but no cost roll-up).

**Finance:** invoicing, receipts/payments, ledgers, GST returns, e-invoice / e-way bill, bank reconciliation, budgets, P&L / balance sheet.

**Logistics / export:** packing lists, shipping documents, container/CBM planning (carton CBM and weights are stored per product but not used in any calculation), letters of credit, shipment tracking.

**HR / payroll / attendance.**

**Platform:** configurable roles (4 fixed roles), field-level permissions, approval engine, general audit log, notifications / email, document templates & company settings (company name, address, GSTIN, bank, T&Cs are hard-coded), multi-company / multi-branch, localisation, reporting & BI (no charts, no report builder, only 3 CSV exports), API keys / webhooks, backups, data-migration tooling beyond the product CSV importers, automated (non-live) tests.

---

## 10. Verified bugs, inconsistencies & risks

Each item was confirmed by reading the code (file refs are `backend/server.py` line numbers at this commit unless stated).

### 10.1 Functional bugs
| # | Issue | Evidence / impact |
|---|---|---|
| 1 | **"Cancelled" and "Archived" quote statuses fail.** UI offers them (QuoteBuilder status select) but `PUT /quotes/{id}/status` only accepts `draft, internal_review, sent, revised, won, lost` → HTTP 400. PRD claims they were added. | l. 2511 |
| 2 | **Duplicated quotes show total 0.** `duplicate_quote` writes `total` but the list/builder read `total_amount` / `total_lines`; `assigned_to` is also not set. | l. 2555–2597 |
| 3 | **Surcharge totals disagree between UI and PDF.** Builder/preview add EUR 400 whenever the flag is on (any currency, even above 5,000); the PDF adds it only for EUR and subtotal < 5,000. The PDF also prints "…EUR 400 shipping surcharge applied" under 5,000 even when the flag is **off**. | QuoteBuilder.jsx l. 512; l. 2994–3024 |
| 4 | **Quote CSV "Total Lines" is always 0** (reads `q["lines"]`, but lines live in `quote_lines`); "Created By" exports a user id, not a name; no totals column. | l. 2246–2248 |
| 5 | **Product list decor fallback corrupts values:** `"120.0".rstrip('.0')` → `"12"` (strips characters, not suffix). The detail endpoint does it correctly. | l. 563 |
| 6 | **Product list thickness filter breaks paging:** applied *after* `skip/limit`, and products without specs pass the filter. | l. 538–541 |
| 7 | **Categories created in the admin UI are invisible** to `/categories` (which filters `is_active: true`, but `create_category` never sets it) → they don't appear in the product-list filter, custom-product form, or hierarchy. | l. 3080, 833 |
| 8 | **Custom-product search/activity/duplicate use a non-existent `name` field** (schema is `product_name`), so global search matches only the code, the activity feed shows blank subtitles, and "duplicate" produces name `" (Copy)"` while leaving `product_name` unchanged. Data-completeness checks `description`, which custom products don't have → every custom product is "missing description". | l. 3996, 4186, 4090, 4055 |
| 9 | **MOQ ignores `master_carton_qty`.** The admin API/model writes `master_carton_qty` (and `unit_packing_type`, `inner_pack_qty`, `unit_weight_kg`) while MOQ, configurator and packaging summary read `carton_qty` (and `packing_type`, `unit_weight_g`). Editing packaging via the API can silently disable carton rounding. | l. 206–219 vs 548–552 |
| 10 | **EUR price selection is ambiguous:** any `currency == "EUR"` row is used regardless of `price_type` (export vs distributor vs sample) — the last one wins. | l. 510–511, 2053 |
| 11 | **Sheet optimiser:** `allow_overproduction` is accepted by UI and API but never used; "MaxRects" is actually guillotine splitting with no free-rect pruning (sub-optimal nesting); leftover areas are a rough strip heuristic; a wasted no-op call to the packer inside the loop; sheet size/margins are code constants. | l. 3137–3349 |
| 12 | **Product import for media always inserts** (re-import duplicates media); orphan pricing/packaging/spec rows are reported but still written. | l. 1636–1654, 1289 |
| 13 | **Numbering is racy / fragile:** quote number read-then-increment (non-atomic; counter never resets by year); challan number = max+1 (race); custom code = count+1 (collides after any delete → unique-index error). | l. 2141, 3518, 2609 |
| 14 | **Challan status has no validation or transition rules** (`PUT` accepts any string); line quantity PUT saves on every keystroke. | l. 3696–3705 |
| 15 | **Pricing has no edit/delete path** in UI or API (POST appends only; import upserts). Duplicate (product, type, currency) rows can be created via POST. | l. 756–772 |
| 16 | **Category rename/delete do not cascade** to products or custom products; product `category` is free text in the UI. | l. 3091–3121 |

### 10.2 Security & access-control gaps
1. **Permissions are mostly cosmetic** (see §3.3): `override_price`, `export_quotes`, `view_costing`, `edit_products`, `manage_users`, `import_data` are not enforced server-side; `view_costing` doesn't hide custom-product costing or the pricing API.
2. **IDOR on quotes:** `GET/PUT /quotes/{id}` and add-line check ownership, but **update/delete line, revise, status change, duplicate, PDF export and CSV export do not** — any sales user can modify or export any quote. CSV export dumps **all** quotes to any authenticated user (including operations).
3. **Challans, global search, activity feed, internal notes, optimiser calculation** require only a valid login. The internal-notes endpoint lets any user overwrite notes on any quote/challan/custom product.
4. **JWT in query strings** (`?auth=`) for images, PDFs and CSVs → leaks into logs/history/referrers; 24 h lifetime, no revocation.
5. **Hard-coded bootstrap admin** (fixed email + default password in source, **re-applied on every restart**), default JWT secret fallback in source, `CORS_ORIGINS` defaults to `*` with credentials, no rate-limit/lockout, no password policy server-side. The PRD and test files also list demo credentials. Rotate everything; do not migrate any of it.
6. **Unescaped user input into `$regex`** across product, quote, challan, custom-product and global search (ReDoS / regex injection).
7. Role strings are not validated; users are hard-deleted; no audit trail of who changed prices, roles or permissions.
8. Third-party scripts in `index.html` (Emergent loader + PostHog) run on every page load of an internal tool.

### 10.3 Engineering debt
* One 4.3k-line `server.py`; no routers, services, repository layer or schema validation for most write endpoints (`Dict[str, Any]` bodies) — arbitrary fields can be written to documents.
* N+1 query patterns (configurator match enrichment, challan list line counts, challan summary counts, recent products).
* No transactions: quote total recomputation after line changes is multi-step and can drift.
* Duplicated/overlapping packaging field names (§4.4); free-text `dimensions` / `thickness` strings on quote lines and custom products rather than numeric fields.
* PDFs use core Helvetica (Latin-1): customer names with other scripts (or the € / ₹ symbols) would raise errors; fixed row heights and truncation (30–40 chars) lose data.
* Emergent-specific storage and key (`EMERGENT_LLM_KEY`) — storage must be re-platformed.
* Tests are live-environment integration tests (need a deployed URL and seeded credentials); no unit tests, no CI config, no frontend tests.
* Unused dependencies on both sides (§2, §8.4).

---

## 11. What to reuse vs. redesign for the new ERP

**Carry over as requirements / domain knowledge (high value)**
* The **product data model**: `product_key` as the immutable business key separate from a non-unique display SKU; master + pricing (many) + packaging (1) + specifications (1) + media (many); category/subcategory taxonomy; decor + thickness + size + finish as the variant dimensions.
* The **import discipline**: taxonomy first, validate categories, orphan detection, preview → import → validate, row-numbered errors. Keep the column alias list (§4.4/§5.3) — it documents the legacy spreadsheet formats you must still ingest.
* **Quotation behaviour users already rely on:** search-first configurator with narrowing filters, snapshot lines, override-with-reason, advisory MOQ, EUR 5,000 minimum / EUR 400 surcharge, versioned revisions with status history, duplicate, PDF, three line types (catalog / custom / manual), customer type and incoterm.
* **Custom-product lifecycle** (inquiry → development → sample → quoted → approved → converted/rejected/dormant) and the idea of promoting a custom item to the master catalogue (stubbed, never implemented).
* **Sheet optimiser inputs/outputs** (group by decor + thickness, grain-lock list, margin/gap/oversize parameters, efficiency & scrap KPIs, per-board layout). Re-implement the packer properly (true MaxRects/skyline or a library) and persist results against production orders.
* **Challan semantics** (types, returnable vs non-returnable, destinations, GSTIN/HSN, DC-YYYY-NNNN numbering, T&Cs, signatures) — but model them as inventory movements with returns reconciled against the issuing challan.
* **Role intent:** admin / management / sales / operations and the 14 named permissions are a decent starting vocabulary; make them real, server-enforced, and extensible (module + action + scope).
* **UX patterns users have validated:** global `/` search across modules, data-completeness dashboard, recent-activity feed, auto-saving internal notes, duplicate actions, CSV exports, print-friendly documents.

**Do not carry over**
* The single-file backend, schemaless `Dict` writes, query-string tokens, hard-coded admin/credentials/secrets, Emergent storage/scripts/analytics, free-text customer fields, cosmetic-only permissions, per-currency-label-without-FX quoting, count-based document numbering.

**Open questions worth deciding before design starts** (not answerable from code)
1. Is the ERP single-company (Crown Decor Pvt. Ltd.) or multi-entity (Crown vs Lamikraft brands)? Are Indian GST/e-way-bill compliance and export documentation both required?
2. Domestic (INR) vs export (EUR) pricing: the code supports multiple price types/currencies but the commercial logic is EUR-only — what are the real price-list rules, per customer type?
3. Does the sheet optimiser need to feed purchasing (boards by decor/thickness) and production, or stay a calculator?
4. Should historical data (products, quotes, challans) be migrated, and in what form? (Only products/pricing/packaging/specs/media/taxonomy have importers today; quotes/challans/custom products do not.)
5. What approval rules apply to price overrides, below-MOQ quotes and below-minimum orders (currently advisory only)?

---

## 12. PRD vs. code discrepancies

`memory/PRD.md` is broadly accurate about *what was built* but overstates a few items:

| PRD says | Code reality |
|---|---|
| "Cancelled/Archived statuses added" (Phase 7) | UI only; backend status endpoint rejects them (§10.1 #1) |
| Quote analytics, margin calculator, bulk price export, customer master, approval workflow, quote-to-order | Not built (listed by PRD as P1/P2 backlog — correct) |
| "Role-based price override: Operations = none" | Enforced in the UI only |
| "Ownership Enforcement: Sales get 403 on others' quotes" | True for view/update/add-line; not for line edit/delete, revise, status, duplicate, PDF, CSV (§10.2 #2) |
| "Dynamic Permission Resolution… merged at runtime" | True for `/auth/me` and UI; backend uses it for only three checks |
| "Data Completeness: missing EUR price / MOQ" | "Missing price" counts products with *no* pricing row of any currency; "missing MOQ" is `pricing rows − rows with moq` (not per product) |
| "Phase 1: 7 CSV imports" | 7 importers exist; `lookup_reference` data is never used anywhere |
| Admin credentials in PRD (`admin`) | Code bootstraps a different, fixed admin and resets its password each restart |
| "Refactor server.py (~3900 lines)" | Now 4,318 lines |
| `design_guidelines.json` (navy/slate palette, 8 product tabs) | Implemented theme is warm gold/brown; 5 tabs |

---

## 13. Testing & delivery history

* **Iterations 1–14** (reports in `test_reports/`), each "all verified" by an automated testing agent: 9 (PDF/CSV export, category CRUD, thickness fix, branding), 10 (management quote access, role-based override, customer type, surcharge toggle, duplicate, password toggle, role page — 14 backend tests), 11 (permissions/ownership — 23), 12 (sheet optimiser — 19), 13 (challans — 31), 14 (global search, completeness, activity, duplicates, notes, CSV — 33).
* Pytest files in `backend/tests/` (≈5.3k lines) cover: access control, challans, quotation engine, quote-builder rewrite, sheet optimiser, SKU portal, imports (pricing/specs/packaging-media), finishing improvements. They run against a **live URL with real credentials**, so they are regression references for expected behaviour, not CI-ready tests. They did not catch the defects in §10.
* `test_result.md` and `.emergent/summary.txt` are platform bookkeeping (the summary is stale: it still says the quotation engine is "testing pending").
* Git history is ~40 machine-generated "auto-commit" snapshots plus a few commits about resetting the production admin password (`dashboard.lamikraft.com`). Deployment topology beyond that is not in the repo (no Dockerfile, CI or infra files).

---

*End of document. Generated from a read-through of the repository; no code was changed.*
