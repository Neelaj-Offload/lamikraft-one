# Lane report: Slice 2 — delivery challans as documents (`lane/s2w2-challans`)

Worktree `D:\lk-wt\work`, env slot 4, branched from `main` c94a13d. Never pushed. Scope: PLAN Slice 2 "challans as
documents" with full legacy parity (CURRENT_STATE_SPEC §4.15, §5.8, §10.1 #13/#14, §10.2 #3/#6; build prompt item 10).
**No stock movement**: `inventory_effect` is always `none` and the posting ids stay null; the Slice-4 movement policy
attaches to the same documents later.

## What was built

### Backend — `backend/app/modules/challans/`
| File | What |
|---|---|
| `models.py` | `challans_challan` (every legacy header field as printed text plus structured links: party, consignee, office/source branch, warehouse ids for S4), `challans_challan_line` (catalog/custom/manual, product link, HSN/SAC, NUMERIC(18,6) quantity, UOM FK, deferrable `(challan_id, line_no)` unique), `challans_return_link` (a Return line against an original line, `returned_qty` running total with CHECK), `challans_challan_revision` (append-only issued snapshot + PDF sha256), `challans_challan_status_history` (append-only) |
| `movement_policy.py` | the type × return type × destination matrix (Job Work forced returnable, Transfer to warehouse/office…) enforced on every save; party role per destination; direction |
| `state.py`, `transitions.py` | the state machine as one table: draft→issued (`issue`, Idempotency-Key required), draft→cancelled (reason), issued→closed, issued→cancelled (restricted `reverse`, reason, blocked while returns exist). Unknown/disallowed → 409 `invalid_transition` with `allowed_transitions`; history row, catalogued event and audit per transition; a fully returned original auto-closes |
| `service.py` | create (DC number through the yearly allocator), header PATCH and line add/edit/remove with `expected_version` (409 `version_conflict`), 422 with field locations, issued challans immutable (409 `challan_not_editable`), duplicate (new number, today, copies lines), admin-only soft delete of drafts (number never reused), scoped list with filters before paging, summary cards over the same filters and scope, CSV export rows |
| `documents.py` | one snapshot → ReportLab PDF via `app.core.documents` (Noto fonts, FROM/TO, line table, total quantity per unit, terms from `document_terms`, three signature boxes, DRAFT watermark, page x of y), the print-view data and the CSV (`core/csv_safe`, BOM, formula-inert) |
| `router.py` | `/api/v1/challans/challans` list, `summary`, `export.csv`, `lookup`, create, detail, PATCH, DELETE, lines POST/PATCH/DELETE, `transitions`, `duplicate`, `revisions`, `revisions/{n}`, `print`, `document.pdf`, `revisions/{n}/document.pdf` |
| `policies.py` | record scope (own/team/branch/company on `owner_user_id`, `branch_id`); lines, history, revisions and return links authorised only through the challan (404 for every child of an invisible challan) |
| `search.py` | global search provider "Challans" (number, destination, shipping name, reference; escaped ILIKE; scoped) |
| `readers.py`, `tools.py`, `jobs.py`, `events.py` | source reader `challans.challan` (never the note), agent tool `draft_challan` (draft only), `challans.returnables_sweep` (`became_due` / `became_overdue` once each), sequence `DC-{yyyy}-{seq:04}` yearly, setting `challan_defaults` (source text, expected return days) |
| `app/seed/world/challans.py` | DC-2026-0001 (Job Work to Precision Edge, issued D-7), DC-2026-0002 (Sample to Maison, issued D-3), DC-2026-0003 (Outward draft to Nordhaus, D0) — `slice_no=2`, idempotent by `origin_ref` |

Internal notes are `platform/collab` notes on `challans.challan` (parent `update` to write, editable after issue, never
printed or exported). Quantities are never added across units (`quantity_by_unit`, `outstanding_by_unit`).

