# Lane report: platform-2 (Slice 2, wave 1)

Branch `lane/s2w1-platform`, worktree `D:\lk-wt\platform`, env slot 2. Migration `0010_platform_slice2.py`
(revision `0010`, down_revision `0009`; upgrade, downgrade and re-upgrade verified on `lk_wt2`; `alembic check` clean).

Status: all seven brief items are implemented, tested and committed. See "Gate output" for the counts.

## 1. Implemented

| Brief item | Backend (under `backend/app/platform/`) | Web (under `apps/web/src/`) |
|---|---|---|
| 1. MFA (TOTP + 10 recovery codes) required for administrators at sign-in and on admin actions; invitations and password resets with demo `.eml`, fragment tokens, single use, expiring, rate-limited | `identity/{crypto,mfa,mfa_service,credentials,mail,account,credential_models,router_auth}.py`; `authz/stepup.py` (MFA + RA flags); session stages `mfa_pending` / `mfa_enrollment_required` in `identity/{sessions,http,service}.py`; `security_policy` setting (`org/settings.py`, `privileged`/`all`) | `app/(auth)/{two-step,invite,reset-password,forgot-password}`; `app/(app)/settings/security`; login routes to `/two-step` (`features/auth/{auth-api,login-form}.ts(x)`) |
| 2. Custom roles (inheritance, deny), overrides UI, role simulator, user admin (invite, deactivate, reactivate, never hard-delete, role change audited with diffs) | `identity/{role_resolution,roles_admin,user_admin,router_admin}.py`; resolution in `identity/actors.py::load_access`; anti-escalation over effective (inherited) grants in `provisioning.py`; `provisioning.reactivate_membership` | `app/(app)/settings/{users,users/invite,users/[userId],roles,roles/new,roles/[roleId],roles/[roleId]/edit,roles/simulate}` with `_lib/{users,overrides,roles,step-up}.tsx` |
| 3. Delegation (time-bounded, scoped, audited), leave (reassignment hints via events), access requests (request → approver → expiring grant) | `identity/{delegation,availability,availability_models,router_people}.py`; `ActorContext.delegated` filled by `load_access` (cache expires at the next boundary); boundary job `identity.delegation_boundaries` (5 min); reader `identity.absence` (dates + cover) | `app/(app)/settings/{delegation,leave,access-requests}` (`_lib/people.tsx`, `_lib/people-picker.tsx`) |
| 4. Notes, attachments, activity on any record (parent read/update; files via platform/files; activity filtered by parent visibility) | `collab/{attachments,activity,router,schemas,models}.py`; file access checker `collab.attachment`; activity read from `domain_event` and filtered per registered `ResourcePolicy` | `features/collab/{notes,attachments,activity,record-panel,api}.ts(x)`; `app/(app)/activity` |
| 5. Global search: `/` shortcut, grouped results, recent searches, types + offset, no leaks, `escape_like` everywhere | existing providers; SEC-06 architecture test (no SQL regex anywhere in `app/`) | `features/search/{search-dialog,search-page,parse,types}.ts(x)` (fixed the dialog's `items`/`per_group` mismatch with the API's `hits`/`limit`; recent searches; "See all"); `app/(app)/search` |
| 6. S3 adapter; image variants | `files/storage.py::S3Storage` (boto3, `LK_STORAGE_BACKEND=s3`, `LK_S3_*`; credentials from the AWS chain), contract-tested with **moto** (in the lockfile); `files/variants.py` (Pillow: `thumb` 256, `medium` 1024, EXIF stripped), `?variant=` downloads | thumbnails in the attachment list |
| 7. Isolation matrix | `tests/integration/security/test_isolation_matrix.py::test_restricted_user_sees_no_sentinel_anywhere` (Kabir and Neha; every GET route on the branch, search, activity, notes, attachments, files) | |

## 2. Decisions taken in the lane (for DECISIONS.md)

