# Domain events

Status: frozen in Slice 0 for Slices 1–4 (Slice 5 listed as a preview). Implements `docs/PLAN.md` canonical
contract 5. Code anchors: `backend/app/platform/events/{defs,models,service}.py`, `backend/app/registry.py`,
`backend/app/platform/uow.py` (`emit`). `docs/EVENTS.md` is generated from the registered `EventDef`s by
`lk events catalogue` and checked in `npm run check`; this file is the design contract the registry must match.

---

## 1. Rules

1. **Name**: `<module>.<entity>.<past_tense_verb>` (`sales.quote.created`, `challans.returnable.became_due`). The
   module prefix equals the permission module and the backend package. Regex enforced by `EventDef`.
2. **Declaration**: each emitting module declares `EventDef(name, aggregate_type, description, payload, version)` in
   its `events.py` and lists it in its manifest. Emitting an undeclared event raises. A subscription, briefing rule,
   automation trigger or ActivitySpec that names an unregistered event **fails startup**
   (`subscription to unregistered event ...`).
3. **Versioning**: `version` starts at 1. A breaking payload change adds a new version; consumers declare the versions
   they accept. Additive optional fields do not bump the version.
4. **Payload content**: ids, business keys (quote number, challan number), versions, enum codes (status from/to,
   reason codes, kinds), changed-field **names**, and dates/deadlines needed for routing. **Never** money amounts,
   quantities, restricted values (costing, margin, bank details), free text, message bodies, personal content or
   secrets. Consumers that need facts re-read the authoritative source through the owning module's read service.
5. **Envelope** (`domain_event` columns, set by the platform): `id` (UUIDv7), `seq`, `company_id`, `event_type`,
   `event_version`, `aggregate_type`, `aggregate_id`, `aggregate_version`, `actor_user_id`, `actor_type`,
   `on_behalf_of`, `correlation_id`, `causation_id`, `occurred_at` (from the Clock).
6. **Base payload**: every payload model extends `EventPayload` with `origin`
   (`user | agent | automation | import | migration | system | channel | seed`). Briefing rules skip
   `origin=migration`; an import job produces one grouped issue, not one per row.
7. **Transactional outbox**: `uow.emit(...)` writes `domain_event` in the same transaction as the change. The relay
   (worker, every 0.5 s, `FOR UPDATE SKIP LOCKED`) fans each event out to one `event.handle` job per subscribed handler
   with `dedupe_key = 'evt:{event_id}:{handler_key}'`. Handler effects commit atomically with a fenced job completion.
8. **Exactly-once effects**: handlers are idempotent; a handler reachable by more than one path uses
   `consumers.once(uow, consumer, event_id)` on the `event_consumption` table. There is no global ordering guarantee:
   handlers compare `aggregate_version` and ignore stale events.
9. **Sequencing**: a consumer may reference an event only after the emitter's `EventDef` is merged on `main`.
10. **Approval invalidation is synchronous**: domain commands that change an approval target call the approvals
    service in the same transaction (`ApprovalTarget` adapter); `approvals.proposal.invalidated` is then emitted. No
    subscription is needed for invalidation.

## 2. Handler keys

| Handler key | Module | Purpose | Slice |
|---|---|---|---|
| `tasks.rules` | tasks | the rule consumer: re-reads sources, upserts issues/tasks/change log, emits `tasks.*` | 1 |
| `briefings.refresh` | briefings | debounced (20 s) refresh of affected users' current briefings from `tasks.*` | 1 |
| `briefings.access_refresh` | briefings | marks permission fingerprints stale so the next open regenerates | 1 |
| `collab.activity_projector` | collab | activity rows for events that declare an ActivitySpec | 2 |
| `sales.document_render` | sales | renders and stores the issued quote PDF | 1 |
| `sales.custom_product_autoadvance` | sales | moves linked custom products forward to `quoted` on issue | 2 |
| `sales.sample_dispatch` | sales | marks a sample dispatched when its challan is issued | 2 |
| `sales.quote_delivery_status` | sales | maps channel delivery statuses to quote dispatch records | 3 |
| `catalogue.completeness_refresh` | catalogue | debounced completeness recount; emits `catalogue.completeness.changed` | 2 |
| `channels.revoke_on_deactivation` | channels | revokes channel sessions and voids armed action refs | 3 |
| `channels.ack_sync` | channels | mirrors acknowledgements to WhatsApp state | 3 |
| `agents.automation_dispatch` | agents | enqueues automation runs (subscribes only to event types used by active automations) | 3 |
| `inventory.shortage_refresh` | inventory | recompute of `inventory_shortage_state` for the (product, warehouse) pairs an event touches; one key per trigger, `inventory.shortage_refresh:<event>` (like `tasks.rules:<event>`); triggers are `inventory.events.SHORTAGE_TRIGGERS` (orders, stock, reservation and `production.work_order.{released,completed,closed,cancelled}` events; pair resolvers registered by production) | 4 |
| `production.material_retry` | production | `production.material_retry:<event>` on `inventory.stock.posted`, `inventory.posting.reversed`, `inventory.reservation.released`: blocked work orders reserve again and unblock (idempotent on replay) | 4 |
| `logistics.packing_list_staleness` | logistics | `logistics.packing_list_staleness:<event>` on `catalogue.product.updated`, `orders.sales_order_line.cancelled`, `orders.sales_order.cancelled`: flags draft packing lists stale (`logistics.packing_list.became_stale`) | 4 |
| `logistics.shipment_status` | logistics | sets shipment dispatched when the linked challan is issued | 4 |
| `finance.invoice_suggestion` | finance | suggests a draft invoice for issued delivery challans | 5 |
| `finance.margin_check` | finance | checks issued quotes' margin from costs of record; emits `sales.quote.margin_below_threshold` | 5 |

