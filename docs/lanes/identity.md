# Lane report: identity (Slice 1, wave 1)

Branch `lane/s1w1-identity`, worktree `D:\lk-wt\identity`, env slot 1. Status: **done, all green** (review-fix pass 2026-10-27, see the last section).
Backend suite: **253 passed** (92 pre-existing + 161 new). `npm run check -- --keep-going`: ruff, pytest unit+contract,
`alembic heads == 1`, web lint/typecheck/vitest pass; `api:check` fails only because routes changed (the integrator
regenerates `backend/openapi.json` and `apps/web/src/lib/api/schema.d.ts`; neither file was committed).
Smoke-tested on a live uvicorn against `lk_wt1`: `lk seed demo` (twice, idempotent), `lk demo sign-in-link`,
demo sign-in, bootstrap, CSRF rejection and acceptance, `lk_ui` cookie, logout, test-support 404 in development.

## 1. Implemented (file paths under `backend/`)

| Item | Files |
|---|---|
| Migration 0003 (`revision="0003"`, `down_revision="0002"`, downgrade drops everything) | `migrations/versions/0003_identity_slice1.py` |
| Access tables: `permission` (global, RLS-exempt), `legacy_permission_alias` (global reference data), `role`, `role_permission`, `membership_role`, `membership_branch`, `user_permission_override` (grant/revoke, scope only for grants, reason, expiry, archive; partial unique open override), `user_preference` (RLS-exempt) | `app/platform/identity/models.py` |
| Auth tables: `auth_session` (token hash, CSRF hash, created/last_seen/idle/absolute expiry, rotated_from, revoked_at/reason, IP and user-agent HMACs), `auth_attempt`, `rate_limit_counter` (windows + lockout state), `demo_sign_in_token` (tenant RLS; hash only) | `app/platform/identity/auth_models.py` |
| Org teams: `team`, `team_member` (lead/member), added to the org manifest | `app/platform/org/teams.py`, `app/platform/org/manifest.py` |
| Enum CHECKs via `helpers.enum_check`, forced RLS via `helpers.enable_tenant_rls` on the 8 tenant tables | migration |
| Catalogue, legacy alias and system-template sync (idempotent; drift repaired with epoch bump + `access_changed`) | `app/platform/identity/roles.py` |
| Resolution rules (role union at max scope + employee base, unexpired grants, revoke always wins), legacy alias table/expansion/§12 predicates, per-`(membership, epoch)` cache that also expires at the next override expiry | `app/platform/identity/access.py` |
| ActorContext building: branches, team peers, zone (preference → user → membership → default branch → company → Asia/Kolkata), locale, epoch; member actor builder; job-runtime user builder; tenant GUC save/restore | `app/platform/identity/actors.py` |
| Provisioning/admin services with authority checks, anti-escalation, self-change ban, last-admin guard, epoch bump + events | `app/platform/identity/provisioning.py` |
| argon2id (pool of 4 threads + semaphore of 4, dummy-hash timing), policy 12–256 + common list + email/company names | `app/platform/identity/passwords.py` |
| Rate limits (IP 30/10 min, email 10/10 min) and email-keyed lockout (5 failures → 15 min × 2^n, cap 4 h; same for unknown emails) | `app/platform/identity/ratelimit.py` |
| Sessions (idle 12 h touched ≤ 1/min, absolute 7 d, rotation on sign-in, revocation), cookies | `app/platform/identity/sessions.py`, `app/platform/identity/http.py` |
| Session resolver, CSRF verifier (constant time), client address (X-Forwarded-For trusted only from a loopback peer, last entry) | `app/platform/identity/http.py`; registered in `app/platform/identity/manifest.py` `on_load` |
| Sign-in, sign-out, demo links (one-time, 15 min, demo companies only; token carries its company id), test sessions, first admin, `/me`, preferences, bootstrap profile, CSRF rotation, maintenance purge | `app/platform/identity/service.py`, `errors.py`, `schemas.py`, `preferences.py`, `tokens.py` |
| Identity router | `app/platform/identity/router.py` |
| Test-support router (mounted from the identity manifest only when `LK_ENV=test`; every handler re-checks) | `app/platform/identity/testsupport.py` |
| `ui` module: bootstrap (§8 payload + `features` readiness + module sections + rotated CSRF) and poll (ETag/304) | `app/modules/ui/{manifest,router,service,schemas}.py` |
| CLI: `lk admin create-first`, `lk admin sync-access`, `lk demo sign-in-link`, `lk seed demo` | `app/cli/commands/{admin,demo,seed}.py` |
| Seed orchestrator (FrozenClock as global business clock, company only when absent, SeedDefs by `(order, name)` and slice, inline drain, `last_world()` + `backend/var/seed/<db>.json`) | `app/seed/runner.py` |
| Identity fixture seed (order 10): crown-demo, roles, HO/FAC, EXP-SALES/OPS-HO with leads, people of fixtures §3 (Vikram only for slice ≥ 2), Arjun invited D−3 10:00 and activated D0 08:00 | `app/seed/world/identity.py` |

