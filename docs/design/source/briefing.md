> Design-workflow output (2026-10-12), kept as source material. Where it conflicts with docs/architecture/*, the architecture docs win.

# Tasks, domain-event consumption, Inbox and Daily Briefing engine (modules: tasks, briefings, workcal)

# Tasks, Events, Inbox and Daily Briefing: subsystem design

## 0. Scope and pipeline
- **Owns** three modules:
  - `tasks`: obligations, personal reminders, issues (root-cause registry and dedup), change log, rule engine that consumes domain events, Inbox.
  - `briefings`: generation, versioned snapshots, items, acknowledgements, snooze, actions, templates, policy, preferences, narration and pins, fallback, WhatsApp summary requests.
  - `workcal`: calendars, shifts, holidays, rollover, leave and delegation.
- **Depends on these interfaces:**
  - identity: effective permissions, `permission_fingerprint(user)`, responsibilities.
  - platform: outbox, event registry, jobs/scheduler, `Clock`, audit.
  - approvals/proposals (agents subsystem): `get_proposal`, `eligible_approvers`, `decide(proposal_id, expected_version, ...)`.
  - domain read services (sales, catalogue, operations, finance, imports, integrations).
  - channels: `whatsapp_briefing_eligibility`, `send_briefing_summary`.
  - voice: TTS adapter.
  - AI provider adapter.
- **Two-stage pipeline:**
  1. Domain events go to the `tasks` rule consumer. It reconciles issues, tasks and the change log, then emits `tasks.*` events.
  2. The `briefings` consumer refreshes snapshots only for affected users who already have a briefing today.
  3. The web client polls and WhatsApp reads the same state.
  - Briefings never interpret raw sales or operations events. One dedup point serves both Inbox and briefing.

## 1. File layout
```
backend/app/modules/workcal/{models,schemas,service,router,events,policies}.py
backend/app/modules/tasks/{models,schemas,service,router,events,policies,tools,consumers,jobs}.py
  issue_keys.py  completion.py  responsibility.py  facts/{sales,ops,finance,admin,common}.py
  rules/{base,registry,sales,operations,finance,admin,identity,agents}.py
backend/app/modules/briefings/{models,schemas,service,router,events,policies,tools,consumers,jobs}.py
  engine/{collect,visibility,group,priority,sections,recommend,overview,fingerprint,assemble}.py
  templates.py  phrasing.py  narration.py  fallback.py  i18n/{en,hi,hi_latn}.py
backend/app/seed/briefing_world.py           # shared by demo seed and tests
backend/tests/{unit,integration,contract}/{tasks,briefings,workcal}/
apps/web/src/app/(app)/today/{page.tsx,all/page.tsx,changes/page.tsx}
apps/web/src/app/(app)/inbox/{page.tsx,[taskId]/page.tsx}
apps/web/src/app/(app)/settings/{briefings,work-calendars}/...  apps/web/src/app/(app)/me/preferences
apps/web/src/components/briefing/{BriefingHeader,Section,Item,ItemActions,SnoozeMenu,HandledDialog,
  ExplainPopover,UpdatesPill,ListenControls,FallbackView,ChangesList}.tsx
apps/web/e2e/{today.sales,today.management,today.isolation,today.voice-pin,today.fallback,today.states,inbox}.spec.ts
```

## 2. Tables
All tables follow the shared conventions: company_id, created/updated by and at (timestamptz UTC), and an integer `version` on editable rows.

### workcal
- **workcal_calendars**: id, company_id, branch_id?, code, name, timezone (IANA, validated against tzdata), workweek_mask smallint (Mon=1 to Sun=64, CHECK > 0), day_rollover_local time (default 04:00). UNIQUE(company_id, code).
- **workcal_shifts**: id, calendar_id, code, start_local, end_local, crosses_midnight (generated from end <= start), rollover_local? (overrides the calendar), precompute_offset_min (0 to 240, default 30), weekday_mask, active. UNIQUE(calendar_id, code).
- **workcal_holidays**: calendar_id, holiday_date, name, kind {full, half_am, half_pm}. UNIQUE(calendar_id, holiday_date).
- **workcal_user_assignments**: user_id, calendar_id, shift_id, timezone_override?, effective_from, effective_to?. EXCLUDE overlapping dateranges per user (btree_gist).
- **workcal_leave**: user_id, start_date, end_date, part, status {requested, approved, rejected, cancelled}, approved_by, reason_code?.
  - Reason is visible only to approvers and admins. Others see "Unavailable".
  - CHECK end >= start.
- **workcal_delegations**: delegator_id, delegate_id, starts_at, ends_at, task_kinds[]? (null = all delegable), include_approvals bool (default false), status {active, revoked, expired}, reason.
  - CHECK delegator <> delegate and ends_at > starts_at.
  - INDEX(delegate_id, starts_at, ends_at).

### tasks
- **tasks_issues**: the root-cause registry.
  - Columns: id = uuid5(NS_LK_ISSUE, f"{company_id}|{issue_key}|{occurrence}"), company_id, branch_id, issue_key, occurrence, family, root_ref_type/id, state {open, resolved, info}, title_facts jsonb, fingerprint char(64), sensitivity, required_permission, scope attributes (scope_owner_id, scope_team_id, scope_branch_id), first_seen_at, last_changed_at, resolved_at, resolution {completed, dismissed, source_closed, superseded}.
  - UNIQUE(company_id, issue_key, occurrence). Partial UNIQUE(company_id, issue_key) WHERE state IN ('open','info').
- **tasks_issue_members**: the grouped symptoms.
  - Columns: issue_id, member_key, ref_type/id/version, facts, required_permission, scope attributes, active, added_at, removed_at.
  - PK(issue_id, member_key).
- **tasks_tasks**: obligations only.
  - Identity and classification: id (uuid7), company_id, branch_id, kind, family, issue_id FK, dedup_key.
  - Content: title, facts jsonb (typed per kind).
  - Source: primary_ref_type/id/version.
  - People: owner_user_id (accountable), assignee_user_id?, queue_code?, assigned_by, delegated_from_user_id?.
  - Due: due_kind {hard, soft, none}, due_at, due_on_date?, due_tz_basis.
  - State: state {open, in_progress, done, dismissed, cancelled, expired}, completion_check (registry code), completion_evidence jsonb, completed_by, on_behalf_of, dismissal_reason_code, dismissal_note, closed_at, overdue_emitted_at.
  - Access: required_permission, scope attributes, sensitivity, origin {rule, user, automation}.
  - CHECKs:
    - due_kind = 'none' if and only if due_at IS NULL.
    - done requires completion_evidence.
    - dismissed requires a reason code.
    - Terminal states require closed_at.
  - Indexes:
    - Partial UNIQUE(company_id, dedup_key) WHERE state IN (open, in_progress).
    - (company_id, assignee_user_id, state, due_at).
    - (company_id, owner_user_id, state).
    - (issue_id).
    - (company_id, primary_ref_type, primary_ref_id).
    - Sweep index (due_at) WHERE state IN (open, in_progress) AND overdue_emitted_at IS NULL.
  - Terminal rows are immutable. If the source regresses, a new row is created.
- **tasks_task_candidates**: task_id, user_id, reason {approver, delegate, queue}. Used for approvals with several possible approvers.
- **tasks_dependencies**: task_id, depends_on_task_id? or depends_on_ref_type/id?, condition_code.
  - CHECK exactly one target.
  - Cycles are rejected by a recursive CTE under an advisory lock.
  - "Blocked" is derived from dependencies, never stored.
- **tasks_task_sources**: task_id, ref_type, ref_id, ref_version, role {primary, evidence, related}.
- **tasks_history**: task_id, at, actor_user_id, actor_kind {user, system, automation}, on_behalf_of, action, from_state, to_state, details, correlation_id.
- **tasks_change_log**: the only allowed source of "changes".
  - Columns: id, company_id, issue_id, task_id?, event_id, event_type, fact_at (when the business fact happened), recorded_at, ref_type/id/version, change_code, before/after jsonb (typed), actor_user_id/automation_id, required_permission, scope attributes, sensitivity.
  - UNIQUE(event_id, issue_id). INDEX(company_id, issue_id, fact_at).
- **tasks_reminders**: personal and private, in a separate table by design.
  - Columns: id, company_id, user_id, text (max 280 characters), remind_at, tz, linked_ref?, linked_task_id?, state {pending, fired, done, cancelled}.
  - Visible only to user_id. Never counted in any aggregate. Never delegated.
- **event_consumptions** (platform-shared): PK(consumer, event_id).

### briefings
- **briefings_briefings**: id, company_id, user_id, work_date, day_type {working, non_working, holiday, leave}, timezone, calendar_id, shift_id, template_code, template_version, status {generating, ready, failed}, trigger {first_open, precompute, whatsapp, agent}, first_opened_at, current_version, last_success_version. UNIQUE(company_id, user_id, work_date).
- **briefings_versions**: immutable snapshot headers.
  - Columns: id, briefing_id, version, cause {initial, event_update, permission_change, manual_refresh}, cause_event_ids uuid[], data_as_of, permission_fingerprint, template_version, priority_rule_version, overview_facts jsonb, overview_template_code, partial_families[], item_set_hash.
  - UNIQUE(briefing_id, version).
- **briefings_version_texts**: PK(version_id, language). Columns: overview_text, item_texts jsonb, source {llm, template}, model, validated.
  - Phrasing never creates a version.
- **briefings_items**: immutable rows, one per issue per version, copy-on-write.
  - Placement and priority: section, rank, display_ordinal, priority_band, priority_score, reason_codes[].
  - Content: title, summary_text (template), facts jsonb (redacted), source_refs jsonb, fact_at.
  - People and due: owner_user_id, assignee_user_id, on_behalf_of_user_id, due_at, due_on_date, due_kind.
  - Action data: recommendation_id, uncertainty_flags[], allowed_actions jsonb, proposal_ref {id, version, content_hash, expires_at}.
  - Grouping and change: member_count, members jsonb, fingerprint, change_kind {new, changed, unchanged}, is_reminder.
  - UNIQUE(version_id, issue_id). INDEX(briefing_id, issue_id).
- **briefings_recommendations**: id, user_id, issue_id, action_code, reason_code, effect_code, facts, alternatives[], based_on_fingerprint, status {active, stale, accepted, dismissed, superseded}, invalidated_at, invalidated_by_event_id, result_ref?, proposal_ref?.
- **briefings_item_states**: PK(user_id, issue_id). Columns: company_id, acked_fingerprint, acked_version_id, acked_at, ack_channel, snoozed_until, snooze_set_at, snooze_channel, snooze_reason, version.
- **briefings_acknowledgements**: user_id, briefing_id, version, method {viewed, explicit, voice, whatsapp}, channel_message_id?, acknowledged_at.
  - Partial UNIQUE(user_id, channel_message_id).
  - Acks are monotonic: a lower version than the current max is ignored.
- **briefings_pins**: id, user_id, briefing_id, kind {voice, chat}, pinned_version, ordinal_map jsonb [{ordinal, issue_id, item_id}], state {active, paused, stopped, completed, expired}, position, channel, expires_at.
  - Partial UNIQUE(user_id, kind) WHERE state IN (active, paused).
- **briefings_templates**: id, company_id, code, name, parent_code?, version, status {draft, published, retired}, config jsonb (validated). UNIQUE(company_id, code, version).
- **briefings_role_templates**: PK(company_id, role_id) mapped to template_code.
- **briefings_policies**: PK company_id. Holds the mandatory controls (versioned config).
- **briefings_user_prefs**: PK user_id. Columns: language, detail_level, voice_enabled, voice_id, speech_rate, web_notifications, summary_time_local, personal_quiet_hours, default_snooze.

## 3. Invariants
1. Every item, count and change traces to a task, issue or change_log row, which in turn traces to a domain event or source record. Nothing is synthesized.
2. A new version is created only when the visible item-set hash or any item fingerprint differs from the previous version.
3. Within a version, each issue appears exactly once, in one section.
4. The initial view shows at most 5 items. Empty sections are never rendered.
5. Visibility is applied before grouping, counting, phrasing, narration, export, WhatsApp and tool output. Aggregates are computed only over the visible set.
6. Snooze never changes `due_at`, task state, escalation or obligation counts.
7. Money facts are always {amount: Decimal string, currency}. Sums are grouped by currency in SQL by the source module. The engine never sums across currencies. The LLM never sees unredacted costing.
8. Personal reminders never appear for anyone except their owner and never count as obligations.
9. A user's briefing resources are reachable only by that user. Any other id returns 404.

## 4. Event consumption and rules
### Consumer algorithm (`tasks/consumers.handle(event)`)
1. Begin a transaction. Insert into `event_consumptions('tasks.rules', event_id)`. On conflict, stop (the event is a duplicate).
2. For each rule registered for `event.type`, call `rule.derive(event, reader)`.
   - `reader` is a read-only facade over the domain services.
   - The rule re-reads the authoritative source state. The event is only a trigger.
   - If the source version is lower than the stored `primary_ref_version`, the event is stale and is ignored.
3. The rule returns a `RuleOutcome`, which may contain:
   - `IssueUpsert(issue_key, root, title_facts, members, scope, sensitivity)`
   - `TaskUpsert(dedup_key, kind, responsibility, due, completion_check, required_permission)`
   - `TaskClose(dedup_key, state, evidence | reason)`
   - `ChangeEntry(change_code, before, after, fact_at)`
4. `service.apply_outcome` then:
   - computes the fingerprint;
   - upserts the issue (if the previous occurrence is resolved, it opens occurrence + 1);
   - upserts tasks by dedup_key and resolves the assignee via `responsibility.resolve`;
   - inserts change_log rows;
   - writes `tasks.*` events to the outbox. All of this happens in the same transaction.
5. If no responsible user is found, the task goes to `queue_code` and an admin issue `responsibility:{queue}` is opened. Work is never silently dropped.

A rule exception is retried by the platform with bounded attempts, then dead-lettered. A dead-lettered rule family sets `partial_families` on the next versions, shown as "Shortage checks unavailable since 09:02".

### Issue keys (deterministic root cause)
Each key below is listed with the members grouped under it.
- `msg:{message_id}`: customer request. Members: reply task, draft quote review, automation evidence.
- `quote:{id}:expiry`
- `quote:{id}:review`: used when no originating message exists.
- `approval:{proposal_id}`: the version is part of the fingerprint, not the key.
- `sample:{id}:followup`
- `info:party:{id}`: informational stream (state `info`, occurrence 1).
- `returnable:challan:{id}`: members are the challan lines.
- `cutplan:{id}:review`
- `po_line:{id}:late`: root when a covering supply is late. Members: shortage, blocked work orders, at-risk sales-order dispatches.
- `shortage:{product}:{warehouse}`: used when no late supply exists.
- `dispatch:{id}:cutoff`
- `qc:{inspection_id}`
- `receipt:{id}:unmatched`
- `invoice:{id}:exception`
- `acctsync:{batch}`
- `import:{job_id}`
- `integration:{connection_id}`
- `access:{request_id}`
- `completeness:{rule}:{category_id}`: members are products.
- `onboarding:{user}:{step}`
- `manual:{task_id}`

Root-cause chains follow only explicit `caused_by` links returned by source services. Grouping is never fuzzy.

### Event catalogue
Format: event → family → issue / task kind / responsibility → close condition (slice). Names are proposals. A contract test asserts that each name exists in the platform event registry.

**Sales**
- `sales.customer_message.received` → sales.customer_replies → msg / reply_needed / party.account_owner, due within the policy SLA in working days. Closes on `sales.customer_message.replied` or when the linked quote is sent. (Slice 1)
- `sales.enquiry.received` / `sales.enquiry.assigned` → sales.enquiries → enquiry_reply / enquiry.assignee. Closes when the enquiry is quoted or closed. (Slice 1)
- `sales.quote.created` (origin user or agent) → sales.quote_review → review_draft / quote.owner. Closes when status leaves draft. (Slice 1, scenario C)
- `sales.quote.sent`, `sales.quote.validity_extended`, `sales.quote.revised`, `sales.quote.expired`, `sales.quote.status_changed`, `sales.quote.reassigned` → sales.quote_expiry → quote_expiry (hard, due on valid_until in the company time zone) / quote.owner.
  - Completes on won, lost, cancelled or archived, on an extension, or when a new revision is sent.
  - Becomes `expired` when the quote lapses.
  - Reassignment updates scope attributes. (Slice 1)
- `catalogue.price_list.published` → sales.commercial_exceptions → ChangeEntry on each affected open-quote issue, plus recommendation COMPARE_PRICE_IMPACT. (Slice 1)
- `agents.proposal.submitted`, `.revised`, `.approved`, `.rejected`, `.invalidated`, `.expired`, `.executed` → common.approvals → approval / candidates = eligible_approvers minus the initiator. Closes on a decision, invalidation or expiry. A revision changes the fingerprint and invalidates recommendations. (Slice 1)
- `sales.sample.dispatched` / `sales.sample.delivered` → sales.samples → recommendation PREPARE_FOLLOWUP (no obligation unless policy sets one). (Slice 2)
- `sales.party.updated` → sales.customer_changes → `info:party:{id}`. (Slice 1)
- `sales.quote.margin_below_threshold` → mgmt.margin_exceptions (sensitivity costing). (Slice 4)

**Agents**
- `agents.automation_run.completed` / `.failed` → common.handled: evidence for "Handled for you", or a failure issue for the automation owner. (Slices 1 and 3)

**Operations**
- `operations.challan.issued` (returnable), `operations.challan.return_received`, `operations.challan.closed`, `operations.challan.cancelled` → ops.returnables → returnable_due / challan.owner. Completes when all lines are reconciled. (Slice 2)
- `production.cut_plan.saved` → ops.cut_plans → review. (Slice 2)
- `inventory.shortage.detected` / `.resolved`, `procurement.po_line.arrival_changed`, `production.work_order.blocked` / `.released`, `inventory.reservation.conflicted` → ops.shortages, ops.production_dependencies, mgmt.decisions. (Slice 4)
- `procurement.grn.posted`, `quality.inspection.requested` / `.failed` → ops.receipts, ops.qc. (Slice 4)
- `logistics.dispatch.scheduled` / `.completed` → ops.dispatch_cutoffs (hard due at the cutoff). (Slice 4)

**Finance**
- `finance.receipt.recorded` / `.unmatched`, `finance.invoice.issue_blocked` / `.draft_ready`, `finance.accounting_sync.failed` / `.completed` → fin.* families. (Slice 5)

**Admin and identity**
- `imports.job.failed` / `.completed` (with errors) → admin.failed_imports. (Slice 2)
- `integrations.connection.failed` / `.restored` → admin.failed_integrations. (Slice 3)
- `catalogue.completeness.changed` → admin.data_completeness, grouped per category. (Slice 2)
- `identity.access.requested` / `.decided` → admin.access. (Slice 1)
- `identity.user.activated` → onboarding tasks from template.onboarding_steps, plus a check-in task for the manager. (Slice 1)
- `identity.user.deactivated` → cancel their reminders and open a "Reassign N open tasks" issue for their manager or admin. (Slice 1)
- `identity.user.permissions_changed` → consumed by briefings (regenerate).

**Workcal**
- `workcal.leave.approved` / `.cancelled`, `workcal.delegation.created` / `.revoked` → audience changes for briefings.

**Channels**
- `channels.briefing_ack.received`, `channels.briefing_request.received`, `channels.item_action.received`, `channels.employee_conversation.escalated` (conversation task). (Slice 3)

**Emitted by this subsystem**
- `tasks.task.created`, `.assigned`, `.started`, `.completed`, `.dismissed`, `.cancelled`, `.expired`, `.became_overdue`
- `tasks.issue.opened`, `.changed`, `.resolved`
- `tasks.reminder.fired`
- `briefings.briefing.generated`, `.updated`, `.acknowledged`, `.generation_failed`
- `briefings.item.snoozed`, `.unsnoozed`
- `briefings.recommendation.invalidated`
- `briefings.pin.started`, `.ended`
- `briefings.summary.requested` (consumed by channels)

## 5. Priority, sections, recommendations
### Priority (`engine/priority.py`, pure and versioned)
The score is the sum of the weights from the template (bounded by policy). Each component adds a reason code:
- **Due:** OVERDUE (hard) 50; DUE_WITHIN_2H 40; DUE_TODAY 35; SOFT_OVERDUE 20; DUE_NEXT_WORKDAY 15; DUE_WITHIN_3_WORKDAYS 5.
- **Dependencies:** BLOCKS_DEPENDENTS(n) 10 per dependent, capped at 30; BLOCKED_BY −10.
- **Impact:** CUSTOMER_COMMITMENT_AT_RISK 25; PRODUCTION_BLOCKED 25; FINANCIAL_EXCEPTION 20; HIGH_VALUE 10. HIGH_VALUE uses a per-currency threshold from policy and never converts with FX.
- **Responsibility:** YOUR_DECISION 20; ASSIGNED_TO_YOU 15; DELEGATED_TO_YOU 10; YOU_OWN 5; FYI 0.
- **Bands:** P1 ≥ 70; P2 40 to 69; P3 15 to 39; P4 below 15.
- **Total order:** band, score desc, due_at asc (nulls last), fact_at asc, issue_id.

### Sections (each issue placed exactly once, first match wins)
1. **needs_you_now**: actionable by the user, not blocked, not snoozed, and (P1, overdue, due within 2 hours, or an approval or decision due within the current work window).
2. **plan_for_today**: actionable and due within the work window, or blocked with expected unblock today, or P2 with no due date, or a personal reminder due today.
3. **recommendations**: an active rule-derived suggestion with no obligation, such as a follow-up draft, price impact or offcut match.
4. **changes_since_last_visit**: info or FYI issues with change_log rows after the cutoff whose fingerprint differs from `acked_fingerprint`. Actionable issues that changed stay in their own section with a "Changed" marker.
5. **handled_for_you**: tasks closed after the cutoff by others or by automation where the user is owner, assignee or candidate, or completed automation runs for the user, each with `result_refs`. This excludes issues that still have an open obligation for the user; those show the handled work as evidence inside the item.
6. **coming_next**: obligations, reminders and scheduled operations (dispatch, returnables, expiries) due after the window and within `horizon_workdays`, skipping non-working days.

Snoozed items are kept out of all sections and are listed in the full list under the filter "Snoozed until …".

### Recommendations
A rule table maps `(kind, facts)` to a recommendation:
- action_code, label;
- reason_code;
- expected_effect_code, rendered only from facts (for example "Unblocks WO-2026-0031, afternoon shift");
- permitted alternatives, filtered by permission.

Persisted with `based_on_fingerprint`. When a new fingerprint arrives for the issue: the old recommendation is marked `stale`, an invalidated event is emitted, and a new recommendation is computed. Actions that reference a stale `recommendation_id` return 409 `RECOMMENDATION_STALE` together with the fresh item.

### Uncertainty flags
- STALE_STOCK_DATA(as_of), shown as for example "No warehouse update since yesterday 18:10"
- MISSING_PRICE
- FX_UNAVAILABLE
- CAPACITY_UNKNOWN
- INTEGRATION_NOT_CONNECTED(provider)
- ESTIMATE
- SOURCE_CHANGED_SINCE_REVIEW
- PARTIAL_RULES(family)
- DEMO_DATA

## 6. Generation on first open (`service.get_today`)
1. Inject the actor (server side). Resolve company, effective permissions and `perm_fp`.
2. Compute `work_date` and `day_type` with workcal (§10).
3. Look up the briefing for (company, user, work_date).
   - If it is ready and the latest version has `perm_fp` equal to the current one: set `first_opened_at` if it is null and return the latest version. If a pin is active, return the pinned version with a state overlay. Done.
   - If `perm_fp` differs: regenerate with cause `permission_change` before serving.
4. Take `pg_advisory_xact_lock(hash(company, user, work_date))` and insert the briefing as `generating`. Concurrent opens wait up to 3 seconds, then receive the fallback.
5. **Collect** (`engine/collect`), every query through `visibility.task_predicate(actor)`:
   - (a) open tasks where the user is assignee, candidate or owner, plus tasks of active delegators within the delegation scope, plus queues the user subscribes to;
   - (b) watch-family issues from the effective template (management cross-team blockers, margin exceptions, financial summary);
   - (c) change_log rows after `cutoff = max(last_ack_at, user.activated_at, now − 7 days)`;
   - (d) closures and automation runs after the cutoff;
   - (e) the horizon for coming_next;
   - (f) the user's own reminders.
6. **Visibility second pass:**
   - `can_view(actor, ref)` per source ref and per group member. Rows that fail are dropped.
   - Facts are redacted by field class (costing, margin, finance).
   - `member_count` counts visible members only.
7. **Group** by issue_id. Tasks of the same issue merge in to supply actions and due dates.
8. Compute priority (§5).
9. Assign sections (§5).
10. Overlay user state: snoozed items are moved aside, and acknowledged-unchanged info items are dropped.
11. Recommendations, uncertainty flags, `allowed_actions` (§9) and `proposal_ref`.
12. **Global rank** by section order, then priority order. Assign `display_ordinal` from 1 to N. `initial_item_ids` are the first 5. Other non-empty sections render as count links. Empty sections are omitted.
13. **Overview facts:**
    - Counts come from SQL over the visible item ids.
    - Money totals come from the source module, `SUM ... GROUP BY currency`.
    - The deterministic `overview_template_code` is selected per language (§11).
14. Persist the version, items and recommendations. Set status `ready`. Emit `briefings.briefing.generated`. Commit.
15. Enqueue `briefings.phrase_version` (optional LLM). Return the response with deterministic text immediately.

Target: under 2 s p95 for 300 candidates. There are no N+1 queries; batched `can_view` uses scope attributes.

## 7. Event-driven updates
1. The `briefings` consumer receives `tasks.issue.*` / `tasks.task.*` and checks idempotency (consumer `briefings.refresh`).
2. Audience = assignees, candidates and owners of the issue's tasks, plus active delegates, plus users whose template watches the issue family and who pass the visibility predicate, plus users whose latest version already contains the issue.
3. For each audience user with a briefing on their current work_date, upsert a job `briefings.refresh_user` with dedupe key (user, work_date) and a 20-second debounce. Users without a briefing today are skipped; their first open computes everything fresh.
4. The job:
   - locks the briefing row;
   - recomputes only the affected issues through steps 5 to 13 (scoped);
   - compares fingerprints and the item-set hash;
   - if unchanged, does nothing (no manufactured version);
   - otherwise copies unchanged items, replaces, adds or removes the changed ones, re-ranks, invalidates stale recommendations, writes version n+1 with `cause_event_ids`, and emits `briefings.briefing.updated`.
5. **Clients:**
   - The web client polls `GET /briefings/today/status` (ETag; every 60 s while visible and on focus). It shows "N updates" and never re-sorts until the user applies.
   - In-place state changes (handled, approved, snooze ended) are overlaid without moving rows.
6. **Time:**
   - `tasks.overdue_sweep` runs every minute on an indexed query and emits `tasks.task.became_overdue`, which is a real fact. This also wakes snoozes (mandatory policy).
   - No other passage of time creates versions. Snooze expiry is a read-time overlay.

## 8. Acknowledgements, changes, delta
- **Ack** is written by:
  - web: briefing visible for ≥ `policy.ack_on_view_seconds` (default 3; 0 disables), method `viewed`;
  - "Mark all seen", method `explicit`;
  - narration completed, method `voice`;
  - WhatsApp "Got it", method `whatsapp`, idempotent on `channel_message_id`.
- Each ack bulk-upserts `item_states.acked_fingerprint` for all items in the acknowledged version. It is monotonic per user.
- **Changes since your last visit** are computed relative to the latest ack on any channel (cross-channel sync).
  - If the latest ack equals the current version, the header shows "Up to date · checked 09:12" and the section is omitted.
  - After leave, the window is bounded to 7 days with an explicit note.
- **"What changed since yesterday?"** calls `GET /api/briefings/changes?since=yesterday`.
  - "yesterday" means the rollover instant of the previous calendar date in the user's time zone. The response states the instant used.
  - Output: change_log rows grouped by issue, with fact_at, actor, typed before and after values, and source links. Permission-filtered, with the same redaction.
  - The UI offers a "Since your last workday" toggle.

## 9. Actions and applicability (`briefings/policies.allowed_actions`)
Every POST carries an `Idempotency-Key`, `briefing_version` and `item_fingerprint`. If the item changed, the response is 409 `ITEM_CHANGED` with the fresh item. Authority is always re-checked by the owning service at execution time.

- **Open**: shown when the source `can_view` passes. It is a link to the canonical screen, which re-checks access.
- **Prepare**: shown when the recommendation has a registered preparer and the user holds the draft-create permission. It runs a reversible draft through the domain service (for example a repeat quote, follow-up message draft, validity-extension revision or requisition draft). A stale recommendation returns 409. Preparers not yet built are not shown, so there are no dead buttons.
- **Assign**: shown to the owner, or to a user with `tasks.assign` whose scope covers the task. Candidate users come from `GET /tasks/{id}/assignable-users`: only active users who can view the source, with leave status flagged. Never shown for reminders.
- **Review**: shown when a draft or proposal awaits the user's review. It opens the review screen with `proposal_id@version`.
- **Approve / Reject**: shown only for approval tasks where the user is an eligible candidate, is not the initiator (separation of duties), and the proposal is current and unexpired. The call goes to `approvals.decide(proposal_id, expected_version)`. A mismatch returns 409 `PROPOSAL_CHANGED`. A revoked permission returns 403 and nothing executes. Reject requires a reason.
- **Snooze**: shown for open items in actionable sections.
  - `until` must not exceed `due_at − policy.snooze_deadline_lead_min` (default 60) for hard deadlines. Otherwise 422 `SNOOZE_BEYOND_DEADLINE {max_until}`.
  - Overdue items allow at most `policy.max_snooze_overdue_min` (default 120).
  - Kinds listed in `policy.unsnoozable_kinds` cannot be snoozed.
  - Material changes and overdue events wake the item.
- **Mark handled**: shown for obligations, never for approvals.
  - The server runs `completion.check(task)` against the source. If complete, the task becomes `done` with evidence. If not, 409 `NOT_COMPLETE {remaining}`.
  - An authorised dismissal is also offered when the user holds `tasks.dismiss` for the kind and scope. It takes a reason code from an enum plus a note. The issue stays open while the root cause persists. Kinds listed in `policy.undismissable_kinds` (approvals, compliance) cannot be dismissed.
  - Manual tasks use an assertion check: the assignee confirms, optionally with evidence, and the owner may be required to confirm by policy.
- **Explain**: always shown. It returns the reason codes as deterministic text, the rule version, the recommendation reason and the sources, plus optional LLM elaboration (§11).

## 10. Calendars and boundaries (`workcal/service`)
- `rollover(user)` = the shift's rollover_local, else the calendar's day_rollover_local.
- `work_date(user, t)` = `(local(t) − rollover).date()`. With rollover 04:00, 00:10 on Tuesday still belongs to Monday. A night shift from 22:00 to 06:00 with rollover 08:00 makes 02:00 on Tuesday part of Monday's work date.
- Work window for date D = [rollover instant of D, rollover instant of D+1). "Due today" means due_at falls inside the window.
- `day_type`: weekday not in workweek_mask gives non_working; a holiday gives holiday; approved full leave gives leave.
  - Non-working, holiday or leave briefings show only overdue or hard deadlines due before the next working window, plus changes and coming_next (the next working day's plan). Plan for today is omitted.
  - There is no precompute or push on these days.
  - A leave briefing lists "With Vikram (delegate)" items.
- **SLA:** `due = shift_end(next_working_day(work_date(receipt), n))`. For example, a message received on Sunday at 17:40 is due Monday at 18:30.
- **Delegation:** the delegate sees the delegator's delegable tasks marked "For Ravi". The delegate's own permissions filter what is visible. Approvals transfer only if `include_approvals` is set and the delegate is independently eligible. Completion records `on_behalf_of`.
- **Quiet hours:** a company window, which users may extend but not shorten. Quiet hours suppress proactive pushes (web notifications, WhatsApp) only. Pushes are queued and re-checked before sending. Briefing contents are never suppressed.
- **Default assumptions** (configurable, recorded in DECISIONS):
  - Asia/Kolkata; workweek Monday to Saturday; office shift 09:30 to 18:30; rollover 04:00; precompute 30 minutes before shift start.
  - Add the `tzdata` dependency, because Windows has no system time-zone database.

## 11. Where the LLM is used, and fallback
- **Deterministic always:** facts, counts, totals, priority, sections, recommendations, overview template text (en; hi and hi-Latn labelled "untested").
- **LLM only in:**
  1. `phrasing.py`: rewording the overview sentence and item explanations in the preferred language. Stored in `version_texts`.
  2. Explain elaboration.
  3. Optional smoothing of the narration script.
- **LLM inputs:** only the redacted, visible facts and reason codes, plus rule descriptions.
- **LLM output validator:**
  - every numeral and amount equals a fact;
  - every currency code is preserved;
  - every proper noun is in the facts;
  - no new dates;
  - at most 2 sentences.
  - On failure, the template text is used. Timeout 4 s. The model is chosen from settings (cheap tier). Demo mode uses a deterministic adapter labelled "Demo".
- **Overview templates:**
  - Management: `decisions_pending = N` and `rest_moving` (no visible non-decision item is OVERDUE or a cross-team blocker) gives "{N-word} decision(s) need(s) you. The rest is moving." Otherwise "{N} decisions need you. {M} items are overdue." and so on.
  - Sales: ordered clauses for customer replies, quotes expiring today, and samples delivered since the ack (special case "yesterday's sample" when count is 1 and fact_date is yesterday).
  - New user: "Welcome, {name}. You have {n} onboarding steps and {m} assigned tasks."
  - Empty: "Nothing needs you right now."
  - The greeting (morning, afternoon, evening) is computed from the local time.
- **AI outage:** status ready, `ai_status=unavailable`, template text shown with the label "Standard wording". Explain returns rule text only.
- **Engine failure:**
  - Response: HTTP 200 with `status=fallback`.
  - It contains `fallback.tasks`, from `tasks.service.list_my_open_tasks(actor)`: an independent, simple, permission-filtered query ordered by due date.
  - It also contains `fallback.last_successful`: the most recent ready version, with generated_at and data_as_of. It is re-filtered by current permissions. Its overview is omitted if `perm_fp` differs.
  - The response includes a timestamped error banner. `briefings.briefing.generation_failed` is emitted.
- **Database or network down:** the client renders its cached version labelled "Offline · as of 09:02". Actions are disabled. Nothing claims to be committed.

## 12. Isolation
- The visibility predicate is compiled from the actor's permission map:
  - (required_permission at company scope)
  - OR (branch scope AND scope_branch_id IN actor.branches)
  - OR (team scope AND scope_team_id IN actor.teams)
  - OR (own scope AND actor IN (scope_owner, assignee, candidate)).
- Source modules emit ownership and scope changes. Rules update the scope attributes. The authoritative `can_view` re-check happens on open, action, Explain and members.
- Other users' briefing, version, item, pin or task ids return 404. Requesting a scope you do not hold (`/inbox?scope=company`) returns 403.
- No "N hidden items" text. Overview facts are computed only from the visible set. Group titles use only redacted title_facts. Change rows require their own permission.
- WhatsApp, narration, tools, CSV and LLM consume the same filtered item models. `policy.channel_max_sensitivity.whatsapp` excludes costing, margin and finance unless allowed.
- There is no admin read of other users' briefings. A role-simulator preview is future scope.

## 13. Listen to my day, and stable references
- `POST /briefings/{id}/pins {kind: voice}` pins the current version.
  - It stores the `ordinal_map` for the initial 5 items, or N items when detail is "full".
  - It returns script segments built deterministically from templates: "Second. Decision. Nordhaus export quote. 240 oak trays, EUR 5,760. Suggested: review the terms." It also returns short-lived authenticated TTS audio from the voice adapter.
- Pause, resume and stop are client-side and take effect immediately. `PATCH /pins/{id}` then records state and position.
- **While a pin is active:**
  - GET returns the pinned order with an in-place overlay and `pending_updates`.
  - "Open the second item" resolves through `POST /pins/{id}/resolve {ordinal: 2}` (or a label match within the pinned list) to an issue.
  - If that issue was resolved since, the reply says so before opening.
- A pin ends on stop, on completion (which acks the pinned version), or after 30 minutes idle. A stopped pin returns 410 `PIN_ENDED`.
- Chat pins work the same way for typed references to the second item.

## 14. WhatsApp summary and channel sync
The briefing consumes the channels interface.
- **Job** `briefings.whatsapp_summary(user, work_date)`: idempotent, runs at `prefs.summary_time_local` on working days outside quiet hours. It proceeds only if:
  - the user has explicit opt-in consent (purpose `daily_briefing_summary`) and has not opted out;
  - the employee link is active;
  - `eligibility` returns either a template that is approved and active, or an open service window.
- If the job is not eligible, no push is sent and the reason is audited. On-demand requests ("What should I handle today?") call `get_today(channel=whatsapp)`.
- **Content:** counts, the top 3 titles up to the channel's sensitivity limit, and a short-lived authenticated link. Quick replies: "Got it" (ack of `version_id`) and "Open Today". Simulated sends are labelled Demo.
- Item actions sent over WhatsApp (snooze, unsnooze, mark handled) call the same service functions, so state is shared with the web.

## 15. Templates, policy, preferences
- **Template config** (Pydantic, `extra=forbid`): rule_families, exclude_families, section_order (a permutation of the six), initial_item_cap (1 to 5), horizon_workdays (1 to 5), priority_weights (bounded), overview_templates, kpi_fact_queries, onboarding_steps, narration {max_items, max_seconds = 75}.
- **Effective template:** the parent chain merged up to depth 4, with cycles rejected on save. Families: union minus excludes. Weights: overridden by the child. `common.*` families are mandatory and cannot be excluded.
- **Seeded templates:** base, sales, operations, management, finance, admin. `role.created` maps a new role to its parent template, base by default.
- Templates choose content only. They never grant visibility.
- **Policy (mandatory, admin only):** snooze bounds, unsnoozable and undismissable kinds, ack_on_view_seconds, SLA workdays, HIGH_VALUE thresholds per currency, channel sensitivity limits, company quiet hours, retention days.
- **Preferences (personal):** language, detail level, voice, notification schedule, personal quiet hours (extend only). Any attempt to weaken a policy returns 422 `MANDATORY_CONTROL`.

## 16. API (all under /api, identity injected server-side)
**Briefings**
- `GET briefings/today?pin=&lang=` returns BriefingView: briefing_id, work_date, day_type, version, status, generated_at, data_as_of, ai_status, overview{greeting, text, text_source, facts}, sections[{code, total, item_ids}], items[ItemView], initial_item_ids, pending_updates, last_ack, partial_families, fallback?.
- `GET briefings/today/status`: version, pending_updates and counts. Polled with an ETag.
- `GET briefings/today/items?section=&filter=snoozed|all&cursor=`
- `GET briefings/{id}/versions/{v}`
- `GET briefings/{id}/versions/{v}/diff?from=`
- `GET briefings/changes?since=last_ack|yesterday|last_workday|<iso>`
- `POST briefings/{id}/refresh`: rate-limited. It does not create a version if nothing changed.
- `POST briefings/{id}/acknowledgements {version, method}`
- `POST|DELETE briefings/items/{issue_id}/snooze`
- `POST briefings/items/{issue_id}/actions/{prepare|assign|review|approve|reject|mark_handled|dismiss}`
- `GET briefings/items/{issue_id}/explain`
- `POST briefings/{id}/pins`
- `PATCH briefings/pins/{pin_id}`
- `POST briefings/pins/{pin_id}/resolve`
- `GET|PUT me/briefing-preferences`
- Settings: `settings/briefing-templates` (CRUD and publish), `settings/briefing-policy`, `settings/roles/{id}/briefing-template`

**Workcal**
- `settings/work-calendars` with nested `/shifts` and `/holidays`
- `users/{id}/work-assignment`
- `leave` (request, approve, cancel)
- `delegations` (GET, POST, DELETE)

**Tasks and Inbox**
- `GET inbox?tab=tasks|approvals|conversations|exceptions|snoozed|done&scope=mine|team|branch|company&kind=&due=&q=&cursor=`
- `GET inbox/counts`
- `GET inbox/export.csv`: visible rows only, formula-escaped.
- `POST tasks` (manual obligation; the assignee must be able to view the linked record)
- `GET|PATCH tasks/{id}` (PATCH with `If-Match` on version)
- `POST tasks/{id}/{assign|start|complete|dismiss}`
- `GET tasks/{id}/history`
- `GET tasks/{id}/assignable-users`
- `POST|DELETE tasks/{id}/dependencies`
- `reminders` (CRUD)

**Test-only**
- `POST _test/clock` and `POST _test/faults`: mounted only when `APP_ENV=test`.

**Agent tools** (`tools.py`; no identity parameters; `extra=forbid`)
- get_daily_briefing(section?, full?)
- explain_briefing_item(item_ref)
- resolve_briefing_reference(ordinal | label)
- snooze_briefing_item
- mark_item_handled
- acknowledge_briefing
- list_my_tasks
- create_personal_reminder
- assign_task (subject to policy)

## 17. Jobs (durable worker)
- `tasks.overdue_sweep`: every 1 minute.
- `tasks.reminder_dispatch`: every 1 minute; uses the same index pattern.
- `briefings.precompute_due_shifts`: every 5 minutes. For each shift whose start minus offset falls in [now, now + 5 min) on a working day, enqueue `precompute(user, work_date)` for active users not on leave. Idempotent because the briefing row is unique.
- `briefings.refresh_user`: debounced.
- `briefings.phrase_version`
- `briefings.whatsapp_summary`
- `briefings.retention_cleanup`: daily, starting in slice 5.

## 18. Seed fixtures (`seed/briefing_world.py`)
- **Anchor and data rules:**
  - All times are offsets from an anchor work date D0. Tests freeze the clock at Mon 2026-10-12 08:55 IST (03:25Z). The demo seed uses `--anchor-date` (default: today).
  - All names are fictional. Emails use `@demo.lamikraft.test`. Credentials are provisioned per the platform seed policy and never stored in the repo.
  - Prior-day briefings are created by running the real engine at seeded clock times.
- **Company and calendars:**
  - Crown Decor Pvt. Ltd. (demo), branch HO.
  - Calendar HO: Asia/Kolkata, Monday to Saturday, shift GEN 09:30 to 18:30, rollover 04:00.
  - Shift NGT 22:00 to 06:00 with rollover 08:00.
  - "Demo holiday" on D0+10.
- **Users:**
  - Sahil Mehta: management, company-scope approvals.
  - Meera Iyer: sales, own scope. Last ack Saturday D−2 18:05.
  - Neha Joshi: sales, own scope. Monday briefing v1 at 08:49, acked 08:50.
  - Ravi Kumar: operations, branch scope.
  - Vikram Singh: operations, NGT shift.
  - Ananya Rao: finance, a new role from the base template.
  - Priya Nair: admin.
  - Arjun Das: sales, activated D0 08:00, manager Sahil.
  - Kabir Shah: role warehouse_assistant (inherits the operations template). Holds only inventory view (branch) and own tasks.
- **Parties:**
  - Nordhaus Interiors GmbH (DE, EUR, owner Meera)
  - Maison Atelier SARL (FR, EUR, Meera)
  - Berg & Co AB (SE, EUR, Meera)
  - Thornbury Kitchens Ltd (GB, GBP, Neha)
  - Vendor: Kaveri Timber Supplies
  - Fabricator: Precision Edge Fabricators
- **Products:**
  - LK-OT-0450 "Oak serving tray 450": decor_no "0120", EUR export price 24.0000/pc, GBP list 21.0000, carton 24.
  - LK-MT-0300 maple trivet: EUR 9.50, which changes to 9.90 in price list v2 published D−1 15:30.
  - LK-AB-0400 ash chopping board: EUR 18.00.
  - LK-WB-1800 walnut board 18 mm, decor "0457".
- **Quotes and messages:**
  - Message M1 from Nordhaus, D−1 19:20: "usual oak tray quote".
  - Quote LK-QT-2026-0041 for Nordhaus: draft prepared by Meera's assistant at D0 08:40. 240 × EUR 24.0000 = EUR 5,760.0000. Submitted for review 08:45 as proposal v1.
  - Message M2 from Berg, D−1 17:40.
  - Quote LK-QT-2026-0038 for Berg: sent, valid until D0. 600 × EUR 9.50 = EUR 5,700.0000. Its reprice preview (from the sales service) is EUR 5,940.0000.
  - Quote LK-QT-2026-0036 for Maison: override 18.00 to 16.50, × 320 = EUR 5,280.0000, awaiting approval.
  - Quote LK-QT-2026-0040 for Thornbury: override GBP 21.00 to 19.50, × 300 = GBP 5,850.0000, awaiting approval.
  - Quote LK-QT-2026-0035 for Thornbury (Neha): expires D0.
  - Maison address updated D−1 10:05.
  - Meera's reminder: "Call Maison about finish preferences", D0+1 10:00.
- **Slice 2 additions:**
  - Maison sample delivered D−1 16:12, via a sample challan.
  - DC-2026-0097: job-work returnable to Precision Edge, due back D0+1 (Ravi).
  - Cut plan CUT-2026-0014 saved D0 08:15.
  - Import IMP-2026-0007 (pricing_master) failed with 3 row errors.
  - Completeness: 4 oak-category products missing a primary image.
- **Slice 4 additions:**
  - PO-2026-0021 line 1 (walnut) arrival moved from D0 to D0+3 at D−1 11:03.
  - Shortage at Main Warehouse.
  - WO-2026-0031 (afternoon) blocked.
  - Reservation conflict, which becomes Sahil's decision.
- **Slice 5 addition:** Maison receipt EUR 2,400.0000 unmatched. The accounting adapter shows "Not connected (demo)".
- **Other:**
  - Kabir's access request (to Priya); Arjun's accepted invitation (handled for Priya).
  - Kabir's task "Count walnut boards in bin A-12", due D0 14:00, owner Ravi.
  - Arjun: 3 onboarding steps plus 1 task from Sahil: "Complete product catalogue walkthrough".
- **Expected computed results:**
  - Meera:
    - Needs you now: Berg expiry, Berg reply.
    - Plan for today: Nordhaus reply, blocked by approval, with draft evidence.
    - Recommendations: Maison follow-up (slice 2 onward).
    - Changes since your last visit: Maison address.
    - Coming next: her reminder.
    - Handled for you: absent.
    - Initial view 5, full list 6.
    - Sentence: "Two customer replies need attention, one quote expires today, and yesterday's sample has been delivered." (slice 2+).
  - Sahil: 3 decisions plus Arjun's check-in in coming next. "Three decisions need you. The rest is moving." (slices 1 to 3).
  - Ananya before slice 5: empty state.

## 19. Build-order slices
- **Slice 1:**
  - workcal; tasks core (issues, tasks, candidates, dependencies, change log, reminders, history); consumers; overdue sweep.
  - Families: common.*, sales.customer_replies, enquiries, quote_review, quote_expiry, customer_changes, price-impact, admin.access, onboarding.
  - Deterministic engine, snapshots, acks, snooze, all actions (Prepare limited to the sales preparers that exist), fallback, templates, policy, preferences.
  - Today, all, changes and Inbox UI.
  - Voice and chat pins with narration script and the demo TTS adapter. Fixtures. Tests A and B (excluding WhatsApp).
- **Slice 2:** samples, returnables, cut plans, custom-product promotion approvals, failed imports, completeness, Inbox CSV.
- **Slice 3:** LLM phrasing and Explain, hi and hi-Latn templates, real TTS adapter, WhatsApp summary, acks and item actions, agent tools, conversation tasks, integration failures.
- **Slice 4:** operations families with root-cause chains, management cross-team blockers and margin exceptions, stale-stock flags.
- **Slice 5:** finance families, management financial visibility, retention.
- **Slice 6:** full role-isolation sweep, e2e across viewports, and a consistency job for scope attributes.

## 20. Tests for A and B (fixtures in §18, clock frozen)
Each item lists the test name, followed by the steps and asserts.

**A**
- **A-01** `unit/workcal/test_work_date_rollover`: 03:25Z gives D0, working.
- **A-02** `integration/briefings/test_sales_first_open_persists`:
  - Meera's first GET returns ready, v1, `trigger=first_open`, and persists rows.
  - A second GET returns the same version with no new rows.
- **A-03** `test_sales_overview_computed`:
  - facts = {customer_replies:2, quotes_expiring_today:1, samples_delivered:{1, fact_date D−1}}.
  - The text matches exactly.
  - After the Berg reply is marked as replied, a refresh gives "One customer reply needs attention…".
- **A-04** `test_sales_only_authorised_source_linked`:
  - Every source_ref returns 200 for Meera.
  - The payload contains no Thornbury, GBP or Neha ids.
- **A-05** `test_due_dates_user_zone`:
  - Berg reply due 13:00Z, labelled "Today 18:30".
  - Expiry labelled "Expires today".
  - A Berlin-zone user sees "Today 15:00".
- **A-06** `test_sections_top5_no_empty`: section counts {needs 2, plan 1, recs 1, changes 1, coming 1}. handled_for_you is absent. initial = 5, full = 6.
- **A-07** `test_changes_backed_by_events`:
  - Each change item maps to change_log rows with event_id and fact_at after Meera's ack.
  - Neha has no changes section.
- **A-08** `test_management_three_decisions`:
  - Three approval items, each with a proposal_ref. Exact sentence.
  - Adding an overdue task for Sahil changes the second clause.
- **A-09** `test_management_scope_required`:
  - Revoking override-approval eligibility removes two decisions.
  - The text becomes "One decision needs you…".
- **A-10** `test_restricted_briefing_contents`: Kabir sees only his count task. No customer names, amounts or foreign counts.
- **A-11** `test_restricted_direct_urls`: Sahil's version, explain, snooze and Meera's task return 404. `inbox?scope=company` returns 403.
- **A-12** `test_restricted_tools_exports_search`:
  - A tool call with an injected `user_id` is rejected.
  - Kabir's CSV contains only his rows.
  - A global search for "Nordhaus" returns no task or briefing hits.
- **A-13** `test_no_aggregate_leak_property` (hypothesis): for random permission subsets, overview numbers equal the counts of visible items, and member_count equals the visible members.
- **A-14** `test_llm_context_redacted`: a recording adapter captures no costing data or invisible records.
- **A-15** `test_new_employee_onboarding`: Arjun's view has no changes or handled sections and shows the welcome sentence.
- **A-16, A-17, A-18** e2e:
  - Meera's Today on desktop and mobile with axe checks: Open navigates to the Berg quote.
  - Kabir gets permission-denied pages with no leaked data.
  - Sahil's Review opens proposal v1.

**B**
- **B-01** `test_source_change_invalidates_recommendation`: a Berg revision event creates v2 with the same issue_id, R1 stale with its event id, R2 active, and a change row linking revision 3.
- **B-02** `test_no_manufactured_versions`:
  - A replayed event_id causes no version.
  - An immaterial notes update causes no version.
- **B-03** `test_out_of_order`: v3 then v2 leaves the facts at v3, and v2 creates no version.
- **B-04** `test_prepare_stale_rec_409`.
- **B-05** `test_voice_pin_no_reorder`:
  - With a pin on v2, a new P1 message creates v3.
  - The pinned order is identical, with pending_updates = 1.
  - Ordinal 2 resolves to the same issue.
  - After stop, GET returns v3. Resolve returns 410.
- **B-06** `test_handled_during_pin_in_place`: Sahil approves, and Meera's pinned item shows the approval in place without moving.
- **B-07** `test_snooze_persists_across_reload_and_whatsapp`:
  - Snooze on web, then reload: the item is snoozed, the task is open, and Inbox counts are unchanged.
  - A WhatsApp sandbox request lists "1 snoozed".
  - A WhatsApp unsnooze is reflected on the web.
  - A WhatsApp ack shows on the web as last_ack.
- **B-08** `test_snooze_cannot_erase_obligation`:
  - Snoozing beyond the deadline returns 422 with max_until.
  - When the clock passes the due time, an overdue event wakes the item into needs_you_now with OVERDUE.
- **B-09** `test_mark_handled_verification`:
  - Returns 409 NOT_COMPLETE.
  - A non-owner's dismissal returns 404.
  - Meera's dismissal with a reason is audited and the issue stays open.
  - A validity extension auto-completes the next task.
  - Approvals never offer mark_handled.
- **B-10** `test_midnight_rollover`: Monday 23:50, 00:10 and 03:59:59 all return the same briefing. 04:00 creates a new Tuesday briefing.
- **B-11** `test_night_shift`: the 21:30 precompute creates Monday's briefing. 02:00 returns Monday. 08:00 returns Tuesday.
- **B-12** `test_weekend`:
  - Sunday gives non_working: no precompute or push, overdue items only, coming_next shows Monday.
  - The Sunday message's SLA due is Monday 18:30.
- **B-13** `test_holiday_leave_delegation`.
- **B-14** `test_precompute_then_first_open`.
- **B-15** `test_ai_outage_template_text`.
- **B-16** `test_engine_failure_fallback`: the fallback task list excludes Neha. last_successful carries timestamps and is re-filtered after a revoke.
- **B-17** `test_permission_change_regenerates`.
- **B-18** `test_acked_unchanged_not_realerted`.
- **B-19, B-20** e2e:
  - Voice pin: pause, resume and stop controls; the waveform shows only while speaking; "Open the second item".
  - Fallback view.

## 21. Future scope (explicit)
- Escalation chains for overdue approvals.
- Per-record watchers.
- Role-simulator briefing preview.
- Server push (SSE) in place of polling.
- Email summaries.
- Briefing print and export.
- Capacity-aware handoffs.
- Full HR leave and attendance (only minimal leave records here).
- Learned or ML priority, which is deliberately excluded.
- Manager views of other people's briefings, which are excluded for privacy.


## Decisions
- **Two-stage event pipeline: domain events → tasks rule consumer (issues/tasks/change log) → tasks.* events → briefings consumer** — One deduplication and root-cause point serves both Inbox and briefings; the briefing engine stays independent of dozens of domain event schemas; each stage is idempotent with its own consumer receipts.
- **Rules treat events as triggers and re-read authoritative source state via domain read services; stale aggregate versions are ignored** — Handles duplicate, out-of-order and replayed events naturally without trusting payloads; required for B-02/B-03 and WhatsApp/webhook-originated events.
- **Stable issue IDs = uuid5(namespace, company_id|issue_key|occurrence) with explicit root-cause keys and caused_by-only grouping** — Deterministic and reproducible in tests, no lookup races, survives regeneration; a resolved issue that recurs gets a new occurrence so stale acks/snoozes do not hide a new problem.
- **Briefing versions are full immutable copy-on-write item snapshots; a version is created only when item fingerprints or the visible set hash change** — Simple diffing for 'changes since last acknowledged version', auditability, and a structural guarantee against manufactured updates; volumes are tiny (tens of items, few versions/day).
- **LLM text lives in briefings_version_texts, generated asynchronously and validated; deterministic template text is always stored first** — AI latency/outage never blocks or reorders the briefing; phrasing never creates a version; numbers and names are validated against facts so the model only explains.
- **Personal reminders are a separate private table (tasks_reminders), never counted or delegated** — Makes the reminder vs operational-deadline distinction structural and prevents reminders leaking into management aggregates or delegates' views.
- **Snooze is a per-user presentation overlay bounded by deadlines and woken by overdue or material change; task due_at/state/escalation untouched** — Satisfies 'snoozing cannot erase the underlying obligation' while still giving users control; bounds are mandatory policy, not preferences.
- **work_date = (local time − rollover offset).date(), rollover per calendar (default 04:00) overridable per shift** — One explicit formula covers midnight, late working and night shifts crossing midnight; testable at exact boundaries.
- **Only one time-driven state change exists: an indexed per-minute overdue sweep emitting tasks.task.became_overdue; snooze expiry is a read-time overlay** — An overdue obligation is a real business fact worth a version; everything else time-based would be a manufactured update; the sweep is cheap and avoids continuous costly polling.
- **Visibility enforced by a SQL predicate over denormalised scope attributes (required_permission, owner/team/branch) plus authoritative can_view re-check on open/action/explain/members** — Avoids N+1 policy calls when listing while preventing leakage if attributes drift; 404 for others' resources avoids existence leaks.
- **Counts and money totals in the overview are computed by SQL over the visible item ids, money grouped by currency by the owning module** — Meets 'currency totals and counts come from query results', prevents cross-currency sums and aggregate leakage.
- **Role templates select rule families, weights, sections, onboarding steps and overview templates via inheritance; they never grant visibility; common families are mandatory** — New roles inherit safely; a misconfigured template cannot expose data because the permission filter always runs afterwards.
- **Voice/chat references use server-side pins (pinned version + ordinal map); web clients show an 'N updates' control and never re-sort on poll** — Stable 'Open the second item' across devices and no silent reordering during an active spoken briefing; in-place state overlays keep users informed without moving rows.
- **Acknowledgement is multi-channel and monotonic per user; web view for ≥3 s counts as an ack (method recorded, policy-configurable), plus explicit, voice-completion and WhatsApp button acks** — Prevents repeated re-alerting of unchanged items while keeping cross-channel sync simple; method is recorded for audit.
- **Fallback path uses an independent simple task query plus the last successful version re-filtered by current permissions** — Engine bugs or DB-heavy failures still give users a permission-safe working list with timestamps, as required for AI/generation failure.
- **Approvals are tasks with candidate approvers that reference proposal_id@version; Approve/Reject delegate to the approvals service with expected_version** — Review/approve binds to a versioned proposal; separation of duties, permission recheck and version mismatch are enforced by the owning service, not the briefing UI.
- **Default calendar assumptions: Asia/Kolkata, Monday–Saturday workweek, 09:30–18:30 office shift, 04:00 rollover, 30-minute precompute; tzdata added as dependency** — Reasonable assumptions for an Indian manufacturer, all configurable and recorded in DECISIONS.md; Windows Python lacks a system tz database.
- **Fixtures defined as offsets from an anchor work date and created through real services/engine; tests freeze the injected Clock at Mon 2026-10-12 08:55 IST** — Example greetings appear only because records compute them; demo seeds stay valid on any date; no datetime.now() in services.
- **Leave and delegation are minimal workcal records (not HR); delegation never widens access and does not transfer approvals unless explicitly included and independently eligible** — Supports briefing context without building out-of-scope HR, and keeps 'handing work never widens access'.

## Risks
- Event-name and payload drift between independently designed subsystems; mitigate with a contract test that every consumed event type exists in the platform event registry and rule readers use public service functions only.
- Denormalised scope attributes on tasks/issues can drift from source ownership if a source module forgets to emit reassignment events; mitigated by authoritative re-check on open/action and a slice-6 consistency job, but list views could briefly show an item the user cannot open.
- Root-cause grouping for operations (late PO → shortage → blocked WO → at-risk dispatch) depends on source modules exposing explicit caused_by links; without them grouping falls back to separate issues (noisier, never wrong).
- Implicit view-acknowledgement may mark items as seen that the user skimmed; mitigated by policy toggle and 'changed' markers on material change, but could under-alert some users.
- LLM output validator may reject valid paraphrases (numbers in words, Hindi numerals), causing frequent fallback to template text; acceptable but reduces phrasing value until validators are tuned per language.
- Hindi/Hinglish template wording is untested by native speakers and must stay labelled until reviewed.
- Event chattiness could create many versions per day; debounce (20 s) and fingerprint gating limit this, but rapid sources (stock movements) need material-change definitions per facts schema.
- WhatsApp template category/approval for employee daily summaries may not be granted by Meta; design degrades to on-demand within the service window, but the push feature may be unavailable in production.
- Postgres features used (btree_gist exclusion constraints, advisory locks) require the chosen local Postgres (pgserver or Docker) to support extensions; verify in platform setup.
- Demo seeds anchored to the seed date will show different sections if seeded on a non-working day; documented --anchor-date option mitigates.

## Acceptance tests
- [A / unit] unit/workcal/test_work_date_rollover: 2026-10-12T03:25Z for Asia/Kolkata day-shift user yields work_date 2026-10-12, day_type working
- [A / integration] integration/briefings/test_sales_first_open_persists: Meera first GET /briefings/today creates briefing+v1 (trigger first_open, first_opened_at set); second GET returns same id/version and writes no rows
- [A / integration] integration/briefings/test_sales_overview_computed: overview_facts equal query results and text equals 'Two customer replies need attention, one quote expires today, and yesterday's sample has been delivered.'; marking Berg reply replied changes the sentence after refresh
- [A / integration] integration/briefings/test_sales_only_authorised_source_linked: every item source_ref resolves 200 for Meera via canonical API; payload contains no Thornbury/GBP/Neha record ids
- [A / integration] integration/briefings/test_due_dates_user_zone: Berg reply due 13:00Z labelled 'Today 18:30' (Asia/Kolkata), quote expiry 'Expires today', Europe/Berlin user sees 'Today 15:00'
- [A / integration] integration/briefings/test_sections_top5_no_empty: Meera sections needs=2, plan=1, recommendations=1, changes=1, coming_next=1; handled_for_you absent; initial_item_ids length 5; full list 6
- [A / integration] integration/briefings/test_changes_backed_by_events: each change item maps to tasks_change_log rows with event_id and fact_at after last ack; Neha (acked after all events) has no changes section
- [A / integration] integration/briefings/test_management_three_decisions: Sahil needs_you_now has 3 approval items each with proposal_ref{id,version}; text 'Three decisions need you. The rest is moving.'; adding an overdue unrelated task changes the second clause
- [A / integration] integration/briefings/test_management_scope_required: revoking Sahil's override-approval eligibility removes two decisions and sentence becomes 'One decision needs you…'
- [A / integration] integration/briefings/test_restricted_briefing_contents: Kabir sees only his bin-count task; payload has no customer names, currency amounts or counts beyond his items
- [A / integration] integration/briefings/test_restricted_direct_urls: Kabir requests for Sahil's version, item explain, item snooze and Meera's task return 404; GET /inbox?scope=company returns 403
- [A / integration] integration/briefings/test_restricted_tools_exports_search: get_daily_briefing tool rejects model-supplied user_id (extra=forbid) and returns only Kabir's items; inbox CSV export has only his rows; global search for 'Nordhaus' returns no task/briefing hits
- [A / integration] integration/briefings/test_no_aggregate_leak_property (hypothesis): for random permission subsets, every overview number equals counts derived from visible items and group member_count equals visible members
- [A / integration] integration/briefings/test_llm_context_redacted: recording phrasing adapter captures no costing fields and no records outside the actor's visibility for Kabir and Meera
- [A / integration] integration/briefings/test_new_employee_onboarding: Arjun gets 3 onboarding steps + 1 assigned task, no changes/handled sections, change-log cutoff = activated_at, sentence 'Welcome, Arjun. You have three onboarding steps and one assigned task.'
- [A / e2e] apps/web/e2e/today.sales.spec.ts: Meera Today at frozen clock shows greeting, computed sentence, <=5 items with status/problem/recommendation/source link/one primary control, 'See all 6'; Open navigates to Berg quote; desktop+mobile screenshots; axe no critical violations
- [A / e2e] apps/web/e2e/today.isolation.spec.ts: Kabir direct URLs to others' quote/briefing/inbox scopes render permission-denied without fragments or counts
- [A / e2e] apps/web/e2e/today.management.spec.ts: Sahil sees three decision items; Review opens quote review bound to proposal v1
- [B / integration] integration/briefings/test_source_change_invalidates_recommendation: Berg quote revision event creates v2 with identical issue_id, R1 status stale with invalidated_by_event_id, new active R2, change-log row linking revision 3
- [B / integration] integration/briefings/test_no_manufactured_versions: replayed event_id and immaterial notes update create no new version and no change entries
- [B / integration] integration/tasks/test_out_of_order_events: quote v3 event then v2 event leaves facts at v3; v2 produces no version
- [B / integration] integration/briefings/test_prepare_stale_recommendation_409: Prepare with stale recommendation_id returns 409 RECOMMENDATION_STALE with fresh item
- [B / integration] integration/briefings/test_voice_pin_no_reorder: pin on v2; new P1 event creates v3; pinned GET order identical with pending_updates=1; ordinal 2 resolves to same issue; after stop GET returns v3 and resolve returns 410
- [B / integration] integration/briefings/test_handled_during_pin_in_place: Sahil approves Nordhaus proposal during Meera's pin; item shows approved state in place, ordinal unchanged
- [B / integration] integration/briefings/test_snooze_persists_across_reload_and_whatsapp: web snooze survives reload, task stays open, inbox counts unchanged; WhatsApp sandbox summary shows '1 snoozed'; WhatsApp unsnooze and ack reflected on web last_ack
- [B / integration] integration/briefings/test_snooze_cannot_erase_obligation: snooze past hard deadline returns 422 with max_until; advancing clock past due emits became_overdue, wakes item into needs_you_now with OVERDUE
- [B / integration] integration/briefings/test_mark_handled_verification: incomplete source returns 409 NOT_COMPLETE; other user's dismissal 404; owner dismissal with reason audited and issue stays open; validity extension auto-completes; approvals never offer mark_handled
- [B / integration] integration/workcal/test_midnight_rollover: Mon 23:50, Tue 00:10 and 03:59:59 return Monday briefing; Tue 04:00:00 first open generates Tuesday briefing; Monday retained
- [B / integration] integration/workcal/test_night_shift_boundary: NGT shift precompute at 21:30 creates Monday briefing; 02:00 Tue opens Monday; 08:00 Tue opens Tuesday
- [B / integration] integration/briefings/test_weekend_behaviour: Sunday open gives day_type non_working, no precompute/push, only overdue/hard items, coming_next shows Monday; Sunday 17:40 message SLA due Monday 18:30
- [B / integration] integration/briefings/test_holiday_leave_delegation: holiday day_type; Ravi on leave delegates to Vikram, who sees permitted items marked 'For Ravi'; approvals not delegated unless include_approvals and independently eligible
- [B / integration] integration/briefings/test_precompute_then_first_open: shift precompute creates briefing with first_opened_at null; later open returns same briefing including interim event versions and sets first_opened_at
- [B / integration] integration/briefings/test_ai_outage_template_text: phrasing adapter timeout gives status ready, ai_status unavailable, deterministic text with 'Standard wording' label; Explain returns rule text only
- [B / integration] integration/briefings/test_engine_failure_fallback: injected engine fault returns status fallback with permission-filtered task list (no Neha items) and last successful version with generated_at/data_as_of, re-filtered after a permission revoke
- [B / integration] integration/briefings/test_permission_change_regenerates: permissions_changed event causes next GET to create version cause permission_change without revoked items; historic version omits overview when fingerprint differs
- [B / integration] integration/briefings/test_acked_unchanged_not_realerted: after ack of v2, a change to one issue produces v3 whose changes section contains only that issue
- [B / e2e] apps/web/e2e/today.voice-pin.spec.ts: Listen to my day with demo TTS; pause/resume/Stop speaking; waveform only while speaking; injected event shows '1 update' without reordering; typed 'Open the second item' opens pinned item 2
- [B / e2e] apps/web/e2e/today.fallback.spec.ts: server fault mode renders fallback task list and last successful briefing with timestamps; no dead buttons
- [C / integration] integration/tasks/test_agent_quote_draft_creates_scoped_next_action: draft Nordhaus quote by Meera's assistant creates review task owned/assigned to Meera with sales.quote.view own scope; Meera's briefing updates; Neha and Kabir unaffected
- [F / integration] integration/briefings/test_approve_rechecks_permission_and_version: approve with stale proposal version returns 409 PROPOSAL_CHANGED; after approval permission revoke returns 403 and nothing executes; initiator cannot approve own proposal
- [K / integration] integration/briefings/test_whatsapp_summary_eligibility: no opt-in or opted-out user gets no push; closed window without approved template is not sent and audited; on-demand request inside window works; simulated send labelled Demo; duplicate ack payload creates one ack
- [N / e2e] apps/web/e2e/today.states.spec.ts: empty state 'Nothing needs you right now.' with no sections, loading skeleton, offline cached version labelled with as-of time and disabled actions, stale data label, keyboard traversal of items/actions, 44px touch targets on mobile
- [invariant / unit] unit/briefings/test_priority_and_sections_properties: deterministic total order, each issue in exactly one section, initial view <=5, no empty sections, every numeral in overview text present in overview_facts
- [invariant / unit] unit/tasks/test_issue_keys: uuid5 issue id stable for same company/key/occurrence and distinct across occurrences; fingerprint ignores immaterial fields
- [invariant / unit] unit/briefings/test_template_inheritance_and_mandatory_controls: cycle rejected, depth limited, common families not excludable, preference attempting to weaken policy returns MANDATORY_CONTROL
- [invariant / contract] contract/test_briefing_contracts: OpenAPI schemas for briefings/tasks/inbox match generated TS types; agent tool schemas contain no identity parameters; every consumed event type exists in platform event registry
