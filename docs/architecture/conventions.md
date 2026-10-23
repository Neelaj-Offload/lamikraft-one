# Code and data conventions

Status: frozen in Slice 0 (checkpoint 0). Changes go through an integrator PR, then lanes rebase.
Authority: `docs/PLAN.md` § Canonical contracts wins over everything in `docs/design/source/`. Where this
file and the code disagree, the code under `backend/app/core/**` and `backend/app/platform/**` is
checked against this file in review and one of them is corrected; neither silently wins.

Related contracts: [api-conventions.md](api-conventions.md), [permissions.md](permissions.md),
[events.md](events.md), [fixtures.md](fixtures.md), [parallel-work.md](parallel-work.md),
[ai-routing.md](ai-routing.md), [motion-system.md](motion-system.md).

---

## 1. Layers and import direction

| Layer | Path | Owns tables? | May import |
|---|---|---|---|
| core | `backend/app/core/**` | no (infrastructure only: config, db engine/base, money, clock, errors, logging, csv_safe, text, documents, http) | stdlib, third-party |
| platform (kernel) | `backend/app/platform/<name>/` | yes, **unprefixed** table names | core, other platform modules |
| modules (domain) | `backend/app/modules/<name>/` | yes, **`<module>_<entity>`** table names | core, platform, other modules' public `service.py`/`schemas.py` only |
| seed | `backend/app/seed/world/**` | no (creates rows only through services) | everything above |
| migrations | `backend/migrations/**` | DDL only (Alembic, linear chain) | core.db, migration helpers |

Imports only go downward. Platform never imports a module; modules contribute to platform through their
`manifest.py` (permissions, events, subscriptions, jobs, sequences, policies, ApprovalTarget adapters,
search providers, settings, tools). An AST architecture test (`backend/tests/contract/test_architecture_rules.py`)
enforces the direction.

## 2. Module list

The module name is the single namespace: backend package = table prefix (domain modules) = permission
module = event module = API route segment = operationId prefix.

### 2.1 Platform kernel (`backend/app/platform/<name>`)

| Module | Owns (tables) | First slice |
|---|---|---|
| `org` | `company`, `branch`, `team`, `team_member`, `setting`, `setting_revision`, `currency` (global reference, RLS-exempt), `uom`, `uom_alias`, `uom_conversion`, `work_calendar`, `work_shift`, `work_holiday`, `work_assignment` | 0/1 |
| `identity` | `app_user` (global, RLS-exempt), `membership`, `membership_branch`, `membership_role`, `role`, `role_permission`, `permission` (catalogue synced from code, RLS-exempt), `user_permission_override`, `delegation`, `user_absence`, `access_request`, `invitation`, `password_reset`, `auth_session`, `auth_attempt`, `rate_limit_counter`, `mfa_factor`, `mfa_recovery_code`, `user_preference` (user-level, RLS-exempt) | 0/1 (MFA, invitations, delegation, access requests: 2) |
| `authz` | no tables: ActorContext, ScopedRepository, ResourcePolicy registry, scope clause, field-guard registry, redaction | 0 |
| `events` | `domain_event` (outbox, RLS-exempt), `event_consumption` | 0 |
| `jobs` | `job`, `job_schedule`, `worker_heartbeat` (RLS-exempt) | 0 |
| `numbering` | `document_sequence`, `document_sequence_counter`, `issued_document_number` | 0/1 |
| `idempotency` | `idempotency_key` | 0 |
| `audit` | `audit_log` (append-only) | 0 |
| `files` | `file_object` | 1 (local_fs), 2 (s3) |
| `collab` | `note`, `note_comment`, `attachment`, `activity` | 1 (notes), 2 (attachments, activity feed) |
| `search` | `search_recent` | 1 |
| `approvals` | `proposal`, `proposal_target`, `proposal_decision`, `approval_policy`, `approval_level`, `approval_authority`, `action_ref`, `execution_receipt` | 0 (interface stub), 1 |
| `system` | `integration_status`, `backup_run` | 0/1 |