### Web — `apps/web/src/features/challans/`
| Route | Screen |
|---|---|
| `/operations/challans` | list with `FactStrip` summary (total, this week, this month, pending returns, issued — each links to the filtered list) and the outstanding quantity per unit; URL-state filters (search, status, type, destination, period, pending returns, mine/all); `DataTable` with phone roles; CSV export link; New challan (capability-gated) — server prefetch + hydration |
| `/operations/challans/new` | every legacy header field; choices follow the movement policy; party picker by destination role; only the destination is required; 422 mapped to fields |
| `/operations/challans/[challanId]` | `RecordHeader` + actions only from `allowed_transitions`/`capabilities` (Issue, Close, Cancel with reason codes, Duplicate, admin Delete, PDF, Print view); details (FROM/TO), edit drawer for drafts; lines with **600 ms debounced quantity autosave**, one save at a time per document, inline Saved / Not saved + Retry (never silent), leave-page warning; add catalogue/manual line (Return lines pick an original line); returns, history, internal note autosave with 409 merge text kept |
| `/print/challans/[challanId]` | print view without the shell (`(print)` layout), from the same data as the PDF |
Plain modules `list-state.ts`, `form-model.ts`, `line-save.ts` (server pages never call client functions). Copy in
`src/messages/challans.ts`. Operations overview now links the delivered challans part.

## Parity rows → code and named tests
All tests under `backend/tests/` unless noted; vitest = `apps/web/src/features/challans/challans.test.tsx`; e2e =
`apps/web/e2e/challans.spec.ts` (the matrix names `e2e/scenarios/l-legacy-parity.spec.ts`; the integrator should
point those rows at `e2e/challans.spec.ts`).

