# Lane report: sales (Slice 1, wave 2)

Branch `lane/s1w2-sales`, worktree `D:\lk-wt\sales`, env slot 6 (API 8060, databases `lk_wt6` / `lk_wt6_test`).
Branched from `lane/s1w1-catalogue`, which was merged in again after its review-fix pass (`13e76b2`, adapted in
`98dbad4`). Scope: enquiries, customer messages, quotes, the quotation PDF, agent tools, source readers, the
`sales.quote.review` approval handler and the fixture seed. Status: **implemented and green**. The only failing gate
step is the expected `api:check` (new routes, so `backend/openapi.json` and the web schema types need regenerating).

## 1. Implemented items

### Data (`backend/app/modules/sales/models.py`, migration `0007_sales_slice1.py`, `down_revision = "0005"`)
- `sales_enquiry` (`ENQ-{yyyy}-{seq:04}`, yearly reset, document date = business date in the company zone),
  `sales_customer_message`, `sales_quote`, `sales_quote_line`, `sales_quote_status_history` (append-only),
  `sales_quote_revision` (append-only, one row per issue) and `sales_quote_dispatch`.
- Every table: forced fail-closed RLS (`helpers.enable_tenant_rls`), varchar + CHECK enumerations mirroring the
  StrEnums (contract-tested), UOM CHECK on line units, `version` for optimistic concurrency on editable rows.
- `sales_quote_line (quote_id, line_no)` unique constraint is `DEFERRABLE` so remove/renumber runs in one
  transaction through `uow.defer_constraints`.
- Quote header: immutable `quote_number` (`{brand}-QT-{yyyy}-{seq:04}`, never reset, one counter shared by brands),
  party snapshot (name, country, currency, contact, addresses; refreshed only explicitly), owner/branch, enquiry and
  origin message, price type, currency, incoterm (+ place), payment terms, validity days, `valid_until` (set at issue),
  customer reference, remarks, surcharge toggle, status (exactly the eight Slice-1 statuses), `revision_no`,
  `issued_at` / `sent_at`, closing fields, persisted engine totals (NUMERIC(18,4) + currency, the full calculation
  JSON, input hash, rule-set version), `line_count`, review bookkeeping (`review_proposal_id`,
  `approved_proposal_id`, `approved_content_hash`, `content_hash`), soft delete.
- Lines: `line_key` (stable uuid), catalog | manual (custom kept in the CHECK for Slice 2), quantity + uom,
  `default_unit_price`, `unit_price`, `override_reason`, discount %, gross/discount/total, Pydantic-validated JSONB
  snapshots (product, packaging, media hint, commercial: price list, item, tier, resolution date), manual presets,
  `internal_note` (never on documents).

### Enquiries and customer messages (ADR-036, `enquiries.py`)
- Create / update / list / get with filters before paging; assignment needs `sales.enquiry.assign`; creating a quote
  from an enquiry marks it `quoted`; closing needs an `outcome_code`; closed enquiries are frozen (`enquiry_closed`).
- `record_customer_message` (received_at from the Clock when absent) and `mark_replied`; the body is external
  content (stored, never fed to rules, never in event payloads).
- Events exactly as events.md §3.6.

### Quotes (`quotes.py`, `transitions.py`, `state.py`, `approvals.py`)
- `create_quote`, `update_quote`, `add_line`, `update_line`, `remove_line` (renumber under deferred constraint),
  `refresh_snapshots`, `delete_quote`; each one unit of work with `expected_version` and `Idempotency-Key` replay.
- Totals are always computed by `commercial.service.calculate` (rule set `quote_commercial`) and persisted in the
  same transaction; the API, list rows, readers, revision snapshot and PDF all read the persisted result (BUG-03).
- Catalog prices via `pricing.service.resolve_price`; ambiguous → 409 `price_ambiguous`; a different unit price or a
  discount needs `sales.quote_price.override` and a reason (or `sales.quote_price.approve` in scope).
  `PRICE_CHANGED_SINCE_SNAPSHOT` is reported on read until an explicit refresh.
