> Design-workflow output (2026-10-12), kept as source material. Where it conflicts with docs/architecture/*, the architecture docs win.

# Critique: completeness

The seven subsystem designs cover almost every explicit requirement in OPUS_5_5_BUILD_PROMPT.md and CURRENT_STATE_SPEC.md. That includes all legacy field groups (spec section 4), the legacy workflows, bugs 10.1 #1-16, security gaps 10.2 #1-8, and tests mapped to every acceptance scenario from A to N. The main risk is not missing features. It is the contracts between subsystems, which do not match.

Blockers (8):
- Five incompatible permission-key vocabularies, which platform startup validation will reject.
- An event catalogue where most names the briefing consumes are never emitted.
- Duplicate calendar, delegation and leave models with contradictory delegation rules.
- No single approvals contract, and two sources of quote-review policy.
- Two storage and file cores.
- No owner for the unit-of-measure (UOM) master.
- No owner for enquiries and customer messages.
- A slice conflict that breaks the slice-1 scenario C path (agent tools are scheduled for slice 3).

Major contradictions:
- Document numbering (quote yearly reset vs never, and a separate finance series table).
- Duplicate stores for notes, CSV writer, AI usage, integration status and user preferences.
- API prefix (/api vs /api/v1), session bootstrap endpoint, CSRF scheme, and invite/reset tokens placed in URL paths.
- Decor normalisation vs grain-lock keys in the cutting optimiser.
- Fixture data: names, products, personas and expected due times differ between designs.
- Ordinals for 'Open the second item' are resolved two different ways.
- WhatsApp briefing actions don't fit the proposal-only action_ref model.
- The webhook is blocked by CSRF and RLS.

Domain gaps:
- Samples
- Pick lists
- Responsibilities and work queues
- Access requests
- Historical (non-login) people for migration
- The pricing-import contract
- The opening-stock import path
- Stock attributes on products (HSN/SAC, stock unit, lot tracking, QC)
- Producer events for the operations, finance and margin briefings

I recommend adding a slice 0 that fixes these as canonical registries and docs before any feature code: permissions, events, API conventions, fixtures, route manifest and ownership. The plan below follows build_order 1-6 and gives each slice exit criteria tied to the acceptance scenarios.

## Findings

### [blocker] Permission keys: 14 legacy intentions plus module/action/scope permissions enforced on every path
- Source: build prompt <legacy_parity_and_corrections> #1; spec 3.2; platform s5 vs commercial s6, catalogue s14, operations s11, briefing s9, agents s10/s13
- Owner: platform
- Problem: The designs use five incompatible key vocabularies:
- Platform: three-part keys such as sales.quote.read, catalogue.product.read, catalogue.costing.read, imports.job.run, ops.challan.*, production.cut_plan.*, system.audit.read, demo.data.reset.
- Commercial: view/edit verbs (sales.quote.view/edit/send, parties.party.view, pricing.costing.view), with a different legacy mapping (view_products->pricing.price.resolve, view_costing->pricing.costing.view).
- Catalogue: two-part keys (catalogue.view, catalogue.edit, catalogue.media_manage, catalogue.import, catalogue.demo_reset, migration.execute).
- Operations: two-part keys under different module names (challans.delete_draft, cutting.plan, inventory.reserve, finance.issue, production.view_costing).
- Others: briefing uses tasks.assign/tasks.dismiss; agents uses audit.trace.view; the promotion approver key is misspelled catalog.product.create.
Platform startup cross-validation will reject the templates, and two conflicting legacy_alias mappings exist.
- Resolution: Slice 0: publish docs/architecture/permissions.md plus a PermissionDef list per module as the only catalogue.
- Use the platform grammar <module>.<resource>.<action> with a fixed verb set: read, create, update, archive, delete, transition, export, approve, manage, run, post, issue.
- Rename every design's keys. Examples: catalogue.view->catalogue.product.read; challans.delete_draft->ops.challan.delete_draft; cutting.plan->production.cut_plan.update; sales.quote.view/edit->sales.quote.read/update; pricing.costing.view->pricing.cost.read; audit.trace.view->system.trace.read; tasks.assign->tasks.task.assign.
- Keep one legacy_alias table built as the union mapping: view_products->catalogue.product.read+pricing.price.resolve; edit_products->catalogue.product.{create,update,archive}+catalogue.media.manage+pricing.price_list.manage; view_costing->pricing.cost.read (one field guard); import_data->imports.job.run.
- Add a contract test: every key referenced in policies.py, tools.py, TEMPLATE_GRANTS, SettingDef or route declarations must exist in the catalogue.

### [blocker] Event-driven briefing and transactional outbox; event names <module>.<entity>.<past_tense_verb>
- Source: shared conventions; build prompt <daily_briefing>; briefing s4 event catalogue vs commercial s8, operations s12, catalogue s13, agents s17, platform s14
- Owner: platform
- Problem: Most event names the briefing consumes are not emitted under those names:
- operations.challan.issued vs challans.challan.issued
- procurement.grn.posted vs procurement.goods_receipt.posted
- logistics.dispatch.* vs logistics.shipment.*
- imports.job.failed vs catalogue.import.failed
- sales.party.updated vs parties.party.updated
- catalogue.price_list.published vs pricing.price_list.activated
- agents.proposal.* vs approvals.proposal.*
- integrations.connection.failed vs system.integration.status_changed
- workcal.* vs identity.delegation.* / identity.absence.*
Operations consumes sales.quote.status_changed and catalogue.packaging.updated; agents consumes tasks.briefing.acknowledged and catalogue.price.changed. None of these is emitted. Some names break the past-tense rule (challans.returnable.due_soon, procurement.purchase_order.overdue), and event module prefixes differ from permission modules.
- Resolution: Slice 0:
- Write docs/architecture/events.md.
- Each events.py declares EventDef entries (name, version, payload schema, producer).
- registry.py fails startup if any subscription, ActivitySpec or briefing rule names an unregistered event.
- Module prefixes must equal the permission module.
- Rename non-past-tense events, e.g. challans.returnable.became_due, procurement.purchase_order.became_overdue.
- Rewrite briefing s4 against the registry; the briefing contract test becomes a registry lookup.
Missing producer events are listed in separate findings.

### [blocker] Configurable leave, delegations, quiet hours, weekends and shifts; explicit midnight, weekend and shift boundaries (B)
- Source: build prompt <daily_briefing>; scenario B; platform s3 delegation/user_absence, s8 calendar; briefing s2 workcal, s10
- Owner: platform
- Problem: Two owners define this, with contradictory semantics.
- Platform: delegation table and user_absence; calendar stored as settings; a local workday split at midnight (test_calendar at 18:30Z); membership.shift_code; endpoints /me/delegations, /me/absences and identity delegations/absences; delegation scheduled for slice 2.
- Briefing: a parallel workcal module (calendars, shifts, holidays, assignments with a btree_gist EXCLUDE constraint, leave with approval, delegations with task_kinds and include_approvals); a 04:00 rollover work_date; delegation tests in slice 1 (B-13).
- Delegation rules conflict. Platform delegation adds delegated keys the delegate may not hold, widening their record scope. Briefing says delegation never widens access, and approvals move only when include_approvals is set and the delegate is eligible in their own right.
- Operations capacity planning uses 'company shifts' from settings, a third source.
- Resolution: Use one model in the platform layer (platform authz cannot import modules):
- app/platform/org owns work_calendar, work_shift, work_holiday, work_assignment and the calendar service, including work_date(user, t) with rollover (default 04:00). Rewrite platform test_calendar to the rollover rule.
- Identity owns one delegation table (permission_keys or task_kinds, include_approvals, reason, window, cancel) and one user_absence table (status requested|approved|rejected|cancelled; reason visible only to approvers).
- Delegation rule: it never adds keys. It only extends the delegate's record scope to the delegator's owned records, for delegable keys the delegate already holds. Approvals move only with include_approvals and independent eligibility.
- Authz resolution and briefing collection call the same function.
- Delete the briefing workcal_* tables and endpoints.
- Make the EXCLUDE constraint depend on btree_gist being available; fall back to a service check.
- Build in slice 1.

### [blocker] Approval bound to an exact versioned proposal; separation of duties (SoD); recheck at execution; review/approve references a proposal (F)
- Source: build prompt <agent_experience>, legacy #6; scenario F; agents s9; commercial s3.3, s2.2 fx_rate, s3.8 promotion; operations s3-s9 inline approvals; briefing s9 decide(proposal_id, expected_version)
- Owner: agent_voice_whatsapp
- Problem: There is no single approval contract:
- Commercial calls request_approval(target_kind, target_id, content_hash, approver_permission) with an in-transaction callback, and keeps its own approval states: quote review_outcome, fx_rate proposed/approved, promotion pending_approval.
- Operations builds approvals into each document: adjustments, counts, opening batches, PO approved_version, invoices, write-offs, reversals.
- Briefing calls decide(proposal_id, expected_version); the agents endpoint takes {decision, content_hash}.
- Quote-review policy has two sources: quote_settings.review_policy (default never) vs the agents seed rule requiring L1 approval for price overrides and quotes below EUR 5,000.
- Briefing test A-09 relies on an undefined 'override-approval eligibility'.
- Authority is defined either by a scoped *.approve permission or by an approval_authority level; how the two combine is never stated.
- Resolution: Make approvals the only engine for every human approval, whether started from the UI or by an agent:
- Domain modules register ApprovalTarget adapters: facts(), content_hash(), version(), on_approved(uow), on_rejected(uow). Documents keep a read-only status mirror.
- Decision API: decide(proposal_id, decision, content_hash, expected_version, reason).
- Eligibility: the approver holds <module>.<resource>.approve at a scope covering the target, AND, if the policy names a level, an active approval_authority. Approvals enforces SoD, backed by the DB CHECK. eligible_approvers() is exposed to tasks.
- Remove quote_settings.review_policy. Review policy lives only in approval_policy, with default 'review only when requested'.
- The demo seed enables a price-override rule so the fixture approvals exist.
- Record rules for overrides and below-minimum quotes as an open business-policy question.
- FX rates, promotion, adjustments, counts, opening batches, POs, invoices, write-offs and reversals all become ApprovalTargets.

### [blocker] S3-compatible storage; validated uploads; authenticated download; re-import must not duplicate media
- Source: build prompt legacy #3/#4; platform s3 file_object/attachment, s9; catalogue s1, s3 core_stored_object, s7
- Owner: platform
- Problem: There are two storage cores and two file tables:
- Platform: file_object and attachment. Key {company}/{purpose}/{yyyy}/{mm}/{id}; dedupe on (company, sha256, purpose); variants thumb_256 and preview_1024; GET /files/{id}/content; garbage collection in system.cleanup.
- Catalogue: core_stored_object, a table placed in app/core even though platform says core has no tables. Key c/{company}/sha256/...; UNIQUE(company, sha256); 320px WEBP thumbnails; GET /media/{id}/content|preview|thumbnail; its own garbage collection.
Both claim the sniffing, size-limit and header code. Quote media_snapshot points at stored_object_id while quote_document uses file_id.
- Resolution: Platform files owns everything shared:
- One file_object table with UNIQUE(company_id, sha256); purpose and classification live on link rows.
- Storage backends, sniffing, size limits, one variant set (thumb_320 WEBP, preview_1024), streaming cookie-authenticated download, and garbage collection.
- catalogue_product_media stays as the product link (ingest_status, source_url_key, legacy ids) with an FK to file_object; media endpoints delegate to the platform download.
- Delete core_stored_object and the catalogue core/storage package.
- Snapshots store file_object ids.

### [blocker] Master data: UOM conversions; physical quantities carry units; integer units reject fractions
- Source: build prompt <connected_erp_scope>; shared conventions; catalogue s0 'Platform: UOM codes and aliases'; operations s0 uoms/uom_conversions; platform s2 Quantity NUMERIC(18,6)
- Owner: platform
- Problem: Catalogue (slice 1 unit_of_sale normalisation) and operations both depend on a UOM master with aliases, an is_integer flag and conversions, but platform defines none. Quantity precision also differs: platform uses NUMERIC(18,6), operations NUMERIC(18,4).
- Resolution: Platform org adds three tables:
- uom: code, name, dimension, is_integer.
- uom_alias: used by imports.
- uom_conversion: from, to, Decimal factor, optional product_id, provenance.
Seed the legacy units (pcs, nos, sheets, kg, g, m, mm, cm, sqm, sqft, box, set, roll, bundle, carton). Use one Quantity type, NUMERIC(18,6) + uom_code, with entry rules per unit (integers only where is_integer; otherwise at most 4 decimal places). Slice 1.

### [blocker] Sales covers enquiries; chain enquiry -> quote; sales briefing shows enquiries and replies (A)
- Source: build prompt <product_contract>, <connected_erp_scope>, <daily_briefing>; briefing s4 sales.customer_message.*/sales.enquiry.*, fixtures M1/M2; frontend /sales/enquiries [S4]
- Owner: commercial
- Problem: No design owns enquiries or customer messages. Commercial covers parties, pricing, quotes and custom products only, and channels store WhatsApp messages only from slice 3. The slice-1 briefing families customer_replies and enquiries, and Meera's expected Today ('Two customer replies need attention'), depend on events nothing in slice 1 produces.
- Resolution: Add app/modules/sales/enquiries with two entities:
- sales_enquiry: ENQ-YYYY-NNNN; party or prospect; source manual|email|whatsapp|phone; received_at; assignee; status new|qualified|quoted|closed_*; linked quotes; required_by.
- customer_message: party/contact; direction; channel; received_at; replied_at; reply_ref; body with external provenance; enquiry/quote links.
Slice 1: manual logging UI, seed data, and events sales.enquiry.{received,assigned,closed} and sales.customer_message.{received,replied}. A quote can link to its enquiry. Slice 3: channels create customer_message rows through this service.