| Row(s) | Test |
|---|---|
| LM-80, LM-81, LM-82, FG-DC-05, LP-10.1 | `integration/challans/test_challan_crud.py::test_all_types_return_types_destinations` |
| FG-DC-03 | `unit/challans/test_movement_policy.py::test_policy_matrix_all_types_and_invalid_combinations` (+ `test_defaults_direction_and_party_roles`, `test_every_type_accepts_its_default_return_type`) |
| LM-83, FG-DC-12, UI-79, LP-10.3 | `unit/challans/test_status_machine.py::test_valid_and_invalid_transitions_table`, `::test_reasons_guards_events_and_idempotency_requirements` |
| API-60 | `integration/challans/test_challan_status.py::test_transitions_validated_and_issued_immutable`, `::test_transition_over_http_is_replay_safe_and_conflicts_are_problems` |
| **BUG-14** (named regression) | `integration/challans/test_challan_regressions.py::test_bug_14_status_only_through_transitions_and_line_edits_never_silent` (+ the status tests above; web half: vitest `debounced line saves (UI-83, BUG-14: never silent)`, e2e `challan_failed_save_shows_inline_retry`) |
| LM-84, FG-DC-02, FG-DC-04, FG-DC-06, FG-DC-08, FG-DC-09, FG-DC-13, UI-78 | `integration/challans/test_challan_crud.py::test_header_fields_round_trip` |
| FG-DC-07 | `integration/challans/test_challan_crud.py::test_gstin_format_checked_not_verified` |
| LM-85, FG-DC-01, BR-08 | `integration/challans/test_challan_numbering.py::test_concurrent_dc_numbers_unique_yearly_reset` |
| BUG-13 (challan part) | `integration/challans/test_challan_regressions.py::test_bug_13_deleted_draft_number_is_never_reused` + the numbering test |
| LM-86, FG-DCL-02…07, FG-REL-04, UI-81, API-62, LP-10.2 | `integration/challans/test_challan_crud.py::test_lines_with_product_lookup_and_uom_rules` |
| API-63 | `integration/challans/test_challan_crud.py::test_line_edit_version_conflict_and_validation`, `::test_line_edit_over_http_replays_and_reports_failures` |
| LM-87, API-57 | `integration/challans/test_challan_crud.py::test_list_filters_before_paging` |
| LM-88, API-58, UI-28 | `integration/challans/test_challan_summary.py::test_summary_counts_scoped`, `::test_summary_and_list_agree_over_http` |
| LM-89, API-65 | `integration/challans/test_challan_crud.py::test_duplicate_with_lines_new_number` |
| LM-90, API-59 | `integration/challans/test_challan_documents.py::test_csv_escaped_and_scoped` |
| LM-91, API-64, FG-DC-10, UI-85, BR-13 (challan part) | `integration/challans/test_challan_documents.py::test_pdf_unicode_pagination_terms_signatures_no_internal_notes` |
| LM-92 | `integration/challans/test_challan_documents.py::test_print_view_matches_pdf_and_api`; e2e `challan_print_preview` |
| LM-93, API-61, LP-10.4 | `integration/challans/test_challan_permissions.py::test_admin_only_draft_delete_number_not_reused`; e2e `challan_admin_draft_delete` (UI-84) |
| FG-DCL-01, SEC-03 (challans), PERM-23 (challans) | `integration/challans/test_challan_permissions.py::test_scope_enforced_on_read_edit_issue_export_and_admin_only_draft_delete`; `contract/challans/test_lane_schema.py::test_routes_declare_their_permissions` |
| LM-94 (S2 part: return document links, no stock) | `integration/challans/test_issue_return_cancel.py::test_partial_return_linked_to_original_line`, `::test_cancel_issued_is_document_only_and_blocked_by_returns` |
| LM-95, FG-DC-11 | `integration/collab/test_internal_notes.py::test_notes_never_printed` |
| LM-96 (challan provider), SEC-06 (challans) | `integration/challans/test_challan_regressions.py::test_sec_06_search_terms_are_literal_and_global_search_is_scoped` |
| UI-19, UI-77, UI-80, LP-11.4 (challans), SCN-L1 (challans) | e2e `challan_create_duplicate_print_csv`; vitest `screens (server render)` |
| UI-83 | vitest `debounced line saves …`; e2e `challan_failed_save_shows_inline_retry` |
| REUSE-06 (S2 part) | the rows above; S4 adds the movement |
| events | `contract/challans/test_lane_schema.py::test_emitted_events_and_payloads_are_in_the_frozen_catalogue`, `::test_state_table_uses_catalogued_keys_and_events`; sweep `integration/challans/test_seed_tools_sweep.py::test_returnables_sweep_emits_due_then_overdue_once` |
| seed / tool | `integration/challans/test_seed_tools_sweep.py::test_seed_world_matches_fixtures_and_is_idempotent`, `::test_draft_challan_tool_creates_an_owned_draft_only` |

Not this lane (deferred with reason): LP-10.5, LP-10.6, SCN-I3 (`test_issue_posts_exactly_one_movement`, reversal
postings, job-work ownership) — Slice 4 inventory; e-way bill / GST value — future scope (LM-94); LM-98 activity feed —
platform-2 lane (collab activity projector); DEBT-02 challan N+1 — list/summary are batched (`_lines_by_challan`,
grouped counts) but no query-count assertion was added.

