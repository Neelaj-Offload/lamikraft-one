# Permissions

Status: frozen in Slice 0. Implements `docs/PLAN.md` canonical contracts 3 (tenancy and authorization) and 4
(permissions). Code anchors: `backend/app/platform/authz/{permissions,context,policy,repository,redaction}.py`,
`backend/app/registry.py`, `backend/app/core/http/authz_decl.py`.

This file is the **only** permission vocabulary. Every key referenced in a `policies.py`, `TEMPLATE_GRANTS`,
`tools.py`, `SettingDef`, route declaration, approval policy or test must appear here; the registry rejects unknown
keys at startup and `backend/tests/contract/test_permissions_catalogue.py` compares the registry with this file.

---

## 1. Grammar

```
<module>.<resource>.<action>      e.g. sales.quote.read, pricing.cost.read, inventory.stock.reserve
```

- `module` is the backend package name ([conventions.md](conventions.md) §2), so it equals the event module and the
  API route segment.
- `resource` is snake_case and singular. **Restricted data is its own resource** (`pricing.cost.read`,
  `pricing.price_list.read`, `org.bank_account.read`) and is enforced by the field-guard registry (§5).
- `action` comes from the closed verb set (§2). Regex: `^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`.

## 2. Verb set

Core verbs (PLAN contract 4): `read`, `create`, `update`, `archive`, `delete`, `transition`, `approve`, `export`,
`manage`, `run`, `execute`, `post`, `issue`.

Domain verbs (implemented in `VERBS` in `app/platform/authz/permissions.py`; extension recorded as ADR-011):
`use`, `assign`, `override`, `send`, `reverse`, `decide`, `dismiss`, `import`, `correct`, `promote`, `reserve`,
`receive`. A domain verb is used only where a core verb would mislead (an owner change is `assign`, not `update`;
outbound delivery is `send`, while marking a quote sent and creating its issued revision is `issue`). New verbs need
an ADR and a change to `VERBS`.

| Verb | Meaning |
|---|---|
| read | view records (detail, list, search, children through the parent) |
| create | create new records (company scope; the creator becomes owner unless stated) |
| update | edit working copies, drafts and editable fields |
| archive | archive / unarchive (soft, reversible) |
| delete | soft-delete drafts that never became documents (numbers are never reused) |
| transition | ordinary state-machine actions of the resource |
| approve | decide approvals (eligibility; separation of duties enforced by approvals) |
| export | PDF, print, CSV and other files leaving the system (rows bounded by read scope) |
| manage | administer configuration of the resource type |
| run | start a computation or job (imports, calculations, dry runs, exports to adapters) |
| execute | perform a prepared, approved or irreversible operation |
| post | write immutable ledger postings (stock movements) |
| issue | issue a numbered document or revision to an external party |
| use | use a capability (search, assistant, speech) |
| assign | change owner or assignee |
| override | override a computed default (price) |
| send | deliver through an external channel |
| reverse | create a compensating reversal of a posted record |
| decide | reserved (not used in the catalogue below) |
| dismiss | close an obligation with an authorised reason |
| import | reserved (not used; imports use `run`) |
| correct | lawful correction transitions that need a reason |
| promote | request promotion of a custom product to the master catalogue |
| reserve | reserve stock |
| receive | receive goods outside a purchase order |

## 3. Scopes

`own < team < branch < company` (`Scope` IntEnum). Columns `R` below mean all four scopes are allowed; `C` means
company only. Non-record permissions (configuration, create, run, use) are company-only.

| Scope | Predicate (from `scope_clause`) |
|---|---|
| own | an owner column (`owner_user_id`, `assignee_user_id`, `initiator_user_id` per policy) equals the actor, or is a delegator for that key |
| team | an owner column is in the actor's team peers (or own/delegated) |
| branch | the record's branch column is in the actor's branches (or own/delegated); resources without a branch column treat branch as company |
| company | every record of the company (always `company_id = ctx.company_id`, backed by RLS) |

- Child objects (lines, revisions, status history, documents, dispatches, costing rows, spec revisions) are
  authorised **only through their parent** (`ParentRef`). Polymorphic children (notes, attachments, activity,
  history) are authorised by the parent's visibility; note writes need the parent's `update`.
- A record that is not visible returns **404**; a visible record with a forbidden action returns **403**.
- Aggregates, counts, facets and search group totals are computed only over scoped selects.

## 4. Route kinds and self-service

Every route declares `public`, `authenticated`, `permission`, `webhook` or `test_support`
([api-conventions.md](api-conventions.md) §2). Self-service needs no permission key (`authenticated` routes):
own profile, password, sessions, MFA enrolment, UI and briefing preferences, personal reminders, personal memory,
own delegations (as delegator), own leave requests, own access requests, WhatsApp enrolment and revocation of own
links. This keeps the employee base free of `identity.*` keys.

## 5. Field guards (restricted data)

One registry: `Restricted(guard_key, model_exposure="deny"|"allow", log="drop")`. DTO fields annotated with a guard
are nulled (and listed in `redacted_fields`) for actors without the guard key, and the same registry drives the
structlog processor, CSV exporter, notification renderers, briefing fact schemas and agent model context.