- One transition table `(from_status, action) → Transition(to_status, permission, requires_reason, guard, event,
  idempotency_required)`: `submit_review`, `withdraw_review`, `mark_sent` (issue), `mark_won`, `mark_lost`,
  `cancel`. Anything else (including `archive`, `revise`, …) is 409 `invalid_transition` with
  `allowed_transitions` (BUG-01). Every transition appends history, emits the specific event and
  `sales.quote.status_changed`, and audits.
- Issue (`mark_sent`): refuses an override / discount / below-minimum quote without an approved review for the
  current content hash (`review_approval_required`); freezes an immutable revision snapshot with its document
  sha256; `valid_until` = issue date in the company zone + validity days; records a dispatch; emits `issued` then
  `marked_sent`; enqueues `sales.document_render`.
- `sales.quote.review` handler: `approve_permission="sales.quote.approve"`, `can_decide` also needs
  `sales.quote_price.approve` for price exceptions and an approve scope covering the quote; approval records the
  approved proposal and content hash (quote stays `internal_review`); rejection returns it to `draft` with history
  and `status_changed` (action `review_rejected`).
- Reads: `get_quote` (capabilities, allowed transitions, review state, redactions), `list_quotes` (`q` escaped
  ILIKE over number / party name / country, status, scope mine|all bounded by read scope, owner, party, paging),
  `status_counts`, history, revisions, revision detail.

### PDF (`documents.py`)
- Rendered from the issued revision snapshot only through `app.core.documents` (A4, embedded Noto fonts, repeated
  table header, totals block with surcharge and threshold note only when the persisted result applied them,
  "Grand total (excludes taxes)", Demo terms, "Page x of y"). Deterministic bytes; `document_sha256` stored at issue
  and verified by the `sales.document_render` job. Seam `store_rendered_document(uow, revision, pdf_bytes)` only
  verifies the hash today.
- `GET /api/v1/sales/quotes/{id}/revisions/{n}/document.pdf`: `application/pdf`, `inline; filename*=…`,
  `Content-Security-Policy: sandbox`, ETag = sha256; nosniff and `Cache-Control: no-store` come from the
  request-context middleware. Authorised through the quote policy (`sales.quote.export`).

### Tools, readers, seed
- Tools: `find_usual_order` (read; latest won quote of the party visible to the actor) and `draft_quote` (draft,
  idempotent, `sales.quote.create`); `resolve_party` / `resolve_product` / `resolve_price` / `calculate_quote` are
  reused from their modules. Inputs carry no identity fields.
- Source readers `sales.quote`, `sales.customer_message`, `sales.enquiry` (a superset of the facts the work lane's
  fake readers expose; money is the grand total in currency minor units, e.g. `5700.00`).
- Seed `sales.world` (order 50): fixtures.md §7.1–§7.4 through the services at each fact's time — 2 enquiries,
  2 messages, quotes `LK-QT-2026-0001` … `0008` from the real allocator, histories, overrides with their reasons,
  reviews at D0 08:20 / 08:30 / 08:45 (`PROP_MAISON`, `PROP_THORNBURY`, `PROP_NORDHAUS`); idempotent on business keys.

### API (`router.py`)
- 26 routes under `/api/v1/sales` with the brief's operationIds (`sales_list_quotes` … `sales_calculate_quote_preview`),
  each declaring `requires(...)`; Page responses; problem+json errors.

