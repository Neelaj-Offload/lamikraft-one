# Lane report: test-world reconciliation after the Slice 1 wave-1 merge

Branch `lane/s1-test-reconcile` (from `main` at `8c6ca46`), worktree `D:\lk-wt\recon`, env slot 9.
Status: **done**. Only tests and one additive reader fact changed; no routes, migrations, seeds or manifests.

## Results

| Gate | Before (main at 8c6ca46) | After |
|---|---|---|
| `npm run test:api` | 709 passed, 2 failed, 130 errors | **843 passed, 1 xpassed**, 0 failed, 0 errors (7 min 05 s) |
| `npm run check -- --keep-going` | (not run) | every step PASS: ruff, pytest unit+contract, alembic heads == 1, api:check (openapi.json matches), web lint, typecheck, vitest (361) |

## Root cause of the 130 errors

1. The briefings/tasks `FakeWorld` built its own company, people and parties, so the tasks seed linked Meera's
   reminder to a fake `parties.party` id; the real parties policy cannot see it, so `create_reminder` raised
   `NotFound` (`app/modules/tasks/service.py:1002`) and the session snapshot build failed.
2. The snapshot build called `base.uninstall()` only after a successful build, so the failure left the fake
   member-actor builder and fake readers registered for the rest of the session. Every later test that needed
   identity's builder (`identity/test_seed.py`, `test_demo_sign_in.py`, `test_me_preferences.py`,
   `test_testsupport.py`, `ui/*`, and `identity/test_cli.py::test_seed_demo_command`, whose parties seed builds
   Priya's actor) got `membership_inactive`, and `parties/test_parties.py` read `None` from the fake parties reader.
3. Even on success the snapshot was built in a session-scoped fixture before the function-scoped
   `_registry_loaded`, so `install` could record "no builder / no parties reader" and `uninstall` would then remove
   the real ones.

## Changes (test file → change → reason)