## 2. Tests (161 new, all passing)

| File | Tests | Covers |
|---|---|---|
| `tests/unit/authz/test_permission_resolution.py` | 6 | hypothesis (`derandomize=True`): `test_revoke_wins_and_scope_is_max`, order independence, expiry, monotonic roles, next expiry |
| `tests/unit/identity/test_passwords.py` | 11 | argon2id, policy, ≤ 4 concurrent hashes |
| `tests/unit/identity/test_preferences.py` | 27 | merge, clears, unknown fields, every mandatory-control key |
| `tests/unit/identity/test_access_rules.py` | 8 | alias table = registry, legacy expansion, cache, keyed hashes, windows |
| `tests/unit/identity/test_cookies.py` | 2 | `lk_session`/`__Host-lk_session`, Secure only in production |
| `tests/unit/ui/test_ui_rules.py` | 14 | nav prefixes, readiness, greeting boundaries/zones, ETags |
| `tests/integration/identity/test_access_sync.py` | 5 | catalogue, alias rows, templates = TEMPLATE_GRANTS, idempotent resync, drift repair |
| `tests/integration/identity/test_legacy_parity.py` | 5 | §3.2 for admin/management/sales/operations through the stored alias table (templates and real members); management has no delete/catalogue-write/identity/imports keys |
| `tests/integration/identity/test_effective_permissions.py` | 13 | union/max, grant/revoke (revoke wins), expiry, validation, epoch + events per change kind, peers/branches, inactive member, zone order, anti-escalation, last admin, cache vs epoch, archive/leave team, tenant GUC kept |
| `tests/integration/identity/test_login.py` | 9 | cookies + SessionInfo, identical 401 for 5 failure kinds, lockout + backoff + Retry-After + audit, unknown-email lockout, email and IP limits, Origin/Sec-Fetch-Site on sign-in, no echo, proxy address trust |
| `tests/integration/identity/test_sessions.py` | 10 | clean 401, idle expiry/extension, absolute expiry, rotation (+ CSRF on re-sign-in), logout, deactivation/disable, CSRF missing/forged/foreign/cross-site/Referer, token bound to session, bootstrap rotation, no URL tokens |
| `tests/integration/identity/test_demo_sign_in.py` | 6 | one use, 15 min, malformed/unknown, demo-only (issue and forged row), inactive member, no password sign-in for demo users |
| `tests/integration/identity/test_me_preferences.py` | 5 | profile, preferences PATCH/409/clears/audit/`lk_ui`, mandatory_control, all memberships |
| `tests/integration/identity/test_seed.py` | 8 | company/branches/teams/leads, people/roles/managers/refs, Arjun's event at 02:30Z, persona scopes, re-seed idempotent, slice 2 adds Vikram, `last_world`, refuses non-demo |
| `tests/integration/identity/test_cli.py` | 7 | create-first once (and refusal anywhere), policy, password source, sign-in link fragment, errors, seed command |
| `tests/integration/identity/test_testsupport.py` | 4 | sign-in by key/ids, fixtures, clock |
| `tests/integration/identity/test_committed.py` | 3 | `@committed`: RLS isolation of the 8 tenant tables; one demo link used by 4 threads → exactly one session; concurrent failure counting |
| `tests/integration/identity/test_maintenance.py` | 1 | purge job keeps live state, removes expired |
| `tests/integration/ui/test_bootstrap.py` | 10 | clean 401, Meera payload (server_now D0, morning, zone, permissions, nav, sections incl. failing one), Kabir sees no Sales, nav per persona, readiness hides areas, greeting in the user's zone |
| `tests/integration/ui/test_poll.py` | 2 | ETag/304/W/ and change detection; 401 |
| `tests/contract/identity/test_routes.py` | 5 | every `/api` operation declares a valid kind and known keys; identity/ui/test operationIds and kinds; test-support 404 + absent outside test; handler guard; no query tokens |

