# Lamikraft One — implementation plan

## Context

Crown / Lamikraft's legacy "SKU Intelligence Portal" (one 4.3k-line FastAPI file + MongoDB, documented in `CURRENT_STATE_SPEC.md`) is a catalogue + export quoting + sheet-nesting + challan tool. Its permissions are cosmetic, it has 16 verified functional bugs and 8 security gaps, and it has no customer master, inventory, purchasing, production or finance. The mission (`OPUS_5_5_BUILD_PROMPT.md`, authoritative) is to build **Lamikraft One**. Its front door is a saved daily briefing for each employee. Speech, typing, direct controls and WhatsApp all reach the same typed, permission-enforced services. It must keep full legacy parity and add connected sales → inventory → purchasing → production → dispatch → finance-handoff slices. Done means a runnable, tested product with honest status docs, not a mock-up.

**Inputs inspected:** all 7 files in `D:\Lamikraft ERP` (spec, concept, build prompt, image prompts, two concept PNGs, START_HERE). There is no code, so this is a greenfield build.

**Design evidence:** a read-only workflow produced 7 subsystem designs and 2 critiques (completeness: 71 findings; feasibility/environment: 35). It is saved at:
- `C:\Users\panel\AppData\Local\Temp\claude\D--Lamikraft-ERP\389414ca-5f85-400e-aa47-bb9e5e1a957d\tasks\wsmiv31ai.output` (JSON, `.result.designs[]` / `.completeness` / `.feasibility`)
- `C:\Users\panel\.claude\projects\D--Lamikraft-ERP\389414ca-5f85-400e-aa47-bb9e5e1a957d\subagents\workflows\wf_edeae75f-a8e\journal.jsonl`

Slice 0, step 1 copies these into `docs/design/source/` so they survive. Where they conflict, the canonical contracts below win.

**User decisions (2026-10-12):**
- Docker Compose for PostgreSQL. Docker Desktop is now running with an 8.1 GB VM.
- Autonomous slice-by-slice execution, with a local `git init` and one commit per verified slice. Never push.
- Claude is the main reasoning brain, using Haiku, Sonnet or Opus by task, with cost efficiency as a hard constraint.
- Gemini 3.8 Flash handles vision and instant answers about what's on screen. Each reply is routed by request type.
- Screen awareness means structured screen context on every message, plus a masked screenshot sent only on demand.

## Environment facts (verified)

- **Machine:** Windows 11, 12 logical CPUs, 15.7 GB RAM.
- **Tools present:** Node 24.18 / npm 12; Python 3.12.10 (`python`) and 3.14 (`py`); git 2.55 (autocrlf=true); Docker 29.6.1.
- **Tools missing:** uv, psql.
- **Disk:** C: is 87% full; D: has 216 GB free. The repo path contains a space.
- **Cached Docker images:** postgres:16-alpine, pgvector/pgvector:pg17, minio/minio:latest. MinIO has stopped publishing free images, so it can't be the maintained default.
- **Version pins:**
  - `typescript ~5.9.3`: TS 7 breaks openapi-typescript and typescript-eslint.
  - `eslint ^9`, `next 16.4.0`, `react 19.3.0`, `tailwindcss 4.3.3` (via `@tailwindcss/postcss`), `react-aria-components 1.22.1`, `@tanstack/react-query 5.104`, `openapi-typescript 7.13` + `openapi-fetch 0.17`, `vitest 5`, `@playwright/test 1.64`.
  - Backend: `fastapi 0.143`, `uvicorn 0.54` (plain, no `[standard]`), `sqlalchemy 2.1` (sync), `alembic 1.20`, `psycopg[binary] 3.3`, `pydantic 2.14`, `anthropic 1.13`, `google-genai 2.29`, `reportlab 5.0.1[shaping]`, `openpyxl`, `argon2-cffi`, `pyotp`, `structlog`, `boto3` + `moto`, `hypothesis`, `pypdf` (tests), `tzdata`.
  - No WeasyPrint (it needs GTK on Windows). No pandas. No rectpack: we write our own packer.

## Canonical contracts, frozen in Slice 0 (these resolve the critics' blockers)

