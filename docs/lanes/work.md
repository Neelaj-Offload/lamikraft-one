# Lane report: work (tasks + briefings), Slice 1 wave 1

Branch `lane/s1w1-work`, worktree `D:\lk-wt\work`, env slot 4. Status: **done for this wave**; every
pre-existing test stays green. Fixture steward requests are in "keys.py requests" below.

## 1. Implemented

### tasks (`backend/app/modules/tasks/`)
| Item | Files |
|---|---|
| Tables `tasks_issue` (UUIDv5 id of `company|issue_key|occurrence`, partial unique live key, occurrence+1 on recurrence), `tasks_issue_member` (expandable root-cause members), `tasks_task` (obligations: kind, origin rule/user/automation/seed, primary source ref + version, owner, assignee, initiator, queue, `due_at` + `due_kind` hard/soft/none, state open/in_progress/done/dismissed/cancelled/expired, completion check + evidence, dismissal reason/note, `closed_by`, scope attributes), `tasks_task_candidate`, `tasks_dependency` (blocked is derived), `tasks_task_history` and `tasks_change_log` (append-only), `tasks_reminder` (private), `tasks_snooze` (per-user overlay), `tasks_onboarding_template`, `tasks_queue` | `models.py`, `backend/migrations/versions/0006_work_slice1.py` (revision `0006`, down `0002`, RLS + append-only + enum CHECKs through helpers, downgrade implemented) |
| Stable ids and root-cause keys (`NS_LK_ISSUE` namespace constant), fingerprints | `issue_keys.py` |
| Reconciliation: one writer for issues/members/tasks/candidates/dependencies/history/change log; idempotent (same facts give no events or change rows), stale reads ignored, terminal tasks never reopened, an authorised dismissal (or a lapse) stands while the cause persists and keeps the issue open | `issues.py` (`apply_outcome`, `settle_issue`, `close_task`) |
| Responsibility: named person, next named person, team-lead fallback (`manager_membership_id`), then the family queue plus a `responsibility:{queue}` triage issue for `tasks.queue.manage` holders; approval candidates = active members minus the initiator that `approvals.is_eligible` accepts when evaluated as each member (`actor_for_member`) | `responsibility.py`, `issues.py` (`sync_queue`) |
| Rule consumer `tasks.rules` (exactly once via `app.platform.events.service.once`, migration-origin skipped, stale aggregate versions ignored, triggers re-read sources through SourceReaders) | `rules/consumer.py`, `rules/outcome.py`, `events.py` |
| Rule families: `common.approvals` (`approvals.proposal.*` → decision task for eligible approvers, soft due at shift end of the submission work date, closes on decision/invalidation/expiry incl. 24 h lapse); `sales.quote_review` + draft review grouped under the originating message; `sales.quote_expiry` ("expires today", hard due at the end of `valid_until` in company time, completes on extension/close, expires on lapse); `sales.customer_replies` (reply due at the shift end of the next working day, closes when replied or a linked quote is sent after arrival, blocked by an open review approval); `sales.enquiries`; `sales.customer_changes` (`parties.party.updated` → `info:party:{id}` FYI with a change-log row); `common.onboarding` (`identity.membership.activated` → template steps with completion checks + manager check-in) | `rules/families.py` |
| Completion checks ("mark handled" verifies the source, never trusts): reply_sent, quote_left_draft, quote_expiry_resolved, enquiry_answered, approval_decided (never), assertion, pref_briefing_saved, recent_record_exists, recent_search_exists, queue_empty | `completion.py` |
| Visibility: SQL predicate from the `tasks.task` ResourcePolicy + candidates, then authoritative `can_view_source` per source (policy `visible_ids` or reader-reported scope) | `visibility.py`, `policies.py` |
| Inbox (tabs tasks/approvals/conversations/exceptions, scopes mine/team/branch/company with 403 above the held scope, keyset cursor pages, source second pass, capabilities + allowed transitions), counts, task detail, complete/dismiss/start transitions (dismiss needs a reason enum + `tasks.task.dismiss` in scope; approvals undismissable), assign (owner or `tasks.task.assign` scope; assignee must be able to view the source), snooze bounded by the deadline (hard: due − 60 min; overdue: now + 120 min; none: 7 days), manual task create, private reminders CRUD | `service.py`, `schemas.py`, `router.py` |
| Jobs: overdue sweep (only time-driven fact; lapses quote-expiry tasks), reminder dispatch, visibility consistency job on `identity.membership.access_changed` / `identity.permission_override.changed` (re-derives open issues: eligibility and scope attributes) | `jobs.py`, `events.py` |
| UiSection `inbox_counts` | `manifest.py` |