## 3. Catalogue

Columns: event · version · first emitted in slice · payload fields beyond `origin` · consumers (handler keys, with the
slice in which the consumer arrives when later than the emitter).

### 3.1 identity

| Event | v | Slice | Payload | Consumers |
|---|---|---|---|---|
| `identity.membership.activated` | 1 | 1 | membership_id, user_id, manager_membership_id | tasks.rules (onboarding steps + manager check-in) |
| `identity.membership.deactivated` | 1 | 1 | membership_id, user_id, reassign_to_membership_id | tasks.rules (cancel reminders, "Reassign N open tasks" issue); channels.revoke_on_deactivation (S3) |
| `identity.membership.reactivated` | 1 | 2 | membership_id, user_id | tasks.rules |
| `identity.membership.access_changed` | 1 | 1 | membership_id, user_id, authz_epoch, change_kinds[] (roles, overrides, delegation, teams, branches, status) | briefings.access_refresh |
| `identity.permission_override.changed` | 1 | 1 | membership_id, permission_key, effect (grant, revoke), archived | collab.activity_projector (S2) |
| `identity.role.created` / `.updated` / `.archived` | 1 | 2 | role_id, role_key, changed_fields[] | collab.activity_projector |
| `identity.invitation.sent` / `.accepted` / `.revoked` | 1 | 2 | invitation_id, membership_id, delivery (email, manual_link) | tasks.rules (admin.access; accepted shows as handled for the inviter) |
| `identity.user.credentials_changed` | 1 | 2 | user_id, kind (password_changed, password_reset, mfa_reset) | channels.revoke_on_deactivation (S3) |
| `identity.delegation.created` / `.cancelled` / `.started` / `.ended` | 1 | 2 | delegation_id, delegator_membership_id, delegate_membership_id, include_approvals, starts_at, ends_at | tasks.rules, briefings.access_refresh |
| `identity.absence.requested` / `.approved` / `.cancelled` | 1 | 2 | absence_id, membership_id, starts_on, ends_on | tasks.rules (approver task, audience changes) |
| `identity.access_request.submitted` / `.decided` | 1 | 2 | access_request_id, requester_membership_id, decision (approved, rejected) | tasks.rules (admin.access) |

### 3.2 org, numbering, collab, system

| Event | v | Slice | Payload | Consumers |
|---|---|---|---|---|
| `org.setting.updated` | 1 | 1 | setting_key, branch_id, version | collab.activity_projector (S2) |
| `org.company.updated` | 1 | 2 | changed_fields[] | collab.activity_projector |
| `org.calendar.updated` | 1 | 2 | calendar_id, changed_fields[] | briefings.refresh (precompute schedule) |
| `numbering.sequence.updated` | 1 | 2 | sequence_key, branch_id, changed_fields[] | collab.activity_projector |
| `collab.note.updated` | 1 | 1 | resource_type, resource_id, note_id, version | collab.activity_projector (S2) |
| `collab.comment.added` | 1 | 2 | resource_type, resource_id, comment_id | collab.activity_projector |
| `collab.attachment.added` / `.archived` | 1 | 2 | resource_type, resource_id, attachment_id, file_id, role | collab.activity_projector; catalogue.completeness_refresh |
| `system.job.dead_lettered` | 1 | 1 | job_id, kind, handler_key | tasks.rules (admin.failed_jobs; marks partial briefing families) |
| `system.integration.status_changed` | 1 | 1 | integration_key, mode, state_from, state_to | tasks.rules (admin.failed_integrations, S3) |
| `system.demo_data.deleted` | 1 | 2 | modules[] | tasks.rules |

### 3.3 approvals