| Guard key | Guards | Model exposure |
|---|---|---|
| `pricing.cost.read` | `pricing_product_cost.*`, `sales_custom_product_costing.*`, production cost inputs, rollups and versions, margin fields on quotes and invoices, informational `unit_cost` on stock movements | deny (never sent to a provider, even for permitted users) |
| `pricing.price_list.read` | price-list item `base_price`(+label), `addon_price`(+label), `yield_qty_per_board`, `price_basis`, `thickness_mm`, item provenance | allow |
| `org.bank_account.read` | company bank account numbers (masked to last 4 otherwise) | deny |

A canary test plants a sentinel in every guarded column and asserts it never appears for unauthorised actors in API
responses, search, exports, notifications, briefing inputs, WhatsApp renders, provider payloads or captured logs.

## 6. Flags

`D` delegable · `MFA` requires an MFA-verified session · `RA` requires recent authentication (10 min) ·
`FG` field guard · `S` sensitive (audited on use). Template abbreviations: `emp` employee base (included in every
template), `mgt` management, `sal` sales, `ops` operations, `fin` finance, `prd` production, `pro` procurement,
`whs` warehouse, `cat` catalogue. **`admin` holds every key at its maximum scope** and is not repeated below.
Scope letters after a template: O own, T team, B branch, C company.

## 7. Catalogue

### 7.1 Kernel: `org`, `identity`, `numbering`, `files`, `collab`, `search`, `audit`, `system`, `approvals`