### briefings (`backend/app/modules/briefings/`)
| Item | Files |
|---|---|
| Tables `briefings_briefing` (one per user and work date), `briefings_version` + `briefings_item` (immutable snapshots, append-only), `briefings_recommendation` (stale on fingerprint change), `briefings_item_state` (acked fingerprint, handled, dismissed), `briefings_acknowledgement` (append-only, monotonic), `briefings_pin` | `models.py`, migration 0006 |
| Deterministic engine: collect as the member (open tasks as owner/assignee/candidate, change log after the cutoff, closures by others, horizon, own reminders), visibility second pass, priority (DUE_TODAY 35, CUSTOMER_COMMITMENT_AT_RISK 25, YOUR_DECISION 20, ASSIGNED_TO_YOU 15, YOU_OWN 5, BLOCKED_BY −10, single highest responsibility component), bands P1–P4, sections (empty omitted), total order section → band → score desc → due asc → fact_at asc → issue id, initial view = top 5 + full list, recommendations (action, reason, effect, permitted alternatives filtered by allowed actions), greeting by period and first name, overview sentence composed from permission-filtered counts (no LLM) | `engine/{collect,priority,sections,recommend,overview,labels,fingerprint,model}.py` |
| Service: first open of the work date (rollover aware, advisory_xact_lock per user, generation inside a savepoint), permission-fingerprint regeneration, no manufactured versions (item-set hash + permission fingerprint), changes since the last acknowledged version (activation cutoff for new members, 7-day floor), "N updates" without re-sorting (`?version=` keeps the shown list), fallback (permission-filtered open tasks + last successful version re-filtered by current permissions, timestamps, `generation_failed` event), precompute, event-driven refresh, acknowledgements, item actions (snooze / unsnooze / mark_handled / dismiss / explain with stale-fingerprint 409 `item_changed`), delta since yesterday/last_workday/last_ack/ISO, voice/chat pins (pinned order, ordinal resolve, 410 `pin_ended`), refresh audience | `service.py`, `schemas.py`, `router.py`, `errors.py` |
| Subscriptions `briefings.refresh` (`tasks.*` → refresh members holding a current briefing; overdue facts wake snoozes) and `briefings.access_refresh`; jobs `briefings.refresh_user`, `briefings.precompute_due_shifts` (ScheduleDef every 300 s; creates the briefing 30 min before shift start on working days) | `events.py`, `jobs.py` |
| UiSection `briefing` (status, version, acknowledged_version, updates_available, generated_at) | `manifest.py`, `service.briefing_section` |

### Changes in this session (on top of the two earlier commits)
- Kept the uncommitted edits (reviewed sound): `issues.py` (dismissed/expired task stands and keeps the issue open while the rule still wants it; simplified evidence), `rules/families.py` (a lapsed quote never re-arms an expiry task; it expires).
- `rules/families.py`: a lapse or a withdrawn quote resolves the expiry issue as `source_closed` (same as the sweep).
- Own-reminder create/edit/cancel/complete now refresh the owner's current briefing (`tasks.service._reminder_changed` → `briefings.service.request_refresh`, one job per reminder version), because the catalogue has no reminder-edit event.
- Tests added: issue ids stable across regenerations, night shift work date + precompute (B-11), seeds idempotent, dismissed reply keeps the issue open, lapsed quote not reopened, event-after-lapse expires before the sweep, reminder changes refresh the briefing.

## 2. Seeds (order 80)
- `backend/app/seed/world/tasks.py`: sales onboarding template (3 steps), queues sales/operations/admin, `REMINDER_MEERA` (D−2 17:30, due D0+1 10:00), Arjun's onboarding at activation D0 08:00, `TASK_ARJUN_WALKTHROUGH` (by Sahil D0 08:05, due D0+2 18:30), `TASK_KABIR_COUNT` (by Ravi D0 08:10, due D0 14:00). Idempotent on business keys.
- `backend/app/seed/world/briefings.py`: Meera's briefing opened and acknowledged Sat D−2 18:05; Neha's Monday v1 generated 08:49 and acknowledged 08:50 (real engine at seeded clock times).