| Event | v | Slice | Payload | Consumers |
|---|---|---|---|---|
| `approvals.proposal.submitted` | 1 | 1 | proposal_id, short_ref, kind, action_key, version, targets[{type, id, version}], initiator_user_id, policy_key, expires_at, tainted | tasks.rules (common.approvals: approval task, candidates = eligible approvers minus initiator) |
| `approvals.proposal.approved` | 1 | 1 | proposal_id, version, decision_id, approver_user_id | tasks.rules (close; "handled for you" for other candidates and the initiator) |
| `approvals.proposal.rejected` | 1 | 1 | proposal_id, version, decision_id, approver_user_id, reason_code | tasks.rules |
| `approvals.proposal.expired` | 1 | 1 | proposal_id, version | tasks.rules |
| `approvals.proposal.invalidated` | 1 | 1 | proposal_id, version, cause (target_changed, permission_revoked, policy_changed), target {type, id, version} | tasks.rules |
| `approvals.proposal.superseded` | 1 | 1 | proposal_id, superseded_by_proposal_id | tasks.rules |
| `approvals.proposal.cancelled` | 1 | 1 | proposal_id, reason_code | tasks.rules |
| `approvals.proposal.executed` | 1 | 1 | proposal_id, receipt_id | tasks.rules (handled for you) |
| `approvals.proposal.execution_failed` | 1 | 1 | proposal_id, error_code | tasks.rules (failure issue for the initiator) |
| `approvals.receipt.undone` | 1 | 3 | receipt_id, proposal_id | tasks.rules |

### 3.4 catalogue, imports

| Event | v | Slice | Payload | Consumers |
|---|---|---|---|---|
| `catalogue.product.created` | 1 | 1 | product_id, product_key | collab.activity_projector (S2), catalogue.completeness_refresh (S2) |
| `catalogue.product.updated` | 1 | 1 | product_id, product_key, changed_groups[] (master, specification, packaging, dimensions, taxonomy, stock_attributes), changed_fields[] | collab.activity_projector (S2), catalogue.completeness_refresh (S2), logistics.packing_list_staleness (S4, when `packaging` ∈ changed_groups) |
| `catalogue.product.archived` / `.restored` | 1 | 2 | product_id, product_key | catalogue.completeness_refresh |
| `catalogue.media.uploaded` / `.deleted` / `.restored` / `.primary_changed` | 1 | 2 | media_id, product_id, media_type | catalogue.completeness_refresh |
| `catalogue.media.ingest_failed` | 1 | 2 | media_id, product_id, error_code | tasks.rules (admin.data_completeness) |
| `catalogue.category.created` / `.renamed` / `.updated` / `.deleted` | 1 | 2 | category_id, changed_fields[] | collab.activity_projector |
| `catalogue.subcategory.created` / `.renamed` / `.updated` / `.deleted` | 1 | 2 | subcategory_id, category_id, changed_fields[] | collab.activity_projector |
| `catalogue.taxonomy.reassigned` | 1 | 2 | from_category_id, from_subcategory_id, to_category_id, to_subcategory_id | catalogue.completeness_refresh |
| `catalogue.completeness.changed` | 1 | 2 | category_id, rule_code | tasks.rules (admin.data_completeness, grouped per rule and category) |
| `imports.job.uploaded` / `.validated` | 1 | 2 | job_id, import_type | — |
| `imports.job.committed` | 1 | 2 | job_id, import_type, has_quarantine | tasks.rules (admin.failed_imports when has_quarantine), catalogue.completeness_refresh |
| `imports.job.failed` | 1 | 2 | job_id, import_type, error_code | tasks.rules (admin.failed_imports) |
| `imports.job.rolled_back` | 1 | 2 | job_id, import_type, mode (all, reversible_only) | catalogue.completeness_refresh |

### 3.5 pricing, commercial, parties

| Event | v | Slice | Payload | Consumers |
|---|---|---|---|---|
| `pricing.price_list.created` | 1 | 2 | price_list_id, code | — |
| `pricing.price_list.activated` | 1 | 1 | price_list_id, code, scope_kind, price_type, currency | tasks.rules (sales.price_impact, S2) |
| `pricing.price_list.retired` | 1 | 2 | price_list_id, code, reason_code | tasks.rules (sales.price_impact) |
| `pricing.price_list_item.superseded` | 1 | 1 | item_id, superseded_by_item_id, price_list_id, product_id | tasks.rules (sales.price_impact, S2: affected open quotes are re-read through `sales.service.open_quotes_using_item`) |
| `pricing.price_list_item.retired` | 1 | 2 | item_id, price_list_id, product_id | tasks.rules (sales.price_impact) |
| `pricing.fx_rate.proposed` / `.approved` / `.rejected` | 1 | 2 | fx_rate_id, base_currency, quote_currency, rate_date | — (the approval itself runs through approvals events) |
| `pricing.product_cost.recorded` | 1 | 2 | product_id, cost_version, source_kind | — (Slice 5 margin consumers) |
| `commercial.rule_set.activated` | 1 | 1 | rule_set_id, code, version_no | collab.activity_projector (S2) |
| `parties.party.created` | 1 | 1 | party_id, party_number, owner_user_id | collab.activity_projector (S2) |
| `parties.party.updated` | 1 | 1 | party_id, party_number, changed_fields[] | tasks.rules (sales.customer_changes: `info:party:{id}` for the owner) |
| `parties.party.archived` | 1 | 2 | party_id | tasks.rules |
| `parties.party.owner_changed` | 1 | 2 | party_id, from_user_id, to_user_id | tasks.rules (scope reassignment) |

### 3.6 sales

