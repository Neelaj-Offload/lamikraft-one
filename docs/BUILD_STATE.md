# Build state

**Checkpoint 0 — Slice 0 (bootstrap, contracts and spikes) verified 2026-10-23.** Slice 1 starting.

Resume rule: a new session reads `docs/PLAN.md`, this file, then `docs/architecture/*`, and continues from
"Next executable step". Nothing below is claimed as implemented unless it appears under **Implemented (verified)**
with evidence in the verification table.

Status vocabulary used across `BUILD_STATE.md` and `PARITY_MATRIX.md`:

| Term | Meaning |
|---|---|
| **Implemented (verified)** | code merged on `main`, tests passing, evidence recorded below |
| **Simulated (Demo)** | real code paths exercised through a labelled Demo provider; no live external effect |
| **In progress** | code exists in the working tree but is not yet verified or merged |
| **Planned** | contract and slice assigned, no code yet |
| **Backlog / future scope** | explicitly not in the requested scope unless the owner adds it (DECISIONS ADR-047) |
| **Blocked** | cannot proceed without an external input; the exact input is named |

---

## 1. Completed

| Item | Evidence |
|---|---|
| All inputs read: `CURRENT_STATE_SPEC.md`, `LAMIKRAFT_ONE_CONCEPT.md`, `OPUS_5_5_BUILD_PROMPT.md`, `IMAGE_PROMPTS.md`, two concept PNGs, `START_HERE.md` | `docs/PLAN.md` "Inputs inspected" |
| Implementation plan approved, including user decisions of 2026-10-12 (Docker Compose Postgres; autonomous slices with local commits; Claude Haiku/Sonnet/Opus by task; Gemini 3.8 Flash for vision and on-screen answers; structured screen context + masked screenshot on demand) | `docs/PLAN.md` |
| Design workflow output preserved: 7 subsystem designs and 2 critiques | `docs/design/source/*.md` (9 files) |
| Repository initialised: `.gitattributes` (`* text=auto eol=lf`, binaries, `backend/tests/fixtures/** -text`, CRLF only for `.ps1/.cmd/.bat`), `.gitignore`, `core.longpaths=true` | commit `8577588` "chore: initialise Lamikraft One repo with design artefacts, plan and backend core start" |
| Bootstrap tools: uv 0.13.0 on PATH; `postgres:17-alpine` image pulled (424 MB); Node 24.18 | `uv --version`, `docker images postgres:17-alpine` |
| Fonts for the PDF engine: Noto Sans Regular/Bold/Italic, Noto Sans Devanagari Regular/Bold, `OFL.txt` | `backend/app/core/documents/fonts/` |
| Python 3.14 no-build gate passed: `uv sync --locked --no-build` installs all **83** locked packages from wheels | `backend/uv.lock` (83 packages), `backend/.python-version` = 3.14; DECISIONS ADR-002 |
| Contract documents written (pending integrator review): conventions, API conventions, permissions, events, fixtures, parallel work, AI routing, motion system; DECISIONS ADR-001…047; PARITY_MATRIX skeleton | `docs/architecture/*.md`, `docs/DECISIONS.md`, `docs/PARITY_MATRIX.md` |

## 2. In progress — Slice 0 lanes (shared working tree, disjoint paths)

