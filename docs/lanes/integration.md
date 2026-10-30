# Lane report: integration backlog after the Slice 1 wave-1 merge

Branch `lane/s1-integration`, worktree `D:\lk-wt\integ`, env slot 8 (`lk_wt8`, `lk_wt8_test`). This lane acts for
the integrator on the cross-lane and kernel-owned requests in `docs/lanes/{identity,platform,catalogue,work,web}.md`.
Migration `0007_ui_recent_record.py` (revision `0007`, down_revision `0006`): it collides by number with the sales
lane's `0007_sales`, so reparent at merge (one of them becomes `0008`).

## 1. Items

| # | Item | Commit | Status |
|---|---|---|---|
| 1 | `LK_TRUSTED_PROXY_HOPS` in core `Settings` (default 0, `.env.example` note: 1 behind the production proxy); identity reads it from settings; uvicorn `--no-proxy-headers` for dev and e2e; production command in `docs/runbooks/local-dev.md` | `7302e65` | done |
| 2 | Kernel `app.platform.bootstrap.build_sections` runs each section in its own SAVEPOINT; the ui module calls the kernel and its copy is gone | `0b61846` | done |
| 3 | Platform post-merge swaps: core `RatioStr` in org schemas; `keys.py` fallbacks deleted from the org seed; exact Cache-Control download test no longer xfail; upload limiter = identity's `rate_limit_counter` installed by identity `on_load` through `set_upload_limiter` (per-process window removed, missing limiter fails closed) | `434c756` | done |
| 4 | `keys.py` constants for catalogue and work (brands, party refs and contacts, taxonomy, product/decor names, price-list refs/names/items, rule set, quote/enquiry refs, `TEXTS`, `ONBOARDING_STEPS` + titles, `TIMES`, `EXPECTED.MEERA_S1_ITEM_ORDER`, `EXPECTED.BERLIN_DUE_LABEL`); seeds and tests import them; fixtures.md §12 in sync | `b62c6cc` | done (see 3.1) |
| 5 | SourceReaders `identity.membership`, `identity.user_preference` (identity), `ui.recent_record` (ui: `ui_recent_record` table with RLS, `POST /api/v1/ui/recent-records`), `search.recent` (search); tests for facts and visibility; OpenAPI and `schema.d.ts` regenerated | `eaf38ed` | done |
| 6 | `app.core.http.capabilities.{Capability, TransitionRead}`; approvals, catalogue, commercial, parties, pricing, tasks, collab and org import them | `62944b3` | done (see 3.2) |
| 7 | `migrations.helpers.immutable_columns(table, columns)` with a contract test (SQL) and an integration test (PostgreSQL) | `052277c` | done |
| 8 | Docs: PARITY_MATRIX pointers and statuses, api-conventions §8 feature flags, conventions §3 | see §5 | done |

## 2. Details

- **Upload limiter (3).** `app.platform.identity.ratelimit.upload_limiter(limit=60)` counts in bucket
  `upload:user:<company>:<user>` of `rate_limit_counter` (fixed 10-minute window, its own short transaction so a
  rejected or failed upload still counts). `set_upload_limiter` now returns the previous limiter (tests restore
  it); `check_upload_rate` raises `RuntimeError` when no limiter is installed (never silently unlimited).
- **Readers (5).** All four answer `None` to an actor who may not see the facts. `identity.membership`: directory
  facts (`user_id`, `display_name`) for `org.directory.read`; `role_templates` and `manager_membership_id` only for
  the system, the member and `identity.user.read`. `identity.user_preference`: `briefing_saved`, `locale_saved`
  (system and self only). `ui.recent_record`: `count`, `by_type` (system and self only). `search.recent`: `count`
  (system and self only). `POST /api/v1/ui/recent-records` (authenticated, 201) stores only records whose type has
  a ResourcePolicy and that the actor can read (unknown or invisible: 404; type without a policy: 422); newest 20
  per user; a repeat moves the record to the top.
- **Readers' canonical paths.** People have no page in Slice 1, so `identity.membership` links to
  `/search?q=<name>&types=org.person` (same as the people search provider); preferences link to `/settings`.

## 3. Declined or partial (with reasons)

1. **Briefings `FakeWorld` (item 4).** `tests/integration/briefings/world.py` still carries literal ref keys
  (`"Q_BERG_EXPIRING"`, ...). The parallel test-reconcile lane is rewriting that module, so it was left untouched to
  avoid a conflict; every other briefings/tasks test now reads `keys.QUOTE_REFS` / `keys.PARTY_REFS` / `keys.TEXTS`.