| Event | v | Slice | Payload | Consumers |
|---|---|---|---|---|
| `sales.enquiry.received` | 1 | 1 | enquiry_id, enquiry_number, party_id, channel, owner_user_id | tasks.rules (sales.enquiries: enquiry_reply) |
| `sales.enquiry.assigned` | 1 | 1 | enquiry_id, from_user_id, to_user_id | tasks.rules |
| `sales.enquiry.quoted` | 1 | 1 | enquiry_id, quote_id | tasks.rules (close) |
| `sales.enquiry.closed` | 1 | 1 | enquiry_id, outcome_code | tasks.rules (close) |
| `sales.customer_message.received` | 1 | 1 | message_id, party_id, contact_id, channel, assignee_user_id, enquiry_id, quote_id | tasks.rules (sales.customer_replies: reply_needed, due by the SLA in working days) |
| `sales.customer_message.replied` | 1 | 1 | message_id, reply_ref_type, reply_ref_id | tasks.rules (close) |
| `sales.quote.created` | 1 | 1 | quote_id, quote_number, owner_user_id, branch_id, party_id, enquiry_id, origin_message_id, duplicated_from_quote_id | tasks.rules (sales.quote_review: review_draft for the owner) |
| `sales.quote.updated` | 1 | 1 | quote_id, version, changed_fields[], line_change_kinds[] (added, removed, changed) | tasks.rules (refresh facts of open issues) |
| `sales.quote.review_requested` | 1 | 1 | quote_id, proposal_id | tasks.rules (close review_draft) |
| `sales.quote.review_withdrawn` | 1 | 1 | quote_id, proposal_id | tasks.rules |
| `sales.quote.issued` | 1 | 1 | quote_id, revision_id, revision_no, valid_until | sales.document_render; tasks.rules (sales.quote_expiry: hard due at the end of valid_until in company time); sales.custom_product_autoadvance (S2) |
| `sales.quote.marked_sent` | 1 | 1 | quote_id, revision_id, dispatch_id | tasks.rules (close reply tasks whose linked quote is sent) |
| `sales.quote.won` | 1 | 1 | quote_id, accepted_revision_id | tasks.rules (close expiry; conversion recommendation in S4) |
| `sales.quote.lost` | 1 | 1 | quote_id, reason_code | tasks.rules |
| `sales.quote.cancelled` | 1 | 1 | quote_id, reason_code | tasks.rules |
| `sales.quote.deleted` | 1 | 1 | quote_id | tasks.rules (close) |
| `sales.quote.status_changed` | 1 | 1 | quote_id, version, action, from_status, to_status | tasks.rules (emitted on every transition alongside the specific event) |
| `sales.quote.revised` | 1 | 2 | quote_id, revision_no | tasks.rules |
| `sales.quote.validity_extended` | 1 | 2 | quote_id, revision_id, valid_until | tasks.rules (completes the current expiry task, opens the next) |
| `sales.quote.archived` / `.unarchived` | 1 | 2 | quote_id, archived_from_status | tasks.rules |
| `sales.quote.status_corrected` | 1 | 2 | quote_id, from_status, to_status, reason_code | tasks.rules |
| `sales.quote.owner_changed` | 1 | 2 | quote_id, from_user_id, to_user_id | tasks.rules (scope reassignment; previous owner loses visibility) |
| `sales.quote.duplicated` | 1 | 2 | quote_id, source_quote_id | collab.activity_projector |
| `sales.quote.restored` | 1 | 2 | quote_id, from_revision_no | tasks.rules |
| `sales.quote.currency_changed` | 1 | 2 | quote_id, from_currency, to_currency | tasks.rules |
| `sales.quote.delivery_status_changed` | 1 | 3 | quote_id, dispatch_id, provider_status, simulated | tasks.rules (delivery failure issue for the owner) |
| `sales.custom_product.created` | 1 | 2 | custom_product_id, custom_code, owner_user_id | collab.activity_projector |
| `sales.custom_product.updated` | 1 | 2 | custom_product_id, changed_fields[] | collab.activity_projector |
| `sales.custom_product.status_changed` | 1 | 2 | custom_product_id, from_status, to_status | tasks.rules |
| `sales.custom_product.spec_revision_recorded` | 1 | 2 | custom_product_id, spec_revision_id | tasks.rules |
| `sales.custom_product.promotion_requested` | 1 | 2 | custom_product_id, promotion_id, proposal_id | — (approvals events drive the approval task) |
| `sales.custom_product.promoted` | 1 | 2 | custom_product_id, product_id | tasks.rules, catalogue.completeness_refresh |
| `sales.custom_product.promotion_rejected` | 1 | 2 | custom_product_id, promotion_id | tasks.rules |
| `sales.custom_product.duplicated` / `.archived` | 1 | 2 | custom_product_id, source_custom_product_id | collab.activity_projector |
| `sales.sample.created` | 1 | 2 | sample_id, sample_number, party_id, owner_user_id | tasks.rules |
| `sales.sample.dispatched` | 1 | 2 | sample_id, challan_id | tasks.rules (sales.samples) |
| `sales.sample.delivered` | 1 | 2 | sample_id, evidence_kind | tasks.rules (sales.samples: PREPARE_FOLLOWUP recommendation) |
| `sales.sample.feedback_recorded` / `.closed` | 1 | 2 | sample_id | tasks.rules |

