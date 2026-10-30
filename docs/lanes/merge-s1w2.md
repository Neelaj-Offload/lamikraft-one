# Lane report: Slice 1 wave-2 merge (acting integrator)

Branch `lane/s1-merge` (from `main` 2832e59), worktree `D:\lk-wt\integ`, env slot 8. Status: **DONE_WITH_CONCERNS**
(every gate green; concerns are listed under "Open items").

## Steps

| # | Step | Commit | Result |
|---|---|---|---|
| 1 | Baseline: slot DBs migrated to head, `npm run test:api` on 2832e59 | (none) | 862 passed |
| 2 | Real identity/ui/search readers in the briefings world | `9833c32` | fake `identity.membership`, `identity.user_preference`, `ui.recent_record`, `search.recent` deleted; onboarding test records a real recent search; reader-removal tests use `monkeypatch` |
| 3 | Merge `lane/s1w2-sales` | `ce3daad` | migration renamed `0008_sales_slice1` (revision 0008, reparented onto 0007); briefings world on the real sales module; `draft_quote` through `idempotent()`; `sales.quote_line` reader; sales seed split into three chronological seeds; 920 passed |
| 4 | Merge `lane/s1w2-agents` | `f2c24fa` | migration renamed `0009_agents_slice1` (onto 0008); swap checklist applied; real catalogue `resolve_product` tool; bootstrap `features.assistant` / `features.voice`; 1058 passed |
| 5 | Merge `lane/s1w1-web` | `cbd928a` | six sales routes kept; briefing/inbox `Wire*` types now generated types; recent-records call on quote/enquiry detail; check green |
| 6 | Product fixes | `f243af8` | party material fields use the parties names; security headers set-if-absent, PDF route sets its own |
| 7 | E2E seed facts | `76f292a`, `5d3b35b` | `/_test/fixtures` publishes `facts.expected`, `facts.quotes`, `facts.enquiries` and refs by business key |
| 8 | Seed demo, Playwright, evidence | `94f1224`, `2492e75` | six product/spec defects fixed (below); 24 screenshots in `docs/evidence/slice-1/` |
| 9 | Final gates | (this report) | see "Gates" |

## Decisions and details

- **Migration chain** (never rewriting merged revisions): 0006 → `0007_ui_recent_record` → `0008_sales_slice1` →
  `0009_agents_slice1`; `alembic heads` = 1. The agents contract test now names 0009/0008.
- **Sales seed order.** `sales.world` (50: enquiries and quotes to D-3), `sales.world.messages` (56: after the Maison
  change at 55), `sales.world.d0` (76: 08:15 override, 08:20/08:30 reviews, 08:40 agent draft, after Arjun's
  activation at 75), so the fixture clock only moves forward (fixtures.md §1 rule 2). Each fact's events are delivered
  at its own time (`_settle`), as the fake world did: the tasks rules re-read current source state, so an obligation
  that opened and closed before the next fact (Maison enquiry, Nordhaus review_draft) must be seen while open.
  `seed_sales` still runs all three (sales tests).
- **Briefings world on real sales.** Fakes, records and fake seeds deleted (`FAKE_READERS`/`FAKE_HANDLERS` are now
  empty; install/uninstall stay as the seam guard). Tests change records through sales services
  (`transition`, `record_message`, `mark_replied`, `create_enquiry`, `agent_draft`, `touch_message`); the Slice-2
  commands sales does not ship (revise, extend validity, notes, owner transfer) are stood in by
  `slice2_quote_change` (real row update and version bump) plus the event that command would emit.
  Test adjustments: the deactivated-assignee message is recorded before the deactivation; the "origin link only"
  test unlinks the message first (real `draft_quote` links it); the overdue sweep counts only the two expiring
  quotes' expiry tasks (won/lost quotes now have done expiry tasks from their history); the seed idempotency test
  drains first.
- **Agents swap.** `fake_sales.py` keeps only the test-only tools (`fetch_external_note`, `send_quote`), the call spy
  and read views of real quotes. Card versions are asserted relative to the drafted version (a real draft is at
  version 2 after its line). `test_agent_c_followup_revise_tool_seam` dropped (sales has no `revise_draft_line`).
  The follow-up test now also sees the line through the screen focus (new `sales.quote_line` reader).
- **Bootstrap** `features.assistant` = agents installed and `agents.assistant.use`; `voice` = false (api-conventions
  §8 updated).