| File | Change | Reason |
|---|---|---|
| `backend/tests/integration/briefings/world.py` | Rebuilt: the company comes from the installed modules' real seeds via `registry.seeds` (`app.seed.runner.installed_seeds` + `ensure_demo_company`), run in `(order, name)` order with a drain after each, as `lk seed demo` does. Fake sales history moved into three test SeedDefs at orders 50 (quotes/enquiries to D-3), 56 (the two D-1 evening messages, after the real Maison change at 55) and 76 (the D0 morning reviews and agent draft, after Arjun's activation at 75), at the same fixture times as before. Fake records reference real party ids (`refs["NORDHAUS"]` …). `actor()` is the real member-actor builder; permission edits are real `user_permission_override` rows (`override`, `set_overrides`) plus an epoch bump; `install`/`uninstall` save and restore every registry entry they touch, register only the fakes listed in `FAKE_READERS`/`FAKE_HANDLERS`, clear identity's access cache, and nothing registers at import. New helpers `change_party_contacts` (real parties update) and `party_version`. | Brief items 2 and 3 |
| `backend/tests/integration/briefings/conftest.py` | Snapshot build uninstalls in `finally` and drops its database when the build fails; `bare_world` runs the real identity and org seeds (orders ≤ 12). | Leak on failure (root cause 2) |
| `backend/tests/conftest.py` | New autouse `_seams_restored`: fails any test whose fixtures leave SourceReaders, the member-actor builder or approval handlers changed; `seam_registrations()` helper. | Brief item 3: no lane can leak into another regardless of order |
| `backend/tests/contract/test_test_seams.py` (new) | Outside fixtures the seams belong to `app.*` modules (identity builder, parties reader; a fake registered at import fails here); `FakeWorld.install` registers only the fakes and `uninstall` restores the registries exactly (twice is a no-op). | Brief item 3 contract test |
| `backend/tests/integration/test_approvals.py` | The `test.thing.review` handler is registered by the fixture and removed on teardown. | It leaked for the rest of the session (caught by the new guard) |
| `briefings/test_expected_briefings.py`, `test_snapshot_rechecks.py`, `test_versions_and_actions.py`, `tasks/test_inbox_and_commands.py`, `test_ownership_and_admin.py`, `test_rules.py` | `world.overrides[X] = {...}` → `world.override(X, {...})`. | Overrides are real rows now |
| `briefings/test_no_aggregate_leak_property.py` | `world.overrides = {...}` → `world.set_overrides({...})` (replaces the previous example's rows). | Same |
| `tasks/*.py`, `briefings/test_versions_and_actions.py` | `world.parties[X].id` → `world.refs[X]`. | Parties are real; ids come from the seeded refs |
| `briefings/test_versions_and_actions.py::test_acknowledged_unchanged_items_are_not_realerted` | Berg's contacts change is a real `parties.update_party` by Priya instead of a hand-emitted event with a hand-bumped version. | The rule ignores events newer than what the real reader returns |
| `briefings/test_versions_and_actions.py::test_delta_since_yesterday_is_source_linked_and_filtered` | The delta source label is the real reader's `P-00002 · Maison Atelier SARL`. | Label belongs to the parties reader |
| `tasks/test_ownership_and_admin.py::test_immaterial_party_update_creates_no_change` | The `notes` event carries the party's current real version (parties has no notes field to change). | Same rule; keeps the immaterial-field check |
| `tasks/test_ownership_and_admin.py::test_member_actor_is_cached_per_transaction` | Wraps `actors._builder` (identity's real builder) instead of `world._builder`. | No fake builder any more |
| `tasks/test_rules.py::test_team_lead_fallback_then_queue` | The message for a deactivated Meera is emitted by the system (`received_by_system=True`). | The real builder has no actor for a deactivated member; an inbound message is not sent by its assignee |

## Product defect fixed (minimal)

- `backend/app/modules/parties/service.py` `read_party_facts`: added `facts["name"]` (= `display_name`). The work
  lane's reader contract (docs/lanes/work.md §11.1) asks `parties.party` for `name` and `party_number`; without it
  `tasks.rules.families.derive_party_change` fell back to the label and the Maison item read
  "P-00002 · Maison Atelier SARL shipping address updated by Priya" instead of "Maison Atelier SARL shipping address
  updated by Priya" (`test_sales_overview_computed.py`). Additive; no other consumer changes.

## Switch to the real modules when they merge

Fixture file: `backend/tests/integration/briefings/world.py` (used by `briefings/` and `tasks/` through
`briefings/conftest.py`).

When **sales** merges (with its `sales.quote` / `sales.customer_message` / `sales.enquiry` readers, its
`sales.quote.review` handler and its seeds):
1. Delete `FakeWorld.fake_sales_seeds`, `build_sales_history`, `build_messages`, `build_d0_morning`,
   `_request_review`, `_quote`, `submit_review`, `change_quote`, `emit_quote` and the `QuoteRec` / `MessageRec` /
   `EnquiryRec` records (`quotes`, `messages`, `enquiries`, `approved`).
2. Delete `read_quote`, `read_message`, `read_enquiry`, `_quote_version`, `_can_decide`; remove `sales.quote`,
   `sales.customer_message`, `sales.enquiry` from `FAKE_READERS`, `sales.quote.review` from `FAKE_HANDLERS`, and
   their `register_reader` / `register_handler` lines in `install`.
3. Tests that mutate fake records (`world.change_quote`, `world.quotes[...]`, `world.messages[...]`, `world._quote`,
   `MessageRec`/`EnquiryRec` in `tasks/test_rules.py`, `briefings/test_versions_and_actions.py`,
   `test_snapshot_rechecks.py`, `tasks/test_agent_quote_draft_creates_scoped_next_action.py`) switch to the sales
   services; refs keep their fixture keys (`Q_BERG_EXPIRING`, `MSG_NORDHAUS`, `PROP_*` …).

When **identity** registers its readers: remove `identity.membership` (`read_membership`, `_membership_key` stays
for overrides or reads `refs[..._MEMBERSHIP]`), and `identity.user_preference`, `ui.recent_record`,
`search.recent` (`_user_reader`, `user_facts`) from `FAKE_READERS` and `install`; `tasks/test_rules.py`
(`world.user_facts[...]`) then records real preferences/recent records instead.

## Concerns (not fixed: product decisions for their owners)

- `tasks.rules.families.MATERIAL_PARTY_FIELDS` uses `name` and `currency`, but the parties module reports
  `display_name`, `legal_name` and `default_currency` in `changed_fields`, so a real rename or currency change is
  treated as immaterial (no change row, no briefing version). Needs one naming decision (work lane or parties lane).
- `tests/integration/catalogue/world.py` still installs its own fake member-actor builder (restored per fixture,
  so it does not leak; the guard now proves it). It could use identity's real builder now.