1. **Who must use MFA at sign-in**: members holding an MFA-flagged key of `identity`, `org`, `audit`, `system` or
   `numbering` ("privileged"); the `security_policy` setting (`identity.mfa.manage`) can require it of everyone.
   Other MFA-flagged keys (e.g. finance's `pricing.fx_policy.manage`) are enforced at use time by
   `authz.stepup.require_step_up`, which owning modules should call (only platform services do so on this branch).
2. **Demo-link sessions** (fictional, passwordless members of `is_demo` companies) are not forced to enrol at
   sign-in; MFA-flagged actions still need a step-up code (enrolling counts). **Test-support sessions**
   (`LK_ENV=test` only) count as MFA-verified so e2e journeys reach administration.
3. **Step-up endpoint**: `POST /identity/session/reauthentication` with the password (recent auth) or a code
   (recent auth + MFA). Problem codes: `mfa_required` and `reauth_required` (401).
4. **Activity** is computed from the outbox (`domain_event`) rather than a projected table: no second copy, no extra
   job per event; visibility is the parent's policy. Collaboration events are attributed to their parent record.
5. **Delegation** stores explicit keys; only delegable keys held by both people count at resolution time.
6. **Deny entries** never remove keys of the implicit employee base (it is a separate union member).
7. Invitations to an email that already has an account (another company) confirm the existing password.
8. Email `smtp` mode is not implemented (409 `not_configured`); demo mode writes `.eml` to `<LK_STORAGE_DIR>/mail/`
   after commit and shows the link once to the administrator.

## 3. API endpoints added (all `/api/v1`)

Identity (auth): `POST identity/session/verification` (public), `POST identity/session/reauthentication`,
`GET identity/me/mfa`, `POST identity/me/mfa/totp`, `POST identity/me/mfa/totp/confirmation`,
`DELETE identity/me/mfa/totp`, `POST identity/me/mfa/recovery-codes`, `DELETE identity/users/{user_id}/mfa`
(`identity.mfa.manage`), `GET|DELETE identity/me/sessions`, `DELETE identity/me/sessions/{session_id}`,
`GET|DELETE identity/users/{user_id}/sessions` (`identity.session.manage`), `POST identity/invitations`,
`POST identity/invitations/{id}/reissue`, `DELETE identity/invitations/{id}` (`identity.user.manage`),
`POST identity/invitations/preview`, `POST identity/invitations/acceptance`, `POST identity/password-resets`,
`POST identity/password-resets/completion` (public, rate-limited), `POST identity/users/{user_id}/password-reset`.

Identity (admin): `GET identity/users`, `GET|PATCH identity/users/{user_id}`, `PUT identity/users/{user_id}/roles`,
`PUT identity/users/{user_id}/branches`, `POST identity/users/{user_id}/deactivation`,
`POST identity/users/{user_id}/reactivation`, `GET identity/permissions`, `GET|POST identity/roles`,
`GET|PATCH identity/roles/{role_id}`, `POST identity/roles/{role_id}/archive`, `GET identity/access/effective`,
`GET identity/access/check`.

Identity (people): `GET|POST identity/delegations`, `POST identity/delegations/{id}/cancel`,
`GET|POST identity/absences`, `POST identity/absences/{id}/decision`, `POST identity/absences/{id}/cancel`,
`GET|POST identity/access-requests`, `POST identity/access-requests/{id}/decision`
(`identity.access_request.approve`), `POST identity/access-requests/{id}/withdrawal`.

Collab and files: `GET|POST collab/attachments`, `PATCH|DELETE collab/attachments/{attachment_id}`,
`GET collab/activity` (`collab.activity.read`), `GET files/{file_id}/content?variant=thumb|medium`.

## 4. Events emitted (all from the frozen catalogue)

`identity.invitation.sent|accepted|revoked`, `identity.user.credentials_changed` (kinds `mfa_enrolled`,
`mfa_disabled`, `mfa_reset`, `password_reset`), `identity.role.created|updated|archived`,
`identity.membership.reactivated`, `identity.delegation.created|cancelled|started|ended`,
`identity.absence.requested|approved|cancelled`, `identity.access_request.submitted|decided`,
`collab.attachment.added|archived` (plus the existing access-changed events).

## 5. Parity rows → tests

| Row | Test |
|---|---|
| PERM-11 | `tests/integration/identity/test_user_admin.py::test_user_admin_requires_manage_keys` |
| PERM-16, FG-USR-02 | `tests/integration/authz/test_role_validation.py::test_unknown_key_scope_cycle_and_escalation_rejected` |
| PERM-19, PERM-23, PERM-24, SEC-01 | `tests/contract/test_route_authz_matrix.py::test_every_route_denies_unauthorised_personas` + `tests/integration/security/test_isolation_matrix.py::test_restricted_user_sees_no_sentinel_anywhere` |
| PERM-27, LM-05, API-06 | `tests/integration/identity/test_invitation_and_reset.py::test_admin_reset_never_returns_password` |
| PERM-29, SEC-05 (lockout/limits/MFA) | `tests/integration/identity/test_login_security.py::test_generic_errors_lockout_and_rate_limits`, `tests/integration/identity/test_mfa.py::test_admin_enrolment_replay_rejected_recovery_once` |
| LP-01.8 | `tests/integration/identity/test_mfa.py::test_admin_enrolment_replay_rejected_recovery_once` |
| LM-04, API-04 | `tests/integration/identity/test_user_admin.py::test_list_create_update_users` |
| LM-06 | `tests/integration/identity/test_deactivation.py::test_last_admin_guard_and_no_self_deactivation` |
| LM-07, API-05, FG-USR-04 | `tests/integration/identity/test_deactivation.py::test_deactivation_keeps_attribution_and_revokes_sessions` |
| LM-08 (UI part) | `tests/integration/authz/test_overrides.py::test_grant_and_revoke_with_reason_and_epoch_bump`; UI `app/(app)/settings/_lib/settings.test.tsx` "show only the controls the server allows on a member" |
| LM-09, API-07 | `tests/integration/authz/test_role_simulator.py::test_effective_permissions_with_sources` |
| LM-96, API-66, LP-11.1 | `tests/integration/search/test_global_search.py::test_grouped_scoped_results_with_deep_links` |
| API-24 | `tests/integration/search/test_global_search.py::test_last_ten_kept_per_user` (matrix names `test_recent_searches.py`) |
| LM-98, API-68, UI-29 | `tests/integration/collab/test_activity.py::test_feed_filtered_by_parent_visibility`; UI `features/collab/collab.test.tsx` "activity feed" |
| LM-99, API-69, UI-66 | `tests/integration/collab/test_internal_notes.py::test_autosave_conflict_409_and_parent_update_required`; UI `features/collab/collab.test.tsx` "internal note" |
| LM-100, SEC-07 | `tests/integration/audit/test_audit_append_only.py::test_update_delete_rejected_and_security_events_recorded` |
| API-27 | `tests/integration/files/test_file_download_authz.py::test_download_requires_parent_read_and_headers` |
| SEC-03, LP-01.4, SCN-A3 (platform part) | `tests/integration/security/test_isolation_matrix.py::test_restricted_user_sees_no_sentinel_anywhere` |
| SEC-06 | `tests/unit/core/test_escape_like.py::test_metacharacters_match_literally`, `::test_no_module_builds_sql_regular_expressions` |
| DEBT-06 | `tests/contract/files/test_storage_adapters.py::test_local_fs_and_s3_moto_same_contract` |
| FG-USR-01 | `tests/integration/identity/test_user_admin.py::test_email_normalised_unique` |
| FG-USR-05 | `tests/integration/identity/test_login_security.py::test_attempts_and_last_login_recorded` |
| UI-08 | vitest `features/search/search-page.test.tsx`, `features/search/search.test.ts` (Playwright spec named in the matrix not written/run) |
| UI-12, UI-26 (forgot/reset/invite pages) | vitest `app/(auth)/auth-links.test.tsx` |
| UI-21, UI-94 | vitest `app/(app)/settings/_lib/settings.test.tsx` "roles" |
| UI-22, UI-95 | vitest `settings.test.tsx` member detail (overrides panel); backend `test_overrides.py` |
| UI-23, UI-90 | vitest `settings.test.tsx` "users" |
| UI-25, UI-91 | vitest `settings.test.tsx` "security and self-service" |

Not done in this lane: FG-USR-03/06 (Slice 5 migration), UI-92 (`/settings/sequences`, numbering UI), API-72
(logo row: the Slice-1 setting/logo flow exists, the matrix-named `test_company_identity.py` was not written),
the Playwright specs the matrix names for UI rows (lane rules: not run; not written).

## 6. Known gaps

- Record pages do not embed `RecordCollaboration` yet (quote workspace and others belong to their lanes): one line,
  `<RecordCollaboration resourceType="sales.quote" resourceId={id} />`.
- MFA step-up is enforced in platform services only; other lanes' services holding MFA-flagged keys should call
  `app.platform.authz.stepup.require_step_up`.
- SMTP delivery is not implemented (demo outbox only).
- Comments (`collab.comment.added`) are not implemented; the internal note is.
- The S3 adapter is moto-tested; no live MinIO smoke test was run (dev-only compose profile).

## 7. Requests for the integrator

1. Regenerate `backend/openapi.json` and `apps/web/src/lib/api/schema.d.ts`; then replace the `requestUntyped`
   calls marked `INTERIM(api-generate)` in `app/(app)/settings/_lib/api.ts`, `features/collab/api.ts` and
   `features/search/*`.
2. `apps/web/next.config.ts`: add `/invite` and `/reset-password` to the `Referrer-Policy: no-referrer` header block
   next to `/demo-sign-in` (the pages also set `<meta name="referrer" content="no-referrer">`).
3. `features/auth` (web lane) was touched minimally: `signIn` returns the stage, `afterSignIn()` routes to
   `/two-step`, and the login form links "Forgot your password?" (its test updated).
4. DECISIONS.md: record §2 above.
5. Documented env: `LK_STORAGE_BACKEND=s3`, `LK_S3_BUCKET`, `LK_S3_ENDPOINT_URL`, `LK_S3_REGION` plus AWS
   credentials from the standard chain; `.env.example` and the runbook should mention them.
6. Navigation: consider listing `/activity` in the More hub and the sidebar's Settings sub-navigation (routes are
   registered with `navGroup: "context"` for the settings pages).

## 8. keys.py requests

None (tests use `keys.PEOPLE`, `keys.PARTY_NAMES`, `keys.PRODUCTS` and seed refs `Q_NORDHAUS_DRAFT`).

## 9. Gate output

(filled below)