### [blocker] Slice 1 delivers the command surface and the full vertical path (request -> lookup -> draft -> briefing task -> review -> document); scenario C
- Source: build_order 1; scenario C; commercial s12 (agent tools slice 3, yet its C test in slice 1); agents s19 slice 1; frontend s9 assistant [S3] vs C e2e in S1
- Owner: commercial
- Problem: Commercial schedules its agent tools for slice 3, but its own slice-1 C test calls find_repeat_quote_basis and draft_quote. Frontend marks the assistant and cards as S3, but its S1 exit includes the C e2e card. The slice-1 vertical path cannot pass as designed.
- Resolution: Move the following into slice 1:
- Commercial tools resolve_party, find_repeat_quote_basis, resolve_price, calculate_quote, draft_quote and request_approval (quote review), registered with the agents registry and run by the Demo provider.
- Frontend: the Today composer text path, run status streaming, and QuoteDraftCard/ProposalCard.
The assistant rail, voice and the remaining cards stay in S3.

### [major] Legacy role templates reproduce legacy rights exactly
- Source: spec 3.2; build prompt legacy #1; commercial s6 vs platform s5 test_legacy_permission_parity
- Owner: commercial
- Problem: Commercial gives management 'everything at company scope', but legacy management had no delete_quotes, edit_products, manage_users, import_data or manage_categories. The platform parity test requires an exact reproduction of the legacy table, so it would fail.
- Resolution: Management template = the legacy 3.2 rights mapped to new keys, plus the new non-destructive keys: sales.quote.approve, sales.quote.correct_status and sales.quote.assign at company scope. It gets no delete, no catalogue/pricing manage and no identity.* keys. The parity test is the gate.

### [major] Redact hidden costing from logs, notifications, exports and model context (E)
- Source: build prompt <agent_experience>; scenario E; platform s5 Restricted(); agents s8 field-sensitivity registry; briefing s6 step 6; operations production.view_costing; commercial pricing.costing.view
- Owner: platform
- Problem: Four redaction mechanisms with different keys exist. A field registered in one is invisible to the others, so model context, briefing facts, exports and logs can diverge.
- Resolution: Use one field-guard registry: Restricted(guard_key, model_exposure=deny|allow, log=drop).
- pricing.cost.read guards product_cost, custom_product_costing, production cost inputs and rollups, and margin fields.
- Agents redact_for_model, briefing fact schemas, the structlog processor, the CSV exporter and notification renderers all call redact() from this registry.
- A canary test plants a costing sentinel in every costing table.