## 3. Tests (all on real PostgreSQL; full suite `npm run test:api`: **198 passed**)
| Folder | Count | Highlights |
|---|---|---|
| `backend/tests/unit/tasks` | 10 | uuid5 stability (hypothesis), fingerprints, snooze bounds |
| `backend/tests/unit/briefings` | 10 | ordering/bands/sections/initial-5/no-empty properties (hypothesis, derandomized), numerals-are-facts, visible-only counts, persona sentences, greeting, zone labels |
| `backend/tests/integration/tasks` | 30 | every rule family, responsibility fallback + queue, replay/migration origin, access-change re-check, inbox tabs/scopes/keyset, commands, reminders private, sweep, dispatch, lapse handling, reminder-driven refresh |
| `backend/tests/integration/briefings` | 47 | each persona of fixtures §9 (Meera, Sahil + A-08/A-09, Neha, Arjun, Kabir, Ravi, Priya, Ananya), A-04/A-05 (Berlin)/A-07/A-10, no manufactured versions, out-of-order, stable ids, recommendation invalidation, N-updates without re-sorting, acks, snooze bounds + overdue wake, mark-handled verification/dismissal, midnight rollover, Sunday, holiday, night shift, precompute, engine-failure fallback, pins, delta, 404 for others' resources, HTTP API + idempotency replay, UiSections, committed: concurrent first opens and tenant RLS isolation, aggregate-leak property |
| `backend/tests/contract/{tasks,briefings}` | 9 | catalogue events/handler keys, route authz + operationId grammar, no identity fields in bodies, payloads fit the catalogue, forced RLS + append-only triggers, no wall clock, pure engine, routers import no models |
| Lane total | **106** | |

The world (`backend/tests/integration/briefings/world.py`) models identity/parties/sales behind the real seams
(fake `actor_for_member` builder, fake SourceReaders, fake `sales.quote.review` approval handler, real outbox
events at fixture times, real approvals rows, the real tasks/briefings seeds). Switching to the real world when
sales merges: build through `registry.seeds`, drop the fakes; tests read ids from `world.refs` and text from `keys.EXPECTED`.

Gate results: section 9.

## 4. API endpoints
| Method and path | operationId | authz |
|---|---|---|
| GET `/api/v1/tasks/inbox` | `tasks_list_inbox` | `tasks.task.read` |
| GET `/api/v1/tasks/inbox/counts` | `tasks_get_inbox_counts` | `tasks.task.read` |
| POST `/api/v1/tasks/tasks` | `tasks_create_task` | `tasks.task.create` (idempotent) |
| GET `/api/v1/tasks/tasks/{task_id}` | `tasks_get_task` | `tasks.task.read` |
| POST `/api/v1/tasks/tasks/{task_id}/transitions` | `tasks_transition_task` | `tasks.task.update`, `tasks.task.dismiss` (idempotent) |
| PUT `/api/v1/tasks/tasks/{task_id}/assignee` | `tasks_update_task_assignee` | `tasks.task.assign` (idempotent) |
| PUT / DELETE `/api/v1/tasks/tasks/{task_id}/snooze` | `tasks_update_task_snooze` / `tasks_delete_task_snooze` | `tasks.task.read` |
| GET / POST `/api/v1/tasks/reminders` | `tasks_list_reminders` / `tasks_create_reminder` | authenticated (own only) |
| GET / PATCH / DELETE `/api/v1/tasks/reminders/{reminder_id}` | `tasks_get_reminder` / `tasks_update_reminder` / `tasks_delete_reminder` | authenticated (own only; others 404) |
| GET `/api/v1/briefings/today` | `briefings_get_today` | `briefings.briefing.read` |
| POST `/api/v1/briefings/{briefing_id}/acknowledge` | `briefings_create_acknowledgement` | `briefings.briefing.read` (idempotent) |
| POST `/api/v1/briefings/items/{issue_id}/actions` | `briefings_run_item_action` | `briefings.briefing.read` (idempotent) |
| GET `/api/v1/briefings/delta?since=` | `briefings_get_delta` | `briefings.briefing.read` |
| POST `/api/v1/briefings/{briefing_id}/pins` | `briefings_create_pin` | `briefings.briefing.read` (idempotent) |
| PATCH `/api/v1/briefings/pins/{pin_id}` | `briefings_update_pin` | `briefings.briefing.read` |
| POST `/api/v1/briefings/pins/{pin_id}/resolve` | `briefings_resolve_pin_reference` | `briefings.briefing.read` |

`backend/openapi.json` and `apps/web/src/lib/api/schema.d.ts` are not committed (integrator regenerates).