| Lane | Scope | State at checkpoint 0 |
|---|---|---|
| Integrator kernel | `backend/app/core/db/**`, `backend/app/platform/**` (authz, identity, org, events, jobs, numbering, idempotency, audit, system, approvals stub), `main.py`, `registry.py` with startup cross-validation, `worker.py`, Alembic baseline + helpers, `tests/conftest.py` (savepoint and `@committed` modes, `drain_events`) | kernel files present in the working tree (UoW with RLS GUCs, ScopedRepository, scope clause, ActorContext, permission/event/job/sequence defs, registry validation, CSRF/Origin middleware, route declarations); not yet verified |
| Web scaffold | `apps/web/**`: Next 16.4 + React 19.3 + Tailwind 4 tokens (light and dark), Manrope, route manifest with coverage test, UI-preference cookie (`theme`, `motion`), Playwright config (127.0.0.1, `workers: 2`, fake-media flags) | scaffold, tokens, `routes.ts` + test and `ui-preferences.ts` + test present; not yet verified |
| Dev tooling | `scripts/dev.mjs` (`setup`, `dev`, `check`, `test-api`, `test-e2e`, `api-generate`, `api-check`, `db-up`, `db-migrate`, `seed-demo`), CLI `lk env init --slot`, `lk db ensure-roles`, `lk db reparent`, `lk admin create-first`, `docker-compose.yml`, `.env.example`, `docs/runbooks/local-dev.md` | root `package.json` scripts and `backend/app/cli/**` present; Playwright Chromium install not yet confirmed |
| PDF engine | `backend/app/core/documents/**` (ReportLab Platypus, embedded Noto fonts, layout and formatting helpers) and the ReportLab spike | fonts, `fonts.py`, `layout.py`, `format.py` present; spike not yet recorded |
| Contract docs | this file, `PARITY_MATRIX.md`, `DECISIONS.md`, `docs/architecture/*.md` | written; awaiting integrator review |

Slice-0 spikes (results in `docs/DECISIONS.md` ADR-048…051):

| Spike | Checks | Result |
|---|---|---|
| PostgreSQL 17 (compose) | roles `lk_owner`/`lk_app`; `pg_trgm`, `btree_gist`; RLS fails closed as `lk_app`; 40-way barrier numbering | **verified** by `lk db status` and `tests/integration/test_platform_kernel.py` (`test_rls_fails_closed_without_tenant_guc`, `test_app_role_cannot_bypass_rls`, `test_concurrent_numbering_is_unique_and_gapless`); `pg_dump`/`pg_restore` round trip moves to Slice 5 (`lk backup`) |
| ReportLab | € ₹ £ glyphs with embedded Noto; 150-row table with repeated header; Devanagari shaping | **verified** — `docs/evidence/slice-0/pdf-spike.md` (35 unit tests) |
| Next 16 rewrites | `/api/*` rewrite to FastAPI; session cookie, CSRF and Origin through rewrites; 25 MB upload; SSE timing | rewrite **verified** (`GET /api/v1/health/ready` → 200 via `127.0.0.1:3000`); cookie/CSRF checks move to the Slice-1 platform lane, upload to Slice 2 files, SSE to Slice 3 (polling is the Slice-1 contract) |
| Toolchain | TypeScript 5.9 + ESLint 9 + `openapi-typescript` generation from `backend/openapi.json` | **verified** — `npm run check` green (ruff, pytest unit+contract, heads=1, api:check, eslint, tsc, vitest 134 tests) |

## 3. Blocked

None.

## 4. Remaining (slices 1–6)