### [minor] Protected costing; deterministic cost rollups with explicit cost versions
- Source: build prompt legacy #5, <connected_erp_scope> Production; commercial s2.2 product_cost; operations s6 prd_cost_versions/rollups
- Owner: operations
- Problem: Two independent cost sources exist for the same product: commercial product_cost and operations prd_cost_rollups. Margin exceptions and custom-product promotion copy costs without saying which source wins.
- Resolution: product_cost is the single per-product cost of record. Its source_kind is manual|import|migration|rollup. Freezing a cost version writes product_cost rows with source_kind=rollup and a link back to the rollup. Margin reads product_cost only. Record this in DECISIONS.

### [major] Sales briefing: quote expiry and customer changes; a changed source invalidates recommendations (B); briefing tasks follow ownership changes (A)
- Source: briefing s4 Sales events; commercial s3.3, s8; operations s12 consumes sales.quote.status_changed
- Owner: commercial
- Problem: Briefing relies on sales.quote.sent, .status_changed, .validity_extended, .expired and .reassigned, and on a 'validity-extension revision' preparer. Commercial emits none of these: it has issued/marked_sent/owner_changed, no status_changed, no expired event (is_expired is computed) and no extend-validity action. If a quote is reassigned, the task's scope attributes never update, which leaks the quote to its former owner.
- Resolution: Commercial emits:
- sales.quote.status_changed {from,to} on every transition, alongside the specific events.
- sales.quote.owner_changed, which the briefing consumes for reassignment.
- pricing.price_list_item.superseded, listing affected open quotes.
Add an explicit extend_validity transition (sent->sent with a new valid_until, a new issued revision, and event sales.quote.validity_extended). Drop sales.quote.expired: the quote_expiry task has a hard due date at the end of valid_until in company time, and the overdue sweep records the expiry.

### [major] Operations briefing: shortages, receipts, production dependencies, dispatch cutoffs, QC, returnables; deduplicate by root cause
- Source: build prompt <daily_briefing>; briefing s4 Operations, issue keys po_line/shortage/dispatch; operations s12
- Owner: operations
- Problem: The operations design can't feed these briefing items:
- Shortages exist only as a query plus reservation.shortfall_detected. With no persisted shortage state, there is no detected/resolved event and nothing to deduplicate on.
- No event fires when a PO line's expected date changes.
- No event for a work order becoming unblocked, and none for reservation conflicts.
- Shipments have no cutoff time.
- QC events are split between procurement and production.
- Finance has no receipt-unmatched, draft-ready or sync-completed event.
- No service returns caused_by links for root-cause grouping.
- Resolution: - Add inv_shortage_state (product, warehouse, qty, evidence, state, version), refreshed by a debounced job after postings, reservations and PO changes. It emits inventory.shortage.{detected,changed,resolved}.
- Add events procurement.purchase_order_line.expected_date_changed, production.work_order.unblocked and inventory.reservation.conflict_detected.
- Add log_shipments.cutoff_at and event logistics.shipment.scheduled.
- Unify QC under quality.inspection.{requested,failed,passed}.
- Add finance.receipt.unallocated_detected, finance.invoice.draft_created and finance.accounting_export.{completed,failed}.
- Read services return caused_by refs.
- Deliver in slices 4 and 5.

### [major] New employees get onboarding; deactivation unlinks WhatsApp; a permission change regenerates the briefing
- Source: briefing s4 identity events; agents s17 consumed; platform s14
- Owner: platform
- Problem: Briefing and agents consume identity.user.activated, .deactivated and .permissions_changed. Platform emits identity.invitation.accepted, identity.membership.deactivated and separate role/override events. As designed, onboarding, channel revocation and briefing regeneration never fire.
- Resolution: Platform emits:
- identity.membership.activated (on invitation accepted or reactivation).
- identity.membership.deactivated.
- identity.membership.access_changed {membership_id, authz_epoch}, whenever an authz_epoch bump changes a member's effective permissions.
Expose effective_permissions_fingerprint(membership) for the briefing's permission fingerprint.

### [major] Admin briefing includes access tasks
- Source: build prompt <daily_briefing>; briefing s4 identity.access.requested/decided; seed 'Kabir's access request'
- Owner: platform
- Problem: No design owns an access-request workflow. Platform has no table, endpoint or event for it, yet the briefing's admin.access family and its fixture depend on one.
- Resolution: Add access_request: requester, permission_key+scope or role_id, optional resource_ref, reason, status, decided_by/at, note.
- Endpoints: POST /me/access-requests, plus identity decide endpoints governed by identity.permission.manage and the anti-escalation rules.
- Approving a request writes a user_permission_override.
- Events: identity.access_request.{submitted,decided}.
- Slice 2. The briefing admin.access family moves to slice 2.

### [major] Approval items, Handled for you, cross-channel acknowledgement
- Source: briefing s4 Agents/Channels; agents s17
- Owner: agent_voice_whatsapp
- Problem: Briefing consumes agents.proposal.{submitted,revised,...}, agents.automation_run.failed and channels.briefing_ack/briefing_request/item_action/employee_conversation events. Agents emits approvals.proposal.* (with superseded, not revised), only automation_run.completed, and generic channels.message.* events. The 'consumer' of briefings.summary.requested doesn't exist.
- Resolution: Register approvals.proposal.{submitted,approved,rejected,expired,invalidated,superseded,executed,execution_failed}, agents.automation_run.{completed,failed} and channels.conversation.escalated. WhatsApp briefing interactions become direct service calls (see the WhatsApp briefing actions finding). Replace briefings.summary.requested with a briefing job that calls the channels send service.

### [major] Atomic unique counters preserving LK-QT-YYYY-NNNN, DC-YYYY-NNNN and CP-NNNN; yearly reset documented; numbers never reused
- Source: build prompt legacy #7; spec 10.1 #13; platform s7; commercial s3.7; operations s4, s9 fin_document_series
- Owner: platform
- Problem: - Platform defaults quote numbering to a yearly reset, using a counter upsert plus a register of issued numbers.
- Commercial says no reset ('legacy continuity'), using UPDATE ... RETURNING.
- Operations calls numbering.next() on a 'document_sequences' table.
- Finance adds a second series table, fin_document_series, with an April financial-year reset.
- The prefixes P-, ENQ-, SMP-, CUT-, PR-, WO-, PL-, SH-, RCPT- and the invoice/credit-note series are not registered.
- Resolution: Platform numbering is the only allocator.
- Add a financial_year reset policy (start month comes from settings) and delete fin_document_series.
- Each module declares its sequences in a SEQUENCE_DEFS registry.
- Record the quote default in DECISIONS as yearly: the 2026 counter continues from the migrated maximum + 1, and the business can switch to never.
- Invoices take a number only at issue.

### [major] Conflict-aware autosaved internal notes; PDFs omit internal notes
- Source: build prompt legacy #11; scenario L; platform collab note; operations chl_challans.internal_notes; commercial party.notes; frontend GET|PUT /notes/{type}/{id}
- Owner: platform
- Problem: Notes are stored twice: in the platform note table and in domain columns (challan internal_notes, party.notes). The endpoint paths differ between frontend and platform, and no design says where legacy internal_notes migrate to.
- Resolution: collab.note is the only store for record-level internal notes; drop chl_challans.internal_notes and party.notes.
- quote_line.internal_note stays as a field and is redacted from documents.
- Canonical endpoints: GET|PUT /notes/{resource_type}/{resource_id}, and POST .../comments for comments.
- Migration writes legacy notes as note rows with provenance metadata.