## 5. Events
- **Emitted:** `tasks.task.created|assigned|started|completed|dismissed|cancelled|expired|became_overdue`,
  `tasks.issue.opened|changed|resolved`, `tasks.reminder.fired`, `briefings.briefing.generated|updated|acknowledged|generation_failed`,
  `briefings.item.snoozed|unsnoozed`, `briefings.recommendation.invalidated`, `briefings.pin.started|ended`.
- **Consumed (`tasks.rules`):** `approvals.proposal.submitted|approved|rejected|expired|invalidated|superseded|cancelled|executed|execution_failed`;
  `sales.quote.created|updated|review_requested|review_withdrawn|issued|marked_sent|won|lost|cancelled|deleted|status_changed|revised|validity_extended`;
  `sales.customer_message.received|replied`; `sales.enquiry.received|assigned|quoted|closed`; `parties.party.updated`; `identity.membership.activated`.
- **Consumed (`tasks.visibility`, `briefings.access_refresh`):** `identity.membership.access_changed`, `identity.permission_override.changed`.
- **Consumed (`briefings.refresh`):** all `tasks.task.*`, `tasks.issue.*`, `tasks.reminder.fired`.

## 6. Permissions used
`tasks.task.read|create|update|assign|dismiss`, `tasks.queue.manage`, `briefings.briefing.read`; source checks
through `sales.quote.read`, `sales.customer_message.read`, `sales.enquiry.read`, `parties.party.read`,
`approvals.proposal.read`, `org.directory.read`; eligibility through the approvals engine (`sales.quote.approve`,
`sales.quote_price.approve`, permissions.md §10). No new keys.

## 7. Settings, sequences, jobs, seeds
- Settings: none (policy values are module constants for this wave: snooze lead 60 min, overdue snooze cap 120 min,
  horizon 3 working days, initial cap 5, change window 7 days, pin idle 30 min, reply SLA 1 working day).
- Sequences: none.
- Jobs: `tasks.overdue_sweep` (every 60 s), `tasks.reminder_dispatch` (every 60 s), `tasks.visibility_consistency`,
  `briefings.refresh_user`, `briefings.precompute_due_shifts` (every 300 s).
- Seeds: `tasks` (80), `briefings` (80).
- `PLATFORM_MODULES`: unchanged (no new platform packages).

## 8. Dependencies requested
None.

## 9. Gate
`npm run check -- --keep-going`: ruff PASS (after an import-format fix, re-run clean), pytest unit + contract PASS,
alembic heads == 1 PASS, **api:check FAIL (expected: routes changed; the integrator regenerates `openapi.json` and
`schema.d.ts`)**, web lint PASS, web typecheck PASS, web vitest PASS (134). Full backend suite `npm run test:api`:
198 passed.

## 10. keys.py requests (fixture steward)
1. `TEXTS = SimpleNamespace(REMINDER_MEERA="Call Maison about finish preferences",
   TASK_KABIR_COUNT="Count walnut boards in bin A-12", TASK_ARJUN_WALKTHROUGH="Complete product catalogue walkthrough")`
   (today in `app/seed/world/tasks.py`).
2. `ONBOARDING_STEPS = ("language_and_detail", "open_product", "global_search")` and the step titles.
3. Seed-ref keys for quotes and parties (`QUOTE_REFS.BERG_EXPIRING = "Q_BERG_EXPIRING"`, …; `keys.QUOTES` holds
   numbers, so tests currently index `world.refs["Q_BERG_EXPIRING"]` / `world.refs["MAISON"]`).
4. `EXPECTED.MEERA_S1_ITEM_ORDER` (issue keys of fixtures §9.1 in order) and `EXPECTED.BERLIN_DUE_LABEL = "Today 15:00"`.
5. Time constants used by seeds and tests (`REMINDER_MEERA_AT`, `MEERA_LAST_ACK_AT`, `NEHA_BRIEFING_AT`, `NEHA_ACK_AT`,
   `ARJUN_ACTIVATED_AT`).

## 11. Contract questions
1. **SourceReaders the next wave must register** (facts the rules read): `sales.quote` (quote_number, party_id,
   party_name, valid_until, sent_at, created_at, origin_message_id, revision_no, origin; status; money;
   `deadlines.valid_until_end`; owner/branch/required permission; `is_closed`), `sales.customer_message`
   (party_id, party_name, contact_name, channel, received_at, replied_at, linked_quote_ids; status), `sales.enquiry`
   (enquiry_number, party_name, received_at, channel; status), `parties.party` (name, party_number; owner),
   `identity.membership` (role_templates), `identity.user_preference` (briefing_saved), `ui.recent_record` and
   `search.recent` (count). Until they exist the onboarding checks answer `not_complete` with `cannot_verify:*`.
