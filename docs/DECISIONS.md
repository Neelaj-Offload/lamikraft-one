# Decisions

Architecture decision records for Lamikraft One. Each entry: context, decision, consequences, status.
Status values: **Accepted** (in force), **Accepted — owner to confirm** (a business-policy default the owner must
confirm; listed in `docs/BUILD_STATE.md`), **Superseded**. Authority order: `OPUS_5_5_BUILD_PROMPT.md` (requirements)
→ `docs/PLAN.md` canonical contracts → `docs/architecture/*` → `docs/design/source/*` (evidence only).

Index: 1 topology · 2 Python · 3 frontend stack · 4 backend dependencies · 5 PostgreSQL · 6 object storage ·
7 tenancy · 8 sessions · 9 CSRF · 10 tokens and first admin · 11 permissions · 12 field guards · 13 events ·
14 approvals · 15 numbering · 16 money · 17 commercial engine · 18 price resolution · 19 PDF · 20 packer ·
21 ledger · 22 cost of record · 23 calendar and delegation · 24 briefing engine · 25 AI routing ·
26 screen awareness · 27 Anthropic adapter · 28 grounding and taint · 29 demo adapters · 30 WhatsApp ·
31 agent progress · 32 motion system · 33 testing · 34 git and parallel work · 35 fixture world ·
36 enquiries and messages · 37 new domain entities · 38 notes · 39 preferences · 40 single registries ·
41 search · 42 API shape · 43 finance and tax · 44 UI primitives · 45 self-service routes ·
46 price-override keys · 47 future scope

---

## ADR-001 Modular monolith, one polling worker, same-origin topology
- **Context**: the build prompt asks for a modular monolith with a small durable worker, not a microservice estate.
  Legacy was one 4.3k-line FastAPI file.
- **Decision**: `apps/web` (Next.js) + `backend/app/{core,platform/*,modules/*}` + `backend/migrations`. One FastAPI
  process, one worker process polling a Postgres job table. Same origin: Next rewrites `/api/*` to FastAPI, no CORS.
  `127.0.0.1` everywhere, never `localhost`.
- **Consequences**: one deployable, one schema, one OpenAPI contract; cookies work for downloads without tokens in
  URLs. Layering (core ← platform ← modules) is enforced by an architecture test. Production needs a reverse proxy in
  front of both processes. **Accepted.**

## ADR-002 Python 3.14 (no-build gate passed)
- **Context**: Python 3.12 was chosen in the platform design only because pgserver lacked newer wheels; pgserver was
  dropped (ADR-005). 3.14 offers stdlib `uuid.uuid7()`.
- **Decision**: `requires-python = "==3.14.*"`, `.python-version` 3.14, dependencies locked in `backend/uv.lock`.
  The Slice-0 gate `uv sync --locked --no-build` passed: **83 locked packages, all installed from wheels, no source
  builds** (uv 0.13.0). Plain `uvicorn` (no `[standard]` extra, whose httptools/uvloop risk MSVC builds). No
  hand-written UUIDv7.
- **Consequences**: no fallback to 3.12 needed; any new dependency must ship a cp314 (or abi3/pure) Windows wheel or
  be rejected. **Accepted.**

## ADR-003 Frontend stack and version pins
- **Context**: the newest TypeScript (7.x) ships no JavaScript compiler API; `openapi-typescript` 7.13 peers
  `typescript ^5`; `typescript-eslint` requires `<6.1`; `eslint-plugin-react` (via `eslint-config-next` 16.4.0)
  supports ESLint ≤ 9.
