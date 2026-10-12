> Design-workflow output (2026-10-12), kept as source material. Where it conflicts with docs/architecture/*, the architecture docs win.

# Critique: feasibility

Feasibility, environment and sequencing review of the seven subsystem designs. I checked the inputs, the machine (read-only) and the official package metadata.

**What I verified on the machine**
- Python 3.12.10 and 3.14.6 are installed (py launcher), plus a uv-managed CPython 3.12.13. The **uv binary itself is not installed**.
- Node 24.18 and npm 12.0.1.
- Docker CLI 29.6.1 is installed but the daemon is down. The WSL2 docker-desktop distro is stopped, Docker AutoStart is false, and there is no .wslconfig, so the VM could take about 50% of RAM.
- There are no PostgreSQL binaries anywhere.
- git system config has core.autocrlf=true and core.symlinks=false. LongPathsEnabled=1, but git core.longpaths is unset.
- C: is 87% full (33 GB free); D: has 216 GB free.
- The repository path contains a space.
- Playwright Chromium builds are cached.

**What I verified in package metadata**
- **pgserver 0.1.4** is the last release (2024-06-08). It ships wheels for cp39–cp312 only and bundles PostgreSQL 16.2. Its published build script does not build contrib modules (pg_trgm, btree_gist). Whether pg_dump/pg_restore are in the Windows build is unverified.
- **pixeltable-pgserver 0.6.0** (Jul 2026) has cp314 Windows wheels, but its contents are unverified.
- **EDB portable Windows binaries** exist for 16.15, 17.11 and 18.6. They need no admin rights and include pg_dump and contrib.
- **Wheels for Python 3.14 on Windows** exist for: psycopg-binary 3.3.6, Pillow 12.3.0, argon2-cffi-bindings (abi3), uharfbuzz (abi3, used for ReportLab shaping) and ReportLab 5.0.1 (pure Python).
- **WeasyPrint on Windows** needs an MSYS2/Pango install, so avoid it.
- **TypeScript must stay on 5.9.x:**
  - openapi-typescript 7.13 has a peer dependency of typescript ^5.x;
  - typescript-eslint 8.71 requires typescript <6.1.0;
  - TypeScript 7.0 ships no JavaScript API.
- **ESLint must stay on 9.x:** eslint-plugin-react 7.37.5 (pulled in by eslint-config-next 16.4.0) supports eslint up to ^9.7.
- **MinIO** community images were discontinued in October 2025, so the local-filesystem adapter plus moto is the right default.
- **Next.js 16 rewrites** reportedly buffer server-sent events (SSE).

**Conclusions**
1. The individual designs are strong, but they are not mutually consistent. Eight cross-design contracts must be frozen in a single-agent Slice 0 before parallel work starts:
   - the permission vocabulary and legacy mapping;
   - the event catalogue;
   - ownership of shared kernel code (files/storage, CSV, money, numbering, calendar/leave/delegation);
   - one fixture world;
   - the approvals interface;
   - API conventions, including how decimals appear in the OpenAPI schema;
   - the unit-of-work and locking primitives;
   - the migration and generated-file rules.
2. Replace pgserver with EDB portable PostgreSQL 17, kept outside the spaced path, with Docker Compose as an optional alternative. That removes the only reason for Python 3.12. Choose 3.14 behind a fail-fast "no source builds" gate.
3. Cut or defer:
   - composite tenant foreign keys;
   - platform MFA, invitations and resets (move to Slice 2);
   - briefing pins, narration and template inheritance (Slice 3 and later);
   - durable server-sent-event agent runs, action references and policy versioning (Slice 3);
   - SeaweedFS and mailpit profiles.
4. Fill the gaps on the Scenario C critical path: an owner for customer messages and enquiries, a mark_won transition, a minimal approvals module, and the clock and test-database rules.
5. At most three lane agents plus one integrator fit in 15.7 GB of RAM. Only the integrator runs Playwright and next build.

Sources:
- https://pypi.org/pypi/pgserver/0.1.4/json
- https://raw.githubusercontent.com/orm011/pgserver/main/pgbuild/Makefile
- https://pypi.org/pypi/pixeltable-pgserver/0.6.0/json
- https://www.enterprisedb.com/download-postgresql-binaries
- https://www.postgresql.org/download/windows/
- https://pypi.org/pypi/psycopg-binary/3.3.6/json
- https://pypi.org/pypi/argon2-cffi-bindings/json
- https://pypi.org/pypi/reportlab/5.0.1/json
- https://pypi.org/pypi/uharfbuzz/0.56.3/json
- https://pypi.org/pypi/pillow/12.3.0/json
- https://doc.courtbouillon.org/weasyprint/stable/first_steps.html
- https://registry.npmjs.org/openapi-typescript/7.13.0
- https://registry.npmjs.org/typescript-eslint/latest
- https://registry.npmjs.org/next/16.4.0
- https://registry.npmjs.org/eslint-config-next/16.4.0
- https://registry.npmjs.org/eslint-plugin-react/latest
- https://registry.npmjs.org/@hookform/resolvers/latest
- https://infoq.com/news/2026/08/typescript-7-released/
- https://dev.to/the-modern-web/why-angular-vue-and-eslint-cant-upgrade-to-typescript-70-yet-and-why-ts-71-changes-441g
- https://gigazine.net/gsc_news/en/20251023-minio-stops-distributing-free-docker-images
- https://www.chainguard.dev/unchained/secure-and-free-minio-chainguard-containers
- https://cubic.dev/pr/lfnovo/open-notebook/pull/770

## Findings

### [blocker] Retain the 14 legacy permission intentions plus module/action/scope permissions, enforced on every read and write (legacy parity item 1)
- Source: build prompt <legacy_parity_and_corrections> #1; platform §5; catalogue §14; commercial §6; operations §11; briefing §9; agents §8/§13
- Owner: platform
- Problem: The designs use incompatible permission keys and two conflicting legacy mappings.

- **Platform:** `<module>.<resource>.<action>` with verbs like read (e.g. catalogue.product.read, catalogue.costing.read, imports.job.run, ops.challan.*, production.cut_plan.*, system.audit.read).
- **Catalogue:** two-segment keys (catalogue.view, catalogue.edit, catalogue.media_manage, catalogue.import).
- **Commercial:** uses `view` instead of `read` (sales.quote.view). It also maps the legacy permissions differently: view_products to pricing.price.resolve, and view_costing to pricing.costing.view.
- **Operations:** two-segment keys (challans.issue, cutting.plan, production.view_costing).
- **Agents:** audit.trace.view and agents.memory.approve.

Platform startup validation will reject every other module's templates, and test_legacy_permission_parity cannot pass while two mapping tables exist.
- Resolution: In Slice 0, platform publishes docs/architecture/permissions.md and the PermissionDef registry. Rules:

- **Grammar:** `<module>.<resource>.<action>`. The module is the backend package name: identity, org, files, system, catalogue, imports, pricing, parties, sales, approvals, tasks, briefings, agents, channels, challans, cutting, inventory, orders, procurement, production, logistics, finance, migration.
- **Closed verb set:** read, create, update, archive, delete, transition, approve, export, manage, run, execute. Restricted data becomes a resource of its own, e.g. pricing.costing.read.
- **One platform-owned legacy table (legacy_alias):**
  - view_products: catalogue.product.read + pricing.price.resolve
  - edit_products: catalogue.product.{create,update,archive} + catalogue.media.manage + pricing.price_list.manage
  - view_costing: pricing.costing.read
  - import_data: imports.job.run
  - manage_categories: catalogue.taxonomy.manage
  - manage_users: identity.user.manage + identity.role.manage + identity.permission.manage
  - quote permissions as in platform §5
- Each module declares PermissionDefs and TEMPLATE_GRANTS in its own policies.py, so there is no central file to fight over.
- Startup cross-validation plus a contract test reject unknown keys.
- Designers rename their keys before Slice 1 begins.

### [blocker] Event-driven briefing updates, transactional outbox and event naming `<module>.<entity>.<past_tense_verb>`
- Source: briefing §4 event catalogue vs commercial §8, operations §12, catalogue §13, platform §14, agents §17
- Owner: platform
- Problem: Most consumed event names are not emitted by any design.

- **Briefing consumes, but nobody emits under that name:**
  - sales.quote.{sent, status_changed, validity_extended, expired, reassigned}; commercial emits marked_sent, issued, won and owner_changed, and has no expired event because expiry is computed.
  - catalogue.price_list.published; commercial emits pricing.price_list.activated and pricing.price_list_item.superseded.
  - agents.proposal.*; agents emits approvals.proposal.*.
  - identity.user.{activated, deactivated, permissions_changed}; platform emits identity.membership.*.
  - operations.challan.issued (emitted as challans.challan.issued).
  - procurement.grn.posted (emitted as procurement.goods_receipt.posted).
  - production.cut_plan.saved (emitted as cutting.plan.calculated).
  - imports.job.failed (emitted as catalogue.import.failed).
- **Nobody emits these at all:** sales.customer_message.*, sales.enquiry.*, identity.access.requested, catalogue.completeness.changed, inventory.shortage.detected, procurement.po_line.arrival_changed, logistics.dispatch.scheduled, channels.briefing_ack.received.
- **Other mismatches:**
  - Operations consumes sales.quote.status_changed and catalogue.packaging.updated, which nobody emits.
  - Agents consumes tasks.briefing.acknowledged and catalogue.price.changed, which nobody emits.
- Resolution: Platform owns the event registry:

- **Declaration:** each emitter declares EventDef(name, version, payload model, aggregate) in its events.py.
- **Catalogue file:** `lk events catalogue` generates docs/EVENTS.md, which is committed and checked in `npm run check`.
- **Fail fast:** consumer rules and subscriptions referencing an unregistered type fail startup and the contract test.
- **In Slice 0, the integrator fixes the Slice 1–2 names:**
  - Briefing uses commercial's quote events (created, review_requested, issued, marked_sent, won, lost, cancelled, owner_changed). Quote expiry comes from the overdue sweep on valid_until.
  - Briefing uses approvals.proposal.*, identity.membership.{activated, deactivated, roles_changed}, identity.permission_override.changed, pricing.price_list.activated, pricing.price_list_item.superseded, and catalogue.product.updated filtered by changed_groups ⊇ {packaging}.
- **Every event not emitted anywhere** is either added to its emitter's design with a slice tag (e.g. sales.enquiry.* in Slice 1; see the enquiry finding) or removed from the consumer's rule table until that slice.
- **Sequencing rule:** a consumer may reference an event only after the emitter's EventDef is merged.

### [blocker] Single owners for shared kernel utilities: S3-compatible storage with sha256 dedupe, formula-safe CSV, Decimal money, atomic numbering
- Source: platform §1/§3 Files/§7; catalogue §1/§3 core_stored_object/§10; commercial §1 core/money.py/§3.7; operations §0 numbering.next and §9 fin_document_series
- Owner: platform
- Problem: Two designs define the same kernel pieces with colliding file paths and tables.

- **Storage:**
  - Platform: app/core/storage/{base,local,s3,factory}.py, plus file_object and attachment tables, with object key {company}/{purpose}/{yyyy}/{mm}/{id}.
  - Catalogue: app/core/storage/{protocol,s3,local_fs,sniff,models,service,gc}.py, plus core_stored_object with content-addressed keys.
- **CSV writer:**
  - Platform: core/csvsafe.py, guarding = + - @ TAB CR.
  - Catalogue: core/exports/csv_safe.py, which adds LF, leading spaces and full-width variants, and declares itself the ONLY writer.
  - Commercial and operations each call a third name.
- **Money:** core/types.py (platform) vs core/money.py (commercial).
- **Numbering:**
  - Platform: counter upsert plus issued_document_number.
  - Commercial: describes `UPDATE … RETURNING`.
  - Operations: numbering.next(session, …) against a 'document_sequences' table.
  - Finance: its own fin_document_series with an April financial-year reset.

Parallel lanes would create both versions and conflict at merge.
- Resolution: Platform owns one implementation of each, at one path, frozen in Slice 0:

- **app/core/money.py:** Money, Quantity, DecimalStr, quantize(currency).
- **app/core/csv_safe.py:** adopts catalogue's rule set. Numerics stay unprefixed. Output has a BOM and uses QUOTE_ALL. A contract test forbids csv.writer elsewhere.
- **app/platform/files:** a single content-addressed file_object table.
  - UNIQUE(company_id, sha256); purpose and classification columns.
  - Storage key `{company}/sha256/{ab}/{sha}`.
  - catalogue_product_media and quote_document reference file_object.id.
  - sniff.py lives in platform/files.
- **app/platform/numbering:**
  - API: `allocate(uow, sequence_key, document_date, branch_id=None) -> DocumentNumber`.
  - Reset policies: never | yearly | financial_year_apr, so finance uses it too and fin_document_series is dropped.
- Catalogue and operations designs drop their duplicate tables and modules.

### [blocker] Seed only fictional records; tests derive expected greetings and figures from records; acceptance fixtures for scenarios A–N
- Source: briefing §18; commercial §1/§11; agents §18; frontend §18; platform §15
- Owner: briefing
- Problem: Four fixture worlds disagree.

- **Company:** 'crown-demo / Crown Decor (Demo)' vs 'Crown Decor Pvt. Ltd. (demo)'.
- **Customer and product:**
  - Briefing: Nordhaus Interiors GmbH, LK-OT-0450.
  - Agents: Nordhaus Möbel GmbH, LK-TRAY-OAK-M.
  - Commercial: Maison Clair (where briefing has Maison Atelier SARL).
- **Price list and prior quote:**
  - Agents: prior won quote LK-QT-2026-0003 on price list EXP-EUR-2026 v3.
  - Briefing: quotes 0035–0041 and no won quote.
- **Personas:**
  - Frontend: Ravi is restricted sales, Arjun is operations, Priya is finance.
  - Briefing: Ravi is operations (branch scope), Arjun is a new sales hire, Priya is admin, Ananya is finance, Kabir is the restricted user.
- **Frozen clock:** 03:30Z (frontend) vs 03:25Z (briefing).
- **Expected due label:** 'Today, 5:00 PM' vs 'Today 18:30'.

Every cross-module test would encode a different truth.
- Resolution: Create one fixture world, backend/app/seed/world/, with briefing's designer as steward and the integrator approving changes:

- **world/keys.py** holds the constants:
  - People and roles: Sahil (management), Meera and Neha (sales, own scope), Ravi (operations, branch), Kabir (restricted warehouse_assistant), Arjun (new sales hire), Ananya (finance), Priya (admin).
  - Parties: Nordhaus Interiors GmbH, Maison Atelier SARL, Berg & Co AB, Thornbury Kitchens Ltd.
  - Product: LK-OT-0450 oak tray, carton 24, EUR 24.0000 on EXP-EUR-2026.
  - Prior won quote: LK-QT-2026-0003, 240 pcs.
  - D0 clock: Mon 2026-10-12 08:55 IST.
- **Per-module files:** world/catalogue.py, world/commercial.py, world/tasks.py, and so on.
- **Creation rules:**
  - Entities are created only through services at clock offsets.
  - Each entity carries a slice tag and is seeded only when its producing feature exists. For example, the 'yesterday's sample' clause appears from Slice 2.
  - Expected briefing sentences per slice live next to the fixtures.
- **Consumers:** frontend e2e and agents tests import keys via test-support 'fixture references', never literals.

### [blocker] Real PostgreSQL for integration and concurrency tests; restore rehearsal proven locally (scenario M); local dev services with a repeatable start command
- Source: environment; platform §2/§15/Risks; briefing §2 (btree_gist EXCLUDE); catalogue §3/§6 (pg_trgm); commercial §2.2 (btree_gist); operations §14; frontend §18
- Owner: platform
- Problem: **pgserver is unsuitable.**
- Its 0.1.4 release (2024-06-08) is the last.
- It ships wheels for cp39–cp312 only.
- It bundles PostgreSQL 16.2, 13 patch releases behind.
- Its published build script builds no contrib modules, so no pg_trgm and no btree_gist.
- pg_dump/pg_restore presence in the Windows build is undocumented.
- Its 'server stops with owning process' semantics are fragile when several worktree processes share it.

The briefing EXCLUDE constraint and the restore-rehearsal tests would fail or diverge between Docker and pgserver, and conditional pg_trgm code paths double the behaviours to test.

**Docker is not a good default either.** The daemon is down (AutoStart false). With no .wslconfig the VM can claim about 7.8 GB. C: is 87% full.

**winget/EDB installer** needs UAC elevation and installs a Windows service, which the agent cannot approve.
- Resolution: **Primary:** EDB portable Windows x64 binaries, PostgreSQL 17.11.
- No admin rights or service. Includes initdb, pg_ctl, pg_dump, pg_restore and contrib.
- Unpack outside the spaced repo path, to D:\lk-dev\pgsql17. The download needs the user's approval.
- `lk devdb init|start|stop|status` wraps pg_ctl for one shared cluster at D:\lk-dev\pgdata on 127.0.0.1:54329.
- Databases per worktree: lk_wt{N}, plus lk_wt{N}_tpl for tests.
- LK_PG_BIN_DIR is used for backup and restore.

**Secondary:** docker-compose postgres:17, only when the user chooses to start Docker Desktop.

**Remove:**
- pgserver from dependencies, and the dev.mjs auto-fallback.
- The PG 16.2 baseline: target PG 17 and avoid PG18-only features.

**Make contrib mandatory:** pg_trgm and btree_gist become required extensions created in the first owner migration, failing fast if absent. This deletes catalogue's and commercial's conditional code paths.

### [blocker] Review/approve references a versioned proposal; separation of duties; recheck at execution (prompt <agent_experience>; scenario C 'review'; management decisions in scenario A)
- Source: commercial §0/§3.3 (request_approval + in-transaction callback); agents §4/§9 approvals module; briefing §9 (approvals.decide, eligible_approvers); platform (none)
- Owner: agent_voice_whatsapp
- Problem: Slice 1 needs approvals for quote internal review and for Sahil's three decisions. Three incompatible contracts exist and no single slice-1 owner is defined:

- **Commercial:** `request_approval(target_kind, target_id, content_hash, approver_permission)` plus a decision callback.
- **Briefing:** `decide(proposal_id, expected_version)` and `eligible_approvers`, consuming agents.proposal.*.
- **Agents:** a full policy engine with levels, authorities, action_refs, executors and receipts in slice 1.

Commercial's lane cannot finish submit_review without an interface.
- Resolution: The approvals module (agents designer) freezes this minimal Slice-1 interface in Slice 0, with a stub so lanes can proceed:

**Service functions**
- `submit(uow, kind, targets[{type, id, version}], content_hash, amounts, policy_key)` returns a Proposal.
- `decide(uow, proposal_id, expected_version, decision, content_hash, comment)`.
- `eligible_approvers(uow, proposal)`.
- `register_handler(kind, on_approved, on_rejected)`, executed in the decision transaction.

**Tables**
- proposal, proposal_target.
- proposal_decision, with the separation-of-duties CHECK.

**Policy**
- One rule per action_key, read from a typed setting. Example: quote review on_exceptions when a price override is present or the quote is below the minimum.

**Events:** approvals.proposal.{submitted, approved, rejected, invalidated, expired}.

**Expiry:** a job.

Quote internal review uses kind `sales.quote.review`.

**Deferred to Slice 3:** policy versioning, levels, authorities, action_refs/nonces and undo.

### [major] Sales briefing covers enquiries, replies and quote expiry; scenario C's 'usual oak tray' request; Sales area includes enquiries
- Source: briefing §4 (sales.customer_replies, sales.enquiries, issue key msg:{message_id}) and §18 (Meera 'Two customer replies…'); frontend §4 (/sales/enquiries is S4); channels arrives in slice 3
- Owner: commercial
- Problem: No design owns a customer-message or enquiry entity before Slice 3–4. Yet briefing's slice-1 rule families, the msg:* root-cause key and Meera's expected overview sentence and section counts (A-03, A-06) depend on sales.customer_message.* and sales.enquiry.* events. Briefing tests would be written against events no lane emits.
- Resolution: Commercial adds a minimal sales_enquiry entity in Slice 1, in its own module.

**Columns**
- party_id, contact_id
- channel (manual | email | whatsapp | phone), received_at
- body (provenance=external), status (open | replied | quoted | closed)
- owner_user_id, linked quote ids

**Actions:** create, assign, mark_replied, link_quote, close.

**Events:** sales.enquiry.{received, assigned, replied, quoted, closed}.

Briefing keys customer-reply issues on `enquiry:{id}`. From Slice 3, channels creates enquiries from customer WhatsApp messages. The minimal enquiry list and detail UI moves from S4 to S1.

### [major] Scenario C: resolve the customer's usual order from fixtures and use current EUR export pricing
- Source: commercial §3.3 and §12 (slice 1 has review, mark_sent, cancel, delete; full status machine in slice 2); agents §18 find_usual_order uses the latest won quote; commercial §9 find_repeat_quote_basis
- Owner: commercial
- Problem: The 'usual order' basis is the latest won quote, but mark_won is not in commercial's Slice 1. The prior won Nordhaus quote therefore cannot be created through services. The alternatives are bypassing services or waiting for Slice 5 migration.

The tool is also named differently in the two designs (find_usual_order vs find_repeat_quote_basis).

The fixtures' 'awaiting approval' override quotes require review_policy=on_exceptions, while commercial's default is never.
- Resolution: - Include `mark_won`, with accepted_revision_id, in Slice-1 transitions.
- Seed the prior quote through services: create, mark_sent, mark_won, at back-dated clock offsets.
- Implement one service, `sales.service.find_repeat_quote_basis`, exposed as the agent tool `find_usual_order`.
- Demo seed sets quote_settings.review_policy=on_exceptions. Record this as a demo assumption in DECISIONS.

### [major] One source of truth for schemas and generated API types; 'Decimal end to end; never floats'
- Source: platform §2/§13; frontend §3; commercial invariants (money as decimal strings); platform and frontend contract tests
- Owner: platform
- Problem: Pydantic v2 emits a number-or-string JSON Schema for Decimal in validation mode. FastAPI's default separate input/output schemas therefore produce request types that accept number, so floats can reach the API, and the 'money fields are strings' contract tests fail for request bodies.

Other API conventions also diverge:
- **Prefix:** /api (platform) vs /api/v1 (frontend).
- **Session endpoint:** GET /auth/session vs GET /session/bootstrap.
- **Allowed actions:** `_actions` vs `capabilities` vs `allowed_actions`.
- **Error codes:** 'version_conflict' vs 'ITEM_CHANGED' and 'RECOMMENDATION_STALE'.
- **Stale proposal status:** 412 vs 409.
- **CSRF scheme:** synchronizer token vs signed double-submit.
- **Quote routes:** /api/quotes vs /api/sales/quotes/{id}/convert-to-order.
- Resolution: In Slice 0, write docs/architecture/api-conventions.md and ship the matching code. These choices are final:

- **Decimals:** `DecimalStr = Annotated[Decimal, BeforeValidator(reject_float), PlainSerializer(str, return_type=str), WithJsonSchema({type: string, pattern: '^-?\d{1,14}(\.\d{1,4})?$'})]`, used by Money and Quantity. A contract test walks both input and output components for any number-typed money or quantity field.
- **Prefix:** `/api/<module>/...`, unversioned, because one client is generated from the same repo. Webhooks stay at /api/webhooks/*.
- **Session:** a single `GET /api/identity/session` bootstrap. The ui module contributes its fields through a registry hook.
- **Allowed actions:** `capabilities: {action: {allowed, reason_code}}` plus `allowed_transitions` everywhere.
- **Errors:** lower_snake_case problem+json codes. All staleness and version conflicts return 409 with a `code`.
- **CSRF:** platform's synchronizer token (lk_csrf cookie plus X-CSRF-Token) plus the Origin check.
- **Routes:** resources nest under their owning module, e.g. /api/sales/quotes and /api/orders/from-quote/{quote_id}.

### [major] Next.js + TypeScript stack using maintained compatible stable releases, locked
- Source: environment / package metadata: openapi-typescript 7.13.0 peer typescript ^5.x; typescript-eslint 8.71.1 peer typescript >=4.8.4 <6.1.0 and eslint ≤^10; eslint-config-next 16.4.0 depends on eslint-plugin-react ^7.37 (peer eslint ≤^9.7); TS 7.0 ships no JS API
- Owner: frontend_verification
- Problem: The 'latest' list says typescript 7.0.2. Installing it breaks openapi-typescript (npm ERESOLVE on the peer dependency, and the code needs the compiler API) and typescript-eslint type-aware rules. TS 6.x would still violate openapi-typescript's ^5.x peer.

ESLint 10 would violate eslint-plugin-react's peer range. The frontend design pins TS correctly but leaves ESLint unpinned.
- Resolution: - Pin `typescript ~5.9.3`, `eslint ^9`, and eslint-config-next 16.4.0 (which brings typescript-eslint 8.x). Keep other versions per the latest list.
- Use exact versions in package-lock and `npm ci` only.
- Do not use `--legacy-peer-deps`.
- Add `npm ls typescript eslint` to `npm run check`.
- Re-evaluate when TypeScript 7.1 ships its API and openapi-typescript widens its peer range. Record in DECISIONS.

### [major] Python FastAPI backend on maintained releases; locked dependencies
- Source: platform §1 (Python 3.12 because of pgserver; custom uuid7); environment (3.12.10 and 3.14.6 installed; uv absent)
- Owner: platform
- Problem: Python 3.12 was chosen only because pgserver lacks cp313+ wheels. Once pgserver is dropped, that reason disappears. 3.12 is security-only until 2028.

The needed Windows wheels exist for 3.14:
- psycopg-binary 3.3.6 (cp314)
- Pillow 12.3.0 (cp314)
- argon2-cffi-bindings (cp310-abi3)
- uharfbuzz (abi3)
- ReportLab 5.0.1 (pure Python)

3.14 adds a standard-library uuid.uuid7, which would remove a hand-written generator.

One risk: `uvicorn[standard]` pulls httptools/uvloop, which may lack cp314 Windows wheels and would trigger an MSVC source build.
- Resolution: - Choose Python 3.14 (`requires-python = "==3.14.*"`, .python-version 3.14).
- Gate it in Slice 0 with `uv lock && uv sync --locked --no-build` (UV_NO_BUILD=1). Any sdist build fails fast. If the gate fails, fall back to 3.12 and record why in DECISIONS.
- Use plain `uvicorn` with watchfiles, not the [standard] extra.
- Use stdlib uuid.uuid7() and drop core/ids generator code.
- Keep tzdata as a dependency.

### [minor] Repeatable setup and start command ('npm run setup' / 'uv sync')
- Source: environment: uv not on PATH (only a uv-managed python3.12.exe shim exists); platform §15
- Owner: platform
- Problem: `npm run setup` begins with `uv sync`, which fails on this machine.

Slice 0 also needs several downloads, each of which needs explicit user approval in this environment:
- uv
- the EDB PostgreSQL zip
- Noto TTF fonts
- the Playwright Chromium build
- Resolution: Slice 0, step 1: ask the user once to approve the bootstrap downloads, then:

- `python -m pip install --user uv==0.13.0`, or winget astral-sh.uv.
- EDB PostgreSQL 17 zip.
- Noto Sans and Noto Sans Devanagari static TTFs with OFL licence.
- `npx playwright install chromium`.

Also:
- `scripts/dev.mjs check-prereqs` prints exact missing tools and versions, without auto-installing.
- Record versions in BUILD_STATE.

### [major] Byte-exact fixtures for webhook signature, replay and import hash tests (scenarios G, K, M); resumable multi-session work in worktrees
- Source: environment: git system core.autocrlf=true, core.symlinks=false, core.longpaths unset (LongPathsEnabled=1 in the OS)
- Owner: integrator
- Problem: With autocrlf=true, checkouts in fresh worktrees rewrite LF to CRLF in text fixtures. That silently breaks:
- HMAC-signed WhatsApp fixture bodies;
- sha256-manifested EJSON/CSV migration fixtures and import re-hash tests;
- shell-style scripts.

The failure appears only in some worktrees and is hard to diagnose. Deep node_modules and .next paths in nested worktrees can also exceed git's path limit without core.longpaths.
- Resolution: Commit .gitattributes before any fixture is added:

```
* text=auto eol=lf
*.png *.jpg *.webp *.pdf *.xlsx *.ttf *.woff2 *.zip binary
backend/tests/fixtures/** -text
*.ps1 *.cmd eol=crlf
```

Also:
- `git config core.longpaths true` (repo-local) at init.
- Add a unit test that recomputes fixture sha256 values against a committed manifest, so any rewrite is caught immediately.

### [major] Local development and Playwright on Windows; Origin/CSRF checks; parallel coding agents in worktrees
- Source: environment: repo path 'D:\Lamikraft ERP' contains a space; Node 24; platform §4 Origin check against LK_PUBLIC_ORIGIN; frontend §3/§18 ports 8100/3100
- Owner: platform
- Problem: - **Paths with spaces:** they break unquoted shell-string spawns, some pg_ctl invocations and data-dir arguments.
- **localhost vs 127.0.0.1:** Node can resolve 'localhost' to ::1 while uvicorn binds 127.0.0.1. If the browser origin is localhost but LK_PUBLIC_ORIGIN is 127.0.0.1 (or the reverse), every write gets 403 from the Origin check, and the session cookie lives in a different cookie jar.
- **Port collisions:** parallel worktrees all default to ports 3000/8000/3100/8100 and the same DB names.
- Resolution: - **Hosts:** use `127.0.0.1` everywhere (LK_API_INTERNAL_URL, LK_PUBLIC_ORIGIN, Playwright baseURL and webServer.url). Never use 'localhost'. Dev startup refuses a mismatched browser origin with a clear message.
- **Per-worktree env:** `lk env init --slot N` writes .env with web 3000+10N, api 8000+10N, e2e 3100+10N/8100+10N, DB lk_wt{N}/lk_wt{N}_tpl, and storage var/ local to the worktree.
- **Spawning:** dev.mjs and the CLI spawn with argument arrays, never shell strings. Quote paths in package scripts.
- **Locations:** create worktrees at D:\lk-wt\<lane> (short, no spaces). PostgreSQL binaries and data live in D:\lk-dev.
- **Smoke test:** one check runs `npm run dev` from the spaced main path.

### [major] Long sessions with several coding sub-agents in parallel worktrees on 12 logical CPUs and 15.7 GB RAM
- Source: environment; frontend §18 (4 Playwright workers; next build && next start); Docker WSL default memory
- Owner: integrator
- Problem: Approximate per-lane memory:

| Component | Memory |
|---|---|
| next dev (Turbopack) | ~1–1.5 GB |
| next build | 2–3 GB peak |
| uvicorn + worker | ~0.3 GB |
| Playwright Chromium, per worker | ~0.3 GB |
| Claude Code agent process | ~0.3–0.5 GB |
| Docker/WSL VM (if used) | up to ~7.8 GB |

Four lanes each running e2e would thrash or hit OOM and produce flaky timing-sensitive concurrency tests.
- Resolution: - At most 3 concurrent lane agents plus the integrator.
- Lanes run module unit, integration and contract tests plus `npm run check`. They do not run next build or Playwright.
- Only the integrator runs `next build` and Playwright (workers=2 locally), guarded by D:\lk-dev\e2e.lock.
- Use native PostgreSQL as the default. Capping the WSL VM memory via .wslconfig, if Docker is used, is a user decision and agents must not change it.
- Concurrency tests use explicit barriers, never timing assumptions.

### [major] Streaming progress for agent runs and same-origin topology without CORS
- Source: frontend §3/§5 (rewrites beforeFiles; SSE for agent runs) and Risks; agents §5/§16 (202 + SSE); third-party Next 16 report that rewrites buffer text/event-stream
- Owner: frontend_verification
- Problem: Next 16 external rewrites are reported to read the upstream body to completion before forwarding, with no config flag to disable it. Agent-run SSE would then arrive all at once.

The frontend design also forbids Next route handlers, which closes off the usual workaround. Large uploads through rewrites are unverified.
- Resolution: **Slice 1**
- Agent progress is polled with `GET /api/agents/runs/{id}?after_seq=` every 500 ms while the run is active. The demo orchestrator finishes in under 2 s.
- Run a Slice-0 spike that measures chunk timing and a 25 MB multipart upload through rewrites, under both `next dev` and `next start`.

**Slice 3**
- If SSE is still buffered, allow exactly one read-only passthrough route handler, src/app/stream/agent-runs/[id]/route.ts, which forwards the cookie and returns upstream.body. Polling remains the fallback.
- Production routes /api directly to FastAPI through the reverse proxy.
- Add an e2e upload-at-size-limit test early in Slice 2.

### [major] PDFs wrap across pages, repeat headers, support Unicode names and €/₹ glyphs; challan and cut-plan PDFs (legacy parity 9/10/11, scenario L)
- Source: commercial §1/§7 ReportLab + Noto Sans; operations §10 challans/templates/challan.html and §7 cut-plan PDF 'SVG plus table'; WeasyPrint Windows docs (MSYS2 + Pango); reportlab 5.0.1 extras (shaping → uharfbuzz)
- Owner: commercial
- Problem: Operations implies HTML-to-PDF via an HTML challan template. On Windows that means WeasyPrint, which needs an MSYS2/Pango install. Two PDF engines would double the font and pagination work.

Other gaps:
- ReportLab embeds only TrueType-outline TTFs, not CFF/OTF or variable fonts. Fontsource packages ship WOFF2 only, so they cannot be reused.
- Devanagari needs HarfBuzz shaping, available through the reportlab[shaping] extra.
- PDF text-extraction tests need a library that no design lists.
- Resolution: - **One engine:** ReportLab for all PDFs (quote, challan, cut plan, invoice) through shared app/core/documents. Commercial owns it and operations reuses it. Delete challan.html.
- **Fonts:** commit static NotoSans-{Regular,Bold}.ttf and NotoSansDevanagari-{Regular,Bold}.ttf with OFL.txt (approved download).
- **Devanagari:** enable `reportlab[shaping]` (uharfbuzz has an abi3 Windows wheel). Verify the output in a Slice-0 probe and a Slice-2 test, or document it as a limitation.
- **Cut plans:** draw boards with reportlab.graphics from placement data, not by parsing SVG.
- **Tests:** add pypdf as a dev dependency for text extraction.

### [major] Typed tools and UI endpoints call the same application services; locks and constraints for stock and numbering; architecture rules enforced
- Source: platform §5 'Making bypass structurally hard' (UoW exposes repos not Session; no text( in modules; every service.py function decorated); operations §1/§3 (session-passing APIs, ordered FOR UPDATE); briefing §6 pg_advisory_xact_lock; commercial §2.4 deferred constraints; catalogue §8/§9.11 FK introspection and is_demo-asserting deletes
- Owner: platform
- Problem: Platform's architecture tests will fail most other designs as written:

- Operations passes `session` into post_movement, numbering.next, outbox.emit and consumers.once.
- Briefing needs advisory locks.
- Commercial needs SET CONSTRAINTS DEFERRED.
- Catalogue needs catalog introspection.

Without sanctioned primitives, lanes will either fight the tests or each invent their own raw-SQL workarounds.
- Resolution: In Slice 0, publish and implement the UoW primitive surface:

- `uow.repo(Model)`
- `repo.get / select / lock(ids, order_by=...)` (ordered SELECT … FOR UPDATE)
- `uow.advisory_xact_lock(namespace, key)`
- `uow.defer_constraints(*names)`
- `uow.emit(event)`, `uow.clock`, `uow.actor`, `uow.allocate_number(...)`
- `uow.system_session(reason)`, allowlisted

Rules:
- Internal helpers take `uow`, never `session`.
- Only public service functions are decorated.
- Raw SQL is allowed only in app/platform/**, app/core/db/** and module `sql.py` files listed in the architecture-test allowlist, with a reason comment.
- Other designers adapt their signatures before Slice 1 starts.

### [major] Company scope on every applicable record and query; simplest design that satisfies requirements
- Source: platform §2 (UNIQUE(company_id,id) on every tenant table, composite (company_id, parent_id) FKs everywhere, plus RLS FORCE)
- Owner: platform
- Problem: Composite tenant FKs on every child relation:
- double the FK columns;
- force explicit primaryjoin and `overlaps=` handling on most SQLAlchemy relationships, because shared company_id columns raise relationship-conflict warnings;
- slow every module designer down.

RLS plus ScopedRepository already gives fail-closed company isolation, and the product launches with one company.
- Resolution: - Cut the blanket composite FKs and UNIQUE(company_id, id).
- Keep RLS (ENABLE+FORCE via the migration helper, NULLIF GUC) and ScopedRepository parent loading.
- Add a contract test that every table with company_id has an RLS policy and that the app role is neither superuser nor BYPASSRLS.
- Keep purpose-specific composite FKs where they carry business meaning, such as quote_line(quote_id, currency).
- List blanket composite FKs as future scope in DECISIONS.

### [major] Slice 1: polished shell, authentication/permissions, tasks/events, saved briefing and the vertical path; build shared infrastructure only as needed
- Source: build prompt <build_order> 1 and final paragraph; platform §17 Slice 1 list
- Owner: platform
- Problem: Platform's Slice 1 includes many things scenario C does not need:
- TOTP MFA with forced enrolment
- invitations with email jobs
- self-service and admin resets
- break-glass and recovery codes
- step-up re-authentication
- session-management UI and exponential lockout
- S3 adapter
- SeaweedFS and mailpit compose profiles
- activity projector and setting revisions

Forced admin MFA also complicates every e2e admin path. This delays the vertical slice by weeks.
- Resolution: **Slice 1 keeps:**
- company and HO branch
- users via CLI and demo seed
- role templates admin/management/sales/operations (no inheritance), resolution with overrides (revoke wins) via API
- opaque sessions, CSRF and Origin checks
- IP/email rate limits with generic errors and a simple lockout counter
- first-admin CLI, demo sign-in links and test-support login
- outbox, jobs and interval scheduler
- idempotency, numbering, typed settings (no revision UI)
- LocalFs files for generated PDFs
- insert-only audit, health checks, log redaction
- route-authz declaration plus the matrix for quote routes

**Moves to Slice 2 (legacy parity):** MFA (required before any non-demo use), invitations and resets, sessions UI, S3 adapter + moto, activity, revisions UI, custom roles.

**Removed:** SeaweedFS and mailpit profiles. Demo email writes .eml files only.

### [major] Saved role-specific daily briefing in Slice 1; voice briefing (Listen to my day) and B scenarios
- Source: briefing §19 Slice 1 vs frontend §20 (Listen S3; tests B in S3); agents slice 3 for voice
- Owner: briefing
- Problem: Briefing's Slice 1 includes features from later slices, contradicting the frontend plan and inflating the critical path:
- voice and chat pins, narration script and demo TTS
- template inheritance to depth 4 with an editor
- per-shift rollover and night shifts
- leave and delegation
- dependencies with recursive-CTE cycle checks under advisory locks
- precompute jobs and the phrasing texts table
- Resolution: **Slice 1:**
- issues, members, tasks, candidates, change_log, history, reminders
- rule consumer for the Slice-1 families: quote review, quote expiry, enquiry replies, approvals, price-list impact, party changes, onboarding
- deterministic engine: priority, sections, top 5, English overview templates
- versions, items, acknowledgements, snooze, mark-handled/dismiss and fallback
- built-in per-role template config in code
- policy defaults from settings
- overdue sweep, Today and Inbox APIs
- default company calendar: Mon–Sat, 09:30–18:30, 04:00 rollover, Asia/Kolkata, plus holidays

**Slice 2:** precompute, leave and delegation.

**Slice 3:** pins, narration, LLM phrasing, hi/hi-Latn, WhatsApp.

**Slice 4:** dependencies and template editor.

### [major] Leave, delegations, quiet hours, weekends and shifts configurable; delegation never widens access
- Source: platform §3 (delegation, user_absence, membership.shift_code/work_time_zone) and §8 (calendar.* settings + calendar service); briefing §2 workcal_* tables and §10
- Owner: briefing
- Problem: There are two calendar implementations, two leave/absence tables and two delegation tables with different semantics:
- **Platform:** permission_keys.
- **Briefing:** task_kinds and include_approvals.

Both designs plan to build them in Slice 1, so they would merge as duplicates with diverging rules.
- Resolution: Make workcal a platform kernel module, app/platform/workcal. The briefing designer writes it, and it is the only calendar API (local_workday, work_date, shift windows, next_working_day).

- **workcal owns:** calendars, shifts, holidays, user assignments and leave. Delete platform's calendar.* settings, membership.shift_code and user_absence.
- **Identity owns** one `delegation` table with:
  - permission_keys (nullable)
  - task_kinds (nullable)
  - include_approvals
  - the 90-day and no-self CHECKs
- Operations' production capacity calendar reuses workcal shifts.

### [major] PostgreSQL with Alembic migrations; parallel worktrees without merge conflicts
- Source: platform §1 (versions/NNNN_slug.py); operations §10 (one revision per module); all designs add tables
- Owner: integrator
- Problem: Parallel lanes each create revisions from the same head, which produces multiple Alembic heads and conflicting NNNN prefixes.

Autogenerate cannot see RLS policies, triggers (append-only audit, immutable ledgers and revisions) or many CHECK constraints, so drafts look complete while they silently omit the security-critical parts.
- Resolution: - **Linear chain only.** A lane writes its revision locally. On rebase, `lk db reparent` sets its down_revision to the integrator's head.
- **Single head.** `alembic heads` must return exactly one, checked in `npm run check`.
- **Naming.** Files are named `NNNN_<module>_<slug>.py`, with NNNN assigned at merge.
- **No edits after merge.** Merged revisions are never edited. Before the end of Slice 2 the integrator may squash per module.
- **Helpers for the invisible parts.** RLS, triggers and enum CHECKs come only from helpers (tenant_table, enable_tenant_rls, append_only).
- **Contract test.** It compares pg_policies and pg_trigger against the registered models.

### [major] One source of truth for schemas and generated API types; locked dependencies
- Source: frontend §3 (openapi.json + schema.d.ts committed; api:check); every lane adds endpoints and dependencies
- Owner: integrator
- Problem: Every backend lane modifies the generated openapi.json and schema.d.ts, and some modify package-lock.json and uv.lock. Hand-merging these produces types that silently drift from the backend.
- Resolution: - **Generated API files:**
  - Never hand-merge them. On conflict, take either side, then run `npm run api:generate`.
  - The export must be deterministic: sorted keys and stable operationIds `<module>_<verb>_<noun>`.
  - `api:check` is part of `npm run check`.
- **Lockfiles:** only the integrator changes package-lock.json and uv.lock. Lanes list requested dependencies in docs/lanes/<lane>.md, or regenerate the lock after rebasing and before the merge request.

### [major] Executable integration and concurrency tests on real Postgres; deterministic clock-dependent briefing tests (A/B)
- Source: frontend §18 (CREATE DATABASE … TEMPLATE per test); platform RLS via transaction-local GUC; briefing §18 frozen Clock; platform Timestamps DEFAULT now()
- Owner: platform
- Problem: - **Cloning cost:** cloning a template DB with about 200 tables per test is slow on Windows, so the suite would take tens of minutes.
- **Rollback mode can hide RLS bugs:** a GUC left from an earlier unit of work persists inside one outer transaction, masking fail-closed bugs.
- **Async effects:** integration tests need outbox and job effects without a running worker.
- **Clock mismatch:** DB-default created_at/occurred_at values use the real now() while services use a frozen Clock. 'Changes since last ack' and rollover tests then compare incompatible times.
- Resolution: **Test modes**
- **Default:** a per-test SAVEPOINT session (SQLAlchemy `join_transaction_mode="create_savepoint"`), connected as lk_app.
- **`@pytest.mark.committed`:** clones from the template DB. Use it for RLS, concurrency, worker and backup tests.

**Helpers**
- `drain_events(uow)` runs the outbox relay and due jobs inline.

**Clock**
- One Clock lives in app/core/time.py, with a per-company override in the test environment only.
- Every business timestamp (occurred_at, fact_at, seeded created_at, due_at) is set from Clock in Python. DB now() is used only for infrastructure: job leases and heartbeats.

Measure clone time in the Slice-0 spike and record it.

### [major] Never put authentication tokens in download query strings; browser review links are short-lived references, not authentication
- Source: build prompt <legacy_parity_and_corrections> #1 and <voice_and_whatsapp>; agents §1 (platform.storage S3 presigned URLs ≤5 min) and §14 (TTS short-lived URL); platform §9 (no presigned URLs)
- Owner: agent_voice_whatsapp
- Problem: The agents design assumes presigned S3 URLs for media and TTS audio. A presigned URL is a bearer credential in the query string, which the prompt forbids. Platform explicitly rules them out.
- Resolution: - TTS output and voice uploads are stored as file_object rows (purpose voice_audio, classification restricted, purge_at 7 days).
- They are served via the cookie-authenticated `/api/files/{id}/content` stream with no-store.
- Remove presigned URLs from all designs.
- WhatsApp media is fetched server-side with the bearer header only.

### [major] Slice 1 command surface and vertical path; do not advertise execution tools before policy and idempotency exist
- Source: agents §19 Slice 1 (durable runs, SSE, action_refs, policy engine, receipts, trace); frontend §20 (assistant rail S3; C e2e in S1); build prompt <build_order> 1
- Owner: agent_voice_whatsapp
- Problem: The agents Slice 1 includes several things the vertical path does not need:
- the full durable runtime with SSE
- armed action references and nonces
- policy versioning
- execution receipts and the trace UI

It also defines a separate ToolContext that duplicates platform's ActorContext.
- Resolution: **Slice 1**
- The deterministic English demo intent grammar runs as an `agent.run` job, the same path later used for real providers, with client polling.
- Tools: resolve_party, find_usual_order, resolve_product, resolve_price, calculate_quote, draft_quote, get_daily_briefing.
- Cards (QuoteDraftCard, ClarificationCard, ErrorCard) are built by the server.
- ID-provenance grounding is enforced.
- ToolContext is a thin wrapper over ActorContext plus run fields, so there is one identity type.

**Slice 3**
- action_refs, memory, automations, the numeric-claim checker, the Anthropic adapter, strict schema export and the trace endpoint.

The execute tool stays hidden until approval handlers are registered with idempotency.

### [major] Atomic unique counters preserve LK-QT-YYYY-NNNN, DC-YYYY-NNNN and CP-NNNN; document yearly-reset settings; never reuse numbers
- Source: platform §7 (quote default yearly reset); commercial §3.7 and Decisions (quote default never); CURRENT_STATE_SPEC §5 (quote counter never resets) and §10.1 #13; operations §4 challan yearly
- Owner: commercial
- Problem: Two designs default the quote counter's yearly reset in opposite ways. The choice changes:
- the numbers users see in January;
- migration counter seeding (per-year maximum vs global maximum);
- the numbering tests.

It is a business-policy choice that neither design flags as needing owner confirmation.
- Resolution: - One numbering engine (platform) with a reset_policy setting.
- **Proposed defaults, until the owner confirms:**
  - LK-QT: `never` (legacy continuity, no surprise renumbering).
  - DC: yearly (legacy).
  - CP: never.
  - Finance: financial_year_apr.
- Migration seeds counters according to the active policy.
- Record this in DECISIONS and in the 'business-policy choices needing confirmation' list in BUILD_STATE.

### [minor] Replace Emergent storage with S3-compatible storage; avoid speculative infrastructure
- Source: platform §1/§15 (SeaweedFS compose profile); catalogue Decisions (local_fs + moto); MinIO community images discontinued Oct 2025
- Owner: platform
- Problem: MinIO is not an option, which is confirmed and correctly handled. However, a SeaweedFS compose profile adds an image to pin and debug and still depends on Docker, while moto already provides the contract tests.
- Resolution: - Ship LocalFsStorage in Slice 1.
- Add S3Storage in Slice 2, contract-tested with moto (one suite for both adapters).
- Drop the SeaweedFS and mailpit profiles. A real S3 or S3-compatible endpoint check becomes a documented pre-production step with credentials.

### [minor] Durable small worker; real provider adapters
- Source: agents §1/§12 (LISTEN/NOTIFY wake-up, AsyncAnthropic), §16 tests (respx), import-linter rule; platform §6 (polling, sync SQLAlchemy)
- Owner: agent_voice_whatsapp
- Problem: psycopg async does not work with the default Windows ProactorEventLoop. The LISTEN/NOTIFY assumption contradicts platform's polling worker. respx and import-linter are extra dependencies that duplicate httpx.MockTransport and platform's AST architecture tests.
- Resolution: - Use sync everywhere: the sync `anthropic.Anthropic` client in worker threads, polling instead of LISTEN/NOTIFY, and a ban on psycopg async (an architecture test greps for AsyncConnection).
- Use httpx.MockTransport instead of respx.
- Use platform AST tests instead of import-linter.

### [minor] Exactly-once handler effects for duplicate and out-of-order events (scenarios B and I)
- Source: operations §0 consumers.once + processed_events; briefing §2 event_consumptions; platform §6 per-handler job dedupe + fence
- Owner: platform
- Problem: Three deduplication mechanisms exist for the same guarantee, built by two different lanes.
- Resolution: Platform provides `consumers.once(uow, consumer, event_id)` on one `event_consumption` table, used inside handlers that can be reached by more than one path. The default path relies on the job dedupe_key and the fenced completion.

### [minor] Every view reachable directly; deep-linked detail tabs
- Source: catalogue §1/§15 (apps/web/app/(app)/products/[productKey]/[tab], apps/web/components); frontend §2/§4 (apps/web/src/app, UUID detail routes, /go/[type]/[key])
- Owner: catalogue_imports_migration
- Problem: The two designs use different directory roots and a conflicting product URL identity. Product keys containing '/', '%' or '#' break dynamic segments.
- Resolution: - Use the apps/web/src/ layout.
- Product detail routes become /products/[productId]/<tab> (UUID).
- /go/product/{productKey} resolves business keys.
- Catalogue frontend files move under src/app/(app)/products and src/features/catalogue.

### [minor] Physical quantities = NUMERIC + explicit unit; clear module boundaries
- Source: platform §2 (NUMERIC(18,6)); operations §1 (NUMERIC(18,4)); table names bare (platform, commercial) vs prefixed (catalogue_, inv_, chl_, tasks_); preference stores in membership.preferences, user_ui_preferences and briefings_user_prefs; platform ai_usage_event vs agents ai_call_log
- Owner: platform
- Problem: These are small inconsistencies that create migration churn and duplicate tables:
- quantity scale differs between designs;
- table naming is inconsistent;
- two AI usage tables exist;
- three preference stores have unclear precedence.
- Resolution: Settle these in conventions.md:

- **Numeric scales:**
  - Transactional quantities: NUMERIC(18,4) + uom_code.
  - Dimensions: NUMERIC(12,3) mm.
  - FX rates: NUMERIC(20,10).
- **Table names:** `<module>_<entity>` for module tables; unprefixed for platform kernel tables.
- **AI usage:** drop platform ai_usage_event; agents' ai_call_log is the single source.
- **Preference stores:**
  - membership.preferences: locale, time zone, language.
  - ui module: theme, sidebar, rail.
  - briefings: briefing preferences.
  - None of them may hold mandatory controls.

### [minor] Tailwind 4 setup; Playwright browser checks on Windows
- Source: frontend §1/§18; environment (Chromium builds 1217–1243 cached; npm 12; npm workspaces)
- Owner: frontend_verification
- Problem: Tailwind 4 relies on native optional binaries (oxide, lightningcss). Installing with `--omit=optional`, or generating the lockfile on one OS and installing on another, can drop them.

Next.js can warn about, or mis-infer, the Turbopack root with root-level npm workspaces.

Playwright 1.64 may need a newer Chromium build than the ones cached. Fake-media flags must be set explicitly.
- Resolution: - Use `@tailwindcss/postcss` in postcss.config.mjs, `@import "tailwindcss"`, `@theme inline` with `--color-*: initial`, and `@plugin` for tailwindcss-react-aria-components.
- Never pass --omit=optional. If Linux CI is added later, regenerate or verify the lockfile on Linux.
- Set `turbopack.root` and `outputFileTracingRoot` to the repo root.
- Run `npx playwright install chromium` in setup (approved download). WebKit is optional.
- Chromium launch args: `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream`.
- `workers: 2` locally.

### [minor] Admin briefing access tasks; new employees get onboarding (scenario A-15)
- Source: briefing §4 (identity.access.requested/decided, identity.user.activated) and §18 (Kabir access request, Arjun activated D0 08:00); platform has no access-request feature and no 'activated' event
- Owner: platform
- Problem: The Slice-1 fixtures and rule families depend on a feature and an event that the platform design does not provide.
- Resolution: - Platform emits `identity.membership.activated` when a membership becomes active (seed, CLI, or invitation acceptance in Slice 2).
- Drop access requests from the Slice-1 fixtures and the admin.access family. Add a minimal access-request flow in Slice 2 alongside invitations, or derive admin tasks from pending invitations.

## Recommended slice plan

## Recommended slice plan

### Conventions for this plan
- **Integrator** is the main coding agent.
  - It owns `main`, all shared files and `docs/BUILD_STATE.md`.
  - It is the only agent that runs `next build` and Playwright.
- **Lanes** are parallel coding agents. At most 3 run at once on this machine.
  - Each lane works in its own worktree at `D:\lk-wt\<lane>`, with its own `.env` slot (`lk env init --slot N`).
  - Each lane writes `docs/lanes/<lane>.md` (status, evidence, next step). The integrator folds this into BUILD_STATE at merge.
- **Merge order** within a wave follows dependency order.
  - After each merge the integrator runs `npm run api:generate`, `npm run check` and `npm run test:api`.
  - Lanes rebase after every integrator merge.

### Slice 0: bootstrap, contracts and spikes (integrator only, no lanes)

**1. Environment** (one user approval for the downloads)
- Install uv 0.13.0.
- Download EDB PostgreSQL 17.11 portable binaries to `D:\lk-dev\pgsql17`.
- Download static Noto Sans and Noto Sans Devanagari TTFs with their OFL licence.
- Run `npx playwright install chromium`.
- Run `git init`, then commit `.gitattributes` (LF, binary, `fixtures -text`) and `.gitignore` before anything else. Set `core.longpaths true`.
- Python gate: run `uv lock && uv sync --locked --no-build` on 3.14. If any package needs a source build, fall back to 3.12 and record why.

**2. Spikes** (time-boxed; results go to `docs/DECISIONS.md`)
- **PostgreSQL:**
  - `initdb`, then create roles `lk_owner` and `lk_app`.
  - `CREATE EXTENSION pg_trgm, btree_gist`.
  - Prove RLS fails closed when running as `lk_app`.
  - Round-trip `pg_dump -Fc` and `pg_restore`.
  - Time `CREATE DATABASE … TEMPLATE`.
- **ReportLab:** € ₹ £ Ł Ω Ж with embedded Noto, a 150-row table with a repeated header row, and Devanagari with `shaping`.
- **Next 16.4 rewrites to 127.0.0.1:** login cookie, CSRF and Origin checks, a 25 MB multipart upload, and server-sent-event chunk timing under `next dev` and `next start`.
- **Toolchain:** TypeScript 5.9 + ESLint 9 + openapi-typescript generation.

**3. Contract documents in `docs/architecture/`** (frozen before lanes start; changes only through an integrator PR)
- `conventions.md`:
  - module list and table prefixes; IDs (stdlib `uuid7`)
  - `Money` / `Quantity` / `DecimalStr` types and NUMERIC scales
  - the Clock rule and time zones
  - UoW primitives and the raw-SQL allowlist
- `api-conventions.md`:
  - `/api/<module>/...` paths and problem+json snake_case error codes
  - the `capabilities` field, Idempotency-Key, pagination
  - session bootstrap and CSRF
  - streaming policy: polling now, a spike in Slice 3
- `permissions.md`: grammar, verb set and the single legacy mapping table.
- `events.md`: event names for Slices 1–2, with emitter, payload and consumers. Generated later as `docs/EVENTS.md`.
- `fixtures.md`: cast, D0 clock (Mon 2026-10-12 08:55 IST), keys, and a slice tag per entity.
- `parallel-work.md`: the ownership and sequencing rules below.
- Interface stubs: approvals (submit, decide, eligible_approvers, register_handler), numbering `allocate`, the files API, `consumers.once`, the workcal API.

**4. Skeleton**
- **Backend `app/core`:** config, db/UoW with RLS GUC, money, time/Clock, errors, logging redaction, `csv_safe`, `escape_like`.
- **Backend platform and tooling:**
  - `registry.py` with PermissionDef / EventDef / SettingDef registration
  - outbox, jobs, worker and interval scheduler skeleton
  - Alembic baseline with helpers (`tenant_table`, `enable_tenant_rls`, `append_only`)
  - architecture tests
  - test harness: savepoint mode, committed clone mode, `drain_events`, test-support router (APP_ENV=test only)
- **CLI:** `lk devdb`, `lk env init`, `lk db ensure-roles`, `lk db reparent`.
- **Frontend:**
  - Next 16.4 / React 19.3 / Tailwind 4 tokens / react-aria-components scaffold under `apps/web/src`
  - openapi-fetch client and generation pipeline
  - route manifest with coverage test, shell skeleton, login stub
  - Playwright config: 127.0.0.1, workers 2, fake media flags
- **Scripts:** `npm run setup | dev | check | test:api | test:e2e | api:generate | api:check`. `dev.mjs` spawns processes with argument arrays and kills process trees with `taskkill /T`.

**5. Docs**
- `BUILD_STATE.md` (checkpoint 0)
- `PARITY_MATRIX.md`: every legacy module, field group, workflow and bug row, each with a target slice
- `DECISIONS.md`, seeded with this review's decisions
- runbook: `local-dev.md`

**Exit criteria**
- From the spaced path `D:\Lamikraft ERP`, `npm run setup && npm run dev` starts native Postgres, the API, the worker and the web app.
- `/api/health/ready` returns 200.
- `npm run check` is green: lint, tsc, vitest, pytest unit, architecture tests, `alembic heads == 1`, `api:check`, fixture sha256 manifest.
- A sample RLS isolation test passes in committed mode as `lk_app`.
- A 2-connection barrier concurrency test passes.
- Spike evidence is recorded.

### Slice 1: shell, authentication, briefing and the quote vertical (scenario C)

**Wave 1** (3 backend lanes in parallel)

**L1 platform** (`backend/app/platform/{identity,authz,org,numbering,settings,files,audit,system}`)
- Opaque sessions, CSRF and Origin checks, login, rate limits with generic errors, simple lockout.
- Role templates admin / management / sales / operations, plus placeholder templates. Effective resolution with revoke-wins overrides.
- First-admin CLI, demo seed users, test-support login, demo sign-in links.
- Numbering for `sales.quote` and `sales.custom_product`.
- Settings: company profile, document terms, quote defaults.
- LocalFs storage for generated documents.
- Audit, and the harness for the route-authorization matrix.

**L2 sales core** (`backend/app/modules/{catalogue,parties,pricing,commercial,sales}`, `app/core/documents`)
- Catalogue tables with full columns; read and search APIs (ILIKE + pg_trgm); seed the oak tray.
- Parties (minimal).
- `sales_enquiry` (minimal).
- Seeded price lists with Pass A resolution.
- Engine v1 with rule set.
- Quotes:
  - header, lines and snapshots
  - persisted totals, numbering, versions
  - transitions: submit_review, withdraw, approve/reject via the approvals interface, mark_sent, mark_won, cancel, delete draft
  - issued revision, ReportLab PDF
  - quote list and detail with `capabilities`
- `sales/tools.py`: find_usual_order, resolve_price, calculate_quote, draft_quote.

**L3 work** (`backend/app/platform/workcal`, `backend/app/modules/{tasks,briefings}`)
- Default calendar.
- tasks / issues / change_log / reminders.
- Rule consumer for the Slice-1 families.
- Deterministic engine, versions, acknowledgements, snooze, mark handled / dismiss, fallback.
- Overdue sweep; Today and Inbox APIs.
- Builds against the event catalogue, using fixture events until L2 merges.

**Wave 2** (starts after L1 and L2 merge)

**L4 agents demo** (`backend/app/modules/{agents,approvals}`)
- Minimal approvals implementation (replaces the stub) and the review handler for `sales.quote.review`.
- Demo orchestrator as an `agent.run` job with a polling API.
- Server-built cards and ID-provenance grounding.

**L5 web** (`apps/web/src/app/(app)/{today,inbox,sales}`, `(auth)`, `src/features/{today,inbox,quotes,assistant}`)
- Shell (desktop, tablet, phone), login.
- Today with command bar and card.
- Inbox.
- Quote workspace: header, lines, quantity edit, server totals.
- Review page and PDF link.
- Minimal enquiries list.

**Checkpoint 1a** (BUILD_STATE), all passing on `main`:
- **Scenario C (API level):**
  - `test_scenario_c_nordhaus_repeat_quote`
  - snapshot immunity
  - `created` event leads to an owner-scoped next action
- **Scenario D:** engine unit and property tests.
- **Scenario F subset:**
  - quote IDOR matrix
  - 40-way concurrent numbering
  - optimistic 409
- **Scenario A subset:**
  - briefing scope
  - restricted direct URLs
  - aggregate-leak property
- **Scenario B subset:**
  - no manufactured versions
  - replay and out-of-order events
  - snooze bounds
  - engine-failure fallback
  - midnight rollover

**Checkpoint 1b:**
- Playwright for login, Meera's and Sahil's Today, and scenario C on desktop and phone.
- Scenario D: surcharge toggle agrees across UI, API and PDF.
- Keyboard journey Today → quote → review.
- axe on Slice-1 routes in both themes.
- Screenshots inspected; defects fixed.
- Evidence (command summaries and screenshot paths) recorded.

### Slice 2: legacy parity

Waves of at most 3 lanes, in this order:

**L1 platform-2**
- TOTP MFA, required for admins.
- Invitations and resets, with demo `.eml` email.
- Custom roles with inheritance and deny; overrides UI; role simulator.
- Delegation table and workcal leave.
- Notes, attachments and activity.
- Search provider registry and global search.
- S3 adapter with a moto contract suite.
- Image variants.

**L2 catalogue and imports**
- Forms, media and taxonomy operations.
- Facets, stats and completeness.
- All 7 import types: staging, quarantine, rollback.
- Lookups, demo reset.

**L3 commercial-2**
- Price-list CRUD: activate, supersede, history.
- FX with approval, Pass B, currency change.
- Full state machine; revision compare and restore; duplicate.
- Custom products with promotion.
- CSV exports and settings UIs.

**L4 operations documents**
- Challans as documents only, with PDF, print, CSV, summaries and debounced edits.
- Cutting:
  - packer: MaxRects + guillotine, with property tests
  - plans and exports
  - predicted offcuts deferred to Slice 4

**L5 web** works per area in the same waves, against generated types.

**Exit criteria**
- Scenarios E, F, G, H and L pass, at API level and e2e.
- Every legacy row in `PARITY_MATRIX.md` maps to an implementation and a test.
- Security items in spec §10.2 are closed.
- An upload at the size limit passes through rewrites.

### Slice 3: agent runtime, voice and WhatsApp

**Agents**
- Sync Anthropic adapter and strict tool-schema export.
- Durable runs.
- Streaming decision from the spike: polling, or one passthrough route.
- Memory, automations (quotas, cancellation) and taint tracking.
- action_refs and the trace endpoint.

**Voice**
- Demo STT/TTS, vendor adapter interface, deterministic read-back.
- Audio stored as `file_object`; no presigned URLs.

**Channels**
- WhatsApp demo provider running through the real webhook route.
- Signature checks, inbox, enrolment, consent, window and templates.
- Outbox reconciliation and review links.

**Briefings-3**
- Pins and Listen to my day.
- LLM phrasing with a validator.
- hi / hi-Latn templates, labelled as untested.
- WhatsApp summary.

**Exit criteria**
- Scenarios B, J and K pass.
- Scenario C passes via text, voice and WhatsApp demo.
- AI outage falls back gracefully.
- Admin AI-usage view works.

### Slice 4: operations
- Inventory: ledger, projections, reservations, counts, opening batches.
- Orders.
- Challan movement-policy go-live.
- Procurement with QC.
- Production: BOM, routing, work orders, cost rollup, feasibility.
- Cut-plan links and offcut lots.
- Logistics.
- Operational briefing families and root-cause chains.

**Exit criteria**
- Scenario I passes, including the barrier no-oversell test, one posting per challan, and duplicate-event replay.
- The ledger stateful property test passes.
- Projection check is green.

### Slice 5: finance, migration and backup
- Finance: drafts, issuance gate, receipts, allocations, ageing, CSV and demo accounting adapters.
- Migration dry-run with fixture exports.
- `lk backup create` and rehearse-restore, using `pg_dump` / `pg_restore` from `LK_PG_BIN_DIR`.
- Offcut reuse, sample lineage, what-if views.

**Exit criteria**
- Scenario M passes.
- A restore rehearsal is proven locally.

### Slice 6: acceptance
- Full A–N matrix at 3 viewports.
- axe on every manifest route.
- Dead-control crawl.
- `pip-audit` and `npm audit`.
- Final screenshot review.
- Exact remaining-work list, plus credential and business-policy items: quote reset policy, tax and accounting system, STT vendor, WhatsApp/Meta setup, DPDP approval for live AI.

### Parallel-work ownership and sequencing rules
- **By directory:**
  - Each lane owns `backend/app/{platform,modules}/<its modules>/`, its tests under `backend/tests/*/<module>`, its route groups under `apps/web/src/app/(app)/<area>`, and `src/features/<feature>`.
  - Cross-lane edits go through the integrator.
- **Single-owner shared files (integrator):**
  - `backend/app/registry.py`: append-only, one line per module.
  - `pyproject.toml`, `uv.lock`, `package.json`, `package-lock.json`.
  - `apps/web/src/api/{openapi.json,schema.d.ts}`: regenerate only, never hand-merge.
  - `apps/web/src/lib/routes.ts`: per-area sections; append-only.
  - `docs/BUILD_STATE.md`, `PARITY_MATRIX.md`, `DECISIONS.md`, `docs/architecture/*`.
- **Distributed registries, so there is no central file to conflict on:**
  - PermissionDefs and TEMPLATE_GRANTS in each module's `policies.py`.
  - EventDefs in `events.py`.
  - SettingDefs in `settings.py`.
  - UI copy in `src/messages/<feature>.ts`.
- **Alembic:**
  - Linear chain; re-parent on rebase (`lk db reparent`); `alembic heads == 1` checked.
  - Merged revisions are never edited.
  - RLS, triggers and CHECK constraints only via helpers.
- **Fixtures:**
  - `backend/app/seed/world/<module>.py` belongs to its lane.
  - `world/keys.py` and expected-sentence tables change only through the fixture steward (briefing) plus the integrator.
- **Contract changes** (permissions, events, API conventions, UoW primitives): integrator PR first, then lanes rebase. A consumer may reference an event or permission only after its definition is merged.
- **Resources:** only the integrator runs Playwright and `next build`, guarded by `D:\lk-dev\e2e.lock`. Lanes run module tests plus `npm run check`.

### Critical files for implementation
- `D:\Lamikraft ERP\docs\architecture\conventions.md`, `api-conventions.md`, `permissions.md`, `events.md`, `fixtures.md` (Slice-0 contracts)
- `D:\Lamikraft ERP\backend\app\core\db.py` (UoW, RLS GUC, lock and advisory primitives) and `backend\app\core\money.py` (DecimalStr / Money)
- `D:\Lamikraft ERP\backend\app\registry.py` (permission, event and setting registration with startup cross-validation)
- `D:\Lamikraft ERP\scripts\dev.mjs` plus `backend\app\cli.py` (`lk devdb`, `env init --slot`, `db reparent`)
- `D:\Lamikraft ERP\backend\tests\conftest.py` (savepoint and committed modes, `drain_events`, Clock override) and `D:\Lamikraft ERP\.gitattributes`