1. **Stack and topology**
   - Monorepo: `apps/web` (Next.js), `backend/app/{core,platform/*,modules/*}`, `backend/migrations`, `docs/`, `scripts/`.
   - The topology is a modular monolith plus one polling worker. It is same-origin: Next rewrites `/api/*` to FastAPI, so there's no CORS. Use `127.0.0.1` everywhere, never `localhost`.
   - Python is 3.14 if `uv sync --locked --no-build` passes; otherwise 3.12, with the reason recorded in DECISIONS.
2. **Database**
   - `postgres:17-alpine` via `docker-compose.yml`, bound to `127.0.0.1:54329`.
   - Extensions `pg_trgm` and `btree_gist` are mandatory.
   - Two roles: `lk_owner` (migrations) and `lk_app` (runtime; not superuser, no BYPASSRLS).
   - Each worktree gets its own databases (`lk_wt{N}`, `lk_wt{N}_tpl`) from `lk env init --slot N`, which also assigns ports.
   - Backup and restore use `pg_dump`/`pg_restore` via `docker compose exec`.
3. **Tenancy and authorization**
   - Every tenant table carries `company_id`. Postgres RLS is enabled and forced on it, failing closed via a `NULLIF(current_setting('app.company_id',true),'')` GUC set per unit of work.
   - Every query goes through a `ScopedRepository` plus a `ResourcePolicy` registry. Child objects (lines, revisions, notes, files, activity) are authorised only through their parent.
   - A record that isn't visible returns 404; one that is visible but forbidden returns 403.
   - No blanket composite tenant foreign keys (recorded as future scope).
   - Contract test: every `company_id` table has an RLS policy.
4. **Permissions**
   - Key format `<module>.<resource>.<action>`, with scope `own < team < branch < company`.
   - Closed verb set: read, create, update, archive, delete, transition, approve, export, manage, run, execute, post, issue.
   - Restricted data is its own resource, e.g. `pricing.cost.read`.
   - Each module declares its `PermissionDef`s and `TEMPLATE_GRANTS` in its own `policies.py`.
   - One `legacy_alias` table maps all 14 legacy permissions.
   - Startup cross-validation and a contract test reject unknown keys.
   - The legacy parity test reproduces spec §3.2 exactly for admin, management, sales and operations. Management gets no delete, catalogue manage or identity keys.
   - Per-user grant/revoke, where revoke wins.
   - Delegation never adds keys; it only extends record scope for keys the delegate already holds.
5. **Events**
   - Name format `<module>.<entity>.<past_tense_verb>`; the module prefix equals the permission module.
   - Each emitter declares an `EventDef` (name, version, payload model) in its `events.py`. `docs/EVENTS.md` is generated from these and checked.
   - A subscription to an unregistered event fails startup.
   - Events go to a transactional outbox, which fans out to per-handler jobs with dedupe keys. `consumers.once()` provides exactly-once effects.
6. **API conventions**
   - Routes live at `/api/v1/<module>/...`. Health is at `/api/v1/health/{live,ready}`; the WhatsApp webhook is at `/api/v1/webhooks/whatsapp`. The webhook route kind is signature-verified, exempt from CSRF, and keeps the raw body.
   - Errors are problem+json with snake_case codes. All version and staleness conflicts return 409.
   - Money and quantities travel as `DecimalStr` strings; floats are rejected in both input and output schemas.
   - Responses carry `capabilities: {action: {allowed, reason_code}}` plus `allowed_transitions`.
   - Unsafe commands accept an `Idempotency-Key` header.
   - Pagination is `Page{items,total,limit,offset}`, with keyset paging for feeds. Filters are applied before pagination.
   - Session state comes from one `GET /api/v1/session/bootstrap`.
   - Agent progress is polled every 500 ms in Slice 1. Slice 0 runs a spike to see whether SSE works through rewrites; if it doesn't, one passthrough route handler is added in Slice 3.
7. **Auth**
   - Opaque server-side sessions in an HttpOnly, SameSite=Lax cookie (`__Host-` in production).
   - CSRF uses a synchronizer token (the `lk_csrf` cookie echoed in `X-CSRF-Token`), plus Origin and Sec-Fetch-Site checks.
   - Passwords use argon2id. Rate limits and lockouts are stored in Postgres.
   - Admins have TOTP MFA (Slice 2).
   - There is no bootstrap admin. A one-time `lk admin create-first` CLI creates the first admin, and demo users sign in via one-time links in the `is_demo` company only.
   - Tokens never appear in URLs. Reset and invite tokens go in a `#t=` fragment, which the page strips with replaceState and then POSTs.