### 3.7 tasks, briefings, agents

| Event | v | Slice | Payload | Consumers |
|---|---|---|---|---|
| `tasks.task.created` / `.assigned` / `.started` / `.completed` / `.dismissed` / `.cancelled` / `.expired` | 1 | 1 | task_id, issue_id, kind, family, owner_user_id, assignee_user_id, due_at, from_state, to_state | briefings.refresh |
| `tasks.task.became_overdue` | 1 | 1 | task_id, issue_id, due_at | briefings.refresh (wakes snoozed items) |
| `tasks.issue.opened` / `.changed` / `.resolved` | 1 | 1 | issue_id, issue_key, family, occurrence, fingerprint | briefings.refresh |
| `tasks.reminder.fired` | 1 | 1 | reminder_id, user_id | briefings.refresh |
| `briefings.briefing.generated` | 1 | 1 | briefing_id, user_id, work_date, version, trigger | — |
| `briefings.briefing.updated` | 1 | 1 | briefing_id, version, cause | — |
| `briefings.briefing.acknowledged` | 1 | 1 | briefing_id, version, method (viewed, explicit, voice, whatsapp), channel | channels.ack_sync (S3) |
| `briefings.briefing.generation_failed` | 1 | 1 | briefing_id, error_code | tasks.rules (admin issue after repeated failures) |
| `briefings.item.snoozed` / `.unsnoozed` | 1 | 1 | issue_id, user_id, snoozed_until | — |
| `briefings.recommendation.invalidated` | 1 | 1 | recommendation_id, issue_id, cause_event_id | — |
| `briefings.pin.started` / `.ended` | 1 | 3 | pin_id, briefing_id, kind (voice, chat) | — |
| `agents.run.completed` | 1 | 1 | run_id, conversation_id, user_id, trigger, status | — (trace) |
| `agents.run.failed` | 1 | 1 | run_id, conversation_id, error_code | — (trace, usage dashboard) |
| `agents.memory_item.approved` | 1 | 3 | memory_item_id, scope | — |
| `agents.automation_run.completed` / `.failed` | 1 | 3 | automation_id, run_id, outcome | tasks.rules (common.handled: "Handled for you" evidence or a failure issue for the owner) |

### 3.8 channels (Slice 3)

| Event | v | Slice | Payload | Consumers |
|---|---|---|---|---|
| `channels.identity.linked` / `.revoked` / `.suspended` | 1 | 3 | identity_id, kind (employee, customer, vendor), user_id | — |
| `channels.message.received` | 1 | 3 | message_id, identity_id, identity_kind, type | agents.automation_dispatch |
| `channels.message.status_changed` | 1 | 3 | message_id, outbox_id, status, simulated | sales.quote_delivery_status |
| `channels.message.delivery_unknown` | 1 | 3 | message_id, outbox_id | tasks.rules (escalation task; never a blind resend) |
| `channels.consent.changed` | 1 | 3 | identity_id, purpose, status | — |
| `channels.account.verified` | 1 | 3 | account_id | — (integration status) |
| `channels.template.status_changed` | 1 | 3 | template_id, status | tasks.rules (admin) |
| `channels.conversation.escalated` | 1 | 3 | identity_id, conversation_ref | tasks.rules (conversation task) |

Customer and vendor messages arriving through channels become `sales_customer_message` rows through
`sales.service.record_customer_message` (direct service call), which emits `sales.customer_message.received`.

### 3.9 challans, cutting

| Event | v | Slice | Payload | Consumers |
|---|---|---|---|---|
| `challans.challan.issued` | 1 | 2 | challan_id, challan_number, challan_type, return_type, destination_type, party_id, inventory_effect, posting_id, sample_id | tasks.rules (ops.returnables when returnable); sales.sample_dispatch; logistics.shipment_status (S4); finance.invoice_suggestion (S5) |
| `challans.challan.closed` | 1 | 2 | challan_id | tasks.rules |
| `challans.challan.cancelled` | 1 | 2 | challan_id, reason_code, reversal_posting_id | tasks.rules |
| `challans.return.received` | 1 | 2 | return_challan_id, original_challan_id, original_line_ids[] | tasks.rules |
| `challans.returnable.became_due` | 1 | 2 | challan_id, expected_return_date (scheduled) | tasks.rules |
| `challans.returnable.became_overdue` | 1 | 2 | challan_id, expected_return_date (scheduled) | tasks.rules |
| `challans.write_off.posted` | 1 | 4 | challan_id, line_ids[], posting_id | tasks.rules |
| `cutting.plan.saved` | 1 | 2 | plan_id, plan_number, owner_user_id | — |
| `cutting.plan.calculated` | 1 | 2 | plan_id, calculation_id, calc_no, input_hash, requires_physical_verification | tasks.rules (ops.cut_plans review) |
| `cutting.plan.verification_required` / `.verified` | 1 | 2 | plan_id | tasks.rules |
| `cutting.plan.released` | 1 | 4 | plan_id, work_order_id | tasks.rules |
| `cutting.plan.archived` | 1 | 2 | plan_id | — |