| Key | Scopes | Flags | Legacy alias | Slice | Templates |
|---|---|---|---|---|---|
| `org.company.read` | C | | | 1 | emp |
| `org.company.update` | C | MFA RA S | | 1 (CLI/seed), 2 (UI) | — |
| `org.directory.read` | C | | | 1 | emp (name, title, team; no contact details) |
| `org.branch.manage` | C | MFA | | 2 | — |
| `org.team.manage` | C | | | 2 | — |
| `org.settings.read` | C | | | 1 | emp (non-sensitive keys only) |
| `org.settings.manage` | C | RA | | 1 | — |
| `org.bank_account.read` | C | FG S | | 2 | fin |
| `org.bank_account.update` | C | MFA RA S | | 2 | — |
| `org.uom.manage` | C | | | 2 | cat |
| `org.calendar.read` | C | | | 1 | emp |
| `org.calendar.manage` | C | | | 1 (seed), 2 (UI) | — |
| `identity.user.read` | C | | manage_users | 1 | — |
| `identity.user.manage` | C | MFA RA S | manage_users | 1 (CLI/API), 2 (invitations, UI) | — |
| `identity.role.read` | C | | manage_users | 1 | — |
| `identity.role.manage` | C | MFA RA S | manage_users | 1 (assign templates), 2 (custom roles) | — |
| `identity.permission.manage` | C | MFA RA S | manage_users | 1 (overrides API), 2 (UI) | — |
| `identity.session.manage` | C | MFA RA | | 2 | — |
| `identity.mfa.manage` | C | MFA RA S | | 2 | — |
| `identity.delegation.manage` | C | RA | | 2 | — |
| `identity.absence.approve` | C | | | 2 | — |
| `identity.access_request.approve` | C | MFA RA S | | 2 | — |
| `numbering.sequence.read` | C | | | 1 | — |
| `numbering.sequence.manage` | C | MFA RA S | | 1 (seed), 2 (UI) | — |
| `files.file.create` | C | | | 1 | emp (attaching still needs the parent's `update`) |
| `collab.activity.read` | C | | | 2 | emp (rows filtered by parent visibility) |
| `search.global.use` | C | | | 1 | emp |
| `audit.log.read` | C | MFA S | | 2 | — |
| `audit.trace.read` | C | MFA | | 3 | — (participants always see their own traces) |
| `system.status.read` | C | | | 1 | — |
| `system.job.read` | C | | | 2 | — |
| `system.job.manage` | C | RA | | 2 | — |
| `system.integration.read` | C | | | 3 | — |
| `system.integration.manage` | C | MFA RA | | 3 | — |
| `system.backup.read` | C | MFA | | 5 | — |
| `system.backup.manage` | C | MFA RA S | | 5 | — |
| `system.demo_data.delete` | C | MFA RA S | | 2 | — (refused unless `company.is_demo`) |
| `approvals.proposal.read` | O C | | | 1 | emp O (proposals you initiated or may decide), mgt C, fin C |
| `approvals.proposal.execute` | O C | RA | | 3 | emp O |
| `approvals.policy.read` | C | | | 1 | mgt |
| `approvals.policy.manage` | C | MFA RA S | | 1 (seed), 3 (levels, authorities, versions) | — |

### 7.2 `catalogue`, `imports`

| Key | Scopes | Flags | Legacy alias | Slice | Templates |
|---|---|---|---|---|---|
| `catalogue.product.read` | C | | view_products | 1 | mgt, sal, ops, fin, prd, pro, whs, cat |
| `catalogue.product.create` | C | | edit_products | 1 (declared), 2 | cat |
| `catalogue.product.update` | C | | edit_products | 1 (declared), 2 | cat |
| `catalogue.product.archive` | C | | edit_products | 1 (declared), 2 | cat |
| `catalogue.product.export` | C | | | 2 | mgt, cat |
| `catalogue.media.manage` | O C | | edit_products | 1 (declared), 2 | cat C (own = media you uploaded) |
| `catalogue.taxonomy.manage` | C | | manage_categories | 1 (declared), 2 | cat |
| `catalogue.lookup.read` | C | | | 2 | cat |
| `imports.job.read` | O C | | import_data | 1 (declared), 2 | cat C |
| `imports.job.run` | O C | | import_data | 1 (declared), 2 | cat C |
| `imports.rollback.execute` | O C | RA S | | 2 | cat C |

### 7.3 `pricing`, `commercial`, `parties`

| Key | Scopes | Flags | Legacy alias | Slice | Templates |
|---|---|---|---|---|---|
| `pricing.price.read` | C | | view_products | 1 | mgt, sal, ops, fin, cat (resolved final prices; no breakdown) |
| `pricing.price_list.read` | C | FG | view_costing | 1 | mgt, fin, cat |
| `pricing.price_list.manage` | C | | edit_products | 1 (declared), 2 | cat |
| `pricing.cost.read` | C | FG S | view_costing | 1 | mgt, fin, prd |
| `pricing.cost.update` | C | S | | 2 | fin, prd |
| `pricing.fx_rate.read` | C | | | 2 | mgt, sal, fin |
| `pricing.fx_rate.create` | C | | | 2 | mgt, fin |
| `pricing.fx_rate.approve` | C | S | | 2 | mgt, fin (never the proposer) |
| `pricing.fx_policy.manage` | C | MFA RA | | 2 | fin |
| `commercial.rule_set.read` | C | | | 1 | mgt, fin |
| `commercial.rule_set.manage` | C | MFA RA S | | 1 (seed), 2 (UI) | — |
| `commercial.margin_policy.manage` | C | MFA | | 5 | fin |
| `parties.party.read` | R | D | | 1 | sal O, mgt C, ops C, fin C, pro C, prd C |
| `parties.party.create` | C | | | 1 | sal, mgt, fin, pro |
| `parties.party.update` | R | D | | 1 | sal O, mgt C, fin C, pro C |
| `parties.party.archive` | R | | | 2 | mgt C |
| `parties.party.assign` | R | | | 2 | mgt C |
| `parties.party.export` | R | | | 2 | sal O, mgt C |
| `parties.customer_type.manage` | C | | | 2 | — |
| `parties.lead_source.manage` | C | | | 7 | mgt |
| `parties.activity.create` | R | D | | 7 | sal O, mgt C |

### 7.4 `sales`

| Key | Scopes | Flags | Legacy alias | Slice | Templates |
|---|---|---|---|---|---|
| `sales.quote.read` | R | D | view_all_quotes (C), view_own_quotes (O) | 1 | sal O, mgt C, ops C, fin C |
| `sales.quote.create` | C | | create_quotes | 1 | sal, mgt |
| `sales.quote.update` | R | D | edit_all_quotes (C), edit_own_quotes (O) | 1 | sal O, mgt C |
| `sales.quote.transition` | R | D | edit_all_quotes (C), edit_own_quotes (O) | 1 | sal O, mgt C |
| `sales.quote.issue` | R | D | edit_all_quotes (C), edit_own_quotes (O) | 1 | sal O, mgt C |
| `sales.quote.archive` | R | D | edit_all_quotes (C), edit_own_quotes (O) | 1 (declared), 2 | sal O, mgt C |
| `sales.quote.delete` | R | | delete_quotes | 1 | — (admin only; never-issued drafts only) |
| `sales.quote.export` | R | D | export_quotes | 1 | sal O, mgt C |
| `sales.quote.approve` | R | S | | 1 | mgt C |
| `sales.quote.correct` | R | S | | 1 (declared), 2 | mgt C (reason required) |
| `sales.quote.assign` | R | | | 1 (declared), 2 | mgt C |
| `sales.quote.send` | R | D | | 3 | sal O, mgt C |
| `sales.quote_price.override` | R | | override_price | 1 | sal O, mgt C (effective scope bounded by `sales.quote.update`) |
| `sales.quote_price.approve` | R | S | | 1 | mgt C (also waives the override reason, §10) |
| `sales.quote_settings.manage` | C | RA | | 1 (seed), 2 (UI) | — |
| `sales.enquiry.read` | R | D | | 1 | sal O, mgt C |
| `sales.enquiry.create` | C | | | 1 | sal, mgt |
| `sales.enquiry.update` | R | D | | 1 | sal O, mgt C |
| `sales.enquiry.assign` | R | | | 1 | mgt C |
| `sales.customer_message.read` | R | D | | 1 | sal O, mgt C |
| `sales.customer_message.create` | C | | | 1 | sal, mgt |
| `sales.customer_message.update` | R | D | | 1 | sal O, mgt C |
| `sales.custom_product.read` | R | D | | 2 | sal O, mgt C, ops C, prd C, cat C |
| `sales.custom_product.create` | C | | | 2 | sal, mgt |
| `sales.custom_product.update` | R | D | | 2 | sal O, mgt C |
| `sales.custom_product.transition` | R | D | | 2 | sal O, mgt C |
| `sales.custom_product.archive` | R | | | 2 | mgt C |
| `sales.custom_product.export` | R | | | 2 | sal O, mgt C |
| `sales.custom_product.promote` | R | | | 2 | mgt C |
| `sales.custom_product.approve` | C | S | | 2 | cat (executor also needs `catalogue.product.create`) |
| `sales.sample.read` | R | D | | 2 | sal O, mgt C, ops C |
| `sales.sample.create` | C | | | 2 | sal, mgt |
| `sales.sample.update` | R | D | | 2 | sal O, mgt C, ops C |
| `sales.sample.transition` | R | | | 2 | sal O, mgt C, ops C |
| `sales.proforma.read` | R | D | | 7 | sal O, mgt C, fin C |
| `sales.proforma.create` | C | | | 7 | sal, mgt |
| `sales.proforma.update` | R | | | 7 | sal O, mgt C |
| `sales.proforma.issue` | C | | | 7 | sal, mgt |
| `sales.proforma.reverse` | C | | | 7 | mgt (cancel an issued or draft PI) |
| `sales.proforma.import` | C | | | 7 | mgt (enter a PI issued before Lamikraft One) |

Every key that appears in the legacy alias table (§8) is declared in Slice 1 even when its feature ships in Slice 2,
so the legacy parity test holds from Slice 1. Modules without tables in Slice 1 (`imports`) ship a manifest containing
only their PermissionDefs.

### 7.5 `tasks`, `briefings`, `agents`, `voice`, `channels`

| Key | Scopes | Flags | Legacy alias | Slice | Templates |
|---|---|---|---|---|---|
| `tasks.task.read` | R | | | 1 | emp O, mgt C, ops B |
| `tasks.task.create` | C | | | 1 | emp (assignee must be able to view the linked record) |
| `tasks.task.update` | R | | | 1 | emp O, mgt C, ops B |
| `tasks.task.assign` | R | | | 1 | emp O, mgt C, ops B |
| `tasks.task.dismiss` | R | | | 1 | emp O, mgt C, ops B (reason required; undismissable kinds per policy) |
| `tasks.task.export` | R | | | 2 | emp O, mgt C, ops B |
| `tasks.queue.manage` | C | | | 1 (seed), 2 (UI) | — |
| `briefings.briefing.read` | O | | | 1 | emp O (no other scope exists: nobody reads another user's briefing) |
| `briefings.template.manage` | C | RA | | 1 (seed), 4 (editor) | — |
| `briefings.policy.manage` | C | MFA RA | | 1 (seed), 2 (UI) | — |
| `agents.assistant.use` | C | | | 1 | emp |
| `agents.memory.approve` | T C | | | 3 | mgt C |
| `agents.automation.manage` | O C | | | 3 | mgt O |
| `agents.ai_usage.read` | C | | | 3 | — |
| `agents.ai_routing.manage` | C | MFA RA S | | 3 | — |
| `voice.speech.use` | C | | | 3 | emp |
| `channels.identity.manage` | C | RA | | 3 | — |
| `channels.account.manage` | C | MFA RA S | | 3 | — |
| `channels.message.read` | R | D | | 3 | sal O, mgt C |
| `channels.message.send` | R | | | 3 | sal O, mgt C (only through approved proposals) |
| `channels.consent.update` | R | | | 3 | sal O, mgt C |
| `channels.outbox.manage` | C | RA | | 3 | — |

### 7.6 `challans`, `cutting`

| Key | Scopes | Flags | Legacy alias | Slice | Templates |
|---|---|---|---|---|---|
| `challans.challan.read` | R | D | | 2 | ops B, mgt C, fin C, sal O |
| `challans.challan.create` | C | | | 2 | ops, sal |
| `challans.challan.update` | R | D | | 2 | ops B, sal O |
| `challans.challan.issue` | R | | | 2 | ops B |
| `challans.challan.transition` | R | | | 2 | ops B (close, cancel draft) |
| `challans.challan.reverse` | R | RA | | 2 (document-only cancel of issued), 4 (reversal posting) | ops B |
| `challans.challan.delete` | R | | | 2 | — (admin only; drafts only) |
| `challans.challan.export` | R | | | 2 | ops B, mgt C, fin C, sal O |
| `challans.write_off.approve` | C | S | | 4 | mgt |
| `cutting.calculation.run` | C | | | 2 | sal, ops, mgt, prd |
| `cutting.plan.read` | R | | | 2 | sal O, ops B, mgt C, prd C |
| `cutting.plan.create` | C | | | 2 | sal, ops, prd |
| `cutting.plan.update` | R | | | 2 | sal O, ops B, prd C |
| `cutting.plan.transition` | R | | | 2 (verify, archive), 4 (release) | ops B, prd C |
| `cutting.plan.export` | R | | | 2 | sal O, ops B, mgt C, prd C |
| `cutting.grain_lock.manage` | C | | | 2 | prd |
| `cutting.settings.manage` | C | | | 2 | prd |

### 7.7 `orders`, `inventory`, `quality`, `procurement`, `production`, `logistics`

| Key | Scopes | Flags | Legacy alias | Slice | Templates |
|---|---|---|---|---|---|
| `orders.sales_order.read` | R | D | | 4 | sal O, mgt C, ops B, fin C, prd B |
| `orders.sales_order.create` | C | | | 4 | sal, mgt |
| `orders.sales_order.update` | R | | | 4 | sal O, mgt C, ops B |
| `orders.sales_order.transition` | R | | | 4 | sal O, mgt C, ops B |
| `inventory.stock.read` | R | | | 4 | ops B, mgt C, sal C, fin C, prd B, pro C, whs B |
| `inventory.warehouse.manage` | C | | | 4 | — |
| `inventory.lot.manage` | R | | | 4 | ops B, prd B |
| `inventory.stock.post` | R | | | 4 | ops B, prd B |
| `inventory.stock.reserve` | R | | | 4 | sal O, ops B, prd B |
| `inventory.stock.receive` | R | RA | | 4 | ops B (receipts without a purchase order) |
| `inventory.posting.reverse` | R | RA S | | 4 | ops B |
| `inventory.adjustment.create` | R | | | 4 | ops B |
| `inventory.adjustment.approve` | R | S | | 4 | ops B, mgt C |
| `inventory.stock_count.create` | R | | | 4 | ops B, whs B |
| `inventory.stock_count.approve` | R | | | 4 | ops B |
| `inventory.opening_batch.create` | C | RA | | 4 | ops |
| `inventory.opening_batch.approve` | C | MFA RA S | | 4 | mgt (never the creator) |
| `inventory.pick_list.create` | R | | | 4 | ops B |
| `inventory.pick_list.update` | R | | | 4 | ops B, whs B |
| `inventory.reorder_rule.manage` | C | | | 4 | pro |
| `quality.inspection.read` | R | | | 4 | ops B, prd B, pro C |
| `quality.inspection.create` | R | | | 4 | ops B, prd B |
| `procurement.vendor_item.read` | C | | | 4 | pro, fin |
| `procurement.vendor_item.manage` | C | | | 4 | pro |
| `procurement.requisition.read` | R | | | 4 | pro C, ops B, prd B |
| `procurement.requisition.create` | C | | | 4 | pro, ops, prd |
| `procurement.requisition.update` | R | | | 4 | pro C, ops B, prd B |
| `procurement.requisition.approve` | R | S | | 4 | pro C, mgt C |
| `procurement.purchase_order.read` | R | | | 4 | pro C, ops B, fin C, mgt C |
| `procurement.purchase_order.create` | C | | | 4 | pro |
| `procurement.purchase_order.update` | R | | | 4 | pro C |
| `procurement.purchase_order.approve` | R | S | | 4 | mgt C |
| `procurement.purchase_order.issue` | R | | | 4 | pro C |
| `procurement.purchase_order.transition` | R | | | 4 | pro C |
| `procurement.goods_receipt.read` | R | | | 4 | pro C, ops B, fin C |
| `procurement.goods_receipt.post` | R | | | 4 | ops B |
| `procurement.vendor_bill.read` | C | | | 4 | fin, pro |
| `procurement.vendor_bill.create` | C | | | 4 | fin |
| `production.bom.read` | C | | | 4 | prd, ops, mgt |
| `production.bom.manage` | C | | | 4 | prd |
| `production.bom.approve` | C | S | | 4 | prd, mgt (never the author) |
| `production.routing.read` | C | | | 4 | prd, ops, mgt |
| `production.routing.manage` | C | | | 4 | prd |
| `production.routing.approve` | C | S | | 4 | prd, mgt |
| `production.work_center.manage` | C | | | 4 | prd |
| `production.work_order.read` | R | | | 4 | prd C, ops B, mgt C |
| `production.work_order.create` | C | | | 4 | prd |
| `production.work_order.update` | R | | | 4 | prd C |
| `production.work_order.transition` | R | | | 4 | prd C, ops B |
| `production.work_order.post` | R | | | 4 | prd C, ops B |
| `production.capacity.read` | C | | | 4 | prd, ops, mgt |
| `production.cost_version.manage` | C | S | | 4 | prd, fin (figures need `pricing.cost.read`) |
| `production.cost_rollup.run` | C | | | 4 | prd, fin |
| `production.feasibility.run` | C | | | 4 | sal, mgt, prd, ops |
| `production.simulation.run` | C | | | 4 | mgt, prd, ops |
| `logistics.packing_list.read` | R | | | 4 | ops B, sal O, mgt C |
| `logistics.packing_list.create` | C | | | 4 | ops |
| `logistics.packing_list.update` | R | | | 4 | ops B |
| `logistics.packing_list.transition` | R | | | 4 | ops B |
| `logistics.shipment.read` | R | | | 4 | ops B, sal O, mgt C |
| `logistics.shipment.create` | C | | | 4 | ops |
| `logistics.shipment.update` | R | | | 4 | ops B |
| `logistics.shipment.transition` | R | | | 4 | ops B |
| `logistics.container_profile.manage` | C | | | 4 | ops |
| `logistics.load_plan.run` | C | | | 4 | ops, sal |

### 7.8 `finance`, `migration`

| Key | Scopes | Flags | Legacy alias | Slice | Templates |
|---|---|---|---|---|---|
| `finance.invoice.read` | R | | | 5 | fin C, mgt C |
| `finance.invoice.create` | C | | | 5 | fin |
| `finance.invoice.update` | R | | | 5 | fin C |
| `finance.invoice.approve` | R | S | | 5 | fin C, mgt C (never the creator) |
| `finance.invoice.issue` | R | RA S | | 5 | fin C (issue gate applies) |
| `finance.receipt.read` | R | | | 5 | fin C, mgt C |
| `finance.receipt.create` | C | | | 5 | fin |
| `finance.receipt.reverse` | R | RA | | 5 | fin C |
| `finance.allocation.create` | C | | | 5 | fin |
| `finance.ageing.read` | C | | | 5 | fin, mgt |
| `finance.accounting_export.run` | C | RA | | 5 | fin |
| `finance.configuration.manage` | C | MFA RA S | | 5 | fin |
| `finance.tax_profile.approve` | C | MFA S | | 5 | fin (never the author) |
| `migration.run.read` | C | MFA | | 5 | — |
| `migration.dry_run.run` | C | MFA | | 5 | — |
| `migration.apply.execute` | C | MFA RA S | | 5 | — (requires a verified backup id) |
| `migration.party_candidate.update` | C | | | 5 | mgt |

## 8. Legacy alias table (the single mapping for all 14 legacy permissions)

Each key's `PermissionDef.legacy_aliases` carries the legacy names; `Registry.legacy_alias_map()` derives this table and
a contract test compares it with the rows below. The scope column is applied by the identity module when expanding
legacy role defaults and per-user overrides during migration.

| Legacy permission | New keys | Scope on expansion |
|---|---|---|
| `view_all_quotes` | `sales.quote.read` | company |
| `view_own_quotes` | `sales.quote.read` | own |
| `create_quotes` | `sales.quote.create` | company |
| `edit_all_quotes` | `sales.quote.update`, `sales.quote.transition`, `sales.quote.issue`, `sales.quote.archive` | company |
| `edit_own_quotes` | `sales.quote.update`, `sales.quote.transition`, `sales.quote.issue`, `sales.quote.archive` | own |
| `delete_quotes` | `sales.quote.delete` | company (service allows never-issued drafts only) |
| `override_price` | `sales.quote_price.override` | the expanded scope of `sales.quote.update` (own if none) |
| `export_quotes` | `sales.quote.export` | the expanded scope of `sales.quote.read` |
| `view_products` | `catalogue.product.read`, `pricing.price.read` | company |
| `edit_products` | `catalogue.product.create`, `catalogue.product.update`, `catalogue.product.archive`, `catalogue.media.manage`, `pricing.price_list.manage` | company |
| `manage_users` | `identity.user.read`, `identity.user.manage`, `identity.role.read`, `identity.role.manage`, `identity.permission.manage` | company |
| `import_data` | `imports.job.read`, `imports.job.run` | company |
| `view_costing` | `pricing.cost.read`, `pricing.price_list.read` | company |
| `manage_categories` | `catalogue.taxonomy.manage` | company |

Legacy section visibility (spec §8.1 `canViewSection`) maps as follows: specifications and packaging need
`catalogue.product.read` (a deliberate change: legacy hid them from sales in the UI only, while sales already saw the
packaging summary in the configurator); base/add-on prices and yield need `pricing.price_list.read`; costing needs
`pricing.cost.read`.

## 9. Role templates

System templates are read-only rows created per company from the merged `TEMPLATE_GRANTS` of all installed modules
(each module contributes grants for its own keys). `employee` grants are included in every template (Slice 1: merged by
the registry; Slice 2: expressed as inheritance of custom roles). The per-key template column in §7 is authoritative;
summary:

| Template | Purpose | Highlights |
|---|---|---|
| `employee` | base for every member | company/directory/settings/calendar read, file upload, search, own tasks (read, create, update, assign, dismiss, export), own briefing, own proposals, assistant and speech use |
| `admin` | administration | every key at its maximum scope; MFA required from Slice 2 |
| `management` | legacy management | legacy §3.2 rights (view_all, create, edit_all, override_price, export, view_products, view_costing) plus non-destructive keys: quote approve/correct/assign/send, price-override approve, enquiries, customer messages, parties (read, create, update, archive, assign, export), custom products (no approve), samples, FX read/create/approve, rule-set and policy read, company-wide tasks, catalogue export, cut plans read/export/run, operations and finance read, approvals for BOM/PO/adjustments/opening stock/invoices. **No `*.delete`, no catalogue write keys (`catalogue.product.create/update/archive`, `catalogue.media.manage`, `catalogue.taxonomy.manage`), no `pricing.price_list.manage`, no `identity.*`, no `imports.*`.** |
| `sales` | legacy sales | view_own, create, edit_own, override_price (reason required), export (own), view_products; own parties, enquiries, customer messages, custom products, samples, cut plans; challan read/create/update/export (own); FX read; stock availability read (S4); feasibility and load-plan runs |
| `operations` | legacy operations (operations lead) | legacy view_all_quotes and view_products; challans and cut plans at branch scope; parties read; custom products and samples read; inventory, quality, production, logistics at branch scope (S4) |
| `finance` | finance | finance keys, FX create/approve/policy, cost read/update, bank account read, parties, quotes and orders read |
| `production` | production planning | production keys, cut plans and grain/settings, cost read/update, inventory read/lots/posts at branch scope |
| `procurement` | purchasing | procurement keys, vendor parties, inventory read, reorder rules |
| `warehouse` | warehouse assistant (restricted) | product read, stock read (branch), pick confirmations and count entry (branch) from Slice 4; before Slice 4 it equals the employee base plus product read |
| `catalogue` | catalogue data steward | product create/update/archive/export, media, taxonomy, lookups, imports and rollback, price-list read/manage, prices, UOM master, custom product read and promotion approval |

## 10. Resolution, overrides, delegation and approvals

Resolution (cached per `(membership_id, authz_epoch)`; the epoch is read with the session on every request):
1. An inactive membership has no permissions.
2. For each role, walk inheritance root → leaf; a grant raises the key to the higher scope; a `deny` in a descendant
   removes a key inherited from that role's own ancestors only.
3. Union across roles, taking the maximum scope.
4. Apply unexpired per-user grants (maximum scope).
5. Remove every key with a per-user revoke. **Revoke always wins.**
6. Delegation (below) adds record reach, never keys.

Anti-escalation: an actor can grant only keys they hold, at no more than their own scope, and never to their own roles
or overrides. Last-admin guard: at least one active, MFA-enrolled membership keeps `identity.role.manage@company`.
Any change to roles, overrides, memberships, teams or delegations increments `company.authz_epoch` in the same
transaction and emits `identity.membership.access_changed`.

**Delegation rule**: a delegation never adds permission keys. For delegable keys (`D`) the delegate **already holds**,
it extends the delegate's record scope to records owned by the delegator (`ActorContext.delegated[key]`). Approvals move
to the delegate only when the delegation sets `include_approvals` and the delegate is independently eligible.
Completions record `on_behalf_of_user_id`. Maximum 90 days; no self-delegation.

**Approval eligibility** (enforced by `app/platform/approvals`, never by the model or the UI):
- The approver holds the target's `<module>.<resource>.approve` key at a scope covering the target record, and — when
  the approval policy names a level (Slice 3) — an active `approval_authority` for that level.
- Quote review proposals (`sales.quote.review`) require `sales.quote.approve`; when the proposal facts include a price
  override, a discount or a below-minimum applicable subtotal, the approver must also hold `sales.quote_price.approve`.
- Separation of duties: the initiator can never decide (service check plus the `proposal_decision` CHECK constraint).
- Override reason rule: setting a price different from the default or a discount needs `sales.quote_price.override`;
  a reason is mandatory unless the actor also holds `sales.quote_price.approve` covering the quote (legacy: management
  and admin free, sales must give a note). This replaces the design-source `override_price_without_reason` key.

## 11. Contract tests

| Test | Asserts |
|---|---|
| `backend/tests/contract/test_permissions_catalogue.py::test_registry_matches_catalogue` | every registered key is in this file and vice versa; grammar and verb set valid |
| `backend/tests/contract/test_permissions_catalogue.py::test_no_unknown_keys_referenced` | keys in policies, templates, tools, settings, routes and approval policies all exist |
| `backend/tests/contract/test_legacy_permission_parity.py::test_legacy_templates_reproduce_spec_3_2` | for admin, management, sales and operations, each of the 14 legacy permissions holds exactly as in spec §3.2 (predicates in §12) |
| `backend/tests/contract/test_legacy_permission_parity.py::test_alias_table_matches_registry` | §8 equals `Registry.legacy_alias_map()` |
| `backend/tests/contract/test_legacy_permission_parity.py::test_management_has_no_destructive_or_identity_keys` | management holds no `*.delete`, no catalogue write keys, no `pricing.price_list.manage`, no `identity.*`, no `imports.*` |
| `backend/tests/unit/authz/test_permission_resolution.py::test_revoke_wins_and_scope_is_max` (hypothesis) | resolution properties |
| `backend/tests/unit/authz/test_delegation.py::test_delegation_never_adds_keys` | delegation only extends reach for held delegable keys |
| `backend/tests/integration/authz/test_revocation_immediate.py::test_epoch_bump_denies_next_request_and_job` | revocation applies to the next request, job and tool call |
| `backend/tests/contract/test_route_authz_matrix.py::test_every_route_denies_unauthorised_personas` | IDOR matrix across all routes |

## 12. Parity predicates (spec §3.2)

| Legacy permission | Holds for a template when |
|---|---|
| view_all_quotes | `sales.quote.read` scope = company |
| view_own_quotes | `sales.quote.read` scope = own exactly |
| create_quotes | `sales.quote.create` present |
| edit_all_quotes | `sales.quote.update`, `.transition`, `.issue`, `.archive` all at company |
| edit_own_quotes | the same four at own exactly |
| delete_quotes | `sales.quote.delete` present |
| override_price | `sales.quote_price.override` present |
| export_quotes | `sales.quote.export` present |
| view_products | `catalogue.product.read` and `pricing.price.read` present |
| edit_products | all five alias keys present |
| manage_users | all five alias keys present |
| import_data | `imports.job.read` and `imports.job.run` present |
| view_costing | `pricing.cost.read` and `pricing.price_list.read` present |
| manage_categories | `catalogue.taxonomy.manage` present |

Expected result (spec §3.2): admin all except view_own_quotes and edit_own_quotes; management view_all_quotes,
create_quotes, edit_all_quotes, override_price, export_quotes, view_products, view_costing; sales view_own_quotes,
create_quotes, edit_own_quotes, override_price, export_quotes, view_products; operations view_all_quotes, view_products.

## 13. Renames from the design sources

| Design-source key | Canonical key |
|---|---|
| `sales.quote.view` / `sales.quote.edit` | `sales.quote.read` / `sales.quote.update` (+ `transition`) |
| `sales.quote.send` (manual mark sent) | `sales.quote.issue` (`sales.quote.send` is channel delivery, Slice 3) |
| `sales.quote.override_price` | `sales.quote_price.override` |
| `sales.quote.override_price_without_reason` | reason waiver through `sales.quote_price.approve` (§10) |
| `sales.quote.correct_status` / `sales.quote.assign` | `sales.quote.correct` / `sales.quote.assign` |
| `catalogue.view`, `catalogue.edit`, `catalogue.archive` | `catalogue.product.read`, `catalogue.product.{create,update}`, `catalogue.product.archive` |
| `catalogue.media_manage`, `catalogue.taxonomy_manage`, `catalogue.lookup_view` | `catalogue.media.manage`, `catalogue.taxonomy.manage`, `catalogue.lookup.read` |
| `catalogue.import`, `catalogue.import_rollback` | `imports.job.run` (+ `imports.job.read`), `imports.rollback.execute` |
| `catalogue.demo_reset`, `demo.data.reset` | `system.demo_data.delete` |
| `catalogue.costing.read`, `pricing.costing.view`, `production.view_costing` | `pricing.cost.read` |
| `pricing.price.resolve`, `pricing.price_list.view` | `pricing.price.read`, `pricing.price_list.read` |
| `pricing.fx.{view,propose,approve}` | `pricing.fx_rate.{read,create,approve}` |
| `parties.party.view` / `.edit` | `parties.party.read` / `.update` |
| `ops.challan.*`, `challans.view/create/edit/issue/close/export` | `challans.challan.{read,create,update,issue,transition,export}` |
| `challans.delete_draft`, `challans.cancel_issued`, `challans.write_off` | `challans.challan.delete`, `challans.challan.reverse`, `challans.write_off.approve` |
| `cutting.view`, `cutting.plan`, `cutting.release`, `cutting.manage_grain_settings`, `production.cut_plan.*` | `cutting.plan.read`, `cutting.plan.update`, `cutting.plan.transition`, `cutting.grain_lock.manage` |
| `orders.{view,create,confirm,cancel}` | `orders.sales_order.{read,create,transition}` |
| `inventory.view`, `.reserve`, `.post`, `.adjust`, `.approve_adjustment`, `.count`, `.approve_count`, `.approve_opening`, `.receive_unplanned`, `.reverse` | `inventory.stock.read`, `inventory.stock.reserve`, `inventory.stock.post`, `inventory.adjustment.create`, `inventory.adjustment.approve`, `inventory.stock_count.create`, `inventory.stock_count.approve`, `inventory.opening_batch.approve`, `inventory.stock.receive`, `inventory.posting.reverse` |
| `finance.{view,draft,approve,issue,record_receipt,allocate,export,configure}` | `finance.invoice.{read,create,approve,issue}`, `finance.receipt.create`, `finance.allocation.create`, `finance.accounting_export.run`, `finance.configuration.manage` |
| `tasks.assign`, `tasks.dismiss` | `tasks.task.assign`, `tasks.task.dismiss` |
| `audit.trace.view`, `system.audit.read` | `audit.trace.read`, `audit.log.read` |
| `migration.dry_run`, `migration.execute` | `migration.dry_run.run`, `migration.apply.execute` |
| `catalog.product.create` (typo) | `catalogue.product.create` |
| `imports.job.run` (feasibility module list), `search.global.use`, `agents.memory.approve` | unchanged |