### [major] Grouped global search with deep links, slash shortcut and recent searches, covering old and new entities under permissions (G)
- Source: build prompt legacy #11; spec 4.16 search_history, 5.9; frontend s12 and its ownership risk; platform s5 'search providers'
- Owner: platform
- Problem: Nobody owns the search endpoint, the provider protocol or recent-search storage. The frontend's S1 depends on GET /search and /search/recent.
- Resolution: Create app/platform/search:
- A SearchProvider protocol built on ScopedRepository.search.
- A search_recent table keeping the last 10 queries per user.
- Endpoints GET /search?q=&types=&per_group= and GET|POST|DELETE /search/recent, under permission search.global.use.
- Providers by slice: slice 1 products, categories, parties, quotes; slice 2 custom products (product_name), challans, cut plans, imports, price lists; slices 4-5 operational documents.
- Restricted fields are never indexed.

### [major] Canonical detail screen with related documents; search, voice and chat reach the same object; only applicable actions shown
- Source: build prompt <product_contract>; frontend s3 capabilities, s7 /records/{type}/{id}/relations, s17 /links/resolve; platform _actions; commercial/briefing allowed_actions
- Owner: platform
- Problem: Related documents and business-key resolution (/go/[type]/[key]) have no backend owner. Action capabilities use three different field names.
- Resolution: Extend ResourcePolicy with business_key_column, label(), canonical_path and relations() (filtered by parent visibility). Platform serves GET /records/{type}/{id}/relations and GET /links/resolve, returning 404 when the record isn't readable. Detail DTOs carry capabilities {action:{allowed, reason_code}} plus allowed_transitions.