- **Generated types.** Briefing and inbox `Wire*` types alias `components["schemas"]` (they matched); the inbox
  dismissal reason is narrowed to the generated enum. The sales, assistant, approvals, search and session adapters
  parse `unknown` at runtime and their hand types are the parsed shapes; a field-by-field diff against
  `openapi.json` found no field the parsers read that the server does not send. Typing their request bodies with the
  generated types is blocked by openapi-typescript marking server-defaulted request fields as required (left as is).
- **Party fields.** `MATERIAL_PARTY_FIELDS` = addresses, contacts, display_name, legal_name, owner_user_id,
  payment_terms, default_currency (labels: name, legal name, currency).
- **Headers.** `RequestContextMiddleware` adds nosniff, Referrer-Policy and `Cache-Control: no-store` only when absent;
  the PDF route sends `X-Content-Type-Options: nosniff` and `Cache-Control: private, no-store` itself.
- **`store_rendered_document` → `files.store_generated`: not wired.** Not small: issued revisions are append-only
  with no file column, and stored files are readable through per-user claims, so a system render job would store an
  orphan nobody can read. Needs a schema decision (file id on the revision or an attachment link).

## Defects found by the first Playwright run (fixed in `94f1224`, `2492e75`)

1. e2e sign-in had no `Origin` → 403 from the CSRF/Origin middleware (every signed-in spec).
2. Assistant polling stopped after the first response when the run stayed `queued` ("Waiting to start" forever).
3. `/sales/quotes`, `/sales/enquiries`, `/sales/customer-messages` 500: server pages called helpers from `"use client"`
   modules; moved to `features/sales/list-state.ts`.
4. Quote line quantity shown as `240.000000`; the sales parser trims fraction zeros (string-only `trimDecimalStr`).
5. Concurrent rule deliveries for one record both inserted the same `tasks_issue` (pk violation, retried later, so the
   review task reached the Inbox late); `apply_outcome` now takes a transaction advisory lock per issue key.
6. Scenario C reloads the Approvals view until the worker has created the review task.
Also: `/sales/messages/{id}` (the message reader's path) maps to the customer-messages list; quote/enquiry detail
pages record recent records.

## Gates (final, on `2492e75` + this report)

- `npm run test:api`: `1063 passed, 1 warning in 1128.62s (0:18:48)`
- `npm run check -- --keep-going`: ruff PASS; pytest unit + contract PASS (481 passed); alembic heads == 1 PASS;
  api:check PASS; web lint PASS; web typecheck PASS; web vitest PASS (28 files, 410 tests)
- `npm run test:e2e` (fresh `lk seed demo`, `--no-build --workers=1` after the full build): `70 passed, 113 skipped`
  — scenario C desktop and phone (3 steps each), keyboard journey, axe on all 24 manifest routes in light and dark
  (48), login smoke on three projects. Skips are project-restricted specs and the opt-in evidence spec. The first
  full run with the build (2 workers) had 5 axe timeouts and a crashed Playwright worker from memory pressure; the
  same tests pass on the rerun.

## Open items

- **Shared test DB.** `npm run test:e2e` runs on `lk_wt8_test`, which `npm run test:api` uses as its template source;
  after an e2e run the next `test:api` builds worlds on top of the demo data and fails (quote numbers shift). Reset
  with `lk db drop --test --yes && lk db create --test && lk db migrate --test` between them; `scripts/dev.mjs` should
  give e2e its own database.
- `lk seed demo` anchors on today but many fixture times are absolute (D0 = 2026-10-12), so a demo seeded on another
  day shows "overdue" items; e2e passes either way.
- `store_rendered_document` wiring (above); approvals `get`/`withdraw` visibility workaround in sales (sales report 5).
- The issue lock is per key inside `apply_outcome`; a handler reconciling several keys could in theory deadlock with
  another doing them in the opposite order (Postgres aborts one; the job retries).
- Adapters still marked `INTERIM(api-generate)` (sales, assistant, approvals, search, session): runtime-parsed;
  typed request bodies wait on openapi-typescript's defaulted-field handling.
- `next build` printed a security advisory for Next.js 16.4.0 and asked to run an upgrade command; not run (needs a
  decision and a lockfile change). Builds need `LK_NEXT_BUILD_CPUS=2` and `NODE_OPTIONS=--max-old-space-size=2048`
  on this machine.
- Still open from earlier reports: CSRF verifier in a threadpool (identity 4), UOM CHECK → FK, integration_status
  registry for the AI provider, catalogue world's own fake member-actor builder, PARITY_MATRIX/BUILD_STATE update
  after the merge to main.