## Migration
`backend/migrations/versions/0010_challans_slice2.py` (revision `0010`, down `0009` = main's head when branched). Five
tables, forced fail-closed RLS, append-only triggers on revisions and history, immutable `challan_number`/company,
enum CHECKs, deferrable line-number unique. **The integrator renumbers it onto the Slice-2 chain** (not renumbered here).

## Registry additions (additive)
- `app/seed/world/keys.py`: `CHALLANS` (DC-2026-0001..0003), `CHALLAN_REFS` (`DC_<KEY>`), `CHALLAN_LINES`.
- `app/seed/runner.py`: `facts.challans` and business-key refs `DC-…` → id in `/_test/fixtures`.
- Module manifest: sequence `challans.challan`, setting `challan_defaults`, search provider, tool `draft_challan`,
  job + schedule `challans.returnables_sweep`, reader `challans.challan`, seed `challans.world` (order 52, slice 2).
- Permissions and events: none added — all `challans.challan.*` keys and the six `challans.*` events come from the
  frozen catalogues (permissions.md §7.6, events.md §3.9).
- Web: `routes.ts` (`operations-challans` context, `operations-challan-new`, `operations-challan`, `print-challan`),
  `query-keys.ts` (`challans.*`, invalidation `challans.challan_changed` / `challans.challan_transition`),
  `messages/challans.ts`, `messages/areas.ts` (`PlannedPart.href`, `liveNote`), `e2e/support/world.ts` (`PRIYA`),
  `e2e/axe-sweep.spec.ts` (`challanId` candidate).
- OpenAPI: `backend/openapi.json` and `apps/web/src/lib/api/schema.d.ts` regenerated (100 paths). Generic schema
  names are Challan-prefixed (`ChallanLineType`, `ChallanUserRef`, `ChallanPeriod`, …) so the sales `LineType` keeps
  its component name.

## Integrator requests
1. Renumber `0010_challans_slice2.py` onto the merged Slice-2 chain.
2. The challan line `custom_product_id` has no FK yet: add `FOREIGN KEY → commercial custom products` once the
   commercial-2 lane's table is on the chain, and validate the id in `service._build_line` for `line_type=custom`.
3. `keys.PARTIES.PRECISION_EDGE = "P-00006"` assumes Kaveri (`P-00005`) is created first by another Slice-2 seed; on
   this branch alone Precision Edge gets `P-00005` (`seed/world/challans.py::_ensure_fabricator` creates it only when
   the parties seed has not). Tests compare by ref, not number.
4. e2e seeds with `lk seed demo` at slice 1, so the challan fixtures are not in the e2e world; `e2e/challans.spec.ts`
   creates its own challans. Seed e2e with `--slice 2` once all Slice-2 seeds are merged (the axe sweep then covers
   `/operations/challans/[challanId]` and `/print/challans/[challanId]`).
5. PARITY_MATRIX: mark the rows above implemented with these test names; point the `l-legacy-parity.spec.ts` names at
   `e2e/challans.spec.ts`.
6. The `ops.returnables` rule family (tasks lane) consumes `challans.returnable.became_due/overdue`; not built here.
7. `ui/recent-records` does not accept `challans.challan`; the workspace therefore does not record recent records.
8. `tests/integration/agents/test_runtime_guards.py::test_tool_input_extra_fields_and_unknown_tools_are_errors`
   used `draft_challan` as its example of an uninstalled tool; it now uses `propose_stock_movement` (Slice 4).
9. Worktree hygiene: `D:/lk-wt/work/node_modules` predated the CP2 lockfile (no `@fontsource-variable/fraunces`);
   `npm install` from the unchanged lockfile fixed the build. Other old worktrees may need the same.

## Gates (2026-11-03, worktree `D:\lk-wt\work`, slot 4)

| Gate | Command | Result |
|---|---|---|
| API suite | `npm run test:api` | **1106 passed, 0 failed** (log `D:\lk-wt\work-testapi.log`) |
| check | `npm run check -- --keep-going` | **7/7 PASS**: ruff, pytest unit + contract 497, alembic heads 1, api:check (openapi matches), web lint, typecheck, vitest 40 files / 514 tests |
| API generate | `npm run api:generate` | committed (`backend/openapi.json` 100 paths; `apps/web/src/lib/api/schema.d.ts`) |
| e2e (this lane's spec) | `LK_NEXT_BUILD_CPUS=2 NODE_OPTIONS=--max-old-space-size=2048 npm run test:e2e -- e2e/challans.spec.ts --workers=1` (then `--no-build` reruns after spec fixes) | **8 passed** (4 tests × desktop, phone), 4 skipped (tablet: `onlyOnProjects`); own database `lk_wt4_e2e`, slice-1 seed |

Not run here: the full e2e suite (other lanes' specs) and the axe sweep for the new routes (needs `--slice 2` seeding,
integrator request 4).