### 3.10 orders, inventory, quality, procurement, production, logistics (Slice 4)

| Event | v | Slice | Payload | Consumers |
|---|---|---|---|---|
| `orders.sales_order.created` | 1 | 4 | order_id, order_number, source_quote_id | tasks.rules |
| `orders.sales_order.confirmed` / `.put_on_hold` / `.completed` / `.cancelled` | 1 | 4 | order_id, reason_code | tasks.rules, inventory.shortage_refresh |
| `orders.sales_order_line.cancelled` | 1 | 4 | order_id, line_id | inventory.shortage_refresh |
| `orders.sales_order_line.delivered` | 1 | 4 | order_id, line_id, challan_id | tasks.rules |
| `inventory.stock.posted` | 1 | 4 | posting_id, source_type, source_id, purpose, product_ids[], warehouse_ids[] | inventory.shortage_refresh |
| `inventory.posting.reversed` | 1 | 4 | posting_id, reversal_posting_id | inventory.shortage_refresh, tasks.rules (re-reserve suggestion) |
| `inventory.reservation.created` / `.released` | 1 | 4 | reservation_id, demand_type, demand_id, product_id, warehouse_id | inventory.shortage_refresh |
| `inventory.reservation.shortfall_detected` | 1 | 4 | demand_type, demand_id, product_id, warehouse_id | inventory.shortage_refresh |
| `inventory.reservation.conflict_detected` | 1 | 4 | product_id, warehouse_id, demand_refs[{type, id}] | tasks.rules (mgmt.decisions) |
| `inventory.shortage.detected` / `.changed` / `.resolved` | 1 | 4 | shortage_id, product_id, warehouse_id, version, caused_by[{type, id}] | tasks.rules (ops.shortages; root-cause grouping by caused_by) |
| `inventory.adjustment.posted` | 1 | 4 | adjustment_id, posting_id | collab.activity_projector |
| `inventory.stock_count.frozen` / `.posted` | 1 | 4 | stock_count_id, posting_id | tasks.rules |
| `inventory.opening_batch.posted` | 1 | 4 | opening_batch_id, posting_id | collab.activity_projector |
| `inventory.pick_list.released` / `.picked` | 1 | 4 | pick_list_id, order_id | tasks.rules (picking tasks) |
| `inventory.projection.mismatch_detected` | 1 | 4 | product_id, warehouse_id | tasks.rules (integrity issue) |
| `inventory.lot.measured` | 1 | 4 | lot_id, lot_kind | — (offcut reuse in S5) |
| `quality.inspection.requested` | 1 | 4 | inspection_id, subject_type, subject_id | tasks.rules (ops.qc) |
| `quality.inspection.passed` / `.failed` | 1 | 4 | inspection_id, subject_type, subject_id | tasks.rules |
| `procurement.requisition.submitted` / `.approved` / `.rejected` | 1 | 4 | requisition_id, requisition_number | tasks.rules |
| `procurement.purchase_order.approved` / `.issued` / `.closed` / `.cancelled` | 1 | 4 | purchase_order_id, po_number | inventory.shortage_refresh, tasks.rules |
| `procurement.purchase_order.became_overdue` | 1 | 4 | purchase_order_id, po_line_ids[] (scheduled) | tasks.rules, inventory.shortage_refresh (a newly late line shows in `caused_by`) |
| `procurement.purchase_order_line.expected_date_changed` | 1 | 4 | purchase_order_id, po_line_id, from_date, to_date | inventory.shortage_refresh, tasks.rules |
| `procurement.goods_receipt.posted` | 1 | 4 | goods_receipt_id, purchase_order_id, line_ids[] | tasks.rules (ops.receipts), inventory.shortage_refresh |
| `procurement.vendor_bill.mismatch_detected` / `.handed_off` | 1 | 4 | vendor_bill_id, match_status | tasks.rules |
| `production.bom.approved` / `production.routing.approved` | 1 | 4 | bom_id or routing_id, version_no | — |
| `production.work_order.released` / `.blocked` / `.unblocked` / `.completed` / `.closed` / `.cancelled` | 1 | 4 | work_order_id, wo_number, caused_by[{type, id}] | tasks.rules (ops.production_dependencies), inventory.shortage_refresh |
| `production.capacity.overloaded` | 1 | 4 | work_center_id, date | tasks.rules |
| `production.cost_rollup.computed` | 1 | 4 | rollup_id, product_id, status (complete, incomplete) | tasks.rules (missing-input issue) |
| `logistics.shipment.scheduled` | 1 | 4 | shipment_id, shipment_number, cutoff_at | tasks.rules (ops.dispatch_cutoffs, hard due at cutoff) |
| `logistics.shipment.dispatched` / `.delivered` / `.exception_recorded` | 1 | 4 | shipment_id, challan_id, evidence_kind, exception_code | tasks.rules |
| `logistics.packing_list.finalised` / `.became_stale` | 1 | 4 | packing_list_id | tasks.rules |