## 2. Fixes made while finishing the tests (this session)
| Defect | Fix | Commit |
|---|---|---|
| `submit_review` wrote the quote twice, so the proposal bound to an intermediate version and every decision came back `invalidated (target_changed)`; seeded reviews could never be approved | one UPDATE, proposal bound to `version + 1` | `1f58909` |
| content hash used the in-memory decimal scale (`16.5` vs `16.5000` from NUMERIC), so quote and proposal hashes disagreed and approvals never became current | decimals normalised before hashing | `1f58909` |
| `withdraw_review` only with a pending proposal: an approved / expired / invalidated review was stuck in `internal_review` | always available from `internal_review` | `1f58909` |
| withdraw / cancel: the session does not autoflush, so the withdrawn proposal was then overwritten as `invalidated`; `approvals.get` raised 404 for a non-eligible actor | flush after withdraw; tolerate invisible requests; issuing invalidates a still-pending review | `1f58909` |
| PDF route duplicated `X-Content-Type-Options` and `Cache-Control` that the middleware appends (`nosniff, nosniff`) | headers left to the middleware | `dd24f8c` |
| reader money was `5700.0000` (column scale) instead of the currency amount | quantised to minor units | `ccb8ec2` |

## 3. Tests
- `tests/integration/sales/`: header, numbering (40 threads, committed, barrier), lines (snapshots, presets,
  override rule, integer UOM, ambiguity), totals (persisted, renumber, Scenario D quote level, preview = persisted),
  status (table, rejection / approval invalidation, append-only, immutable revision, cancel/archive, permissions,
  idempotency, dispatch), delete, IDOR matrix + export scope, list (filters, scope, paging, metacharacters, tabs),
  enquiries, messages, readers, seed world (numbers, facts, idempotency, decidable reviews), Scenario C, HTTP surface.
- `tests/integration/documents/`: `test_quote_pdf.py::test_layout_unicode_pagination_and_totals` (+ non-EUR,
  headers/scope), `test_output_channels_agree.py::test_api_pdf_csv_print_totals_identical` (API detail, list row,
  snapshot and PDF; CSV/print are Slice 2).
- `tests/contract/sales/test_lane_schema.py`: enum CHECKs, forced RLS, append-only triggers vs `__append_only__`,
  events/payloads/keys in the frozen catalogue, registered tools/readers/handler/sequences/seed/job/policies.

## 4. Gates
- `npm run test:api`: `330 passed in 272.23s` (sales integration 47, documents 4, sales contract 5 among them).
- `npm run check -- --keep-going`: ruff PASS, pytest unit + contract PASS (`162 passed`), alembic heads == 1 PASS,
  **api:check FAIL (`backend/openapi.json is out of date`, expected: new routes)**, web lint / typecheck / vitest PASS
  (`134 passed`).

## 5. Deviations and notes
- PDF metadata dates: `app.core.documents.build_pdf` runs ReportLab in invariant mode (fixed dates), so the
  creation date is the invariant one, not the snapshot's `issued_at`. Output is deterministic either way; changing
  it is a kernel change.
- `sales.document_render` is enqueued directly by `mark_sent` and by the `sales.quote.issued` subscription; both use
  the same dedupe key, so one job runs.
- A never-issued quote's document is 403 `quote_not_issued` (visible, nothing to export), not 404.
- `sales.quote.delete` is held only by admin templates in the catalogue (Priya); sales and management cannot
  delete drafts (they cancel).
- Proposals are submitted from `submit_review`, which relies on the quote being clean at that point (one UPDATE →
  `version + 1`); `test_seeded_reviews_are_decidable` guards it.

## 6. Requests for the integrator
1. Regenerate `backend/openapi.json` and `apps/web/src/lib/api/schema.d.ts` (26 new sales routes).
2. At merge with the work lane: remove the fake `sales.quote` / `sales.customer_message` / `sales.enquiry` readers
   and the fake `sales.quote.review` handler from `tests/integration/briefings/world.py`; the real ones register in
   `sales` `on_load`. The real quote reader adds facts (superset); message `is_closed` is `true` once replied.
3. Wire `store_rendered_document` to `platform/files.store_generated` after the platform lane merges.
4. `RequestContextMiddleware` appends `x-content-type-options`, `cache-control: no-store` unconditionally; a route
   cannot choose its own Cache-Control. Consider "set if absent".
5. The approvals engine's `get` hides a proposal from anyone who is not the requester or an eligible approver;
   `withdraw` is requester-only. Sales works around both (management pulling a quote back invalidates the request).