## 3. API endpoints

| Method and path | operationId | Kind |
|---|---|---|
| `POST /api/v1/identity/session` | `identity_create_session` | public |
| `DELETE /api/v1/identity/session` | `identity_delete_session` | authenticated |
| `POST /api/v1/identity/demo-sign-in` | `identity_create_demo_session` | public |
| `GET /api/v1/identity/me` | `identity_get_me` | authenticated |
| `PATCH /api/v1/identity/me/preferences` | `identity_update_preferences` | authenticated |
| `GET /api/v1/session/bootstrap` | `ui_get_session_bootstrap` | authenticated |
| `GET /api/v1/ui/poll` | `ui_poll_sections` | authenticated |
| `POST /api/v1/_test/sign-in` | `identity_create_test_session` | test_support (LK_ENV=test only) |
| `GET /api/v1/_test/fixtures` | `identity_get_test_fixtures` | test_support |
| `POST /api/v1/_test/clock` | `identity_update_test_clock` | test_support |

Problem codes used: `invalid_credentials`, `session_expired`, `unauthenticated`, `link_invalid_or_used`, `rate_limited`,
`account_locked` (429 + `Retry-After`), `csrf_token_invalid`/`origin_mismatch`/`cross_site_request` (middleware),
`mandatory_control`, `validation_failed`, `version_conflict`, `permission_escalation`, `self_access_change`,
`last_admin`, `not_demo_company`, `admin_exists`. No Idempotency-Key is required by api-conventions §6 for these routes.

## 4. Events

Emitted: `identity.membership.activated` (invited → active only; Arjun at D0 08:00 with `origin=seed`),
`identity.membership.access_changed` (roles, branches, teams, overrides, status, template drift),
`identity.permission_override.changed`. Consumed: none.

## 5. Permissions used