- **Decision**: `typescript ~5.9.3` (5.9.3 installed), `eslint ^9` (9.39.5), `next 16.4.0`, `react 19.3.0`,
  `tailwindcss 4.3.3` via `@tailwindcss/postcss`, `react-aria-components 1.22.1` as the only primitive library,
  `@tanstack/react-query 5.104`, `openapi-typescript 7.13` + `openapi-fetch 0.17`, `vitest 5`, `@playwright/test 1.64`,
  `@axe-core/playwright 4.13`. Exact versions in the lockfile, `npm ci` only, never `--legacy-peer-deps`, never
  `--omit=optional` (Tailwind's native binaries). Re-evaluate TypeScript 7 when 7.1 ships an API and the tools widen
  their peer ranges.
- **Consequences**: generated API types and type-aware lint keep working; `npm ls typescript eslint` is part of
  `npm run check`. **Accepted.**

## ADR-004 Backend dependency set and exclusions
- **Decision**: fastapi 0.143, uvicorn 0.54, SQLAlchemy 2.1 (sync), alembic 1.20, psycopg[binary] 3.3, pydantic 2.14,
  pydantic-settings, python-multipart, argon2-cffi, pyotp, segno, cryptography, structlog, tzdata, boto3, pillow,
  reportlab[shaping] 5.0.1, openpyxl 3.1.5 + defusedxml, httpx, anthropic 1.13, google-genai 2.29; dev: pytest,
  hypothesis, moto[s3], pypdf, ruff.
- **Excluded**: WeasyPrint (needs GTK/Pango on Windows), pandas (its type inference caused the legacy `120.0` and
  leading-zero corruption), rectpack (ADR-020), respx (use `httpx.MockTransport`), import-linter (AST architecture
  tests instead), psycopg async, Celery/Redis, a chart library.
- **Consequences**: fewer moving parts; lanes request any new dependency through the integrator. **Accepted.**

## ADR-005 PostgreSQL 17 through Docker Compose
- **Context**: the feasibility critique recommended EDB portable binaries because Docker was stopped. The user chose
  Docker Compose on 2026-10-12; Docker Desktop now runs with an 8.1 GB VM. The host has 15.7 GB RAM; C: is 87 % full
  (Docker's WSL disk lives there); D: has ~216 GB free.
- **Decision**: `postgres:17-alpine` (pulled, 424 MB) in `docker-compose.yml`, bound to `127.0.0.1:54329`. Extensions
  `pg_trgm` and `btree_gist` are mandatory (first owner migration fails fast if absent). Roles `lk_owner`
  (migrations) and `lk_app` (runtime; not superuser, no BYPASSRLS, statement and idle timeouts). Per-slot databases
  `lk_wt{N}` and `lk_wt{N}_tpl` created by `lk env init --slot N`. `pg_dump`/`pg_restore` run through
  `docker compose exec` (no host psql). pgserver and SeaweedFS/mailpit profiles are dropped.
- **Consequences**: one engine version for dev and tests, contrib available; at most 3 lanes plus the integrator fit
  in RAM; images are kept minimal and dumps/backups written to D: (`backend/var/backups`) to protect C:. Changing
  `.wslconfig` or Docker resources is a user decision. **Accepted.**

## ADR-006 Object storage: local filesystem by default, S3 adapter tested with moto
- **Context**: legacy used Emergent object storage (must be replaced). MinIO stopped publishing free community images
  (October 2025), so it cannot be the maintained default.
- **Decision**: `platform/files` with one content-addressed `file_object` table (UNIQUE(company, sha256)), storage
  adapters `local_fs` (dev default) and `s3` (boto3, any S3-compatible endpoint) sharing one contract suite run against
  moto. An optional compose `s3` profile may use the cached MinIO image for a dev-only real-endpoint smoke test. No
  presigned URLs: downloads stream through the backend with cookie authentication.
- **Consequences**: re-imports cannot duplicate media; a real S3 endpoint check is a documented pre-production step
  with credentials. **Accepted.**

## ADR-007 Tenancy: RLS plus ScopedRepository, no blanket composite tenant FKs
- **Context**: the platform design proposed composite `(company_id, id)` FKs on every child; the feasibility critique
  showed they double FK columns and complicate every SQLAlchemy relationship, while the product launches with one
  company.
- **Decision**: every tenant table carries `company_id` with RLS ENABLE + FORCE and the fail-closed policy
  `company_id = NULLIF(current_setting('app.company_id', true), '')::uuid`, set transaction-locally by the UoW. All
  queries go through `ScopedRepository` + `ResourcePolicy`; children are authorised only through their parent; not
  visible → 404, visible but forbidden → 403. Purpose-specific composite FKs remain where they carry business meaning
  (`sales_quote_line (quote_id, currency)`). Contract test: every `company_id` table has a policy; `lk_app` is neither
  superuser nor BYPASSRLS.
- **Consequences**: isolation holds even if a code filter is missed; blanket composite tenant FKs are future scope for
  multi-company. **Accepted.**

## ADR-008 Opaque server-side sessions instead of JWT
- **Decision**: 256-bit random token in an HttpOnly, SameSite=Lax cookie (`lk_session` in dev, `__Host-lk_session` in
  production); only its SHA-256 is stored. Idle 12 h, absolute 7 days, recent-auth 10 min; rotation on login, MFA and
  password change; revocation on the next request. argon2id hashing; rate limits and lockouts in Postgres.
- **Consequences**: instant revocation (fixes legacy unrevocable 24 h JWTs); a per-request indexed lookup.
  **Accepted.**

## ADR-009 CSRF: synchronizer token plus Origin and Sec-Fetch-Site
- **Context**: the frontend design proposed a signed double-submit cookie; the platform design a stored token hash.
- **Decision**: stored hash of the CSRF secret on the session; readable `lk_csrf` cookie echoed in `X-CSRF-Token` on
  every unsafe method; Origin (else Referer) must equal `LK_PUBLIC_ORIGIN`; `Sec-Fetch-Site: cross-site` is refused.
  Problem codes `cross_site_request`, `origin_mismatch`, `csrf_token_invalid`. The webhook route kind is exempt and
  verifies signatures instead.
- **Consequences**: one scheme in code and tests; the client refetches bootstrap and retries once on an invalid token.
  **Accepted.**

## ADR-010 No tokens in URLs; no bootstrap admin
- **Decision**: the backend ignores `?auth=`/`?token=`; reset, invitation and demo sign-in tokens travel in a `#t=`
  fragment that the page strips with `replaceState` before POSTing, with `Referrer-Policy: no-referrer`. The app never
  creates users or resets passwords at startup; `lk admin create-first` creates the first admin once and refuses when
  one exists; demo users are passwordless and sign in through one-time links only in the `is_demo` company. Admin MFA
  (TOTP) arrives in Slice 2.
- **Consequences**: closes legacy §10.2 #4 and #5; an e2e check asserts no request URL or log line contains a token.
  **Accepted.**

## ADR-011 Permission grammar, verb set and legacy mapping
- **Context**: the designs used five incompatible vocabularies and two legacy mappings.
- **Decision**: `<module>.<resource>.<action>`, scopes `own < team < branch < company`, restricted data as its own
  resource (`pricing.cost.read`). The plan's 13 core verbs are extended by 12 domain verbs already implemented in
  `app/platform/authz/permissions.py` (`use, assign, override, send, reverse, decide, dismiss, import, correct, promote,
  reserve, receive`), used only where a core verb would mislead. Each module declares `PermissionDef`s and
  `TEMPLATE_GRANTS` in its own `policies.py`; startup cross-validation and a contract test reject unknown keys. One
  legacy alias table maps all 14 legacy permissions; the parity test reproduces spec §3.2 exactly for admin,
  management, sales and operations; management gets no delete, catalogue write or identity keys. Per-user
  grant/revoke with revoke winning. Delegation never adds keys. Full catalogue: `docs/architecture/permissions.md`.
- **Consequences**: legacy-aliased keys are declared in Slice 1 even when their features ship in Slice 2. If the
  integrator prefers the 13-verb set only, the keys using domain verbs are listed in permissions.md §13 for renaming.
  **Accepted.**

## ADR-012 One field-guard registry for restricted data
- **Decision**: `Restricted(guard_key, model_exposure, log)` on DTO fields; `redact()` used by API DTOs, logs, CSV,
  notifications, briefing facts and model context. `pricing.cost.read` guards product cost, custom-product costing,
  production cost data and margins with `model_exposure=deny` (never sent to providers even for permitted users).
- **Consequences**: costing redaction is structural (scenario E); a canary test plants sentinels in every guarded
  column. **Accepted.**

## ADR-013 Event registry and transactional outbox
- **Decision**: names `<module>.<entity>.<past_tense_verb>` with the permission module as prefix; `EventDef` per
  emitter; payloads carry ids, keys, versions, enum codes and changed-field names only; a subscription to an
  unregistered event fails startup; the outbox fans out to per-handler jobs with dedupe keys; `consumers.once()` gives
  exactly-once effects where a handler is reachable twice; `docs/EVENTS.md` is generated and checked. The resolved
  catalogue (e.g. `sales.quote.{created,review_requested,issued,marked_sent,won,lost,cancelled,owner_changed,
  status_changed,validity_extended}`, `approvals.proposal.*`, `identity.membership.{activated,deactivated,
  access_changed}`, `inventory.shortage.{detected,changed,resolved}`) is in `docs/architecture/events.md`.
- **Consequences**: briefing consumers can only reference real producers; no broker. **Accepted.**

## ADR-014 Approvals: one engine for every human approval
- **Context**: commercial, operations, briefing and agent designs each had their own approval contract, and quote
  review policy had two sources.
- **Decision**: `backend/app/platform/approvals` (kernel, because every module registers `ApprovalTarget` adapters and
  platform cannot import modules) provides `submit`, `decide(proposal_id, decision, content_hash, expected_version,
  reason)`, `eligible_approvers` and adapters (`facts`, `content_hash`, `version`, `on_approved`, `on_rejected`).
  Separation of duties is a DB CHECK on `proposal_decision`. Eligibility = the target's `.approve` key at a covering
  scope (+ an approval authority level from Slice 3). The model has no approve tool; decisions bind to an `action_ref`
  nonce and the content hash. Review policy lives only in `approval_policy`: default "review only when requested"; the
  demo seed adds a rule that overrides, discounts and below-minimum quotes need an approved review before issue.
- **Consequences**: FX rates, promotions, adjustments, counts, opening batches, POs, invoices, write-offs and reversals
  all become ApprovalTargets. Thresholds for overrides and below-minimum quotes are a business decision.
  **Accepted — owner to confirm thresholds.**

## ADR-015 Numbering defaults (legacy continuity)
- **Context**: designs disagreed on the quote counter reset; legacy never reset the quote counter.
- **Decision**: one allocator (`uow.allocate_number`) with reset policies `never | yearly | financial_year`.
  Defaults: `LK-QT-YYYY-NNNN` never resets (YYYY = local creation year, one counter shared across brands);
  `DC-YYYY-NNNN` yearly; `CP-NNNN` never; `ENQ-`, `SMP-`, `CUT-`, `IMP-`, `SO-`, `PR-`, `PO-`, `GRN-`, `WO-`, `PL-`,
  `SH-`, `RCPT-` yearly; finance documents on the April financial year, numbered only at issue. Numbers are never
  reused; drafts are soft-deleted; counters only increase; migration seeds counters to the legacy maximum + 1.
- **Consequences**: fixes the legacy races (§10.1 #13). **Accepted — owner to confirm the quote reset policy.**

## ADR-016 Money, quantities and numeric scales
- **Decision**: `core/money.py` is the only implementation: Money (amount + currency), Quantity (value + uom), DecimalStr
  (string in every schema; floats rejected). Money NUMERIC(18,4) + CHAR(3); unit prices 4 dp; quantities
  NUMERIC(18,6) + uom_code with integer-UOM rules (others ≤ 4 dp at entry); dimensions NUMERIC(12,3) mm; FX
  NUMERIC(20,10). Totals rounded ROUND_HALF_UP at the currency minor unit; never summed across currencies.
- **Consequences**: the client never does arithmetic. **Accepted — accountant to confirm rounding.**

## ADR-017 Commercial engine rule set v1
- **Decision**: pure Decimal engine whose persisted result is read by UI, API, PDF, print, CSV and agents. Recommended
  order quantity `ceil(5000 / unit price)` rounded up to a carton multiple (EUR 24, carton 24 → 216), labelled as an
  order-value recommendation distinct from product MOQ. EUR 400 surcharge only when currency is EUR, the toggle is on and
  0 < applicable subtotal < 5,000 (5,000 exactly: none). Applicable subtotal = merchandise net after line discounts,
  excluding tax and surcharge. Missing/zero price or non-EUR currency returns an explanation, never a fabricated
  threshold. Tax is not calculated (TaxProvider returns `not_calculated`, totals say "Excludes taxes").
- **Consequences**: legacy bug §10.1 #3 cannot recur; undiscounted legacy cases match. **Accepted.**

## ADR-018 Price resolution and anti-relabel
- **Decision**: tier-first (customer agreement → customer-type list → standard), then currency, unit and effective
  date. An ambiguous tier stays ambiguous (no fall-through) unless a unique explicit priority exists; zero price is
  unavailable. FX conversion is a second pass only when policy enables it and an approved, dated rate exists. A deferred
  FK `(quote_id, currency)` plus a CHECK (`currency = source_currency OR fx_rate_id IS NOT NULL`) makes relabelling
  impossible. Active price-list items are immutable; changes are effective-dated supersedes with history. Pricing
  import maps each (price_type, currency) to `STD-{TYPE}-{CUR}` by default (the demo world maps (export, EUR) to
  EXP-EUR-2026).
- **Consequences**: fixes §10.1 #10 and #15; scenario E enforced by the database. **Accepted.**

## ADR-019 ReportLab is the only PDF engine
- **Decision**: `core/documents` with ReportLab Platypus and embedded Noto Sans and Noto Sans Devanagari (OFL, committed
  with `OFL.txt`); `LongTable(repeatRows=1)` with Paragraph cells and in-row splitting; `reportlab.graphics` for challan
  and cut-plan drawings; `reportlab[shaping]` for Devanagari. No WeasyPrint, no HTML templates for PDFs.
- **Consequences**: € ₹ £ and Unicode names render; long documents paginate; Devanagari shaping is verified in a spike
  and Slice 2 or recorded as a documented, tested limitation. **Accepted.**

## ADR-020 Own sheet packer
- **Context**: rectpack only rotates globally, exposes no guillotine cut tree, warns about float precision and has not
  been released since 2021.
- **Decision**: a pure `cutting/packer` package: MaxRects with free-rectangle pruning (nested mode) and a guillotine
  packer that records its cut tree, integer deci-millimetres, kerf modelled by inflating pieces and the bin, margins,
  a separately enabled +10 mm oversize that flags "verify before release", grain locks keyed on the canonical decor,
  bounded explicit overproduction into open boards only, explicit unfit reasons, deterministic multi-start, and an
  independent guillotine checker. Results say "Heuristic layout, not guaranteed optimal".
- **Consequences**: property tests prove non-overlap, bounds, grain rules and exact area reconciliation (scenario H).
  **Accepted.**

## ADR-021 Double-entry immutable stock ledger
- **Decision**: every movement goes from one location to another; virtual locations may go negative, stock-bearing ones
  never; balances and summaries are projections updated in the same transaction; reservations and outbound postings lock
  the same summary row (no oversell); UNIQUE(source_type, source_id, purpose) gives exactly one posting per source event;
  corrections are reversals; opening stock only from approved opening batches; legacy challans are document-only.
- **Consequences**: scenario I invariants are database-enforced; a nightly projection check detects drift.
  **Accepted.**

## ADR-022 Single cost of record
- **Decision**: `pricing_product_cost` is the per-product cost of record (`source_kind` manual, import, migration,
  rollup). Freezing a production cost version writes product_cost rows with `source_kind=rollup`. Margin reads
  product_cost only.
- **Consequences**: no competing cost sources for margin exceptions or promotion. **Accepted.**

## ADR-023 One calendar, delegation and absence model
- **Decision**: `platform/org` owns work calendars, shifts, holidays and assignments with `work_date(user, t)` and a
  04:00 rollover; `identity` owns one `delegation` and one `user_absence` table. Defaults: Asia/Kolkata, Monday–Saturday,
  09:30–18:30, precompute 30 min before shift start. Delegation never widens access (ADR-011).
- **Consequences**: authz resolution and briefing collection call the same functions. **Accepted — owner to confirm the
  workweek and shift defaults.**

## ADR-024 Deterministic briefing engine
- **Decision**: two-stage pipeline (domain events → `tasks.rules` → `tasks.*` → `briefings.refresh`); stable issue ids
  (UUIDv5 of the root cause); copy-on-write versioned snapshots created only when fingerprints or the visible set change;
  rule-based priority with reason codes; six sections without forced empties, top five; snooze bounded by deadlines;
  mark-handled verified against the source; deterministic text first, optional LLM phrasing validated against facts;
  "N updates" control with no re-sorting; server pins for voice; fallback to a permission-filtered task list and the last
  successful briefing.
- **Consequences**: no manufactured updates (scenario B); AI outage never blocks the briefing. **Accepted.**

## ADR-025 AI routing by request type
- **Context**: user decision: Claude is the reasoning brain (Haiku/Sonnet/Opus by task, cost efficiency a hard
  constraint); Gemini 3.8 Flash handles vision and instant on-screen answers; each reply is routed by request type.
- **Decision**: deterministic grammar (no model) → `claude-haiku-5-5` (low effort) for routing, extraction and phrasing →
  `claude-sonnet-5-5` (medium) for tool orchestration → `claude-opus-5-5` (medium) only on escalation rules; Gemini 3.8
  Flash read-only for vision extraction and screen answers, handing off to Claude when data or an action is needed.
  Configurable in Settings → AI routing. Cost controls: per-task caps, phrasing cache by fact hash, Message Batches for
  pre-shift phrasing, image downscale/dedupe, per-user and per-workflow quotas, one `agents_ai_call_log` priced at report
  time. Live mode requires recorded DPDP approval. Details: `docs/architecture/ai-routing.md`.
- **Consequences**: cheap lookups never reach the expensive model; everything works in Demo without keys.
  **Accepted — owner to confirm DPDP approval before live use.**

## ADR-026 Screen awareness: structured context always, masked screenshot on demand
- **Decision**: every assistant message carries structured screen context (route, open records with versions, visible
  items with stable refs, selection, filters, unsaved draft); the server treats it as a hint and re-reads every record
  through the permission layer. A masked screenshot is sent only for visual requests, image/document requests or
  "Look at my screen"; `data-restricted` elements are blacked out client-side before capture from the app's own DOM;
  default preference `ask` (one tap), optional `auto`; a company admin setting disables capture; nothing is captured
  continuously; captures are restricted files purged after 24 h.
- **Consequences**: instant screen answers without broad data exposure. **Accepted.**

## ADR-027 Anthropic adapter rules
- **Decision**: synchronous `anthropic.Anthropic` client in the worker; a manual provider-neutral loop;
  `tool_choice: auto` with `strict: true` on write/proposal tools (forced tool choice returns 400 on the 5.5 models);
  adaptive thinking with explicit `output_config.effort`; iterate all content blocks; typed exception chain; server-side
  refusal fallbacks (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`) on Sonnet/Opus requests; prompt
  caching of a deterministic tools + system prefix per role template; append-only history within a run.
- **Consequences**: contract tests replay recorded responses through `httpx.MockTransport`. **Accepted.**

## ADR-028 Grounding and taint
- **Decision**: ID provenance for every tool input; numeric provenance for quantities; prices never model inputs except a
  permission-gated override stated by the user; a numeric-claim checker strips unsourced figures; runs that read external
  content are tainted (send tools hidden, explicit confirmation required).
- **Consequences**: the model cannot invent prices, quantities or ids, and injected instructions cannot trigger sends.
  **Accepted.**

## ADR-029 Labelled Demo adapters for every provider
- **Decision**: Demo adapters for the Claude-shaped orchestrator, vision, STT/TTS, WhatsApp, email (`.eml` files) and
  accounting exercise the same service boundary, are labelled "Demo" in every output, and need no keys. Live mode with a
  missing credential fails visibly; there is no silent fallback to Demo. "Connected" appears only after verification.
- **Consequences**: the product is fully runnable locally; honest status everywhere. **Accepted.**

## ADR-030 WhatsApp: Demo provider through the real webhook route
- **Decision**: a Cloud API adapter and a Demo provider; the Demo provider posts HMAC-SHA256-signed payloads through the
  real `/api/v1/webhooks/whatsapp` route (webhook route kind: signature-verified, CSRF-exempt, raw body kept, RLS-exempt
  inbox), so signature, inbox, dedupe and reconciliation code always run. Timeouts become `unknown` and escalate; never a
  blind resend. Separate employee and customer identities; consent, opt-out, 24-hour window and templates tracked per
  recipient.
- **Consequences**: scenario K is testable without credentials; live requires the Meta setup listed in BUILD_STATE.
  **Accepted.**

## ADR-031 Polling-first agent progress
- **Context**: Next.js 16 rewrites reportedly buffer server-sent events.
- **Decision**: Slice 1 polls `GET /api/v1/agents/runs/{id}?after_seq=` every 500 ms. A Slice-0 spike measures SSE chunk
  timing and a 25 MB upload through rewrites; if SSE is buffered, Slice 3 adds exactly one passthrough route handler and
  polling stays the fallback. Briefing and Inbox use 60 s polling with ETags.
- **Consequences**: no dependency on streaming through rewrites for correctness. **Accepted.**

## ADR-032 Motion system: expressive showcase surfaces, calm operational screens
- **Context**: the owner set a goal of an Awwwards-level experience with Motion (Framer Motion), GSAP, parallax and
  Three.js. The build prompt requires restraint: 150–220 ms transitions for drawers and state changes, a waveform only
  while recording or speaking, no ambient AI orb, no neon purple gradients or glass panels, reduced-motion support, and
  readable dense tables.
- **Decision**: expressive choreography is allowed only on named showcase surfaces — sign-in (entrance timeline and
  pointer parallax over real swatch textures), the Today greeting choreography, briefing item entrance and "N updates"
  reveals, 3D material and product viewers using real swatch textures at real dimensions, cut-plan nesting playback,
  the document generation reveal, and page/drawer transitions. Dense operational tables, forms, settings and print views
  get only micro state transitions. No infinite decorative loops, no auto-rotate, no scroll-jacking in the app, no
  reordering during a spoken briefing. Three.js and GSAP are lazy-loaded and confined by import rules; budgets: 60 fps,
  transform/opacity only, no layout thrash, ≤180 KB initial JS per app route and ≤220 KB initial / ≤300 KB deferred on
  showcase routes. Everything honours `prefers-reduced-motion` and the in-app `motion=full|reduced` preference (OS reduce
  always wins). Details: `docs/architecture/motion-system.md`.
- **Consequences**: the brand gets memorable moments where they help comprehension, while daily work stays fast; the
  design-lint test and reduced-motion e2e checks enforce the boundary. **Accepted.**

## ADR-033 Testing strategy
- **Decision**: unit tests with hypothesis for the engine, packer, ledger, permission resolution, redaction and briefing
  ordering; integration tests on real Postgres as `lk_app` in per-test SAVEPOINT mode, with `@pytest.mark.committed`
  clone mode for RLS, concurrency, worker and backup tests; `drain_events`; barrier-based concurrency tests; Clock-only
  business time; a test-support router only when `LK_ENV=test` (the plan's `APP_ENV=test`); byte-exact fixtures with a
  sha256 manifest; Playwright run only by the integrator with `workers: 2`, fake-media flags and axe WCAG 2.2 AA in both
  themes; screenshots inspected, not pixel-diffed.
- **Consequences**: fast deterministic suites; template-clone timing is measured in the Slice-0 Postgres spike.
  **Accepted.**

## ADR-034 Git and parallel work
- **Decision**: local git only, one commit per verified slice, never push; `.gitattributes` first (`* text=auto eol=lf`,
  binaries listed, `backend/tests/fixtures/** -text`); `core.longpaths true`. Lanes (max 3) work in `D:\lk-wt\<lane>`
  worktrees with their own env slots from Slice 1; Slice 0 lanes share the tree with disjoint paths and no git state
  changes. Alembic is one linear chain (`lk db reparent`, `alembic heads == 1`); generated API types are regenerated,
  never hand-merged; the integrator owns lockfiles, registry, routes manifest and docs. Only the integrator runs
  Playwright and `next build`. Details: `docs/architecture/parallel-work.md`.
- **Consequences**: predictable merges on a 15.7 GB machine. **Accepted.**

## ADR-035 One canonical fixture world
- **Decision**: `backend/app/seed/world/` created only through services at clock offsets from D0 = Mon 2026-10-12 08:55
  IST; personas Sahil, Meera, Neha, Ravi, Kabir, Arjun, Ananya, Priya (+ Vikram from Slice 2); parties Nordhaus Interiors
  GmbH, Maison Atelier SARL, Berg & Co AB, Thornbury Kitchens Ltd; LK-OT-0450 oak tray, carton 24, EUR 24.0000 on
  EXP-EUR-2026; prior won LK-QT-2026-0003 for 240 pcs. World quotes are numbered 0001–0008 in allocation order (the
  briefing design's illustrative 0035–0041 numbers would need counter jumps); scenario C therefore creates
  LK-QT-2026-0009. Expected Slice-1 sentences: Meera "Two customer replies need attention and one quote expires today.",
  Sahil "Three decisions need you. The rest is moving." Details: `docs/architecture/fixtures.md`.
- **Consequences**: every test encodes the same truth; greetings appear only because records compute them.
  **Accepted.**

## ADR-036 Enquiries and customer messages belong to sales from Slice 1
- **Decision**: `sales_enquiry` (ENQ numbering, party or prospect, channel, owner, status, linked quotes) and
  `sales_customer_message` (party/contact, direction, channel, received/replied, external-provenance body, links) with
  manual logging in Slice 1; channels create messages through the same service from Slice 3.
- **Consequences**: the Slice-1 sales briefing has real producers for replies and enquiries. **Accepted.**

## ADR-037 Additional domain entities
- **Decision**: samples (`sales_sample`, SMP numbering, Slice 2) distinct from challans; pick lists
  (`inventory_pick_list`, Slice 4) feeding draft challan lines without a second movement; persisted shortage state
  (`inventory_shortage_state`, Slice 4) with detected/changed/resolved events; QC unified in a `quality` module;
  `cutoff_at` on shipments; party roles {customer, vendor, fabricator, transporter, job_worker}; nullable product stock
  attributes (HSN/SAC, stock UOM, lot tracking, QC) from Slice 1, required when inventory goes live.
- **Consequences**: briefing families for operations have real producers. **Accepted.**

## ADR-038 Notes have one store
- **Decision**: `collab.note` is the only store for record-level internal notes (one autosaved internal note per record,
  conflict-aware with 409 and three-way merge; comments append-only). Domain `internal_notes` columns are not created;
  legacy notes migrate as note rows with provenance. `sales_quote_line.internal_note` stays a line field, redacted from
  documents.
- **Consequences**: one permission rule (parent update to write, parent read to read). **Accepted.**

## ADR-039 One preference store; mandatory controls are never preferences
- **Decision**: `identity.user_preference` with typed sections (ui: theme, motion, sidebar, rail, density, shortcuts;
  locale; briefing; voice; assistant). The `lk_ui` cookie mirrors theme and motion for server rendering. A guard rejects
  preferences that would weaken policy (422 `mandatory_control`).
- **Consequences**: no competing preference tables. **Accepted.**

## ADR-040 Single registries for integration status and AI usage
- **Decision**: `system.integration_status` is the only integration state (`connected` only via verification);
  provider configuration tables hold configuration only. `agents_ai_call_log` is the only AI usage store; cost is
  computed at report time from a configurable price table.
- **Consequences**: Settings and the admin briefing show one truthful state. **Accepted.**

## ADR-041 Search without regular expressions
- **Decision**: `platform/search` providers built on `ScopedRepository.search`, tokenised ILIKE with `escape_like`
  plus pg_trgm ranking, `search_recent` keeping the last 10 queries per user, restricted fields never indexed, group
  totals scoped.
- **Consequences**: closes legacy regex injection (§10.2 #6); custom products are found by `product_name`. **Accepted.**

## ADR-042 API shape
- **Decision**: `/api/v1/<module>/...`; exceptions `/api/v1/health/{live,ready}`, `/api/v1/session/bootstrap`,
  `/api/v1/webhooks/whatsapp`; problem+json with snake_case codes; all staleness and version conflicts 409;
  DecimalStr strings; `capabilities` + `allowed_transitions`; `Idempotency-Key` header; `Page{items,total,limit,offset}`
  and keyset pages for feeds; operationIds `<module>_<verb>_<noun>`; readiness excludes optional provider keys.
- **Consequences**: one generated client; deterministic OpenAPI export. **Accepted.**

## ADR-043 Finance stops at operational documents and an accounting adapter
- **Decision**: invoice and credit-note drafts, an issue gate on tax profile and provider configuration (labelled drafts
  always allowed), receipts, allocations, ageing, a CSV adapter and a Demo accounting adapter, reconciliation. No native
  general ledger, tax filing, GST/e-invoice/e-way-bill or bank payment execution without a verified integration; tax
  rules are never fabricated.
- **Consequences**: live tax-invoice issuance waits for the owner's accounting system and provider choice.
  **Accepted — owner to choose the accounting system and e-invoice provider.**

## ADR-044 UI primitives and data display
- **Decision**: react-aria-components is the only primitive library; native semantic tables; no chart library; design
  tokens on CSS variables with the default Tailwind palette removed; Manrope Variable (OFL, self-hosted) with Noto Sans
  Devanagari fallback; tabular numerals for money, units and quantities.
- **Consequences**: accessible components without mixing libraries; KPI-card walls are a review-checklist violation.
  **Accepted.**

## ADR-045 Self-service routes need no permission key
- **Decision**: own profile, password, sessions, MFA enrolment, preferences, reminders, personal memory, own delegations,
  own leave and access requests, and WhatsApp enrolment are `authenticated` routes; the employee base therefore carries no
  `identity.*` keys, and directory read is `org.directory.read`.
- **Consequences**: the management parity statement ("no identity keys") is literally true. **Accepted.**

## ADR-046 Price-override permissions
- **Decision**: `sales.quote_price.override` (legacy `override_price`) and `sales.quote_price.approve`. A reason is
  mandatory unless the actor holds `sales.quote_price.approve` covering the quote (legacy: management and admin free,
  sales must give a note). Review proposals with overrides, discounts or below-minimum subtotals require
  `sales.quote_price.approve` in addition to `sales.quote.approve`.
- **Consequences**: replaces the design-source `override_price_without_reason`; scenario A-09 (revoking override
  eligibility removes two of Sahil's decisions) follows from real keys. **Accepted.**

## ADR-047 Explicit future scope
- **Decision**: not built unless the owner adds them: full HR, attendance and payroll; native general ledger and chart of
  accounts; GST returns, e-invoice and e-way-bill without a chosen provider; bank payment execution; SSO/OIDC and passkeys;
  multi-company switching UI and blanket composite tenant FKs; push transport (SSE/WebSocket) for briefings; OCR beyond
  the vision confirmation flow; carrier APIs and 3D container stowage; inventory valuation (FIFO/average); MRP
  time-phasing; malware scanning for uploads; vector memory.
- **Consequences**: listed honestly in BUILD_STATE "Remaining" and the final handover. **Accepted.**

## ADR-048 Slice-0 spike: PostgreSQL 17
- **Decision**: `postgres:17-alpine` via compose on `127.0.0.1:54329`; `lk_app` is `NOSUPERUSER NOBYPASSRLS`; tenant RLS is
  forced and fails closed without `app.company_id`. Verified by committed-mode tests and `lk db status` (2026-10-23).
- **Consequences**: backup round trip is proven in Slice 5 with `lk backup create` and a restore rehearsal. **Accepted.**

## ADR-049 Slice-0 spike: ReportLab is the only PDF engine
- **Decision**: ReportLab 5.0.1 `[shaping]` with embedded Noto Sans and Noto Sans Devanagari; evidence in
  `docs/evidence/slice-0/pdf-spike.md`. **Accepted.**

## ADR-050 Slice-0 spike: Next 16 rewrite topology
- **Decision**: same-origin `/api/*` `beforeFiles` rewrite to FastAPI is verified for health; cookie/CSRF/Origin behaviour
  through the rewrite is verified by the Slice-1 platform lane's e2e login test; uploads (25 MB) by Slice-2 files; agent
  progress uses 500 ms polling until a Slice-3 SSE spike. **Accepted.**

## ADR-051 Run uvicorn as a module on Windows
- **Decision**: `python -m uvicorn` instead of the `uvicorn.exe` console-script shim, which Windows Application Control
  blocks on this machine (os error 4551). Applies to `npm run dev` and `npm run test:e2e`.
- **Consequences**: identical behaviour; no unsigned launcher needed. **Accepted.**

## ADR-052 Who must use MFA, and step-up (platform-2, Slice 2)
- **Decision**: members holding an MFA-flagged key of `identity`, `org`, `audit`, `system` or `numbering`
  ("privileged") must enrol and verify TOTP at sign-in; the `security_policy` setting (`identity.mfa.manage`) can
  require it of everyone. Other MFA-flagged keys are enforced at use time by `authz.stepup.require_step_up`, which owning
  modules call. Step-up is `POST /identity/session/reauthentication` (password = recent auth; code = recent auth +
  MFA); problem codes `mfa_required` / `reauth_required` (401). Demo-link sessions are not forced to enrol at sign-in
  (MFA-flagged actions still need a step-up); test-support sessions (`LK_ENV=test` only) count as MFA-verified.
- **Consequences**: only platform services call `require_step_up` so far; catalogue enforces recent-auth (`ra`) for
  its flagged keys. Other lanes wire step-up as they meet MFA-flagged keys. **Accepted.**

## ADR-053 Activity, delegation, deny, invitations and email (platform-2)
- **Decision**: (1) the activity feed is computed from the outbox (`domain_event`), filtered by the parent record's
  registered `ResourcePolicy`; collaboration events are attributed to their parent. (2) Delegation stores explicit keys;
  only delegable keys held by both people count at resolution. (3) Deny entries never remove keys of the implicit
  employee base. (4) An invitation to an email that already has an account confirms the existing password. (5) Email
  `smtp` mode is not implemented (409 `not_configured`); demo mode writes `.eml` under `<LK_STORAGE_DIR>/mail/` after
  commit and shows the link once to the administrator.
- **Consequences**: live email waits for SMTP credentials (BUILD_STATE §6). **Accepted.**

## ADR-054 Customer types are a table; catalogue media; imports run as the requester (catalogue-imports)
- **Decision**: `parties_party.customer_type` is a composite FK to `parties_customer_type(company_id, code)`; built-in
  `standard`/`dealer`/`distributor` rows are provisioned per company; inactive types cannot be newly assigned. Product
  media live in `platform/files` (sniffed, deduplicated, one live primary image, soft delete with reason). Import jobs
  run as the requesting user (`actor_for_member`), commit in 500-row batches re-planned under lock, and roll back from a
  hashed plan; the demo reset is `is_demo` only, recent sign-in, a 5-minute HMAC token and a typed phrase.
- **Consequences**: `pricing_price_list.customer_type` is not yet an FK (open item); web party forms still offer the
  three built-in types only (open item). **Accepted.**

## ADR-055 Canonical decor key for cutting (cutting, Slice 2)
- **Decision**: the cutting optimiser groups by the catalogue identifier rule: `120.0` → `120` with a warning, `0120`
  stays distinct (PARITY FG-GRN-01, PLAN). This supersedes `operations.md` §14, which kept `'120'` and `'120.0'` apart.
  Calculation results are stored as normalised append-only rows (not JSONB); configuration tables (settings, machine
  profiles, grain locks) are read with an explicit company filter plus RLS, gated by any `cutting.` key, because the
  frozen catalogue has no `.read` key for them. The grain-lock audit field is `decor` (the redactor blanks fields
  containing "key").
- **Consequences**: release and work-order links arrive in Slice 4. **Accepted.**

## ADR-056 Slice-2 merge: one screen per route, main's chrome with the lanes' editors
- **Decision**: where a Slice-2 lane rebuilt a screen that Checkpoint 2 had already built, the merged route keeps the
  Checkpoint-2 screen (PageHeader/RecordHeader chrome, facets, fact strips, the Material tab, rail context) and takes
  the lane's forms and commands into it: the product record gains inline section editors, archive/restore, Media and
  History tabs (`?tab=`; the server's `/products/{id}/{section}` paths redirect to the tab); the catalogue list gains
  Add product / Export CSV; the price-list list gains New price list; the customer record gains archive/restore.
  Screens the lane owns outright (taxonomy manager, price-list detail editor, imports, lookups, customer types, custom
  products, samples, FX rates, quote settings) keep the lane's body with the shared header chrome. The product record
  cache holds the raw server record so the editors round-trip every field; the view parses it with `select`.
- **Consequences**: one implementation per route and per query key; the lanes' duplicate list/detail components were
  removed with their tests ported. **Accepted.**

## ADR-057 Approval expiry is not scheduled outside production (Slice-2 merge)
- **Decision**: `approvals.expire_due` keeps its 5-minute schedule in production but is created disabled in
  development and test (`enabled_in_dev=False`). Fixture times are absolute (D0 = 2026-10-12), so the real-time sweep
  expired every seeded review on its first run and emptied the demo and e2e Inboxes part-way through a run. The
  service function stays tested directly (`tasks/test_rules.py`).
- **Consequences**: an expired review still leaves its quote in `internal_review` with no open approval (no
  `on_expired` handler); recorded as an open item for the sales/approvals owners. Revisit when fixture times become
  relative to the anchor. **Accepted.**

## ADR-058 Slice-2 e2e world and cross-lane links (Slice-2 merge)
- **Decision**: `npm run test:e2e` seeds the demo world at `--slice 2` (cut plan, challans, Kaveri and Precision Edge
  parties), so the axe sweep covers challan and cut-plan records. Scenario C asserts that its draft number follows
  the seeded quotes rather than equals `SCENARIO_C_NEW`, because Slice-2 specs that run earlier create drafts.
  Migration `0015_slice2_cross_lane_links` adds `challans_challan_line.custom_product_id → sales_custom_product.id`
  and `sales_sample.challan_id → challans_challan.id` (RESTRICT); the challans service validates a custom line's
  product as a field error. The Slice-2 migration chain is 0010 platform → 0011 catalogue → 0012 commercial → 0013
  cutting → 0014 challans → 0015 links.
- **Consequences**: `challans.challan.issued` carries `sample_id = null` until a challan can reference the sample it
  ships (owners: challans + sales). **Accepted.**