### 3.11 finance (Slice 5) and the Slice-5 preview

Finance payloads carry ids, numbers, enum codes and dates only: never amounts, quantities, margins, bank details or
free text (consumers re-read through `finance` readers). `sales.quote.margin_below_threshold` is emitted by the
finance margin check (`finance.margin_check` consumer) and carries ids only — margin values never leave the
restricted read path.

| Event | v | Slice | Payload | Consumers |
|---|---|---|---|---|
| `finance.invoice.draft_created` | 1 | 5 | invoice_id, doc_type, party_id, sales_order_id, suggestion_id, original_invoice_id | tasks.rules (fin.invoice_suggestions) |
| `finance.invoice.submitted` / `.approved` / `.rejected` / `.cancelled` | 1 | 5 | invoice_id, doc_type, version, reason_code | tasks.rules (fin.invoice_approvals) |
| `finance.invoice.issue_blocked` | 1 | 5 | invoice_id, doc_type, version, blocker_codes[] | tasks.rules (fin.invoice_approvals) |
| `finance.invoice.issued` | 1 | 5 | invoice_id, doc_type, document_number, party_id, due_date | tasks.rules |
| `finance.invoice.became_overdue` | 1 | 5 | invoice_id, document_number, due_date (scheduled, once per invoice) | tasks.rules (fin.overdue_invoices) |
| `finance.credit_note.issued` | 1 | 5 | credit_note_id, document_number, original_invoice_id | tasks.rules |
| `finance.receipt.recorded` / `.reversed` | 1 | 5 | receipt_id, receipt_number, party_id, reason_code | tasks.rules (fin.unallocated_receipts) |
| `finance.receipt.unallocated_detected` | 1 | 5 | receipt_id, receipt_number (scheduled, once per receipt) | tasks.rules (fin.unallocated_receipts) |
| `finance.allocation.created` / `.reversed` | 1 | 5 | allocation_id, invoice_id, receipt_id, credit_note_id, reverses_allocation_id | tasks.rules (fin.unallocated_receipts, fin.overdue_invoices) |
| `finance.invoice_suggestion.created` / `.dismissed` | 1 | 5 | suggestion_id, challan_id, sales_order_id, party_id | tasks.rules (fin.invoice_suggestions) |
| `finance.accounting_export.completed` / `.failed` | 1 | 5 | export_id, adapter, error_code | tasks.rules (fin.accounting_sync) |
| `finance.accounting_export.reconciled` | 1 | 5 | export_id, adapter, reconciliation_status | tasks.rules (fin.accounting_sync) |
| `finance.tax_profile.verified` | 1 | 5 | tax_profile_id, version | — |
| `sales.quote.margin_below_threshold` | 1 | 5 | quote_id, exception_id, revision_no | tasks.rules (mgmt.margin_exceptions) |

Preview (other Slice-5 lanes): `migration.run.completed`, `migration.run.failed`, `system.backup.completed`,
`system.backup.failed`, `system.restore_rehearsal.completed`.

## 4. Consumer index: briefing rule families (`tasks.rules`)

| Slice | Family | Triggering events |
|---|---|---|
| 1 | common.approvals | `approvals.proposal.*` |
| 1 | sales.quote_review | `sales.quote.created`, `.review_requested`, `.review_withdrawn`, `.status_changed`, `.deleted` |
| 1 | sales.quote_expiry | `sales.quote.issued`, `.marked_sent`, `.won`, `.lost`, `.cancelled`, `.status_changed`; overdue sweep on `valid_until` (no `sales.quote.expired` event exists) |
| 1 | sales.customer_replies | `sales.customer_message.received`, `.replied`, `sales.quote.marked_sent` |
| 1 | sales.enquiries | `sales.enquiry.received`, `.assigned`, `.quoted`, `.closed` |
| 1 | sales.customer_changes | `parties.party.updated` |
| 1 | common.onboarding / common.offboarding | `identity.membership.activated`, `identity.membership.deactivated` |
| 1 | admin.failed_jobs | `system.job.dead_lettered` |
| 2 | sales.price_impact | `pricing.price_list_item.superseded`, `.retired`, `pricing.price_list.activated`, `.retired` |
| 2 | sales.samples, sales.custom_products | `sales.sample.*`, `sales.custom_product.status_changed`, `.promoted`, `.promotion_rejected` |
| 2 | ops.returnables, ops.cut_plans | `challans.*`, `cutting.plan.calculated`, `.verification_required` |
| 2 | admin.failed_imports, admin.data_completeness, admin.access | `imports.job.*`, `catalogue.completeness.changed`, `catalogue.media.ingest_failed`, `identity.access_request.*`, `identity.invitation.*` |
| 2 | common.delegation | `identity.delegation.*`, `identity.absence.*` |
| 2 | scope reassignment | `sales.quote.owner_changed`, `parties.party.owner_changed` |
| 3 | common.handled, channels, admin.failed_integrations | `agents.automation_run.*`, `channels.message.delivery_unknown`, `channels.conversation.escalated`, `system.integration.status_changed`, `sales.quote.delivery_status_changed` |
| 4 | ops.shortages (live: one issue per short product × warehouse, causes — order lines, work-order materials — as evidence members), ops.picking, admin.stock_integrity (live), ops.production_dependencies (live: blocked work order with its shortage, overloaded day, incomplete rollup), ops.receipts, ops.qc, ops.dispatch_cutoffs, mgmt.decisions, mgmt.cross_team_blockers | §3.10 events; `inventory.pick_list.*`, `inventory.projection.mismatch_detected`, `production.capacity.overloaded`, `production.cost_rollup.computed` |
| 5 | fin.invoice_suggestions, fin.invoice_approvals, fin.overdue_invoices, fin.unallocated_receipts, fin.accounting_sync, mgmt.margin_exceptions (mgmt.financial_visibility: not built) | §3.11 events |