| Slice | Delivers | Exit |
|---|---|---|
| 0 (finish) | kernel verified; CLI; scripts; spikes; runbook `docs/runbooks/local-dev.md`; integrator review of contracts | `npm run setup && npm run dev` from `D:\Lamikraft ERP`; `GET /api/v1/health/ready` 200; `npm run check` green; RLS isolation test and two-connection barrier test pass; spike evidence recorded |
| 1 | sessions, CSRF, login, rate limits, lockout; role templates + overrides; first-admin CLI; demo sign-in links; numbering; settings; LocalFs files; audit; route-authz matrix; UOM master; default work calendar; catalogue tables + read/search; minimal parties; enquiries and customer messages; seeded price lists with tier resolution; commercial engine v1; quotes (header, lines, snapshots, totals, numbering, versions, transitions submit_review/approve/reject/mark_sent/mark_won/cancel/delete draft, issued revision, ReportLab PDF); tasks, issues, change log, reminders, queues; deterministic briefing engine; Today/Inbox APIs; approvals engine with `sales.quote.review`; Demo orchestrator as `agent.run` with polling; shell, login, Today, Inbox, quote workspace, review page, enquiries list | scenario C (API + e2e, desktop and phone); scenario D (engine + UI/API/PDF agreement); F subset (IDOR matrix, 40-way numbering, optimistic 409); A subset; B subset; keyboard journey; axe in both themes |
| 2 | full legacy parity: MFA, invitations, resets, custom roles, overrides UI, role simulator, delegation, leave, access requests, notes, attachments, activity, global search, S3 adapter; catalogue forms, media, taxonomy, facets, stats, completeness, identifier normalisation, packaging alias reconciliation, import workbench for all seven types, lookups, demo reset; price-list CRUD and supersede, pricing import contract, FX with approval, full quote state machine, compare/restore, duplicate, custom products with promotion, samples, CSV exports, settings UIs; challans as documents; cutting optimiser (MaxRects + guillotine) with saved plans and true-scale canvas | scenarios E, F, G, H, L at API and e2e; every PARITY_MATRIX row maps to code and a test; all §10.2 items closed |
| 3 | Anthropic adapter and routing table; durable runs (streaming per spike); memory; automations; action refs; trace view; AI usage dashboard; Gemini vision adapter + Demo; masked screenshot; voice (push-to-talk, transcript, TTS, read-back, offline drafts); WhatsApp Cloud adapter + Demo through the real webhook; Listen to my day, LLM phrasing, delta view, WhatsApp summary | scenarios B, J, K; C via text, voice and WhatsApp demo; graceful AI outage |
| 4 | sales orders; inventory ledger, reservations, pick lists, counts, adjustments, transfers, reversals, opening batches; challan movement policy; procurement with GRN and QC; production (BOM, routing, work orders, cut-plan links, offcut lots, capacity, cost rollups, feasibility, what-if); logistics; operations briefing families | scenario I incl. no-oversell barrier test, single posting per challan, replay safety; ledger property tests |
| 5 | finance drafts, issue gate, receipts, allocations, ageing, CSV + Demo accounting adapter, reconciliation, margin; migration dry-run tooling for every legacy entity; `lk backup create` + rehearsed restore; offcut reuse, sample lineage, what-if views | scenario M; restore proven locally |
| 6 | full A–N matrix at 1440/834/390 px; axe on every manifest route; dead-control crawl; `pip-audit`, `npm audit`; final screenshots; handover docs (setup, provider guide, migration and backup runbooks, remaining-work list) | all A–N green; PARITY_MATRIX 100 % with evidence |

### Implemented vs simulated vs backlog (current)

| Category | Items |
|---|---|
| Implemented (verified) | none yet at product level (checkpoint 0) |
| Simulated (Demo) — planned | Claude-shaped orchestrator (Slice 1), vision and on-screen answers (Slice 3), STT/TTS (Slice 3), WhatsApp provider through the real webhook route (Slice 3), email as `.eml` files (Slice 2), accounting adapter (Slice 5). Every output labelled "Demo"; Settings shows "Demo — not connected" |
| Backlog / future scope | full HR, attendance and payroll; native general ledger; GST/e-invoice/e-way-bill without a chosen provider; bank payment execution; SSO/passkeys; multi-company switch UI and blanket composite tenant FKs; push transport for briefings; OCR beyond vision confirmation; carrier APIs and 3D stowage; inventory valuation; MRP; upload malware scanning; vector memory |

## 5. Business-policy decisions needing owner confirmation

Demo defaults are in force until confirmed; each is recorded in `docs/DECISIONS.md`.