8. **Shared kernel, one owner each**
   - `core/money.py`: Money, Quantity, DecimalStr, and quantize per currency.
   - `core/csv_safe.py`: the only CSV writer. It escapes `= + - @` TAB CR LF, leading spaces and full-width variants. Output is QUOTE_ALL with a UTF-8 BOM.
   - `core/documents`: ReportLab Platypus with embedded Noto Sans and Noto Sans Devanagari (OFL). It is the only PDF engine.
   - `platform/files`: one content-addressed `file_object` table with UNIQUE(company, sha256), magic-byte sniffing, size limits and cookie-authenticated streaming downloads. No presigned URLs.
     - Storage adapters: `local_fs` (dev default) and `s3` (boto3, contract-tested with moto). An optional compose `s3` profile uses the cached MinIO image for a real-endpoint smoke test, dev only.
   - `platform/numbering`: `allocate()` with reset policies never, yearly or financial_year.
   - `platform/org`: company, branch, team, the UOM master (`uom`, `uom_alias`, `uom_conversion`), and the work calendar (shifts, holidays, assignments, 04:00 rollover).
   - `identity`: delegation and user_absence.
   - `platform/search`: providers plus recent searches.
   - `collab`: notes (the only store for internal notes), attachments and activity.
   - One `user_preference` store.
   - One `integration_status` registry.
   - One field-guard registry, `Restricted(guard_key, model_exposure, log)`. Costing is redacted from DTOs, logs, exports, notifications and model context.
   - One **approvals** module. It is the only engine for every human approval, whether started in the UI or by an agent. It provides `submit`, `decide(proposal_id, decision, content_hash, expected_version)`, `eligible_approvers`, and `ApprovalTarget` adapters. Separation of duties is enforced by a DB CHECK.
9. **Unit-of-work primitives**
   - `uow.repo`, `lock(ids)` (ordered FOR UPDATE), `advisory_xact_lock`, `defer_constraints`, `emit`, `clock`, `actor`, `allocate_number`, and `system_session(reason)`.
   - Raw SQL is allowed only in `platform/**`, `core/db/**`, and allow-listed `sql.py` files.
   - Everything is sync; psycopg async is banned.
   - All business timestamps come from the injected Clock.
10. **Numbering defaults** (legacy continuity; owner to confirm): `LK-QT-YYYY-NNNN` never resets, `DC-YYYY-NNNN` resets yearly, `CP-NNNN` never resets, and finance follows the April financial year. Numbers are never reused, and drafts are soft-deleted.
11. **Fixture world** (`backend/app/seed/world/`, created only through services, with a slice tag per entity)
    - Company: Crown Decor Pvt. Ltd. (Demo), `is_demo`.
    - People: Sahil (management), Meera and Neha (sales, own scope), Ravi (operations, branch), Kabir (restricted warehouse assistant), Arjun (new sales hire), Ananya (finance), Priya (admin).
    - Parties: Nordhaus Interiors GmbH, Maison Atelier SARL, Berg & Co AB, Thornbury Kitchens Ltd.
    - Product: LK-OT-0450 oak tray, carton 24, EUR 24.0000 on price list EXP-EUR-2026.
    - Prior quote: won LK-QT-2026-0003, 240 pcs.
    - Clock: frozen at Mon 2026-10-12 08:55 IST.
    - Tests reference fixture constants, never literals.
12. **Git and parallel work**
    - `.gitattributes` comes first: `* text=auto eol=lf`, binary types listed, and fixtures marked `-text`.
    - `core.longpaths true`.
    - Alembic is a linear chain: `lk db reparent` on rebase, and `alembic heads == 1` is checked.
    - RLS, triggers and CHECK constraints are created only through migration helpers.
    - Only the integrator edits the lockfiles, `registry.py`, `docs/*` and `apps/web/src/lib/routes.ts`. Generated API types are regenerated, never hand-merged.