2. Sales must register the `sales.quote.review` ApprovalHandler (eligibility §10) — tests use a fake.
3. Section display order: the product brief lists Changes before Recommendations; fixtures §10 (architecture)
   orders the Maison follow-up (Recommendations) before the Maison address (Changes). Implemented per fixtures §10.
4. No catalogue event for reminder create/edit/cancel: implemented as a direct `briefings.refresh_user` job; a
   `tasks.reminder.changed` event would be cleaner.
5. Brief describes task kind `manual|system`; implemented fine-grained kinds (reply_needed, quote_expiry,
   review_draft, approval_decision, enquiry_reply, onboarding_step, onboarding_checkin, queue_triage, manual) plus
   `origin` (rule/user/automation/seed). Design-source paths `/briefings/changes` and `/acknowledgements` were
   replaced by the brief's `/briefings/delta` and `/{id}/acknowledge`.
6. `briefings.pin.started|ended` are tagged Slice 3 in events.md but are used now (voice pins are in this wave).

## 12. Known gaps (with reasons)
- No LLM phrasing / Explain elaboration (`ai_status = not_used`): Slice 3 by design; text is template-only.
- Leave and delegation day types ("For Ravi" items) and the WhatsApp summary: identity delegation/absence land in
  Slice 2, channels in Slice 3; holiday, weekend, rollover and night-shift behaviour are covered.
- Briefing templates, mandatory policy and personal preferences tables are not built; their values are constants
  (section 7). Prepare action is not offered (no sales preparers yet; no dead buttons). Approve/Reject are exposed
  as `via: approvals` actions and executed by the approvals API (wave 2).
- Refresh is deduplicated per (event, member) rather than a 20 s debounce; concurrent first opens wait on the
  advisory lock instead of falling back after 3 s (the committed concurrency test proves one briefing).
- Inbox CSV export, assignable-users, task history and dependency endpoints: Slice 2 / not in this brief.
- Tests run on the lane's fake world for identity/parties/sales until those lanes merge.

## Fix pass (2026-10-27)

Two adversarial reviews (2026-10-23) produced 15 correctness-security findings (CS) and 12 spec-conformance
findings (SP). An interrupted pass left uncommitted tasks-side fixes; this pass verified them, finished the
briefings side, added a regression test per fixed finding and committed: `7e7c95b` (tasks), `34e8822`
(briefings, migration 0006 column change, seed order), `029641a` (tests).