| # | Decision | Demo default | Blocks |
|---|---|---|---|
| 1 | Quote-number reset policy | `LK-QT-YYYY-NNNN` never resets (legacy continuity); DC yearly; CP never; finance April financial year | nothing (configurable) |
| 2 | Approval thresholds for price overrides, discounts and below-minimum quotes | review only when requested; demo rule requires an approved review before issuing quotes with overrides, discounts or a below-minimum subtotal | live approval policy |
| 3 | Statutory accounting system (Tally / Zoho Books / other) | CSV export adapter + Demo adapter | live accounting sync |
| 4 | E-invoice / e-way-bill provider and tax profiles | none; tax not calculated; drafts labelled | live tax-invoice issuance |
| 5 | STT/TTS vendor for English and Hindi/Hinglish (shortlist Sarvam, Google, Azure) | Demo adapter; browser fallback labelled and off by default; Hindi/Hinglish labelled untested | production voice |
| 6 | DPDP approval to send business data and masked screenshots to Anthropic and Google; any data-residency constraint | `LK_AI_MODE=demo`; screenshots disabled in live until approved | live AI |
| 7 | WhatsApp Business account, numbers (employee assistant vs customer service) and Meta app | Demo provider | live WhatsApp |
| 8 | Legal entity structure (one company vs Crown and Lamikraft entities) | one company, two brand tokens (LK, CR) | multi-entity setup |
| 9 | Company identity: logo, legal address, GSTIN, PAN, IEC, bank details, document terms | "Not configured" placeholders labelled in documents | issued documents |
| 10 | Rounding policy (line-level HALF_UP to the minor unit; FX unit prices to 2 dp) | as stated | accountant sign-off |
| 11 | Workweek, shifts and rollover | Mon–Sat, 09:30–18:30, Asia/Kolkata, 04:00 rollover | nothing (configurable) |
| 12 | Meaning of the legacy "+10 mm oversize" (assumed larger raw board per side) | separately enabled, plans flagged "verify before release" | cut-plan release |
| 13 | Semantics of legacy `lookup_reference` data | preserved, browsable and exportable; unused in rules | any rule that would consume it |
| 14 | HSN/SAC codes per product; financial-year start month | empty; April | challan HSN completeness, finance numbering |
| 15 | Price precedence when an agreement exists in another currency | tier-first, direct currency preferred, FX only when enabled with an approved dated rate | nothing (policy versioned) |
| 16 | Ownership transfer timing for exports (challan issue vs transporter handover) | ownership passes at challan issue | inventory go-live |

## 6. Credentials needed for live mode

Placed by the user in `.env` (never in documents or the repository). Without them the corresponding integration stays
Demo and the UI says so; nothing pretends to be connected.

| Integration | Variables / inputs |
|---|---|
| Anthropic (Claude) | `ANTHROPIC_API_KEY`; `LK_AI_MODE=live` only after DPDP approval |
| Google (Gemini 3.8 Flash vision) | `GEMINI_API_KEY` |
| WhatsApp Cloud API | WABA ID, phone number ID, access token, app secret, verify token, Graph API version; a public HTTPS webhook URL with a valid certificate; Meta business verification; approved templates |
| STT/TTS | vendor API key(s) for the chosen provider |
| S3-compatible storage | endpoint URL, bucket, region, access key id and secret (`LK_STORAGE_BACKEND=s3`) |
| Email (invitations, resets, quote dispatch) | SMTP host, port, username, password, from address (`LK_EMAIL_MODE=smtp`) |
| Accounting system | credentials for the chosen system's adapter |
| E-invoice / e-way-bill | provider credentials and verified tax profiles |

## 7. Verification evidence

Filled at each checkpoint; one row per executed check.

| Date | Slice | Check | Command | Result | Evidence |
|---|---|---|---|---|---|
| 2026-10-23 | 0 | setup | `npm run setup` | all 9 steps PASS | console |
| 2026-10-23 | 0 | API suite | `npm run test:api` | 92 passed | console |
| 2026-10-23 | 0 | check | `npm run check -- --keep-going` | 7/7 PASS | console |
| 2026-10-23 | 0 | dev boot | `npm run dev`; `curl /api/v1/health/ready` on :8000 and via :3000 rewrite | 200 / 200; `/login` 200 | console |

## 8. Next executable step

Slice 0 is committed. Run Slice 1 in worktree lanes (`D:\lk-wt\<lane>`, env slots 1–4) per `docs/PLAN.md`:
wave 1 = platform, catalogue/parties/pricing/commercial, work (tasks/briefings); wave 2 = sales quotes + PDF,
approvals/agents-demo, web shell/login/Today/Inbox/quote workspace.