## AI architecture (user decisions plus the agent design)

**Model routing.** Configurable in Settings → AI routing; the defaults below are tuned for cost.

| Task class | Default | Notes |
|---|---|---|
| Deterministic commands ("open the second item", snooze, navigate, stop speaking) | grammar parser, no model | zero cost; works when the AI is down |
| Intent/entity extraction, request routing, briefing phrasing, overview sentence, narration script, Explain, notifications | `claude-haiku-5-5`, effort low | facts and numbers are injected from queries; the model only phrases |
| Orchestration with typed tools (draft/revise quote, challan draft, proposals) | `claude-sonnet-5-5`, effort medium | the main brain |
| Escalation: multi-domain planning, management cross-team analysis, what-if, repeated clarification failure, "think harder" | `claude-opus-5-5`, effort medium | rule-triggered, never the default |
| Vision extraction (photos, handwriting, bills, POs, delivery notes) and instant answers about what's on screen | Gemini 3.8 Flash via `google-genai` | exact model ID verified against Google docs at build time; read-only, no tools; output is untrusted data; uncertain fields go to structured confirmation; hands off to Claude whenever data or an action is needed |
| Demo mode | deterministic Demo adapters, Claude-shaped and vision | labelled "Demo"; no keys needed |

**Screen awareness**
- Every web assistant message carries a structured **screen context**: route, open record references and versions, visible items with stable references, selection, filters, and unsaved draft.
- The server treats this context as a hint only. It re-reads every referenced record through the permission layer.
- A **masked screenshot** is sent only when the request is visual, involves an image or document, or the user taps "Look at my screen".
  - Elements marked `data-restricted` are blacked out on the client before capture.
  - A company admin setting can disable screenshots entirely.
  - Nothing is captured continuously.

**Runtime rules**
- One orchestrator per employee, with domain tool groups (Sales, Catalogue, Procurement, Production, Warehouse, Finance, Management).
- Every run is a durable `agent.run` job following resolve → authorised read → validate → propose/execute → commit → receipt.
- `ToolContext` wraps the server-built `ActorContext`; the model cannot set identity.
- The model has **no approve tool**. Approvals come only from authenticated human actions, each bound to a nonce `action_ref` plus the proposal's content hash.
- **Grounding:** a numeric-claim checker strips any money or quantity figure that didn't come from this run's tool outputs. Every ID must trace back to context or a tool result.
- **Taint:** runs that read external content (customer or vendor messages, vision output) are marked tainted. Tainted runs hide send tools and require explicit human confirmation.
- **Anthropic adapter** (per the claude-api skill):
  - sync client running in the worker;
  - a manual, provider-neutral loop;
  - `tool_choice: auto` with `strict: true` (forced tool choice returns 400 on the 5.5 models);
  - adaptive thinking with explicit effort;
  - iterate over all content blocks rather than assuming the first is text;
  - a typed exception chain;
  - server-side refusal fallbacks (`fallbacks: "default"`);
  - prompt caching of a deterministic tools+system prefix for each role template.
- **Cost controls:**
  - per-task `max_tokens` caps;
  - phrasing cached by fact-hash, so unchanged items never regenerate;
  - Message Batches for pre-shift phrasing;
  - images downscaled and deduplicated by hash before any vision call;
  - per-user and per-workflow quotas;
  - `ai_call_log` is the single usage store, priced from a configurable table and shown on the admin usage dashboard.
- Keys live only on the server. Live mode fails visibly when keys are missing.

## Slices

Each slice must persist data, enforce authority and pass its end-to-end scenarios before the next one starts. At every checkpoint, update `docs/BUILD_STATE.md` (completed, in progress, blocked, remaining, evidence and the next executable step), `docs/PARITY_MATRIX.md` and `docs/DECISIONS.md`, then make a local commit.

### Slice 0: bootstrap, contracts and spikes (integrator only)
1. **Repository setup:** `git init` with `.gitattributes`, `.gitignore` and `core.longpaths`. Copy the design artefacts to `docs/design/source/`.
2. **Bootstrap downloads** (the harness asks for approval):
   - `pip install --user uv==0.13.0`
   - `docker pull postgres:17-alpine`
   - static Noto Sans and Noto Sans Devanagari TTFs plus `OFL.txt`
   - `npx playwright install chromium`
   - Then run the Python 3.14 no-build gate.