### [major] One source of truth for schemas and generated API types
- Source: frontend s3 /api/v1 and BACKEND_INTERNAL_URL; platform s1/s13 /api and LK_API_INTERNAL_URL; all module endpoint lists
- Owner: platform
- Problem: The API prefix and the backend URL environment variable differ. The generated client, CSP, health checks and webhook URLs would disagree.
- Resolution: Decide in api-conventions.md: business routes under /api/v1 (design paths are relative to it), health under /api/v1/health/*, the webhook at /api/v1/webhooks/whatsapp, and LK_API_INTERNAL_URL as the only environment variable name.

### [major] Never put authentication tokens in URLs; secure password reset
- Source: build prompt legacy #1; spec 10.2 #4; platform s4 fragment rule; frontend s4 /reset-password/[token], /invite/[token]
- Owner: frontend_verification
- Problem: Frontend routes put invitation and reset tokens in the URL path, where they reach Next server logs, browser history and the Referer header.
- Resolution: Use /invite, /reset-password and the demo sign-in page with the token in a #t= fragment. The page reads it, removes it with replaceState and POSTs it, with Referrer-Policy: no-referrer. Add an e2e check that no request URL or log line contains the token.

### [major] Secure session handling; CSRF protection
- Source: platform s4 GET auth/session and stored csrf_hash; frontend s3 signed double-submit cookie, s17 GET /session/bootstrap
- Owner: frontend_verification
- Problem: There are two bootstrap endpoints and two server-side CSRF schemes. Whichever the backend implements, the other design's tests fail.
- Resolution: Keep one endpoint, GET /api/v1/session/bootstrap, owned by the ui module and built on the platform session service. Use the platform CSRF scheme (stored hash; lk_csrf cookie echoed as X-CSRF-Token) and add the frontend's Sec-Fetch-Site and Origin checks.

### [major] Escape spreadsheet formula injection in every CSV output (G)
- Source: build prompt legacy #4; platform core/csvsafe.py; catalogue core/exports/csv_safe.py with its single-writer contract test; commercial csv_safe(); operations exports.safe_csv
- Owner: platform
- Problem: There are two shared CSV utilities with different escape rules. The catalogue contract test (only one module may write CSV) forbids the platform module.
- Resolution: One app/core/csvsafe.py, owned by platform and built in slice 1:
- Catalogue's escape rule set: = + - @ TAB CR LF, leading spaces and full-width variants.
- QUOTE_ALL, CRLF line endings, UTF-8 BOM, typed numeric cells, xlsx_safe_cell, and stripping of the guard prefix on import.
- The single-writer contract test targets this module.

### [major] No tokens in download URLs; avoid costly polling; streamed progress
- Source: agents s1 consumes 'presigned URLs' and 'LISTEN/NOTIFY'; platform s6/s9/s18
- Owner: agent_voice_whatsapp
- Problem: Agents assumes presigned S3 URLs and LISTEN/NOTIFY, both of which platform excludes. How SSE gets worker progress is unspecified, and AsyncAnthropic is planned inside a synchronous thread-pool worker.
- Resolution: - Audio and media are file_object rows streamed with cookie auth; WhatsApp outbound media uses the Meta media upload.
- The SSE handler polls agent_run_step for seq > last every 250-500 ms with no open transaction, and supports Last-Event-ID resume.
- The worker uses the synchronous Anthropic client.

### [major] Inventory by product and lot; HSN/SAC on challan lines; packaging snapshots for logistics
- Source: operations s0 depends on product base_uom/track_lots/qc_required/hsn_sac; catalogue s3 catalogue_product
- Owner: catalogue_imports_migration
- Problem: Catalogue products lack HSN/SAC, stock unit, stock-tracked, lot-tracking and QC-required attributes. Packaging weights don't say whether they are per carton or per unit.
- Resolution: Add nullable columns in the slice-1 schema: hsn_sac, stock_uom_code, is_stock_tracked, track_lots, qc_required. They become editable in slice 2, and are required once inventory goes live in slice 4. Add them to the importer field specs. Document in CATALOGUE_FIELDS.md that net/gross kg is per master carton and unit_weight_g is per unit.

### [major] Handle decor 120.0 without corrupting 120; never rotate grain-locked material (H)
- Source: build prompt legacy #12/#9; scenario H; catalogue s4.1; operations s7 grouping test
- Owner: operations
- Problem: Catalogue turns '120.0' into '120', but the cutting packer treats '120', '120.0' and '0120' as separate decors and keys grain locks by raw text. A lock on 120 would not stop rotation of an item entered as 120.0, which violates scenario H.
- Resolution: Cutting, grain locks and migration all use catalogue normalise_identifier with the decor policy: 120.0 becomes 120 with a visible warning, and 0120 stays distinct. Grain-lock lookup uses the canonical key. Update the grouping test and add a test proving a lock on 120 blocks rotation of an input of 120.0.

### [major] pricing_master import; editable price lists with history; rollback of unreferenced imports
- Source: build prompt legacy #4/#5; catalogue s0 pricing.imports.*, s9.9; commercial s2.2 immutable active items
- Owner: commercial
- Problem: Catalogue calls pricing functions that commercial never defines (preview/apply/revert of legacy rows, active_price_exists, display_prices). Nothing says which price list a legacy row goes into, how imports affect an active list, or how rollback undoes a superseded price.
- Resolution: Define the pricing import contract:
- Each (price_type, currency) maps to a standard list STD-{TYPE}-{CUR}.
- Importing into an active list supersedes items, with valid_from taken from the mapping.
- revert_change restores an item only if no quote line references the new item and nothing has superseded it since.
- Provide display_prices() (redacted) and active_price_exists().
- Jointly owned contract test.

### [major] Opening stock is an explicit approved migration
- Source: build prompt <connected_erp_scope> Inventory; operations s3 'created from import staging'; catalogue s9.1 seven types
- Owner: operations
- Problem: No import definition exists for opening stock.
- Resolution: Inventory registers an opening_stock import definition through the catalogue engine. Its commit creates a draft inv_opening_batch and never posts stock; a different user's approval posts it. Slice 4.

### [major] Migrate users via invitations; keep historical attribution for inactive people
- Source: build prompt <migration>; catalogue s0 identity hooks, s11 Users; platform app_user.status
- Owner: platform
- Problem: Platform has no historical (non-login) person and no way to create a pending-invitation user. Legacy creators who were hard-deleted cannot be referenced, so created_by foreign keys would fail.
- Resolution: Add app_user.status 'historical' (no credentials; shown as 'Name (former)'), plus ensure_historical_person() and create_pending_invitation_user(), which creates the user without sending anything. Slice 5.

### [major] Migrate quotes, lines, revisions and custom products; keep issued snapshots exactly
- Source: build prompt <migration>; catalogue s11 legacy_import_* adapters; commercial s12 slice 5
- Owner: commercial
- Problem: The legacy_import_* functions are undefined. Legacy quotes have both created_by and assigned_to, but new quotes have a single owner.
- Resolution: Define legacy_import_quote/line/revision/custom_product:
- origin=migration; stored totals are kept, never recomputed.
- Revisions are stored as revision kind=legacy, with status history built from status_from/to.
- party_link_status=legacy_unlinked.
- Owner = assigned_to, else created_by; created_by is kept separately.
Document this in the migration runbook.

### [major] No-access users receive no sensitive fragments or aggregate leakage (A)
- Source: scenario A; briefing s12 and risks; platform s5 child-visibility rule
- Owner: briefing
- Problem: Tasks and issues are authorised by copied ('denormalised') scope attributes kept in sync by events. This breaks the platform rule that child records are authorised through their parent. Given the event-name mismatches, these attributes will drift and leak titles, and the consistency job isn't scheduled until slice 6.
- Resolution: Register ResourcePolicies for task, issue and change_log.
- List queries combine the scope predicate with a batched source-visibility filter (visible_ids per source type), so drift can only hide items, never show them.
- Render titles from redacted facts at read time.
- Move the consistency job to slice 1.
- Add a canary test that reassigns a quote and checks the previous owner's view.

### [major] Employees and responsibilities as master data
- Source: build prompt <connected_erp_scope>; briefing s0 depends on identity responsibilities, s4 queue_code
- Owner: briefing
- Problem: No design defines responsibilities or work queues, which the briefing needs to route tasks.
- Resolution: Tasks owns tasks_queue, tasks_queue_member and tasks_responsibility_rule. Rules map a responsibility key (party.account_owner, quote.owner, warehouse.receiving...) to a resolver: record_field, team_queue, role or named member, with a fallback queue. Configured in /settings/briefings. Slice 1.

### [major] 'Open the second item' uses an explicit stable reference; no reordering during a spoken briefing (B)
- Source: scenario B; briefing s13 pins; agents s5/s7 agent_context_entry; frontend s8
- Owner: agent_voice_whatsapp
- Problem: Two independent ordinal mechanisms exist (briefing pins and agent object context), so a voice command during Listen could resolve against the wrong list.
- Resolution: The agents pre-route checks first for an active briefing pin and resolves through briefings.resolve_pin(). Otherwise it uses the latest presented list. Presenting a briefing in chat creates a briefing chat pin. Test B-05 also runs through the agent path.

### [major] Cross-channel acknowledgement; snooze and handled state survive channel switching; summaries only with opt-in (B, K)
- Source: briefing s14; agents s4 action_ref and consent purposes
- Owner: agent_voice_whatsapp
- Problem: Briefing expects a channels eligibility check, a send-summary function and WhatsApp quick replies (ack, snooze, unsnooze, mark handled). Agents' action_ref is tied to proposals and supports only confirm/approve/reject/choose/open. The consent purpose names also differ.
- Resolution: Generalise action_ref with target_type proposal|briefing_version|briefing_item, a target fingerprint, and the actions ack, snooze, unsnooze and mark_handled, dispatched to briefing services. Channels exposes eligibility(user, purpose) and send_summary(). Canonical consent purpose: daily_briefing. Slice 3.

### [major] One source of truth for API types; a voice transcript submits once (J)
- Source: agents s2 web files and s16 /turns client_utterance_id; frontend s2/s9/s10 /messages client_message_id and text_delta
- Owner: frontend_verification
- Problem: Both designs claim the same web files. The endpoint, idempotency field and SSE event names differ. Agents ships a browserSpeech module while frontend says there is no SpeechRecognition dependency, and the offline label copy differs.
- Resolution: Frontend owns all apps/web code; agents owns the contract.
- Request: POST /agent/conversations/{id}/turns {client_utterance_id, text, input_mode, context}.
- SSE events: status|step|card|clarification|text|error|done.
- Browser speech becomes an optional, labelled fallback adapter, off by default.
- One offline label, taken from messages/en.ts.

### [major] Tool context carries the authenticated actor and effective permissions, injected by the server
- Source: build prompt <agent_experience>; platform ActorContext; agents ToolContext and channel_session
- Owner: agent_voice_whatsapp
- Problem: Agents resolves permissions separately from the platform ActorContext and its authz_epoch, so the two can diverge after a revocation.
- Resolution: ToolContext becomes a frozen wrapper {actor: ActorContext, run_id, conversation_id, automation_id, clock}, built only via platform build_actor_context(channel, auth_strength). Deactivation and credential events revoke channel_session.

### [major] Never show 'connected' until verified; integration status; missing provider configuration blocks live issuance
- Source: platform integration_status; agents channel_account.status; operations fin_provider_configs.status; briefing integration:{connection_id}
- Owner: platform
- Problem: There are three status vocabularies and no shared event, so Settings and the admin briefing can't show one truthful state.
- Resolution: platform integration_status is the single registry. Provider config tables hold configuration only and report through integrations.report(). The event system.integration.status_changed drives the briefing issues.

### [major] Personal preferences for language, detail, voice and schedule; persistent theme; mandatory controls are never preferences
- Source: build prompt <daily_briefing>, legacy #11; platform app_user/membership.preferences; frontend user_ui_preferences; briefing briefings_user_prefs; agents personal memory
- Owner: platform
- Problem: Language is stored in four places and voice/detail settings in two, with no defined precedence.
- Resolution: Identity owns a user_preference table (user-level, exempt from RLS) with typed sections: ui, locale, briefing and voice. Frontend and briefings read it through the identity service; agents memory must not store these keys. A guard rejects any attempt to weaken mandatory controls.

### [major] Verify webhook authenticity and acknowledge promptly (K)
- Source: platform s4 CSRF on every unsafe method, s2 RLS; agents s15 webhook_inbox with company_id
- Owner: platform
- Problem: Meta's POST will fail the CSRF/Origin check. webhook_inbox is a tenant table, but the company is unknown at insert time.
- Resolution: Add a 'webhook' route kind: signature-verified, exempt from CSRF and Origin checks, raw body preserved, rate-limited. Exempt webhook_inbox and webhook_rejection from RLS. The worker resolves the company via channel_account.

### [major] PDFs wrap and repeat headers, with Unicode names and currency glyphs (L)
- Source: build prompt legacy #11; commercial s1 ReportLab and Noto; operations challan.html and SVG-in-PDF; frontend test expects Devanagari
- Owner: commercial
- Problem: There are two PDF renderers, and the frontend's Devanagari expectation conflicts with commercial, which lists Devanagari shaping as a risk.
- Resolution: core/documents (ReportLab Platypus with embedded Noto Sans and Noto Sans Devanagari) is the only PDF engine. Challan and cut-plan PDFs use reportlab.graphics. Verify Devanagari shaping in slice 2, or turn it into a documented, tested limitation. Remove challan.html.

### [major] Seed only fictional records; show greetings and counts only when fixtures support them (A, C)
- Source: briefing s18; commercial s1 seed; agents s18; frontend s18; platform s15
- Owner: briefing
- Problem: The fixtures contradict each other:
- Nordhaus Interiors vs Nordhaus Möbel; Maison Atelier vs Maison Clair.
- Product LK-OT-0450 vs LK-TRAY-OAK-M.
- The prior quote LK-QT-2026-0003 exists only in agents.
- Frontend makes Ravi a restricted sales user, but briefing makes him operations with company-wide quote read.
- Clocks of 03:25Z vs 03:30Z.
- Due label 'Today 18:30' vs 'Today, 5:00 PM'.
- Resolution: Build one canonical world in backend/app/seed/world.py, documented in docs/architecture/fixtures.md and created through real services.
- Adopt the briefing s18 names.
- Add the prior won Nordhaus quote (240 x EUR 24) and a standard EUR export list.
- Use Kabir and Neha as the restricted and peer personas.
- Freeze the clock at 2026-10-12T03:25Z.
- Tests reference fixture constants, not literals.

### [major] Each slice completes an end-to-end workflow; voice in slice 3
- Source: build_order; briefing s19 slice 1; commercial s12; frontend Today voice parts in S3
- Owner: briefing
- Problem: Briefing slice 1 includes families whose producers arrive later (enquiries, price impact, access requests) and includes voice pins and narration, while the voice UI is in S3.
- Resolution: - Slice 1: common, quote_review, quote_expiry, approvals, customer_changes, enquiries/replies and onboarding families, plus the server pin model and the 'N updates' control with no reordering.
- Slice 2: price impact, access, samples, returnables, cut plans, imports and completeness.
- Slice 3: Listen to my day, text-to-speech and WhatsApp.
Adjust the B tests to match.

### [major] Sales covers samples; sample delivery in the briefing; sample lineage
- Source: build prompt <product_contract>, build_order 5; briefing s4 sales.sample.*; commercial spec revision fields
- Owner: commercial
- Problem: There is no sample entity. A challan being issued is not the same as delivered.
- Resolution: Add sales_sample: SMP-YYYY-NNNN; party; lines; status requested|dispatched|delivered|feedback_received|closed; challan link; delivered_at with evidence; feedback; links to spec revision and quote/order. Events sales.sample.{dispatched,delivered,feedback_recorded}. Slice 2, with lineage in slice 5.

### [major] Flow reservation -> production/picking -> delivery/challan
- Source: build prompt <connected_erp_scope>; concept 'pick lists'; operations s2-s4
- Owner: operations
- Problem: There is no pick list or pick confirmation step.
- Resolution: Add inv_pick_lists, generated from reserved demand: lines with lot, location, qty to pick and qty picked; statuses draft|released|picking|picked|cancelled. Confirming a pick fills the draft challan lines; any optional staging is a bin relocation only, never a second outbound movement. Slice 4.

### [major] Management briefing shows margin exceptions
- Source: build prompt <daily_briefing>; briefing s4 sales.quote.margin_below_threshold (slice 4); commercial margin view (slice 5)
- Owner: commercial
- Problem: Nothing defines margin computation, a threshold policy or the event.
- Resolution: Calculate restricted margin per line and header from product_cost (with a cost_complete flag). Add a commercial.margin_policy setting with thresholds per currency. Emit the event on review request or issue. Slice 5 for both commercial and briefing.

### [minor] Every view reachable directly; deep links work
- Source: frontend s4 route manifest vs catalogue, commercial, briefing, operations and agents route lists
- Owner: frontend_verification
- Problem: Routes conflict across designs:
- products/[productKey] vs [productId]
- /sales/quotes/[id]/print vs /print/quotes/[id]
- inbox/[taskId] vs /inbox/tasks/[taskId]
- operations and settings routes that are missing from the manifest
- Resolution: The lib/routes.ts manifest is authoritative. Slice 0 merges all module route lists into it, using UUID detail routes plus /go/[type]/[key].

### [minor] Typed briefing contract
- Source: frontend s8 top_item_ids/is_fallback//poll; briefing s16 initial_item_ids/status=fallback/today/status
- Owner: frontend_verification
- Problem: Field names and the polling endpoint differ between frontend and briefing.
- Resolution: Use only generated types with the briefing field names. /poll aggregates the briefing status and inbox counts, or is dropped. Item routes are keyed by issue_id.

### [minor] Optimistic concurrency; understandable errors
- Source: platform body version; frontend expected_version and 412 proposal_stale; briefing If-Match and UPPERCASE codes
- Owner: platform
- Problem: How versions are sent, error-code casing and HTTP status for conflicts all differ between designs.
- Resolution: Send expected_version in the request body. Use lowercase problem codes from a central ErrorCode enum exported in OpenAPI. Status codes: 409 for conflicts, 410 for ended pins, 422 for validation. Idempotency-Key always travels as a header.

### [minor] Expose provider usage and latency to administrators
- Source: platform ai_usage_event (stores cost) vs agents ai_call_log (cost computed at report time)
- Owner: agent_voice_whatsapp
- Problem: Usage is logged to two tables with two endpoints.
- Resolution: Agents owns a single ai_call_log; drop the platform table and endpoint. Compute cost from a price table at report time. Briefing phrasing uses the agents provider adapter.

### [minor] Exactly-once handling of duplicate events (I)
- Source: platform fenced jobs; operations processed_events; briefing event_consumptions
- Owner: platform
- Problem: Three deduplication mechanisms with two table names.
- Resolution: Keep platform fencing, plus one event_consumption table with a consumers.once() helper; remove the module-specific tables.

### [minor] Clearing sample data only in an isolated demo dataset
- Source: platform demo.data.reset; catalogue catalogue.demo_reset relying on undefined purge hooks
- Owner: platform
- Problem: Two reset features, and the per-module purge hooks they depend on are undefined.
- Resolution: Add a DemoPurgeHook registry. One endpoint under permission demo.data.reset, requiring a preview token, a typed phrase and MFA. Every hook asserts the company is_demo; catalogue's reset becomes its hook.

### [minor] Deterministic tests and a restore rehearsal (M)
- Source: platform, operations, frontend and catalogue test fixtures; APP_ENV vs LK_ENV; briefing _test router vs frontend testsupport
- Owner: platform
- Problem: The test database, clock and test-support plumbing are designed several times over.
- Resolution: Platform owns:
- conftest.py: pgserver, a template database per test, tests run as lk_app.
- An injectable Clock with a per-tenant override.
- One testsupport router, mounted only when LK_ENV=test.
- One restore-rehearsal test.

### [minor] Noisy environments get photos, scanning and structured confirmation
- Source: build prompt <voice_and_whatsapp>; agents future OCR
- Owner: frontend_verification
- Problem: Scanning is not designed anywhere.
- Resolution: S3: attach photos from the composer. S4: camera barcode scanning with a manual-entry fallback on warehouse screens. Structured confirmation uses ReadbackCard. OCR goes to future scope.

### [minor] Deliver a provider configuration guide
- Source: build prompt <finish_contract>
- Owner: agent_voice_whatsapp
- Problem: No design owns this deliverable.
- Resolution: Write docs/PROVIDERS.md covering Anthropic, STT/TTS, WhatsApp, S3, SMTP and accounting: env vars, verification steps, demo vs live, and what 'connected' requires.

### [minor] Marked sent vs actual delivery; follow-up drafts
- Source: commercial quote_dispatch method email; briefing 'follow-up message draft' preparer
- Owner: agent_voice_whatsapp
- Problem: No outbound email adapter or message-draft entity exists.
- Resolution: Add a channels email adapter (demo writes .eml; live uses SMTP) and a message_draft entity. Sending is an approved proposal. Hide the Prepare follow-up action until this exists (slice 3).

### [minor] Challan destinations: Fabricator, Transporter, Vendor, Office
- Source: spec 5.8; commercial party flags; operations movement policy
- Owner: commercial
- Problem: Parties have only customer and vendor flags.
- Resolution: Add a party_role set {customer, vendor, fabricator, transporter, job_worker}. Office destinations map to branch/office locations, not parties.

### [minor] Legacy challans keep document-only history
- Source: operations movement policy returns 422 for invalid combinations; spec 5.8
- Owner: operations
- Problem: The movement policy could reject combinations that were valid in legacy data.
- Resolution: Enforce the type/destination matrix only when inventory_effect=posting. Document-only challans and migration accept legacy combinations with a warning.

### [minor] Company isolation with composite foreign keys
- Source: platform s2 tenant FKs and RLS exemptions; catalogue/commercial composite FKs without company_id
- Owner: platform
- Problem: New global tables are not on the RLS exemption list, and module composite FKs omit company_id.
- Resolution: tenant_table() generates (company_id, ...) composite FKs automatically. Add an architecture test: every table is either tenant-scoped with RLS or explicitly exempt.

### [minor] Shared unit of work; no raw SQL sessions in modules
- Source: operations post_movement(session), numbering.next(session); platform architecture tests
- Owner: operations
- Problem: Operations passes raw SQLAlchemy sessions, which the platform architecture tests forbid.
- Resolution: Use uow handles (repo, lock, numbering.allocate). Simulation runs in uow.read_only(), which raises on flush.

### [minor] Readiness/health
- Source: agents 'readiness reports ai: misconfigured'
- Owner: agent_voice_whatsapp
- Problem: A missing optional AI key would make /health/ready return 503 and take the app down.
- Resolution: Report AI configuration in /system/status and integration_status; readiness covers only the database, migrations and storage.

### [minor] Retain product stats, recent products, completeness and activity
- Source: spec 8.3 Dashboard; frontend route map
- Owner: frontend_verification
- Problem: No screen is designated to replace the legacy dashboard.
- Resolution: The parity matrix maps the dashboard to: the /products home (stats, recent products, completeness link, category filters, with no KPI-card wall), the challan summary, and /activity, each with tests.

### [minor] New roles inherit role templates
- Source: briefing briefings_role_templates keyed by role_id
- Owner: briefing
- Problem: No rule says which briefing template applies to a user with several roles.
- Resolution: Merge the templates for all of a user's roles: union of families, weights bounded by policy, and overview template from the highest-priority role. Make the rule deterministic and tested.

### [minor] Offcut reuse in slice 5
- Source: operations cutting in slice 2 already uses offcut lots
- Owner: operations
- Problem: The slice-2 cutting design depends on lots that only arrive in slice 4.
- Resolution: Slice 2 uses standard boards only; board lots come in slice 4 and offcut reuse in slice 5.

### [minor] Bulk loads must not flood briefings
- Source: catalogue s11 events flagged for briefings; briefing consumer
- Owner: briefing
- Problem: Briefing rules don't skip migration or bulk-import events.
- Resolution: The event envelope carries origin. Rules skip origin=migration, and each import job produces one grouped issue.

### [minor] Typed agent tools named in the prompt
- Source: agents tool catalogue vs commercial, operations and catalogue tool names
- Owner: agent_voice_whatsapp
- Problem: Tool names differ between designs (find_usual_order vs find_repeat_quote_basis, and others).
- Resolution: Domain tools.py names are canonical. The tool names the prompt requires are kept, as aliases where they differ.

### [minor] Money as an amount with its currency
- Source: platform core/types Money; commercial core/money.py and currency table
- Owner: platform
- Problem: Money types and currency metadata are defined twice.
- Resolution: One core/money.py. A global currency reference table, exempt from RLS. Per-company enabled currencies in settings.

### [minor] Avoid continuous costly processing
- Source: agents automation dispatcher consumes all events
- Owner: agent_voice_whatsapp
- Problem: The dispatcher would create one job per event.
- Resolution: Subscribe only to event types referenced by active automations, and check quotas before enqueueing.

### [minor] Notification schedule preference
- Source: briefing web_notifications preference; frontend push listed as future
- Owner: briefing
- Problem: The preference has no delivery mechanism.
- Resolution: V1 uses Inbox counts plus an optional in-tab browser Notification, or removes the preference until push exists.

### [minor] Replaceable STT/TTS; browser speech is not the only production dependency
- Source: agents s14 vendor 'pending choice'
- Owner: agent_voice_whatsapp
- Problem: With no server vendor chosen, this requirement can't be verified.
- Resolution: Choose one vendor adapter in slice 3, with contract tests against recorded fixtures. Hindi and Hinglish stay labelled Untested. Record the vendor choice as blocked on credentials and business choice.

### [minor] Legacy section visibility (pricing tab, packaging and specs)
- Source: spec 8.1 canViewSection
- Owner: catalogue_imports_migration
- Problem: No design decides which sections sales users can see.
- Resolution: Record in the parity matrix:
- Specs and packaging require catalogue.product.read.
- Base/add-on prices and yield require pricing.price_list.read.
- Costing requires pricing.cost.read.
Cover these in the route matrix tests.

## Recommended slice plan

## Recommended slice plan (aligned to build_order 0-6)

Rules for every slice:
- Each slice ends with:
  - updated D:\Lamikraft ERP\docs\BUILD_STATE.md and PARITY_MATRIX.md rows (implemented, test id, evidence);
  - desktop and phone screenshots inspected;
  - route-matrix and canary tests green for every route added.
- No navigation entry for unbuilt screens.
- Registries (permissions, events, sequences, routes, fixtures) are the only source of names; startup validation fails on drift.

### Slice 0: Contracts and environment (build_order 0)
**Contents**
- docs/architecture/permissions.md: the canonical catalogue in platform grammar, the legacy_alias union mapping, and template grants (legacy table 3.2 exact).
- docs/architecture/events.md: EventDef registry, including the producer events added by the findings.
- docs/architecture/api-conventions.md:
  - /api/v1 prefix and LK_API_INTERNAL_URL;
  - body expected_version, Idempotency-Key header, problem+json codes;
  - capabilities field;
  - Page and cursor shapes;
  - money and quantity JSON.
- docs/architecture/fixtures.md: the canonical world, frozen clock 2026-10-12T03:25Z, and personas (Meera, Neha, Sahil, Ravi, Kabir, Arjun, Ananya, Priya).
- docs/architecture/ownership.md:
  - storage owned by platform files;
  - calendar and delegation in platform;
  - approvals as the single engine;
  - notes, search, relations and preferences in platform;
  - apps/web owned by frontend.
- DECISIONS entries:
  - quote sequence reset (yearly);
  - delegation semantics;
  - approval defaults;
  - decor canonicalisation;
  - PDF engine;
  - TypeScript 5.9 pin.
- PARITY_MATRIX skeleton: every row from spec sections 3, 4.1-4.16, 5.1-5.9, 6, 8.2-8.3, 10.1 #1-16 and 10.2 #1-8 mapped to an owner, slice and planned test.
- Machine probes, recorded in DECISIONS:
  - pgserver start, PG version, pg_trgm and btree_gist availability;
  - pg_dump and pg_restore presence;
  - uv sync on Python 3.12;
  - Playwright browsers on Windows.
- Monorepo skeleton:
  - registry with startup cross-validation, architecture tests;
  - conftest.py (pgserver template DB, lk_app role, RLS on);
  - injectable Clock, testsupport router (LK_ENV=test only);
  - lib/routes.ts manifest merged from all designs.

**Exit criteria**
- npm run setup and npm run dev work on the pgserver path with Docker stopped.
- /api/v1/health/live and /api/v1/health/ready return 200.
- npm run check is green.
- Negative tests prove that an unknown permission, event or route declaration stops startup.
- Probe results are documented.

### Slice 1: Shell, identity/authz, tasks/briefing, quote vertical path by text (build_order 1)
**Contents**
- **Platform:**
  - core (money, Quantity, csvsafe, ids, Clock), RLS with composite FKs, UoW/@command, outbox, jobs, scheduler, event_consumption, idempotency;
  - identity (login, sessions, CSRF, lockout, TOTP for privileged users, invitations with manual link, reset, profile, deactivation), first-admin CLI;
  - authz kernel with the full catalogue, ScopedRepository, field-guard registry;
  - numbering (quote, enquiry, party), settings (company, documents, calendar);
  - org calendar with work_date rollover, single delegation and absence model, UOM master;
  - files (local backend), notes, activity, relations, link resolver;
  - search framework and recent searches, user_preference, integration_status;
  - audit, logging, health, demo world seed.
- **Catalogue:** all tables (including stock attribute columns), normalise.py, list and detail with pagination before limit, resolve_product, seed.
- **Commercial:**
  - money engine and rule set v1, minimal parties, enquiries and customer messages (manual logging);
  - seeded price lists with Pass A resolution and the item supersede needed by fixtures;
  - quotes: header, catalog and manual lines, snapshots, numbering, concurrency;
  - list (mine/all), review via approvals, mark_sent, cancel, draft delete;
  - issued revision, PDF and print, status_changed and owner_changed events;
  - slice-1 agent tools.
- **Approvals core and agents shell:**
  - proposals, decisions, ApprovalTarget for quote review, action_ref, receipts, expiry;
  - ToolContext wrapping ActorContext, registry, Demo provider, orchestrator, grounding, redaction, cards, SSE by polling.
- **Briefing:**
  - tasks core (issues, tasks, candidates, change log, reminders, history), queues and responsibility rules;
  - rule consumer, overdue sweep, ResourcePolicies, scope-consistency job;
  - engine and snapshots, acknowledgements, snooze, actions (open, review, approve, reject, assign, snooze, mark handled, explain), fallback, templates, policy;
  - families: common, quote_review, quote_expiry, approvals, customer_changes, enquiries and replies, onboarding;
  - server pins with no-reorder 'N updates'.
- **Frontend:**
  - shell (sidebar, rail, phone bottom nav), auth pages using fragment tokens, session/bootstrap;
  - Today (composer text path, QuoteDraftCard, ProposalCard), Inbox (tasks, approvals), search dialog;
  - product read, party minimum, quote workspace (configurator drawer, lines, summary, review, preview/PDF);
  - notes, profile and preferences, design tokens, axe and visual capture.

**Exit criteria**
- **Scenario A** green for web and text: A-01 to A-15 integration tests plus e2e for Meera, Sahil and the restricted persona Kabir, and the canary leak test.
- **Scenario C** green through the Demo assistant, via both integration and e2e: 240 x EUR 24.0000 = EUR 5,760.00, draft, scoped review task, snapshot unchanged after supersede.
- **Scenario D** green on API, PDF and print. List CSV may wait for slice 2, but the totals engine is shared.
- **Scenario F** subset:
  - IDOR on all slice-1 quote sub-endpoints;
  - permission revoked after proposal blocks execution;
  - changed content invalidates approval;
  - 50 concurrent quote numbers.
- **Scenario B** subset: B-01 to B-04, B-08 to B-10, B-12 and B-14 to B-18.
- **Scenario N** baseline: three viewports, keyboard journey, touch targets, axe, no dead controls on S1 routes.
- **Platform invariant suites** green: RLS, login, session/CSRF, MFA, audit append-only, outbox exactly-once, job queue, idempotency.

### Slice 2: Complete legacy parity (build_order 2)
**Contents**
- **Catalogue:** forms, archive, taxonomy operations, media on platform files, facets, stats, recent, completeness, lookups, export; the import workbench for all seven types with rollback and quarantine recheck; demo reset hook.
- **Commercial:**
  - full parties with roles;
  - price lists (create, activate, retire, supersede, history), the pricing import contract, product_cost;
  - FX with approval, Pass B and currency change;
  - full status machine, extend_validity, compare/restore, duplicate, custom lines, full configurator, CSVs, settings;
  - custom products including promotion via approvals, samples (manual delivery);
  - search and completeness providers; Devanagari PDF verification.
- **Operations:** cutting optimiser (standard boards, grain locks using canonical decor, guillotine and nested modes, saved plans, exports); document-mode challans with movement policy only when posting.
- **Platform:** custom roles, overrides UI, role simulator, access requests, jobs console, S3 adapter with moto.
- **Agents:** parity tools (revise, duplicate, search_records, product details, price-change proposals, optimise_cut_plan, draft_challan, draft undo).
- **Briefing:** price impact, admin.access, samples, returnables, cut plans, failed imports, completeness, Inbox CSV.
- **Frontend:** all S2 screens, with routes reconciled.

**Exit criteria**
- Scenarios E, F (complete), G, H and L green.
- A named regression test for each of bugs 10.1 #1-16.
- Route-matrix coverage of 10.2 #1-8 across every legacy module.
- Every legacy page in spec 8.2 has a replacement route with a test.
- Parity matrix: all legacy rows implemented and tested.

### Slice 3: Agent runtime, voice, WhatsApp sandbox (build_order 3)
**Contents**
- Anthropic adapter (strict schema export, contract fixtures), circuit breaker, ai_call_log, memory, automations (scoped subscriptions), taint tracking.
- Voice:
  - STT and TTS vendor adapters plus demo, push-to-talk, transcript edit, read-back;
  - Listen to my day on briefing pins, with pin-first ordinal resolution in the agent pre-route.
- WhatsApp (demo and live adapter):
  - webhook route kind, enrolment, consent, window and templates, outbound reconciliation, review links;
  - generalised action_ref for briefing acknowledgement and snooze, summary job;
  - email adapter and message drafts, prepare_quote_send.
- LLM phrasing and Explain for briefings; Hindi and Hinglish labelled Untested; PROVIDERS.md.

**Exit criteria**
- Scenario B complete: voice pin with no reorder, WhatsApp snooze/acknowledgement synchronisation, AI outage fallback.
- Scenario C via voice, WhatsApp text and voice note, with identical results.
- Scenarios J and K green, plus the injection taint test.
- Settings shows Demo / Not connected; no live outbound messages; one trace per request.

### Slice 4: Connected operations (build_order 4)
**Contents**
- **Operations:**
  - warehouses, locations, lots, ledger, summaries, reservations; counts, adjustments, transfers, reversals as ApprovalTargets;
  - opening_stock import definition and batch approval;
  - sales order conversion, pick lists, challan posting policies with go-live switch;
  - procurement (shortage state and events), production (BOM, routing, WO, QC, capacity from org calendar, cost versions), cut-plan links and board lots;
  - logistics (shipments with cutoff_at, packing, load suggestion); caused_by links.
- **Catalogue:** stock attributes required; packaging snapshot service.
- **Commercial:** won-to-order handoff, correction guard, sample-to-challan and shipment links.
- **Briefing:** operations families with root-cause grouping; management cross-team blockers.
- **Agents:** operations tools and executors.
- **Platform:** branch and team scopes, operations sequences.
- **Frontend:** operations screens, scan input.

**Exit criteria**
- Scenario I end to end.
- Ledger stateful property tests and reservation concurrency (no oversell) pass.
- Duplicate-event replay causes no second effect.
- Slice-4 fixture additions produce the expected grouped operations issues.
- Isolation and canary tests extended to operations routes and tools.

### Slice 5: Finance, migration, backup, planning (build_order 5)
**Contents**
- **Finance:** invoices and credit notes (numbered at issue, financial-year policy), issue gate, receipts, allocations, ageing, CSV and demo accounting adapter, provider gates through integration_status.
- **Briefing:** finance families and management financial visibility.
- **Commercial:** margin with policy and event.
- **Migration:**
  - dry-run, apply and rerun; historical persons and pending-invitation users;
  - commercial and operations legacy_import_* adapters, party review, media ingest;
  - sequences reconcile, reconciliation report, runbook.
- **Platform:** backup create, restore rehearsal schedules, retention.
- **Operations:** offcut library reuse, what-if (read-only uow), sample lineage view.

**Exit criteria**
- Scenario M green:
  - counts and totals per currency reconcile;
  - rerun yields 0 inserts and 0 updates;
  - no stock from legacy challans;
  - restore rehearsal passes on this machine.
- Finance invariant tests pass; Ananya's briefing is non-empty and redacted correctly.
- Offcut-reuse property tests and the what-if write-guard test pass.

### Slice 6: Acceptance and isolation sweep (build_order 6)
**Contents**
- Full A-N matrix at desktop, tablet and phone.
- Canary sweep across every route, tool, export, search, briefing, WhatsApp render and captured log.
- axe on every manifest route in both themes; dead-control crawl.
- pip-audit and npm audit triage; header and CSP checks; screenshot review and fixes.
- Final docs, an exact remaining-work list, and a list of integrations blocked on credentials or business policy:
  - WhatsApp live;
  - STT/TTS vendor;
  - Anthropic key with DPDP approval;
  - accounting system;
  - GST, e-invoice and e-way bill;
  - approval rules for overrides and below-minimum quotes.

**Exit criteria**
- All A-N tests green and recorded in BUILD_STATE.
- Parity matrix 100% with test evidence.
- No open blocker or major finding.
- Future scope listed honestly (HR, payroll, native general ledger, SSO, push transport, OCR).

### Critical files for implementation
- D:\Lamikraft ERP\OPUS_5_5_BUILD_PROMPT.md (authoritative requirements)
- D:\Lamikraft ERP\CURRENT_STATE_SPEC.md (legacy fields, sections 3, 4, 5, 8 and 10)
- D:\Lamikraft ERP\docs\architecture\permissions.md (to be created in slice 0: canonical permission catalogue and legacy aliases)
- D:\Lamikraft ERP\docs\architecture\events.md (to be created in slice 0: event registry)
- D:\Lamikraft ERP\backend\app\registry.py (to be created: startup cross-validation of permissions, events, routes and sequences)