Environment notes (2026-10-23): Windows Application Control blocks the `uvicorn.exe` venv shim, so `scripts/dev.mjs`
runs `python -m uvicorn`. Docker Desktop 4.82 can fail to start on stale AF_UNIX socket files in
`%LOCALAPPDATA%\Dockerun` and `%LOCALAPPDATA%\docker-secrets-engine`; moving those folders aside fixes it
(runbook). `next dev` 16.4.0 prints a security-advisory nudge and exits once; a retry continues. The advisory is
tracked for the Slice-6 `npm audit` pass.

---

## 9. Interim checkpoint — Slice 1 wave 1 merged (2026-10-27, session cut by usage limit)

**On `main` (commit `33ba1ac`):** the five wave-1 lanes (identity `lane/s1w1-identity`, platform `lane/s1w1-platform`,
catalogue `lane/s1w1-catalogue`, work `lane/s1w1-work`, web `lane/s1w1-web` at its fix-pass state) are merged after
each lane's adversarial review and a completed fix pass (117 findings; every blocker and major fixed with regression
tests; deferred minors are listed in each `docs/lanes/<lane>.md` "Fix pass (2026-10-27)" section). Migrations are one
chain 0001 → 0002 → 0003 identity → 0004 platform → 0005 catalogue → 0006 work (`alembic heads` = 1). `openapi.json`
and `schema.d.ts` regenerated (62 paths, 180 schemas).

**Verification on `main` after the merge:** `npm run test:api` → **708 passed, 1 failed, 1 xpassed**. The failure is
`tests/integration/identity/test_seed.py::test_people_roles_managers_and_refs` (a `KeyError` on a membership id once
the org and catalogue seeds run alongside the identity seed: integration drift, not a lane defect). `npm run check` and
`lk seed demo` have not been run on the merged tree yet.

**Still running when the session stopped (work lands on their own branches; nothing is merged yet):**
- sales lane `lane/s1w2-sales` (`D:\lk-wt\sales`, slot 6): quotes, enquiries, customer messages, approvals handler,
  PDF, tools, seeds — brief in the session scratchpad `s1w1/sales-brief.md`.
- agents-demo lane `lane/s1w2-agents` (`D:\lk-wt\agents`, slot 7): Demo orchestrator, `agent.run` job, polling API,
  cards, grounding — brief `s1w1/agents-brief.md`.
- web wave 2 on `lane/s1w1-web` (`D:\lk-wt\web`, slot 5): Today/Inbox bound to real APIs, quote list and workspace,
  review page, enquiries, assistant composer, Playwright specs — brief `s1w1/web2-brief.md`.
Both backend lanes were told to merge `lane/s1w1-catalogue` into their branches (wire-shape changes) and to reset
their slot databases because migration 0005 was edited in place.

**Next executable step:** (1) fix the one failing seed test on `main`; run `npm run check` and `npm run test:api` to
green; (2) when the three lanes report, review their reports, merge in the order sales → agents → web, reparent
`0007_sales` onto 0006 and `0008_agents` onto 0007, regenerate types, switch the work lane's fake sales readers/handler
and the agents lane's fake sales tools to the real modules; (3) integrator backlog from the lane reports
("Requests for the integrator" in each `docs/lanes/*.md`): uvicorn `--no-proxy-headers` and `LK_TRUSTED_PROXY_HOPS`
in core settings; kernel `build_sections` per-section savepoint; platform's post-merge swaps (core `RatioStr`,
`keys.py` fallbacks, download Cache-Control xfail, upload limiter); keys.py constants requested by catalogue and work;
SourceReaders `identity.membership`, `identity.user_preference`, `ui.recent_record`, `search.recent`; PARITY_MATRIX
test pointers; (4) `lk seed demo`, `npm run dev`, Playwright for scenario C at desktop and phone, axe in both themes,
screenshots to `docs/evidence/slice-1/`; (5) update sections 1–4 and 7 of this file, PARITY_MATRIX statuses, and make
the Slice-1 commit.