`approvals` sits in the kernel because every domain module registers `ApprovalTarget` adapters with it
and platform code cannot import modules. The Slice-1 wave-2 agents-demo lane owns
`backend/app/platform/approvals/**` for that wave only (see [parallel-work.md](parallel-work.md)).

### 2.2 Domain modules (`backend/app/modules/<name>`)

| Module | Table prefix | Scope | First slice |
|---|---|---|---|
| `catalogue` | `catalogue_` | product master, specifications, dimensions, packaging, media links, taxonomy, lookup_reference | 1 (read), 2 (full) |
| `imports` | `imports_` | import workbench for all seven legacy types; staging, issues, changes, rollback | 2 |
| `parties` | `parties_` | parties, contacts, addresses, tax identifiers, customer types, party roles | 1 (minimal), 2 (full) |
| `pricing` | `pricing_` | price lists, items, history, product_cost (protected), FX rates and policy | 1 (seeded, resolution), 2 (CRUD, FX) |
| `commercial` | `commercial_` | commercial rule sets and the pure Decimal engine | 1 |
| `sales` | `sales_` | quotes (lines, revisions, documents, status history, dispatches, settings), enquiries, customer messages, custom products, samples | 1 / 2 |
| `orders` | `orders_` | sales orders and lines from accepted quotes | 4 |
| `tasks` | `tasks_` | tasks, issues, change log, reminders, queues, responsibility rules, Inbox | 1 |
| `briefings` | `briefings_` | briefings, versions, items, recommendations, item states, acknowledgements, pins, templates, policy | 1 |
| `agents` | `agents_` | conversations, turns, runs, run steps, object context, memory, automations, `agents_ai_call_log` (the plan's single `ai_call_log`) | 1 (demo), 3 (live) |
| `voice` | `voice_` | utterances; STT/TTS adapters | 3 |
| `channels` | `channels_` | WhatsApp/email accounts, identities, enrolment, sessions, webhook inbox (RLS-exempt), messages, outbox, consent, templates, review links, message drafts | 3 |
| `challans` | `challans_` | delivery challans, lines, return links, movement policy | 2 (documents), 4 (postings) |
| `cutting` | `cutting_` | sheet optimiser: settings, machine profiles, grain locks, plans, calculations, placements, cuts, links | 2 |
| `inventory` | `inventory_` | warehouses, locations, lots, ledger (postings, movements), balances, summaries, reservations, counts, adjustments, opening batches, pick lists, shortage state, reorder rules | 4 |
| `quality` | `quality_` | QC inspections for receipts, outputs and returns | 4 |
| `procurement` | `procurement_` | vendor items, requisitions, purchase orders, goods receipts, vendor-bill handoff | 4 |
| `production` | `production_` | BOMs, routings, work centres, work orders, materials, outputs, scrap, cost versions and rollups, feasibility, simulations | 4 |
| `logistics` | `logistics_` | packing lists, shipments, tracking refs, container profiles, load suggestions | 4 |
| `finance` | `finance_` | invoices and credit notes, tax profiles, provider configuration, receipts, allocations, accounting exports and sync | 5 |
| `migration` | `migration_` | dry-run/apply runs, source files, id maps, issues (quarantine), party candidates and decisions | 5 |
| `ui` | `ui_` | session bootstrap, recent records, poll aggregation | 1 |

### 2.3 Standard files per module

```
<module>/
  manifest.py   MANIFEST = ModuleManifest(...)  (registry entry point; integrator adds the module to INSTALLED_MODULES)
  models.py     SQLAlchemy models
  schemas.py    Pydantic request/response models (DecimalStr for every money/quantity field)
  service.py    public service functions (the only entry point for routers, tools, jobs and other modules)
  router.py     FastAPI router; no SQLAlchemy or model imports
  policies.py   PermissionDefs, ResourcePolicies, TEMPLATE_GRANTS, ApprovalTarget adapters
  events.py     EventDefs and Subscriptions
  tools.py      agent ToolSpecs (call service.py only)
  jobs.py       JobDefs / ScheduleDefs (optional)
  settings.py   SettingDefs (optional)
  search.py     SearchProvider (optional)
  sql.py        allow-listed raw SQL (optional, see §9)
```

Tests: `backend/tests/{unit,integration,contract}/<module>/test_*.py`. Web code: `apps/web/src/app/(app)/<area>/**`
and `apps/web/src/features/<feature>/**`.

## 3. Table naming and schema rules

- Domain tables: `<module>_<entity>`, singular entity (`sales_quote`, `sales_quote_line`, `inventory_stock_movement`).
  Child tables extend the parent name (`sales_quote_line`, `challans_challan_line`).
- Kernel tables: unprefixed (`company`, `membership`, `file_object`, `proposal`).
- Design-source names are renamed to this rule (e.g. `import_job` → `imports_job`, `inv_stock_postings` →
  `inventory_stock_posting`, `chl_challans` → `challans_challan`, `cut_plans` → `cutting_plan`,
  `ord_sales_orders` → `orders_sales_order`, `inv_shortage_state` → `inventory_shortage_state`).
- Constraint names come from the metadata naming convention in `app/core/db/base.py`
  (`ix_`, `uq_`, `ck_`, `fk_`, `pk_` + table + columns). Explicit names are used for deferrable
  constraints so `uow.defer_constraints(name)` can reference them.
- Enumerations: `varchar` + CHECK generated from a Python `StrEnum`. No native PostgreSQL enums.
- JSONB: only for validated snapshots and flexible specifications, always through a Pydantic model on write.
  Never for data that is filtered, joined or aggregated.
- Model flags on `Base`: `__tenant_rls__` (default True; False only for documented platform-internal or
  global tables), `__append_only__` (trigger rejects UPDATE/DELETE: audit, ledgers, issued revisions,
  status histories, consent log), `__audited__` (automatic audit diff).
- RLS, triggers, append-only and CHECK constraints are created **only** through migration helpers in
  `backend/migrations/helpers.py` (`tenant_table`, `enable_tenant_rls`, `append_only`, enum CHECK helper).
  A contract test compares `pg_policies`/`pg_trigger` with the model flags.
- RLS-exempt tables (exhaustive list, extended only by integrator PR): `company`, `app_user`, `permission`,
  `user_preference`, `auth_session`, `auth_attempt`, `rate_limit_counter`, `password_reset`, `mfa_factor`,
  `mfa_recovery_code`, `domain_event`, `event_consumption`, `job`, `job_schedule`, `worker_heartbeat`,
  `currency`, `backup_run`, `channels_webhook_inbox`, `channels_webhook_rejection`. Exempt tables are touched
  only by platform code (or the channels webhook route) with explicit filters.

## 4. Identifiers

- Primary keys: `id uuid` holding a UUIDv7 from the standard library (`uuid.uuid7()`, Python 3.14), exposed as
  `app.core.db.base.new_id`. No hand-written generator.
- Business keys (`product_key`, `quote_number`, `challan_number`, `party_number`, `custom_code`, ...) are
  separate columns, immutable once assigned, unique per company, and never derived from sequences of ids.
- Web detail routes use UUIDs; `/go/[type]/[key]` resolves business keys (voice, search, WhatsApp links).
- Stable briefing issue ids are UUIDv5 of `company_id|issue_key|occurrence` (namespace constant in
  `app/modules/tasks/issue_keys.py`).
- Correlation ids are UUIDv7 strings created at ingress and propagated through jobs, events and traces.

## 5. Columns and mixins

From `app/core/db/base.py`: `IdMixin`, `TenantMixin` (`company_id NOT NULL`, FK RESTRICT), `BranchMixin`
(`branch_id` nullable), `TimestampMixin` (`created_at`, `updated_at` timestamptz, stamped from the Clock),
`ActorStampMixin` (`created_by`, `updated_by` → `app_user`), `VersionMixin` (`version` integer, SQLAlchemy
`version_id_col`, optimistic concurrency), `ArchivableMixin` (`archived_at`, `archived_by`). Ownership
columns are named `owner_user_id` (accountable) and `assignee_user_id` (doing the work) everywhere.

Soft delete: documents with business numbers are never hard-deleted (`deleted_at`/`deleted_by` or
`archived_at`); their numbers are never reused. Users are never hard-deleted.

## 6. Money, quantities, dimensions and FX

Types live only in `app/core/money.py` (`Money`, `Quantity`, `DecimalStr`, `quantize_money`,
`quantize_unit_price`, `quantize_quantity`, `CURRENCY_EXPONENT`). Floats are rejected with `TypeError` at
every boundary (input schema, output schema, engine, tool input).

| Kind | Column type | Naming | Rules |
|---|---|---|---|
| Money amount | `NUMERIC(18,4)` + `CHAR(3)` currency | `<name>_amount`, `<name>_currency` | CHECK both null or both set; currency `^[A-Z]{3}$` and in the enabled set (INR, EUR, USD, GBP). Totals are quantized to the currency minor unit with ROUND_HALF_UP; storage keeps 4 dp. Never summed across currencies. |
| Unit price | `NUMERIC(18,4)` + currency | `unit_price`, `default_unit_price` | 4 dp (`quantize_unit_price`); EUR 24.0000 stays 24.0000. |
| Quantity | `NUMERIC(18,6)` + `uom_code` (FK `uom.code`) | `quantity`, `qty_<state>` | Entry rule per UOM: `uom.is_integer` units (pcs, nos, sheets, box, set, roll, bundle, carton) accept integers only; others accept at most 4 decimal places. Storage keeps 6 dp. Every transactional quantity > 0 unless documented. |
| Dimension | `NUMERIC(12,3)` | suffix `_mm` (or `_cm` for legacy carton dimensions kept as entered) | Canonical millimetres; the original string is kept in a `*_source` column as provenance. |
| Thickness | `NUMERIC(8,3)` | `thickness_mm` | `0.8` and `0.80` are the same value. |
| Weight | `NUMERIC(14,3)` grams / `NUMERIC(12,4)` kilograms | `unit_weight_g`, `net_weight_kg`, `gross_weight_kg` | Canonical unit weight is grams; carton weights are per master carton. |
| Volume | `NUMERIC(12,6)` | `cbm` | Cross-checked against L×W×H/1e6 (warning beyond 2 %). |
| FX rate | `NUMERIC(20,10)` | `rate` (1 base = rate quote) | Dated, sourced, approved; never invented. |
| Percentage | `NUMERIC(7,4)` | `<name>_pct` | 0–100 unless documented. |
| Packer geometry | integer deci-millimetres (in memory only) | — | Inputs with more than 1 dp in mm are rejected (422). |

JSON carries every decimal as a string matching `^-?\d{1,14}(\.\d{1,6})?$` (`DecimalStr`), money as
`{"amount": "5760.00", "currency": "EUR"}` and quantities as `{"value": "240", "uom": "pcs"}`. The client
formats strings with `Intl.NumberFormat`; it never does arithmetic on money or quantities.

### UOM rules

`org` owns `uom(code, name, dimension, is_integer)`, `uom_alias(alias, uom_code)` and
`uom_conversion(from_code, to_code, factor NUMERIC(20,10), product_id NULL, provenance)`. Seeded codes:
pcs, nos, sheets, kg, g, m, mm, cm, sqm, sqft, box, set, roll, bundle, carton. A missing conversion is a 422
(`uom_conversion_missing`); conversions are never guessed. Imports map unit text through `uom_alias`
(`UOM_UNKNOWN` otherwise).

## 7. Time and the Clock rule

- All timestamps are `timestamptz` in UTC. Local business dates are `date` columns computed in the
  resolved zone. Zone resolution: user → membership → branch → company → `Asia/Kolkata`.
- **Every business timestamp comes from the injected Clock** (`uow.now()`, `app/core/clock.py`):
  `created_at`, `updated_at`, `occurred_at`, `fact_at`, `due_at`, `issued_at`, seeded history. DB `now()` is
  reserved for infrastructure (job leases, heartbeats, `event_consumption.consumed_at`).
- `datetime.now()`, `date.today()` and `time.time()` for business purposes are banned in modules
  (architecture test). Tests freeze the clock globally or per company (`set_company_clock`, only when
  `LK_ENV=test`).
- Work date: `work_date(user, t) = (local(t) − rollover).date()`, rollover 04:00 by default (per calendar,
  overridable per shift). Defaults: Asia/Kolkata, Monday–Saturday, office shift 09:30–18:30. `tzdata` is a
  dependency because Windows has no system zone database.

## 8. Unit-of-work primitives

One command = one `UnitOfWork` (`app/platform/uow.py`) = one transaction, run as a server-built
`ActorContext`. The UoW sets `app.company_id`/`app.user_id` transaction-locally on entry and commits before
the HTTP response is sent (a 2xx means committed). Service functions take `uow`, never a raw `Session`.

| Primitive | Purpose |
|---|---|
| `uow.repo(Model)` | `ScopedRepository`: `get(id, action)` (404 not visible / 403 visible-but-forbidden), `select(action)`, `list`, `count`, `exists`, `search(text)` (escaped ILIKE / trigram) |
| `uow.lock(Model, ids)` | ordered `SELECT ... FOR UPDATE` (sorted ids; deterministic order) |
| `uow.advisory_xact_lock(namespace, key)` | transaction-scoped advisory lock (briefing generation, sequence repair) |
| `uow.defer_constraints(*names)` | `SET CONSTRAINTS ... DEFERRED` for named deferrable constraints (quote currency FK, line renumbering) |
| `uow.expect_version(obj, expected)` | optimistic check; mismatch raises `VersionConflict` (409) |
| `uow.emit(event_name, aggregate_id=, payload=, aggregate_version=, causation_id=)` | outbox row in the same transaction ([events.md](events.md)) |
| `uow.enqueue(kind, payload, **options)` | durable job in the same transaction (payload = ids only) |
| `uow.allocate_number(sequence_key, document_date=, resource_type=, resource_id=, branch_id=, tokens=)` | the only document-number allocator |
| `uow.audit(action, **fields)` | append-only audit entry |
| `uow.now()` / `uow.clock` | business time |
| `uow.after_commit(callback)` | side effects that must only follow a commit (never DB writes) |
| `uow.system_session(reason)` | allow-listed platform files only; logged with the reason |
| read-only UoW | simulations and what-if (`production`, `inventory`) run in a UoW whose flush raises |

Lock order for stock (Slice 4): document header → lines (by id) → `inventory_stock_summary` (product,
warehouse) → `inventory_stock_balance` (key) → `inventory_reservation` (id). Deadlock or serialisation
failures retry up to 3 times; safe because commands carry idempotency keys.

No transaction is ever held across an AI provider call, an outbound HTTP call or a file stream.

## 9. Raw SQL allowlist

Raw SQL (`text(...)`, `session.execute` on strings, `exec_driver_sql`) is allowed only in:

1. `backend/app/core/db/**`
2. `backend/app/platform/**`
3. `backend/migrations/**`
4. module `sql.py` files listed in `ALLOWED_SQL_FILES` in `backend/tests/contract/test_architecture_rules.py`,
   each with a one-line reason comment at the top (e.g. recursive CTE for BOM explosion, `SUM ... GROUP BY
   currency` for ageing, reference counting by FK introspection).

Banned everywhere in modules: regex operators (`~`, `~*`, `SIMILAR TO`, `regexp_*`) on user input, string
interpolation into SQL, `LIKE` without `app.core.text.escape_like`. User input never becomes a regular
expression (legacy §10.2 #6).

## 10. Synchronous only

- FastAPI endpoints are `def`, SQLAlchemy 2.1 is used synchronously with psycopg 3, jobs run in the worker's
  thread pool. `psycopg` async, `AsyncSession`, `AsyncConnection`, `AsyncAnthropic` and LISTEN/NOTIFY are
  banned (architecture test greps for them); psycopg async does not work with the Windows Proactor loop.
- Outbound HTTP uses `httpx` synchronously; tests use `httpx.MockTransport` (no respx).
- The Anthropic adapter uses the synchronous `anthropic.Anthropic` client inside the worker; the Gemini
  adapter uses the synchronous `google-genai` client. See [ai-routing.md](ai-routing.md).

## 11. Shared kernel single owners

| Concern | Single implementation | Rule |
|---|---|---|
| Money and quantities | `app/core/money.py` | no other Money type |
| CSV output | `app/core/csv_safe.py` (`write_csv`, `escape_cell`, `strip_guard`) | contract test forbids `csv.writer`/`DictWriter` elsewhere and `text/csv` Blob creation in `apps/web` |
| PDF output | `app/core/documents` (ReportLab Platypus, embedded Noto Sans + Noto Sans Devanagari, OFL) | no WeasyPrint, no HTML-to-PDF |
| Files | `app/platform/files` (`file_object`, UNIQUE(company, sha256), magic-byte sniffing, size limits, cookie-authenticated streaming) | no presigned URLs; storage keys never derived from filenames |
| Numbering | `app/platform/numbering` via `uow.allocate_number` | no module counters |
| Calendar | `app/platform/org` work calendar service | no module calendars |
| Delegation / absence | `app/platform/identity` | one table each |
| Notes | `app/platform/collab.note` | no domain `internal_notes` columns (quote line `internal_note` is a line field, redacted from documents) |
| Search | `app/platform/search` providers on `ScopedRepository.search` | restricted fields never indexed |
| Preferences | `identity.user_preference` (typed sections ui, locale, briefing, voice, assistant) | mandatory controls are never preferences |
| Integration state | `system.integration_status` | "connected" only via a verification routine |
| AI usage | `agents_ai_call_log` | cost computed at report time from a price table |
| Approvals | `app/platform/approvals` | the only approval engine |
| Field guards | `Restricted(guard_key, model_exposure, log)` registry in `app/platform/authz/redaction.py` | used by DTOs, logs, exports, notifications, model context |

## 12. Errors, logging and secrets

- Errors are `AppError` subclasses in `app/core/errors.py`, rendered as problem+json with snake_case codes
  ([api-conventions.md](api-conventions.md) §3).
- structlog with a redaction processor: secrets, tokens, cookies, CSRF values, OTPs, API keys and restricted
  field names are removed; personal content keys (body, message, transcript, note, content) are dropped;
  emails and phone numbers are masked. Request and response bodies are never logged; the engine runs with
  `hide_parameters=True`.
- Provider secrets live only in environment variables read server-side (`ANTHROPIC_API_KEY`,
  `GEMINI_API_KEY`, `LK_*`). Settings never hold secrets. Live mode with a missing secret fails visibly.

## 13. Testing conventions

- Default integration mode: per-test SAVEPOINT session connected as `lk_app`. `@pytest.mark.committed`:
  a database cloned from `lk_wt{N}_tpl` for RLS, concurrency, worker and backup tests.
- `drain_events(uow)` runs the outbox relay and due jobs inline. Concurrency tests use `threading.Barrier`
  with separate connections, never sleeps.
- Tests reference fixture constants from `app.seed.world.keys`, never literals ([fixtures.md](fixtures.md)).
- Property tests use hypothesis (`derandomize=True` in CI) for the engine, packer, ledger, permission
  resolution, redaction and briefing ordering.
- Never SQLite. Byte-exact fixtures live under `backend/tests/fixtures/**` (marked `-text` in
  `.gitattributes`) with a sha256 manifest test.
- The test-support router is mounted only when `LK_ENV=test` (the plan's `APP_ENV=test`; settings use the
  `LK_` prefix) and a contract test proves it returns 404 otherwise.

## 14. Naming in code

- Pydantic: `<Entity>Create`, `<Entity>Update` (dirty fields + `expected_version`), `<Entity>Read`,
  `<Entity>Summary` (list rows), `<Entity>Page` only as `Page[<Entity>Summary]`.
- Service functions: verbs matching the action (`create_quote`, `transition_quote`, `issue_challan`).
- Event names, permission keys and operationIds follow their documents; never invent a parallel vocabulary.