Checked in services (system/CLI/seed actors bypass): `identity.user.manage`, `identity.role.manage` (+ anti-escalation
against the actor's own keys), `identity.permission.manage`, `org.team.manage`, `org.branch.manage`; company creation
is CLI/system only. All routes are `public`, `authenticated` or `test_support` (self-service needs no key, ADR-045).
Navigation reads key prefixes only.

## 6. Settings, sequences, jobs, seeds, CLI

Settings: none. Sequences: none. Job `identity.purge_auth_state` (+ hourly schedule): expired counters, attempts
> 90 days, sessions ended > 30 days. Seed: `SeedDef("identity", order=10)`. CLI: `admin create-first`,
`admin sync-access`, `demo sign-in-link`, `seed demo`. Audit actions: `auth.login.{succeeded,failed,locked}`,
`auth.logout`, `auth.demo_sign_in.succeeded`, `identity.demo_link.issued`, `identity.membership.{provisioned,activated,roles_changed}`,
`identity.permission_override.{set,archived}`, `identity.preferences.updated`, `identity.first_admin.created`.

## 7. Dependencies requested

None.

## 8. Contract questions

1. **Kernel route validation is a no-op on FastAPI 0.143.** `app/core/http/authz_decl.validate_routes` and
   `webhook_paths` iterate `app.routes` for `APIRoute`, but included routers are `_IncludedRouter` objects, so an
   undeclared route starts fine and the webhook CSRF exemption set is empty (the WhatsApp webhook would get 403 in
   Slice 3). Covered meanwhile by `tests/contract/identity/test_routes.py` (OpenAPI walk). Fix belongs in core.
2. **RLS-exempt list** (conventions §3): `legacy_permission_alias` is global reference data like `permission`
   (no `company_id`); please add it to the list. `demo_sign_in_token` stays tenant-scoped (token = `<company hex>.<secret>`).
3. **Activation semantics**: staff provisioned directly as active (seed, first admin) emit no
   `identity.membership.activated`; only invited → active does, so onboarding is created only for Arjun (fixtures §9).
4. **Navigation readiness**: templates already grant later-slice keys (sales holds `challans.*`, `inventory.stock.read`,
   `logistics.*`), so permission-only filtering would show Operations to sales users in Slice 1. Nav therefore also
   requires an installed module of the area; `features` reports readiness. Web lane to confirm.
5. **CSRF verifier blocks the event loop**: `register_csrf_verifier` is sync and the middleware is async, so one indexed
   query runs on the loop per unsafe request. Suggest `run_in_threadpool` in `CsrfOriginMiddleware`.
6. **Proxy trust**: behind the Next rewrite every request comes from 127.0.0.1; the last `X-Forwarded-For` entry is used
   only for loopback peers. A production reverse proxy in front of Next needs a configurable trusted-hop count
   (`LK_TRUSTED_PROXY_HOPS` in core config, integrator-owned).
7. **Test-support through the CSRF middleware**: e2e helpers must send `Origin: LK_PUBLIC_ORIGIN` (and `X-CSRF-Token`
   once a session cookie exists); bootstrap rotates `lk_csrf` on every call (ADR-009 retry-once applies).
8. **Platform manifests import `app.seed.context`** for `SeedDef` (as the kernel docstring prescribes); an architecture
   test enforcing "imports only go downward" should allow it.
9. `/api/v1/identity/me` returns the current `membership` in detail plus `memberships` (summaries across companies);
   sign-in picks the most recently used company (no company switch endpoint; ADR-047 future scope).

## 9. Known gaps (with reasons)

- **Admin HTTP endpoints** for role assignment, overrides, branches and teams are not in this brief; the services exist
  with permission checks, anti-escalation and the last-admin guard, and are tested. Their keys carry MFA/recent-auth
  flags, which need the Slice-2 MFA and re-authentication endpoints before a safe UI/API can ship.
- **MFA and recent-auth enforcement**, delegation (`ActorContext.delegated` stays empty), absences, invitations,
  password change/reset and session lists are Slice 2 (permissions.md §7.1). Session `stage` is always `active`.
- **Recent records** (`ui` module) are not part of this brief.
- Playwright/e2e and `next build` were not run (lane rule); `openapi.json`/`schema.d.ts` are left to the integrator.

## Fix pass (2026-10-27)

Two adversarial reviews (2026-10-23, lenses correctness-security and spec-conformance) were reconciled against the
working tree. An earlier fix pass had stopped part-way through and left uncommitted work. That work was verified,
completed, given tests and committed in `5b3aa25`. Every fixed finding has a regression test.

| finding | severity | status |
|---|---|---|
| CS-1 Per-IP sign-in limit could be bypassed with a spoofed `X-Forwarded-For`, and every browser shared one bucket | blocker | fixed in `5b3aa25`. `client_ip` trusts the ASGI client only when no forwarded entry could have produced it. uvicorn's proxy-headers rewrite also covers `host:port` entries, which the interrupted pass had missed (its port-0 heuristic). Otherwise the entry `LK_TRUSTED_PROXY_HOPS` positions from the right is used, and the default of 0 means the address is unknown: one shared bucket that no client value can escape. Production must set hops=1 behind the reverse proxy; when it is 0, a startup warning is logged. Tests: `test_login.py::test_a_spoofed_forwarded_address_never_opens_a_fresh_bucket`, `::test_uvicorn_proxy_headers_cannot_be_used_to_spoof_the_client` (real `ProxyHeadersMiddleware`), `::test_forwarded_addresses_count_from_the_trusted_reverse_proxy`. The dev-server flag and core setting are under integrator requests |
| CS-2 Signing in while holding another company's session cookie returned 500 | major | fixed in `5b3aa25`. The previous session is revoked with a Core UPDATE, and `rotated_from_id` is set only for the same user in the same company. Logout clears the cookies even when it answers 401. Tests: `test_sessions.py::test_signing_into_another_company_replaces_the_foreign_session`, `::test_an_expired_foreign_cookie_does_not_block_sign_in`, `::test_logout_with_a_dead_session_still_clears_the_cookies` |
| CS-3 A database error in a bootstrap or poll section aborted the transaction | major | fixed in `5b3aa25`. The ui module builds each section inside its own SAVEPOINT, which keeps the CSRF rotation. Test: `ui/test_bootstrap.py::test_a_database_error_in_one_section_leaves_the_rest_of_the_bootstrap_intact` (bootstrap and poll). The kernel `build_sections` still lacks the savepoint (integrator request) |
| CS-4 Concurrent demotions could bypass the last-admin guard | major | fixed in `5b3aa25`. `provisioning.lock_access` takes a transaction advisory lock per company in `assign_roles`, `set_permission_override`, `archive_permission_override` and `deactivate_membership`. Committed test: `test_committed.py::test_two_admins_demoting_each_other_concurrently_keep_one_admin`, confirmed to fail (`['ok','ok']`) with the lock removed |
| CS-5 `provision_membership` did not check that branch, default-branch and manager ids belong to the actor's company | minor | fixed in `5b3aa25` (422 for a foreign branch, 404 for a foreign manager). Test: `test_provisioning_guards.py::test_provisioning_rejects_branches_and_managers_of_another_company` |
| CS-6 Demo users could sign in with a password | minor | fixed in `5b3aa25`. Memberships in `is_demo` companies are never password sign-in targets. Test: `test_demo_sign_in.py::test_a_demo_member_with_a_password_still_cannot_sign_in_by_password` |
| CS-7 N+1 queries across tenants on sign-in, /me and the last-admin guard | minor | partly fixed in `5b3aa25`: the last-admin guard now resolves access only for candidate holders found in one query (test: `test_provisioning_guards.py::test_a_company_grant_of_role_management_counts_for_the_last_admin_guard`). Deferred: `_memberships_of` still loops per company. Fixing it needs a SECURITY DEFINER lookup (new migration and grants), which is more than 15 minutes of work. A deployment has one company plus the demo company, so the cost stays bounded |
| CS-8 / SC-6 `legacy_permission_alias` is RLS-exempt but missing from the conventions §3 list | minor | declined in code (the contract wins: the list is extended only by integrator PR). Integrator request below |
| CS-9 The CSRF verifier blocks the event loop | minor | deferred: the fix belongs in core `CsrfOriginMiddleware` (`run_in_threadpool`, or an async verifier). Integrator request below |
| SC-1 Permission-override API missing (API-08/09, LM-02) | major | fixed in `5b3aa25`. Added `GET/PUT/DELETE /api/v1/identity/users/{user_id}/permission-overrides[/{key}]`, with `reauth_required` (401) for the RA flag (permissions.md §6) and an idempotent PUT. `/me` returns effective `permissions` and open `overrides`. Tests: `authz/test_overrides.py::test_grant_and_revoke_with_reason_and_epoch_bump`, `::test_override_api_validation_and_authority`, `::test_override_changes_need_a_recent_password_sign_in`, `identity/test_profile.py::test_me_returns_profile_and_effective_permissions` |
| SC-2 `POST /api/v1/identity/me/password` missing (LM-03/API-03) | major | fixed in `5b3aa25`. The current password is required, the policy applies (and the new password must differ), the caller's session rotates, and the user's other sessions in every company are revoked. Rate-limited to 10 per 10 minutes per user, and audited. Tests: `test_profile.py::test_change_password_revokes_other_sessions`, `::test_change_password_needs_the_current_password_and_the_policy`, `::test_change_password_is_rate_limited` |
| SC-3 Catalogue and templates were never synced at startup | major | fixed in `5b3aa25`. The identity router lifespan runs `roles.sync_access_all` once per API start (skipped when `LK_ENV=test`). A failure is logged and does not stop the API. `lk admin sync-access` shares the same function. Tests: `test_access_sync.py::test_api_startup_repairs_template_drift_without_the_cli`, `::test_the_identity_router_lifespan_runs_the_sync_when_the_app_starts`, `::test_a_failing_sync_does_not_stop_the_api` |
| SC-4 Verifying tests named in PARITY/permissions §11 missing; `last_login_at` and "startup creates no users" untested | minor | partly fixed in `5b3aa25`. Added the named `test_profile.py::{test_me_returns_profile_and_effective_permissions, test_change_password_revokes_other_sessions}` and `authz/test_overrides.py::test_grant_and_revoke_with_reason_and_epoch_bump`, plus `test_profile.py::test_sign_in_records_the_attempt_and_last_login` and a no-new-users assertion in the startup-sync test. Deferred: renaming the other existing tests to the matrix IDs. The behaviour is covered under the names in §2, and the matrix pointers are an integrator request |
| SC-5 Seed activated Arjun at D0 08:00 inside the order-10 seed (non-chronological) | minor | fixed in `5b3aa25`. A second SeedDef, `identity.activation` (order 75), runs after the history seeds (20–60) and before tasks/briefings (80). Covered by `test_seed.py` (Arjun's event at 02:30Z, idempotent re-seed) |
| SC-7 Preferences PATCH did not require `expected_version`, and the 409 lacked `current/changed_by/changed_at` | minor | fixed in `5b3aa25`. `expected_version` is required (`ge=0`), and the 409 carries `current_version`, `current`, `changed_by` and `changed_at`. Test: `test_me_preferences.py::test_patch_preferences_merges_sections_and_sets_the_ui_cookie` (409 body and missing-field 422). **Web lane: every PATCH must send `expected_version`** |
| SC-8 No producer of `identity.membership.deactivated` | minor | fixed in `5b3aa25`. `provisioning.deactivate_membership` requires `identity.user.manage`, refuses your own membership and the last admin, revokes sessions and unused demo links, bumps the epoch and emits the event. Tests: `test_provisioning_guards.py::test_deactivation_revokes_sessions_and_links_and_emits`, `::test_the_last_role_manager_cannot_be_deactivated`. No HTTP route: admin user endpoints are Slice 2 (LM-06/07) |

New endpoints in this pass (all on the `identity` router):

| Method and path | operationId | Kind |
|---|---|---|
| `POST /api/v1/identity/me/password` | `identity_update_password` | authenticated |
| `GET /api/v1/identity/users/{user_id}/permission-overrides` | `identity_list_permission_overrides` | permission (`identity.user.read` or `identity.permission.manage`) |
| `PUT /api/v1/identity/users/{user_id}/permission-overrides/{permission_key}` | `identity_set_permission_override` | permission (`identity.permission.manage`, RA) |
| `DELETE /api/v1/identity/users/{user_id}/permission-overrides/{permission_key}` | `identity_delete_permission_override` | permission (`identity.permission.manage`, RA) |

New problem codes used: `reauth_required` (401), `password_changed` (409, a concurrent change). New audit actions:
`auth.password.changed`, `auth.password.change_failed`, `identity.membership.deactivated`.

### Gate output

- `npm run test:api` (full pytest, real PostgreSQL): `276 passed in 140.01s` (253 before this pass + 23 new tests).
- `npm run check -- --keep-going`: `backend: ruff check PASS`, `backend: pytest unit + contract PASS` (145 passed),
  `alembic heads == 1 PASS`, `web: lint PASS`, `web: typecheck PASS`, `web: vitest PASS` (134 passed);
  `api:check FAIL — backend/openapi.json is out of date` (expected: routes changed, the integrator regenerates).

### Requests for the integrator

1. **uvicorn proxy headers**: start uvicorn with `--no-proxy-headers` in `scripts/dev.mjs` (dev and e2e servers) and in the
   production run command, so that `request.client` stays the real peer. Identity no longer depends on this, but it
   removes a client-controlled input.
2. **`LK_TRUSTED_PROXY_HOPS`**: move it from `app/platform/identity/config.py` into `app.core.config.Settings`, and add it
   to `.env.example` and the production runbook. It must be `1` behind the production reverse proxy (ADR-001).
3. **Kernel `app/platform/bootstrap.build_sections`**: wrap each section in `uow.session.begin_nested()`, as
   `app/modules/ui/service.build_sections` now does. The ui module carries its own copy until the kernel does.
4. **`CsrfOriginMiddleware`**: call the registered CSRF verifier through `run_in_threadpool`, or accept an async
   verifier. The identity verifier makes one indexed query per unsafe request.
5. **conventions.md §3**: add `legacy_permission_alias` (global reference data with no `company_id`) to the RLS-exempt
   list and to the identity table list.
6. **PARITY_MATRIX test pointers**: LM-01/API-01, PERM-25/26, SEC-04/05, UI-03/05/06, PERM-28 and the legacy-parity rows
   point at test names that the lane covers under other names (see §2). Point them at the existing tests, or ask for
   thin aliases. LM-02, LM-03, LM-08 and API-08/09 now exist under the matrix names.
7. **Regenerate** `backend/openapi.json` and `apps/web/src/lib/api/schema.d.ts`: 4 new operations, `MeRead.permissions`
   and `MeRead.overrides`, and `PreferencesPatch.expected_version` is now required.