3. **Spikes**, recorded in DECISIONS:
   - **Postgres:** roles, extensions, RLS fails closed as `lk_app`, `pg_dump`/`pg_restore` round trip, and template-clone timing.
   - **ReportLab:** € ₹ £ glyphs, a 150-row table with a repeated header, and Devanagari shaping.
   - **Next 16 rewrites:** cookie, CSRF and Origin checks; a 25 MB upload; SSE chunk timing.
   - **Toolchain:** TypeScript 5.9 + ESLint 9 + OpenAPI type generation.
4. **Contract documents in `docs/architecture/`:** `conventions.md`, `api-conventions.md`, `permissions.md`, `events.md`, `fixtures.md`, `parallel-work.md`, `ai-routing.md`. Add interface stubs for approvals, numbering, files, `consumers.once`, workcal and the AI adapters.
5. **Skeleton**
   - Backend: core, UoW/RLS, money, Clock, errors, redacting logs, `csv_safe`, `registry.py` with startup validation, outbox, jobs, worker, scheduler, Alembic baseline with helpers, architecture tests, and the test harness (savepoint mode, `@committed` clone mode, `drain_events`, and a test-support router only when `APP_ENV=test`).
   - CLI: `lk env init --slot`, `lk db ensure-roles`, `lk db reparent`, `lk admin create-first`.
   - Frontend: Next scaffold with tokens (light and dark), Manrope Variable (OFL) self-hosted, the route manifest and its coverage test, and Playwright config (127.0.0.1, `workers: 2`, fake-media flags).
   - Scripts: `npm run setup|dev|check|test:api|test:e2e|api:generate|api:check`. `scripts/dev.mjs` starts compose, the API, the worker and the web app, spawning with argument arrays and killing process trees.