| finding | severity | status |
|---|---|---|
| CS1 older versions served after a revoke (?version=, pins, explain) | blocker | fixed in 34e8822 (untrusted versions re-check every source and member, overview withheld, blocker titles redacted, Explain/item 404, permission_change ends pins) |
| CS2 briefing Dismiss closes other people's obligations | major | fixed in 7e7c95b (caller's own tasks only) |
| CS3 manual assignment undone by re-derivation | major | fixed in 7e7c95b (`assigned_by` is an override while the assignee is active and can open the source) |
| CS4 inconsistent lock order, no retry | major | fixed in 7e7c95b (issue → tasks by id everywhere; `tasks.txn.retry_transient`, 3 attempts, on tasks and briefings HTTP commands; consumers/jobs retried by the job runtime) |
| CS5 refresh reads before the lock (duplicate version, false failure) | major | fixed in 34e8822 (re-read with populate_existing after the advisory lock) |
| CS6 reply items expose numbers of invisible quotes | major | fixed in 34e8822 (quote_numbers from visible quote members only) |
| CS7 reply ignores origin_message_id links | major | fixed in 7e7c95b; fake world no longer double-links (029641a) |
| CS8 undated P3/P4 obligations absent from Today | minor | fixed in 34e8822 (Plan for today) |
| CS9 whitespace reminder text → 500 | minor | fixed in 7e7c95b (schema validator + service guard) |
| CS10 briefings seed ordered before tasks seed | minor | fixed in 34e8822 (order 81) |
| CS11 N+1 in inbox and reconciliation | minor | fixed in 7e7c95b (per-page scope queries, batched policy visibility, member contexts cached per transaction) |
| CS12 aggregate-leak test did not test member counts | minor | fixed in 029641a (`test_no_aggregate_leak_property.py`) |
| CS13 inbox_counts without tasks.task.read | minor | fixed in 7e7c95b |
| CS14 naming another owner checked coarsely | minor | fixed in 7e7c95b (assign scope over the named owner; owner must see the linked record) |
| CS15 delta accepts any instant, no limit | minor | fixed in 34e8822 (clamped to the 7-day change window, keyset pages) |
| SP1 permission-only change writes a version | major | fixed in 34e8822 (`briefings_briefing.permission_fingerprint` records re-verification; no version, no "N updates") |
| SP2 onboarding depends on undefined readers; dead mark-handled | major | fixed in 7e7c95b/34e8822 for what the lane owns (role template from grants without a reader; mark_handled offered only when the check's reader is installed). The reader contract itself is a request below |
| SP3 PARITY_MATRIX names test files that do not exist | major | fixed in 029641a for A1–A4, B1–B4, B6, C2 (tests moved/added under the named files and functions); B5 lives in another lane's folder: request below |
| SP4 no consumer for identity.membership.deactivated | major | fixed in 7e7c95b (`common.offboarding`) |
| SP5 Sahil's facts omit rest_moving | minor | fixed in 34e8822 (boolean fact when the decisions template is used) |
| SP6 dead-letter / generation-failure consumers missing | minor | fixed in 7e7c95b/34e8822 (`admin.failed_jobs`, PARTIAL_RULES flag and `partial_families`) |
| SP7 every party update creates a change and version | minor | fixed in 7e7c95b (material fields only, re-read version check, no event id in the fingerprint) |
| SP8 refresh not debounced | minor | deferred: needs per-(user, work date) coalescing with a run_after delay and rewiring of the refresh tests; versions are still only written on real changes |
| SP9 optional concurrency guards | minor | partly fixed: expected_version required on task transitions/assignments (7e7c95b); PinUpdate gains an optional expected_version and PinView.version (34e8822; required would 409 voice clients after every ordinal resolve). Deferred: making item_fingerprint/briefing_version required on item actions changes the web client contract; coordinate with the web lane |
| SP10 Review action links to an unplanned /approvals/{id} route | minor | deferred: request below |
| SP11 literal fixture names in tests | minor | partly fixed in 029641a (tests import the seed constants); keys.py constants still pending (section 10) |
| SP12 delta and reminders not paginated | minor | fixed (reminders Page in 7e7c95b, delta CursorPage-style keyset in 34e8822) |

Contract note: CS1/SP1 needed two new columns on `briefings_briefing` (`permission_fingerprint`,
`consecutive_failures`), added to the lane's unmerged revision `0006` rather than a new revision.

### Gates (2026-10-27)
- `npm run test:api`: **224 passed** in 63.73s.
- `npm run check -- --keep-going`: ruff PASS, pytest unit + contract PASS (104 passed), alembic heads == 1 PASS,
  api:check FAIL (expected: `backend/openapi.json is out of date`, routes/schemas changed), web lint PASS,
  web typecheck PASS, web vitest PASS (134).

### Requests for the integrator
1. Regenerate `backend/openapi.json` and `schema.d.ts` (new/changed: `ReminderList` page fields, required
   `expected_version` on `TaskTransition`/`TaskAssignment`, `PinUpdate.expected_version`, `PinView.version`,
   `DeltaView.limit/next_cursor`, delta `limit`/`cursor` query, `OverviewView.facts` booleans).
2. PARITY_MATRIX SCN-B5 names `tests/integration/workcal/test_midnight_rollover.py::test_rollover_at_0400`
   (workcal folder, not this lane); the briefing-side rollover check is
   `tests/integration/briefings/test_versions_and_actions.py::test_midnight_rollover`.
3. Web lane: an `/approvals/[id]` review route (the briefing Review action and proposal source links use it),
   or tell this lane the canonical quote review route to point at.
4. Identity/UI/search lanes: register SourceReaders `identity.membership` (role_templates),
   `identity.user_preference` (briefing_saved), `ui.recent_record` and `search.recent` (count); until then the
   onboarding steps show no mark-handled control. The platform should emit `system.job.dead_lettered` with
   `handler_key` (consumed now).
5. Lane env note: the slot-4 databases were downgraded/upgraded to apply the 0006 change; tasks/briefings
   tables in `lk_wt4` are empty until the next seed run.