2. **Item 6.** `briefings` has no Capability copy (nothing to switch). `tasks.AllowedTransition` stays: it differs
  from `TransitionRead` (`requires_reason` defaults to false, so the schema's `required` list differs) and switching
  it would change the wire schema.
3. **api-conventions §8 (item 8).** The bootstrap `features` block carries area readiness only; no assistant/voice
  flags are emitted today. The doc now reserves `features.assistant` and `features.voice` (missing = false), which
  is what the web parser already reads; the agents lane emits them.
4. **Not in this brief, still open:** identity request 4 (`CsrfOriginMiddleware` should call the verifier in a
  threadpool); catalogue question 1 (UOM CHECKs to FKs on `uom.code`); moving the existing raw-SQL guards of 0005
  to `immutable_columns` (brief: do not rewrite merged migrations).

## 4. Tests

New tests: `tests/unit/files/test_limits.py` (rewritten, 3), `tests/integration/files/test_files.py::test_identity_installs_the_shared_upload_limiter`,
`tests/integration/ui/test_source_readers.py` (7), `tests/contract/test_migration_helpers.py` (6),
`tests/integration/test_migration_helpers.py` (1).

Gate output at `052277c` (+ docs):
- `npm run test:api -- --ignore=tests/integration/briefings --ignore=tests/integration/tasks`: **760 passed** in 421 s.
- `npm run test:api -- tests/integration/briefings tests/integration/tasks --maxfail=25`: **4 passed, 25 errors**. Every
  error is the same pre-existing failure (below), not caused by this lane.
- `npm run check -- --keep-going`: ruff PASS; pytest unit + contract PASS (373 passed); alembic heads == 1 PASS;
  api:check PASS (`openapi.json` regenerated and committed); web lint PASS; web typecheck PASS; web vitest PASS (361).

**Pre-existing red: the briefings/tasks `FakeWorld` snapshot cannot be built.** Reproduced on this branch at
`0b61846` (items 1–2 only) in an isolated run. `tests/integration/briefings/world.py::FakeWorld.build` runs the real
seeds; `app/seed/world/tasks.py` links Meera's reminder to `ctx.refs["MAISON"]`, which in the FakeWorld is a fake
party id, and `tasks.service.create_reminder` checks `can_view_source(uow, "parties.party", id)`. Since the parties
module registers a real ResourcePolicy for `parties.party`, the check queries `parties_party`, finds nothing and
raises `NotFound`. Because the build fails after `FakeWorld.install()`, the fake member-actor builder and fake
readers are never uninstalled, so in a single full-suite run the identity and ui tests that run later error too
(that is why the suite is run in two parts here). This is the test-reconcile lane's work (drop the fake
identity/parties readers and use the real world); `identity.membership` and the other readers it needs are now
registered for real by this lane.

## 5. PARITY_MATRIX

- Pointers updated (39 rows): identity request 6 (LM-01, API-01, PERM-25/26/28, SEC-04/05, UI-03/05/06; LM-02/03/08
  and API-08/09 already named existing tests), work SCN-B5 →
  `tests/integration/briefings/test_versions_and_actions.py::test_midnight_rollover`, and the catalogue lane's
  row-to-test mapping (LM-10/11/61, API-10/13, UI-35/39/40, FG-PRD-01/05/09, FG-REL-01, FG-TAX-01/02/03, FG-PKG-11,
  FG-PRC-10, BR-01..04, BUG-05/07/10, SCN-D1/D2/D4, GAP-01). FG-TAX-05/06 keep their slice-2 pointer.
- Statuses from the junit results of the two runs above: **40 rows → implemented** (slice 1, every named pytest test
  passed), **13 rows → in progress** (slice 1→2, plus FG-QUO-10, FG-QLN-10 and SEC-05 whose tests pass but cover only
  part of the row). Checkpoint 1 note added at the top of the file. Not moved: rows named by Playwright/vitest,
  rows whose test does not exist yet (185 slice-1 rows), and the briefings scenario rows (SCN-A1/A4/B1/B2/B5/C2)
  whose tests error on the FakeWorld issue.
- `docs/architecture/api-conventions.md` §8: `features` contents named (area readiness keys; reserved `assistant`
  and `voice`). `docs/architecture/conventions.md` §3: `legacy_permission_alias` was already in the RLS-exempt list;
  added to the identity table list; `immutable_columns` added to the helper list.

## 6. Requests for the integrator

1. **Migration numbering**: `0007_ui_recent_record.py` (down_revision `0006`) collides with the sales lane's
   `0007`; reparent at merge and regenerate `openapi.json`/`schema.d.ts` after the sales/agents merges.
2. **FakeWorld**: the test-reconcile lane should switch the briefings/tasks world to the real readers now
   registered (`identity.membership`, `identity.user_preference`, `ui.recent_record`, `search.recent`) and to the
   real parties (the reminder's `parties.party` link is what fails), and may replace the literal ref keys in
   `world.py` with `keys.QUOTE_REFS` / `keys.ENQUIRY_REFS` / `keys.PARTY_REFS`.
3. **Web**: call `POST /api/v1/ui/recent-records` when a detail route opens (product detail first, for onboarding
   step "Open a product record").
4. **Agents lane**: emit `features.assistant` / `features.voice` in the bootstrap (api-conventions §8).
5. **Still open, outside this brief**: identity request 4 (CSRF verifier in a threadpool); catalogue question 1
   (UOM CHECKs → FKs); optional follow-up migration moving 0005's raw-SQL `product_key` guard onto
   `immutable_columns`.
6. **PARITY_MATRIX** statuses moved on this branch; confirm them on `main` after the merge and record the evidence
   in `docs/BUILD_STATE.md`.