Rules treat events as triggers and re-read authoritative state; a stale `aggregate_version` is ignored; replays and
out-of-order deliveries create no new briefing version (tests B-02, B-03).

## 5. Renames from the design sources

| Design-source name | Canonical |
|---|---|
| `operations.challan.issued` | `challans.challan.issued` |
| `challans.returnable.due_soon` / `.overdue` | `challans.returnable.became_due` / `.became_overdue` |
| `procurement.grn.posted` | `procurement.goods_receipt.posted` |
| `procurement.po_line.arrival_changed` | `procurement.purchase_order_line.expected_date_changed` |
| `procurement.purchase_order.overdue` | `procurement.purchase_order.became_overdue` |
| `procurement.qc.rejected`, `production.qc.failed` | `quality.inspection.failed` |
| `logistics.dispatch.*` | `logistics.shipment.*` |
| `imports.job.failed` vs `catalogue.import.failed` | `imports.job.failed` |
| `sales.party.updated` | `parties.party.updated` |
| `catalogue.price_list.published`, `catalogue.price.changed` | `pricing.price_list.activated`, `pricing.price_list_item.superseded` |
| `catalogue.packaging.updated` | `catalogue.product.updated` with `packaging` ∈ changed_groups |
| `agents.proposal.*` | `approvals.proposal.*` (`revised` → `superseded`) |
| `integrations.connection.failed` / `.restored` | `system.integration.status_changed` |
| `identity.user.activated` / `.deactivated` / `.permissions_changed` | `identity.membership.activated` / `.deactivated` / `.access_changed` |
| `identity.membership.roles_changed`, `identity.permission_override.changed` (as trigger) | `identity.membership.access_changed` (override event kept for activity) |
| `identity.access.requested` / `.decided` | `identity.access_request.submitted` / `.decided` |
| `workcal.leave.*`, `workcal.delegation.*` | `identity.absence.*`, `identity.delegation.*` |
| `sales.quote.sent`, `.reassigned`, `.expired` | `sales.quote.marked_sent`, `sales.quote.owner_changed`, overdue sweep on `valid_until` |
| `sales.quote.review_approved` / `.review_rejected` | `approvals.proposal.approved` / `.rejected` (+ `sales.quote.status_changed`) |
| `production.cut_plan.saved` | `cutting.plan.saved` / `cutting.plan.calculated` |
| `inventory.shortage` (query only) | `inventory.shortage.{detected,changed,resolved}` from `inventory_shortage_state` |
| `inventory.reservation.conflicted` | `inventory.reservation.conflict_detected` |
| `production.work_order.released` (as unblock) | `production.work_order.unblocked` |
| `tasks.briefing.acknowledged`, `channels.briefing_ack.received` | `briefings.briefing.acknowledged` (WhatsApp acks call the briefing service directly) |
| `briefings.summary.requested` | removed: the `briefings.whatsapp_summary` job calls the channels send service |
| `channels.briefing_request.received`, `channels.item_action.received` | removed: direct service calls through `action_ref` |
| `channels.employee_conversation.escalated` | `channels.conversation.escalated` |
| `org.sequence.updated` | `numbering.sequence.updated` |
| `files.attachment.*` | `collab.attachment.*` |
| `catalogue.completeness.changed` (no producer) | produced by `catalogue.completeness_refresh` |

## 6. Contract tests

- `backend/tests/contract/test_events_registry.py::test_every_subscription_names_a_registered_event`
- `backend/tests/contract/test_events_registry.py::test_names_follow_grammar_and_module_prefix`
- `backend/tests/contract/test_events_registry.py::test_payloads_contain_no_money_text_or_restricted_fields`
- `backend/tests/contract/test_events_registry.py::test_events_md_is_up_to_date` (generated `docs/EVENTS.md`)
- `backend/tests/integration/events/test_outbox_exactly_once.py::test_dispatch_once_per_handler_despite_rerun`
- `backend/tests/integration/events/test_outbox_exactly_once.py::test_stale_aggregate_version_ignored`
- `backend/tests/integration/tasks/test_out_of_order_events.py::test_v3_then_v2_creates_no_version`
