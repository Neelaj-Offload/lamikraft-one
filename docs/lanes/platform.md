# Lane report: platform (Slice 1, wave 1)

Branch `lane/s1w1-platform`, worktree `D:\lk-wt\platform`, env slot 2. Migration `0004_platform_slice1.py`
(revision `0004`, down_revision `0002`; upgrade, downgrade and re-upgrade verified on `lk_wt2_test`).

Status: all ten brief items are implemented and tested. Backend suite: **296 passed** (92 that existed before plus
**204 new**). `ruff` is clean and `alembic heads` = 1. In `npm run check -- --keep-going` every step passes except
`api:check`, which fails as expected because routes changed (`openapi.json` and `schema.d.ts` are left to the
integrator).

## 1. Implemented (with paths)

| Item | Files |
|---|---|
| Settings: `setting` and `setting_revision` (append-only) tables; a `SettingDef` registry built from `ModuleManifest.settings`; get/put with an optimistic version, revisions, a masked audit entry and the `org.setting.updated` event | `backend/app/platform/org/{models,settings,service,stepup,schemas,router}.py` |
| Built-in definitions: `company_identity` (unset values are listed in `not_configured_fields`; the default names come from the `company` row), `bank_details` (`accounts[].account_number` is `Restricted("org.bank_account.read")`; `account_number_last4` is always derived), `document_terms`, `quote_defaults` (EUR, FOB, 30, LK, export, duplicate assignee true), `brands` (LK Lamikraft, CR Crown) | `backend/app/platform/org/settings.py` |
| Cross-setting checks: the quote default brand must be a configured brand, and a brand in use cannot be removed. The logo must be a readable PNG or JPEG of the same company | `settings.py`, `backend/app/platform/files/service.py::require_logo_image` |
| Recent-auth step-up for RA permissions (`reauth_required`, 401) | `backend/app/platform/org/stepup.py` |
| Reference data: `currency` (global, RLS-exempt, `lk_app` can only read it; INR, EUR, USD and GBP, all exponent 2); `uom`, `uom_alias` and `uom_conversion` with the 15 seeded codes, aliases and exact standard factors; `convert()` tries a product-specific row, then a generic row, direct or reverse. Anything else raises 422 `uom_conversion_missing`, so nothing is chained or guessed. `validate_quantity()` applies the per-unit entry rules (integer units, at most 4 dp, > 0) | `backend/app/platform/org/reference.py`, `models.py` |
| Work calendar: `GET /org/calendar/me` (source, today's work date, day type, shift window, precompute time, next working day, upcoming holidays) built on the single `workcal.py` (`resolve_calendar` added) | `backend/app/platform/org/{calendar_service,workcal}.py` |
| Seed `org.reference_calendar_settings` (SeedDef order 12): unit master, HO-GEN (Asia/Kolkata, Mon–Sat, GEN 09:30–18:30, rollover 04:00, precompute 30 min, company default on the HO branch), the "Demo holiday" on D0+10 (follows `facts["anchor_d0"]`), and neutral Demo document terms. Identity, bank details and logo stay "not configured". Re-running it is idempotent | `backend/app/seed/world/org.py`, `backend/app/platform/org/manifest.py` |
| Files: `file_object` (UNIQUE company+sha256, random storage key, sniffed `kind`/`content_type`, declared type, purpose, restricted flag); `StorageBackend` protocol with `LocalFsStorage` (`LK_STORAGE_DIR`, keys validated against escaping the root); a streamed multipart receive that hashes and spools while reading and cuts off at the per-purpose limit (image 15, document 25, import 50 MiB); sniffing of PNG/JPEG/GIF/WEBP (verified by decoding with Pillow, bomb-guarded), PDF, XLSX (macro-free OOXML) and UTF-8 CSV/TXT; rejection of SVG, HTML/XML, macro and OLE documents, extension mismatches and purpose mismatches; dedupe; downloads authorised through `register_file_access(resource_type, checker)`, with a creator-only fallback for exports and unreferenced uploads; the company logo is readable by every holder of `org.settings.read`; headers: `nosniff`, `CSP: sandbox`, `CORP: same-origin`, RFC 6266 `filename*`, `inline` only for images and PDF, `private, no-cache` with an ETag and 304 (`no-store` and an audit entry for restricted files and exports); `store_generated()` for files that services create | `backend/app/platform/files/**`, `backend/app/platform/org/files_access.py` |
| Collab notes: `note` (one per record; body at most 20,000 characters). GET and PUT are authorised only through the parent's `ResourcePolicy`: an unknown type or an invisible parent gives 404, a visible parent without `update` gives 403, and `capabilities.update` is reported. A stale `expected_version` gives 409 `version_conflict` with `current` (body, author, time). Emits `collab.note.updated` (ids and version only) | `backend/app/platform/collab/**` |
| Search: the `search_recent` table (newest 10 per user; a repeated search moves to the top); providers are dispatched by their read permission, with an optional `types` filter; each provider runs in its own savepoint, so a failure is reported in `unavailable_groups`; hits are capped per group with `has_more`; the minimum query is 2 characters; `search_terms` and `match_all_terms` turn the query into escaped ILIKE terms only (each term is matched both folded and as typed); the people provider covers active members' name, full name and job title (never contact details) | `backend/app/platform/search/{models,service,people,router,schemas,manifest}.py` (`defs.py` unchanged) |
| Audit read API: filters (action, literal action prefix, actor, resource, outcome, time window with a time zone required) are applied before the limit; keyset paging on `(occurred_at, id)` with an opaque base64url cursor; every read is itself audited; index `ix_audit_log_keyset` | `backend/app/platform/audit/{query,router,schemas,models,manifest}.py` |
| Integration status: the `integration_status` table (a CHECK makes `connected` require `verified_at`) and a registry for `ai.anthropic`, `ai.gemini`, `channels.whatsapp`, `email`, `storage` and `accounting`. The mode comes from config. Live mode with a missing secret shows `error`/`secret_missing`. `record_verification` (called from `run_verification`) is the only way a row becomes `connected`, and it emits `system.integration.status_changed`. UiSection `integrations` (not polled) carries modes and labels for the Demo badges | `backend/app/platform/system/{integrations,models,service,schemas,integrations_router,manifest}.py` |
| Route-authz matrix contract: every mounted `/api` route has one known `x-authz` kind; declared keys are in the catalogue and the registry; the platform lane's routes are pinned; the setting routes cover every SettingDef; operationIds have the form `<module>_<verb>_<noun>` and match the owning module | `backend/tests/contract/system/test_route_authz.py` |
| Registry | `backend/app/registry.py`: appended `app.platform.files`, `app.platform.collab`, `app.platform.search` to `PLATFORM_MODULES` (the only edit) |

## 2. Tests added (204, all passing; 296 in the full suite)

| File | Tests | Covers |
|---|---|---|
| `tests/unit/org/test_settings_defs.py` | 10 | SettingDef contract, catalogue keys, guard paths, built-in models, round trips; hypothesis: an account number never reaches actors without the guard or a model |
| `tests/unit/org/test_reference_rules.py` | 5 | seeded codes and integer units, alias uniqueness, compatible standard factors, `RatioStr` wire format |
| `tests/unit/files/test_sniff.py` | 38 | accepted kinds; SVG, HTML, macro (xlsm, `vbaProject.bin`), OLE, docx, broken zip, extension mismatch, non-UTF-8, NUL and truncated images rejected; decompression bomb; filename sanitising; RFC 6266; storage keys and path escape |
| `tests/unit/search/test_terms.py` | 6 | folding and cap, escaping of `%`, `_` and `\`, regex metacharacters kept as text; hypothesis: any input compiles to ILIKE only, with no unescaped wildcard |
| `tests/integration/org/test_settings.py` | 22 | defaults and not-configured fields, fixture quote defaults and brands, revision/event/audit on write, 409 with the current value, no-op writes, 422 without echoing input, 401/403/404, recent auth, brand rules, bank redaction (sales vs finance, revisions, list, audit, outbox), guard needed to write, derived last4, Idempotency-Key replay / reuse / rights rechecked |
| `tests/integration/org/test_reference.py` | 30 | currencies, read-only currency table, UOM listing and factors, idempotent seeding, exact conversions (parametrised), 422 `uom_conversion_missing`, unknown units, product-specific factors, floats rejected, `org.uom.manage`, entry rules, tenant isolation; hypothesis: lossless round trips |
| `tests/integration/org/test_calendar.py` | 10 | `/calendar/me` at D0 (all dates derived from `keys.CLOCK_D0`), rollover, Sunday and holiday, built-in default, night-shift assignment with its own rollover, 403, manage permission, seed registration/content/idempotency/anchor |
| `tests/integration/org/test_platform_committed.py` | 3 | `@committed`: RLS isolation and fail-closed behaviour on the new tenant tables; concurrent first setting writes (one wins, one gets 409); concurrent uploads of the same bytes (one row, the losing storage copy removed) |
| `tests/integration/files/test_files.py` | 21 | metadata, random key and staging cleanup; dedupe per company; 415 reasons; per-purpose limits (413 while streaming and on `Content-Length`); malformed multipart; 403/401; download headers, ETag/304, inline vs attachment; uploader-only access, tenant isolation, parent checker decides; exports creator-only with `no-store` and audit; generated files sniffed; logo flow |
| `tests/integration/collab/test_notes.py` | 10 | read/save/event; parent not visible gives 404; read-only parent gives 403; unknown type or record; cross-tenant; 409 with the current note and "keep mine"; first-save conflict; no-op save; length limit; Idempotency-Key replay with rights rechecked |
| `tests/integration/search/test_search.py` | 22 | people by name and title, no contact details, inactive and other-tenant exclusion, `%`, `_`, `\`, `.*`, `[a-z]+`, `((`, `^$|` treated as text (each with a decoy), diacritics, minimum length, cap and `has_more`, permission dispatch, `types`, failing or mislabelled provider; hypothesis: every hit contains the literal query; recent searches (order, repeats, per user, keep 10, clear only mine, validation) |
| `tests/integration/audit/test_audit_api.py` | 7 | ordering and actor names, keyset pages that never skip or repeat while new rows arrive, filters (literal `%` prefix, time window), 422 for cursor and naive time, cursor round trip, 403, read audited, tenant isolation |
| `tests/integration/system/test_integrations.py` | 9 | demo/not_connected defaults, admin only, live mode with a missing secret, connected only after verification (events and audit), a verification from another mode ignored, DB CHECK, verification routine, manage permission, UI section |
| `tests/contract/org/test_platform_tables.py` | 4 | forced RLS for the lane's tables, currency grants, append-only triggers vs model flags, `setting_revision` cannot be rewritten |
| `tests/contract/system/test_route_authz.py` | 7 | route-authz matrix (item 9) and operationIds |

Shared helpers: `tests/integration/org/platform_lane.py` (catalogue template grants, `ApiClient` with an injected
server-built actor and the configured Origin), plus a `conftest.py` in each test folder. Notes use a temporary
parent table with a real `ResourcePolicy` (`tests/integration/collab/conftest.py`).

## 3. API endpoints added

| Method and path | operationId | x-authz |
|---|---|---|
| GET `/api/v1/org/settings` | `org_list_settings` | permission `org.settings.read` |
| GET `/api/v1/org/settings/{key}` | `org_get_setting` | permission `org.settings.read` |
| PUT `/api/v1/org/settings/{key}` (optional `Idempotency-Key`) | `org_update_setting` | permission: the manage keys of every registered definition (`org.company.update`, `org.bank_account.update`, `org.settings.manage`, `sales.quote_settings.manage`); the service checks the key of the definition being written |
| GET `/api/v1/org/settings/{key}/revisions` | `org_list_setting_revisions` | permission `org.settings.read` |
| GET `/api/v1/org/currencies` | `org_list_currencies` | authenticated |
| GET `/api/v1/org/uoms` | `org_list_uoms` | authenticated |
| GET `/api/v1/org/calendar/me` | `org_get_my_calendar` | permission `org.calendar.read` |
| POST `/api/v1/files?purpose=image\|document\|import` (multipart part `file`) | `files_upload_file` | permission `files.file.create` |
| GET `/api/v1/files/{file_id}/content` | `files_download_file_content` | authenticated (parent-authorised) |
| GET `/api/v1/collab/notes?resource_type=&resource_id=` | `collab_get_note` | authenticated (parent policy) |
| PUT `/api/v1/collab/notes?resource_type=&resource_id=` (optional `Idempotency-Key`) | `collab_update_note` | authenticated (parent `update`) |
| GET `/api/v1/search?q=&limit=&types=` | `search_list_results` | permission `search.global.use` |
| GET `/api/v1/search/recent` | `search_list_recent` | permission `search.global.use` |
| POST `/api/v1/search/recent` (frontend_verification §12 contract) | `search_create_recent` | permission `search.global.use` |
| DELETE `/api/v1/search/recent` | `search_delete_recent` | permission `search.global.use` |
| GET `/api/v1/audit?action=&action_prefix=&actor_user_id=&resource_type=&resource_id=&outcome=&occurred_from=&occurred_to=&cursor=&limit=` | `audit_list_entries` | permission `audit.log.read` |
| GET `/api/v1/system/integrations` | `system_list_integrations` | permission `system.integration.read` |

## 4. Events

- Emitted: `org.setting.updated` {setting_key, branch_id, version}; `collab.note.updated` {resource_type,
  resource_id, note_id, version}; `system.integration.status_changed` {integration_key, mode, state_from,
  state_to}. Payloads never carry values, note text or secrets (tests check this).
- Consumed: none.

## 5. Permissions used (all from the frozen catalogue)

`org.settings.read`, `org.settings.manage`, `org.company.update`, `org.bank_account.read` (field guard),
`org.bank_account.update`, `sales.quote_settings.manage` (manage key of `quote_defaults`), `org.uom.manage`,
`org.calendar.read`, `org.calendar.manage`, `org.directory.read` (people provider), `files.file.create`,
`search.global.use`, `audit.log.read`, `system.integration.read`, `system.integration.manage`. Notes use the parent
resource's own keys through its policy.

## 6. Settings, sequences, jobs, seeds

- SettingDefs: `company_identity`, `bank_details`, `document_terms`, `quote_defaults`, `brands` (company scope).
- UiSection: `integrations` (`in_poll=False`).
- File access registration: `org.setting` (company logo).
- Seed: `org.reference_calendar_settings`, order 12.
- Sequences and jobs: none.

## 7. Dependencies requested

None. Pillow, python-multipart, openpyxl and hypothesis are already locked.

## 8. Contract questions (for the integrator)

1. **The core route validator sees no routes.** In FastAPI 0.143, `app.routes` holds `_IncludedRouter` wrappers, so
   `app/core/http/authz_decl.validate_routes` and `webhook_paths` currently check nothing. That also leaves the
   WhatsApp webhook without its CSRF exemption once it exists. Fix: iterate `fastapi.routing.iter_route_contexts(app.routes)`
   and use `ctx.path`, as `tests/contract/system/test_route_authz.py` does.
2. **`RequestContextMiddleware` always appends `Cache-Control: no-store`.** File downloads therefore carry
   `private, no-cache` *and* `no-store`, and browsers will not reuse the ETag (api-conventions §11). Proposal: add
   the header only when the response has not set one.
3. **Idempotent commands in `app/platform/service.py`.** With `from __future__ import annotations` the return
   annotation is a string, so a keyed command returns a raw `dict` both on the first call and on replay. A replay also
   skips every check that lives inside the function. The settings and notes services work around this by
   authorising first and then calling an inner idempotent function. A kernel fix would re-run authorisation and
   resolve the annotation with `typing.get_type_hints`.
4. **`DecimalStr` stops at 6 dp, but `uom_conversion.factor` (and FX rates) are NUMERIC(20,10).** Org exposes
   factors as a local `RatioStr` (normalised string, up to 10 dp; e.g. sqft→sqm `0.09290304`). Please add a canonical
   ratio type to `app/core/money.py`.
5. **`quote_defaults` uses `sales.quote_settings.manage` as its manage key** (catalogue, Slice 1, RA), because the
   sales module owns quote policy. Confirm, or move the definition to the sales lane's manifest.
6. **`approvals_withdraw_proposal`** (approvals module, another lane) uses the verb `withdraw`, which is not in the
   api-conventions §13 list. The lane's contract test checks the verb list only on platform routes.
7. **Requested `keys.py` additions** (fixture steward): `HOLIDAYS.DEMO = ("Demo holiday", 10)` (D0 offset),
   `SHIFTS.GEN = "GEN"`, `CALENDAR_HO_GEN_WINDOW = ("09:30", "18:30", "04:00", 30)`. Until they exist, tests read
   these from `app/seed/world/org.py` and derive dates from `keys.CLOCK_D0`.
8. **Requested `routes.ts` entry** (web lane): people search hits link to `/people/[userId]` (a directory card:
   name, title and team only). Alternatively name another target and the provider path will change.
9. The S1 seed links HO-GEN to branch `HO` when the identity seed (order 10) has created it. Otherwise the
   calendar is company-wide.

## 9. Known gaps (with reasons)

- **Upload rate limiting** (api-conventions §11): the `rate_limit_counter` primitive belongs to the identity lane
  and is not on `main` yet. It is a single call to add in `files/router.py` once it exists.
- **MFA enforcement** for MFA-flagged keys (`org.company.update`, `org.bank_account.update`, `audit.log.read`)
  starts in Slice 2 (permissions.md §9). The recent-auth (RA) check is enforced now.
- **pg_trgm ranking**: no extension is installed. Ranking is done in Python (exact, prefix, then word prefix), and
  matching is escaped ILIKE.
- **Deduplicated uploads from a second user**: the existing file id is returned (`deduplicated: true`), but until a
  parent references it, only the first uploader can download it (creator-only rule). Neither the 24-hour expiry
  of unattached uploads nor an uploader-claim table exists yet. Both belong with Slice-2 attachments.
- **Image variants** (`?variant=thumb_256|preview_1024`, EXIF stripping) and the **S3 adapter** are Slice 2 by
  design. `get_storage()` answers 409 `not_configured` for `LK_STORAGE_BACKEND=s3`.
- **Authentication**: identity's session resolver and CSRF verifier are not in this worktree. HTTP tests inject a
  server-built `ActorContext`, and the Origin check stays active.