6. **Docs:** BUILD_STATE (checkpoint 0); PARITY_MATRIX with every legacy module, field group, workflow, bug (§10.1 #1–16) and security gap (§10.2 #1–8), each with a target slice; DECISIONS; `runbooks/local-dev.md`.

**Exit:** `npm run setup && npm run dev` works from the spaced path, `ready` returns 200, `npm run check` is green, an RLS isolation test and a two-connection barrier test pass, and spike evidence is recorded.

### Slice 1: shell, auth, briefing and the quote vertical path (scenario C)

**Wave 1**, three lanes in parallel:
- **Platform lane:**
  - sessions, CSRF, login, rate limits, simple lockout;
  - role templates and overrides; first-admin CLI; demo sign-in links;
  - numbering, settings (company identity, terms, quote defaults);
  - LocalFs files, audit, route-authz matrix;
  - UOM master, workcal default calendar (Mon–Sat 09:30–18:30 Asia/Kolkata, 04:00 rollover).
- **Sales-core lane:**
  - catalogue tables with every legacy column (plus nullable HSN/SAC, stock UOM, lot and QC flags), read and search APIs, seeded oak tray;
  - minimal parties, `sales_enquiry` and `customer_message`;
  - seeded price lists with tier resolution;
  - the Decimal commercial engine v1 (rules in item 7 of the legacy section);
  - quotes: header, lines, snapshots, persisted totals, numbering, optimistic versions;
  - transitions: submit_review, approve/reject via approvals, mark_sent, mark_won, cancel, delete draft;
  - issued revision and ReportLab PDF;
  - tools: `resolve_party`, `find_usual_order` (wrapping `find_repeat_quote_basis`), `resolve_product`, `resolve_price`, `calculate_quote`, `draft_quote`.
- **Work lane:**
  - tasks, issues, change_log, reminders, responsibility rules and queues;
  - rule families: quote review, quote expiry, enquiries/replies, approvals, customer changes, onboarding;
  - deterministic briefing engine: rule-based priority with reason codes, six sections with no forced empties, top five;
  - versioned snapshots, stable issue IDs (uuid5 of the root cause), acknowledgements, snooze bounded by deadlines, mark-handled vs authorised dismissal, the AI-down fallback, the "N updates" control with no re-sorting;
  - overdue sweep; Today and Inbox APIs; a visibility consistency job.

**Wave 2:**
- **Agents-demo lane:**
  - the approvals module (replacing the stub) with the `sales.quote.review` handler;
  - a Demo orchestrator as an `agent.run` job with a polling API;
  - server-built cards (QuoteDraftCard, ClarificationCard, ErrorCard), ID-provenance grounding, and structured screen context.
- **Web lane:**
  - shell: 208 px sidebar, slim top bar, collapsible 300 px rail, and the phone bottom nav (Today, Inbox, Work, More);
  - login; Today (greeting, one factual sentence computed from records, command bar, prioritised items, full list); Inbox;
  - quote workspace with server totals, review page with changes, PDF link, minimal enquiries list.

**Exit:**
- Scenario C at the API and e2e levels (desktop and phone).
- Scenario D at engine level plus UI/API/PDF agreement.
- Scenario F subset: IDOR matrix, 40-way concurrent numbering, optimistic 409.
- Scenario A subset: scope, direct URLs, an aggregate-leak property test.
- Scenario B subset: no manufactured versions, event replay and out-of-order handling, snooze, fallback, midnight and weekend rollover.
- Keyboard journey; axe passes in both themes; screenshots inspected and defects fixed.

### Slice 2: complete legacy parity

Run in waves of at most three lanes.
- **Platform-2:**
  - MFA (required for admins), invitations and resets (demo `.eml` output);
  - custom roles with inheritance and deny, the overrides UI, a role simulator;
  - delegation, leave, access requests;
  - notes, attachments and activity; global search with the `/` shortcut and recent searches;
  - the S3 adapter (moto suite); image variants.
- **Catalogue and imports:**
  - validated forms, media, taxonomy (foreign keys, safe rename, delete-or-reassign);
  - facets, stats, accurate completeness, filtering before paging;
  - identifier normalisation: leading zeros kept, `120.0` → `120` with a warning, `0120` stays distinct;
  - packaging alias reconciliation with conflict quarantine;
  - the import workbench for all seven types: CSV/XLSX, aliases, staging, preview, row-numbered downloadable error report, 500-row transactional batches, orphan quarantine, idempotent re-import, history and hashes, before/after review, rollback of unreferenced imports;
  - lookup browser and export; demo-only reset.
- **Commercial-2:**
  - price-list create/edit/retire with effective-dated supersede and history; the pricing import contract (`STD-{TYPE}-{CUR}`);
  - FX snapshots with approval, and currency switching that resolves the right list or applies an approved dated conversion;
  - the full quote state machine, including archived, correction paths and `extend_validity`; revision compare and restore-into-new-draft; duplicate;
  - custom products with every field, the state machine, protected costing and promotion with lineage and approval; samples (`SMP-YYYY-NNNN`);
  - CSV exports and settings UIs.
- **Operations documents:**
  - challans as documents: all types, destinations and fields; validated transitions; DC numbering; PDF, print, CSV; summaries; debounced edits that surface failures;
  - cutting: our own MaxRects packer with free-rectangle pruning, plus a guillotine packer with a cut tree;
    - kerf handled by inflating pieces; margins and a separately enabled +10 mm oversize flagged "verify before release";
    - grain locks keyed on the canonical decor; bounded explicit overproduction; unfit reasons; reconciled area metrics;
    - save, reopen, duplicate and export plans, with a true-scale interactive board canvas.
- The web lane works per area against the generated types.

**Exit:** scenarios E, F, G, H and L pass at the API and e2e levels; every PARITY_MATRIX row maps to code and a test; all §10.2 security items are closed.

### Slice 3: agent runtime, voice, vision and WhatsApp
- **Agents:**
  - Anthropic adapter with strict tool export; the routing table; durable runs (streaming per the spike);
  - memory scopes (personal, team, customer, policy) with provenance, retention and an inspect/correct UI;
  - automations with owner, trigger, tools, quotas and cancellation;
  - `action_ref`s; the trace view; the admin AI-usage, latency and failure dashboard.
- **Vision:** a Gemini 3.8 Flash adapter plus a Demo adapter; masked screenshot capture; the instant-answer path with hand-off to Claude; photo and document extraction into structured confirmation cards.
- **Voice:**
  - push-to-talk with a recording indicator, mic-denial handling and cancel;
  - an editable final transcript that sends once (client utterance UUID with a unique constraint);
  - optional TTS, stopped on interrupt; read-back of consequential values;
  - STT/TTS adapter interface with a Demo adapter and a labelled, off-by-default browser fallback; English plus Hindi/Hinglish preferences, labelled untested;
  - offline drafts labelled and never shown as committed.
- **WhatsApp:**
  - a Cloud API adapter plus a Demo provider that posts signed payloads through the real webhook route;
  - HMAC-SHA256 signature check; inbox deduplicated by event ID, prompt 200, async processing; out-of-order status handling;
  - outbox reconciliation by provider ID, where an unknown status escalates and is never blindly resent;
  - authenticated enrolment, revocation, re-authentication; separate customer identities;
  - consent, opt-out, 24-hour window and templates; 15-minute review links that also require login;
  - "Demo" / "not connected" labels until a connection is verified.
- **Briefings-3:** Listen to my day (pause, resume, stop; stable pins with no re-sorting); LLM phrasing with a validator; the "what changed since yesterday" delta view; WhatsApp summary only with opt-in; cross-channel acknowledgements.

**Exit:** scenarios B, J and K pass; scenario C passes via text, voice and WhatsApp demo; an AI outage degrades gracefully.

### Slice 4: connected operations
- Sales orders from accepted quotes: idempotent via UNIQUE(source_quote), with partial fulfilment and cancellation.
- Inventory:
  - warehouses, locations and lots; a double-entry immutable movement ledger with projections updated in the same transaction;
  - reservations protected by row locks, with no oversell and no silent negatives; pick lists;
  - stock counts, adjustments, transfers, reversals; opening-stock batches approved by a second person;
  - the challan movement policy per type, with exactly one posting per source event; return reconciliation against the original lines.
- Procurement: requisition → PO → partial GRN → QC → vendor-bill handoff.
- Production: versioned BOMs and routings, work orders, issue and consumption, cut-plan links, offcut lots, capacity calendars from workcal, deterministic cost rollups with missing-input flags, delivery feasibility with evidence, and read-only what-if.
- Logistics: packing lists from packaging snapshots, CBM and weights, shipments with cutoffs, load suggestions.
- Operational briefing families: shortages via `inv_shortage_state`, receipts, dispatch cutoffs, QC, returnables; root-cause grouping.

**Exit:** scenario I passes, including a barrier test proving no oversell, a single posting per challan and replay safety; the ledger property tests pass.

### Slice 5: finance, migration, backup and new capabilities
- **Finance:**
  - invoice and credit-note drafts; an issue gate on tax and provider configuration (labelled drafts are still allowed);
  - receipts, allocations, ageing;
  - a CSV adapter plus a demo accounting adapter; reconciliation; margin policy and exceptions.
- **Migration dry-run tooling** for every legacy entity:
  - ID maps, quarantine, a reconciliation report, reruns without duplication;
  - candidate party links; historical users;
  - exact quote snapshots with discrepancy reports; no stock from legacy challans;
  - a cutover and rollback runbook.
- **Backup:** `lk backup create` and a rehearsed restore into a temporary database.
- **New capabilities:** offcut reuse, sample lineage, what-if views.

**Exit:** scenario M passes, and the restore is proven locally.

### Slice 6: acceptance and handover
- The full A–N matrix at 1440, 834 and 390 px viewports.
- axe on every manifest route; a dead-control crawl; `pip-audit` and `npm audit`.
- Final screenshot review, sent to the user.
- Handover docs: setup, provider configuration guide, migration and backup runbooks, and an exact remaining-work list.

## Legacy-parity rules that tests must pin (from spec and prompt)

1. **Commercial engine:** Decimal with explicit rounding; one persisted result that UI, API, PDF, CSV and agents all read.
   - **Recommended quantity:** `ceil(5000/price)`, rounded up to a carton multiple. At EUR 24 with a carton of 24, that gives 216. Labelled separately from the product MOQ.
   - **Surcharge:** EUR 400 only when currency is EUR, the toggle is on, and 0 < subtotal < 5000. Subtotal 4800 gives 4800 with the toggle off and 5200 with it on; 5000 gets none.
   - **Missing data:** a missing or zero price, or a non-EUR currency, returns an explanation instead of a fabricated threshold.
2. **Price resolution:** customer agreement → customer-type list → standard list, then currency, unit and effective date. An ambiguous match stays ambiguous and does not fall through. A currency label can't change without a price list or an approved FX rate: a deferred FK plus CHECK enforces this.
3. **Quote states:** draft, internal_review, sent, revised, won, lost, cancelled, archived. Transitions are validated; issued revisions are immutable, enforced by trigger; duplicates get real totals, a cleared customer reference and the assignee per policy; correction paths need a management permission and a reason.
4. **Every §10.1 bug has a named regression test:** the cancelled/archived statuses, duplicate totals, CSV line counts and creator names, surcharge consistency, decor `120.0`, thickness paging, category activation, `product_name` search, carton aliases, deterministic EUR selection, nesting overlaps, media duplicates and orphans, concurrent numbering, challan validation, pricing edit paths, taxonomy references.
5. **Every §10.2 gap has an IDOR or permission test:** each route, child line, revision, export, media download, note, activity item, search result and agent tool.

## Execution method

- **Integrator:** I am the integrator. I own Slice 0, contracts, merges, generated types, lockfiles, docs, `next build`, Playwright, screenshots and commits.
- **Workflow per slice, wave 1:** up to three lane agents, each in its own git worktree and env slot. Lanes implement against the frozen contracts and run their module tests plus `npm run check`. Lanes never run Playwright or `next build`.
- **Workflow per slice, then:**
  - adversarial review agents per lane diff: correctness, security/IDOR and spec-conformance lenses;
  - lane fixes;
  - integrator merge in dependency order, `api:generate`, the full suite, e2e, and browser screenshots at desktop and phone sizes;
  - a verification workflow per acceptance scenario;
  - fixes, then a commit and doc update.
- **Bounded retries:** after three failed attempts at the same thing, I record the cause in BUILD_STATE and move to the next unblocked work.
- **Progress updates:** I give one at each wave and checkpoint, keeping implemented behaviour, simulated providers and backlog clearly separated.
- **No speculative frameworks and no placeholder buttons.** Every visible control works or isn't rendered.

## Needs owner input later (not blocking; demo defaults are recorded in BUILD_STATE)

- Quote-number reset policy.
- Approval thresholds for price overrides and below-minimum quotes.
- Statutory accounting system (Tally / Zoho / other) and the e-invoice/e-way-bill provider.
- STT/TTS vendor for Hindi and English (shortlist: Sarvam, Google, Azure).
- Approval under DPDP to send business data and screenshots to Anthropic and Google, plus any data-residency constraint.
- WhatsApp Business account, numbers and Meta app.
- Legal entity structure.
- Company identity: logo, GSTIN, bank details, terms.
- Live credentials, each placed in `.env` by the user: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, WhatsApp (WABA ID, phone number ID, token, app secret, verify token), the STT/TTS key, the S3 endpoint, SMTP.

## Verification

- **Backend:** `npm run test:api` runs pytest unit tests (with hypothesis property tests for the engine, packer, ledger and redaction), integration tests on real Postgres (savepoint and committed modes), and contract tests (permissions, events, RLS coverage, the single CSV writer, the API decimal schema, provider adapters with fixtures, webhook signatures and replay).
- **Frontend:** `npm run check` runs lint, tsc, vitest, `api:check`, `alembic heads == 1` and the fixture sha256 manifest.
- **End to end:** `npm run test:e2e` runs Playwright journeys mapped to scenarios A–N at 3 viewports, plus axe (WCAG 2.2 AA) in both themes and the dead-control crawl.
- **Manual inspection:** after each slice I run `npm run dev`, open the app in the built-in browser, sign in as each persona, walk the slice's workflows at desktop and phone sizes, and fix visible defects. Screenshots are saved under `docs/evidence/slice-N/` and sent to you at slice exits.
- **Acceptance evidence:** command summaries, test counts and screenshot paths are recorded in BUILD_STATE. A slice is "done" only when its exit scenarios pass on `main`.
