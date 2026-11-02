# Build state

**Checkpoint 2 — web surfaces for every API that exists, plus the showcase motion system, on `main` 2026-11-02.**
(Checkpoint 1 — Slice 1 — merged 2026-10-30. Checkpoint 0 — Slice 0 — verified 2026-10-23.) Slice 2 backend next.

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

## 2. In progress

Nothing in flight. Slice 1 is merged on `main` (see section 9 for what it contains and its evidence). Slice-0 lanes
and spikes are complete; their results are in `docs/DECISIONS.md` ADR-048…051 and `docs/evidence/slice-0/`.

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
| 2026-10-30 | 1 | API suite on `main` 27502a8 | `npm run test:api` | 1063 passed | `D:\lk-wt\test-main-s1.log` |
| 2026-10-30 | 1 | check on `main` 27502a8 | `npm run check -- --keep-going` | 7/7 PASS (unit+contract 481, vitest 410) | `D:\lk-wt\check-main-s1.log` |
| 2026-10-30 | 1 | e2e on `lane/s1-merge` (= `main` 27502a8) | `npm run test:e2e -- --no-build --workers=1` on fresh `lk seed demo` | 70 passed, 113 skipped (project-scoped / opt-in) | `docs/lanes/merge-s1w2.md` |
| 2026-10-30 | 1 | screenshots inspected | 24 PNGs at 1440/390 × light/dark | 3 defects found and fixed in c0d2c7e; re-checked live on slot 8 | `docs/evidence/slice-1/` |
| 2026-10-30 | 1 | vitest after the screenshot fixes | `npx vitest run` | 411 passed | console |
| 2026-11-02 | CP2 | check on the working tree | `npm run check -- --keep-going` | 7/7 PASS (ruff, pytest unit+contract 481, alembic heads 1, api:check, web lint, typecheck, vitest 39 files / 496 tests) | scratchpad `check-cp2.log`, summary in this row |
| 2026-11-02 | CP2 | dev boot and route sweep | `npm run dev` on 127.0.0.1:3200 / 8200, signed in as Meera and Sahil through `lk demo sign-in-link` | 21 routes rendered real data or an honest state; no console errors on the clean server | `docs/evidence/checkpoint-2/README.md` |
| 2026-11-02 | CP2 | showcase surfaces in the browser | sign-in light/dark/phone, story scroll, Today reveal, sidebar indicator, product Material tab (WebGL canvas 838×627, three presets) | as designed; reveal gate and entrance hold under Strict Mode and hidden tabs | `docs/evidence/checkpoint-2/*.jpg` |
| 2026-11-02 | CP2 | e2e on the working tree | `LK_NEXT_BUILD_CPUS=2 NODE_OPTIONS=--max-old-space-size=2048 npm run test:e2e -- --workers=1` (own database, production build) | 96 passed, 0 failed, 165 skipped (project-scoped / opt-in); axe sweep in light and dark now includes `/products/[productId]`, `/sales/parties/[partyId]`, `/products/price-lists/[priceListId]` | scratchpad `e2e-cp2-run2.log`; the first run found 7 login failures (sand numerals at 2.21:1, missing h1 "Sign in"), fixed before the rerun |

## 8. Next executable step

Slice 2 (complete legacy parity) per `docs/PLAN.md`, in waves of at most three lanes, starting from `main` at the
Checkpoint-2 commit. The web side of Slice 2 (product and price-list forms, imports workbench, cutting canvas,
challans) builds on the screens and recipes in `docs/superpowers/specs/2026-11-02-checkpoint-2-build-guide.md`.
Before the first Slice-2 wave:
1. Re-run `npm run test:e2e` on `main` once the machine has memory to spare: the 2026-10-30 run after c0d2c7e
   stopped in `next build` with an out-of-memory error (machine had 1.6 GB free of 15.7 GB). The same code passed
   e2e on the merge branch earlier the same day; c0d2c7e changes only three components (vitest-covered, checked live).
2. Decide the Next.js 16.4.0 security advisory: `next build`/`next dev` stop once and recommend an upgrade. It
   changes lockfiles, so it waits for the owner (also on the Slice-6 `npm audit` list).
3. Carry the open items below into the Slice-2 lane briefs.

Open items carried from Slice 1 (owners in brackets):
- Rendered quote PDFs are rendered on demand from the immutable snapshot; storing them through
  `platform/files.store_generated` needs a schema decision (revisions are append-only, file claims are per user). [sales + platform]
- `lk seed demo` anchors on today but fixture times are absolute (D0 = 2026-10-12): seed with
  `--anchor-date 2026-10-12` until fixture times are made relative. [fixtures]
- Five web adapters still parse responses at runtime (`INTERIM(api-generate)`): openapi-typescript marks
  server-defaulted fields required in request bodies. [web]
- `tasks_issue` per-key advisory locks can deadlock if two handlers take keys in opposite orders (Postgres aborts
  one; the job retries). Sort keys before locking. [work]
- CSRF verifier in a threadpool; UOM CHECK constraints → foreign keys; `integration_status` registry; catalogue
  test world still uses its own fake actor builder. [integrator / catalogue]
- Approvals engine: `get` hides proposals from management who are neither requester nor approver; `withdraw` is
  requester-only (sales invalidates instead). [approvals]
- Enquiry outcome codes are free text; a catalogue is needed. Quote delete is a capability, not a transition. [sales]
- Composer: Enter inserts a newline; decide whether Enter sends (Shift+Enter for newline). [web, design]

Open items carried from Checkpoint 2 (owners in brackets):
- `next build` stops once per build on the Next.js 16.4.0 security nudge (`SecurityFatalError`) and must be
  retried; the e2e orchestration therefore needs two invocations until the upgrade decision is made. [owner]
- `queryKeys.sales.quotes()` has no `party_id` slot; the customer record uses an inline key under the same prefix.
  Add the parameter to the factory. [web]
- `UiPreferencePatch` in `lib/session/preferences.ts` names only theme/sidebar/rail; the profile page passes the
  wider patch (motion, density, shortcuts) through a typed cast in `features/settings/api.ts`. Widen the type. [web]
- Procedural fixture swatches stand in for product media (`public/swatches/README.md`); replace through
  `features/material-viewer/swatches.ts` when catalogue media land. [catalogue, web]
- The sign-in headline uses Fraunces (OFL, `@fontsource-variable/fraunces`, loaded on `/login` only); the owner's
  design system may replace it through `--font-display` in `globals.css`. [design]
- The Next.js 16.4.0 advisory and lockfile upgrade decision from Checkpoint 1 still stands. [owner]

---

## 9. Checkpoint 1 — Slice 1 on `main` (2026-10-30)

Merged in this order (lane reports under `docs/lanes/`): identity, platform, catalogue (parties, pricing, commercial),
work (tasks, briefings), test-reconcile, integration backlog, sales, agents-demo, web (waves 1 and 2); the wave-2
merge and its fixes are recorded in `docs/lanes/merge-s1w2.md`. Migration chain 0001 → 0009 (0007 ui recent records,
0008 sales, 0009 agents), `alembic heads` = 1. `openapi.json` / `schema.d.ts` regenerated.

What runs: password sign-in with CSRF, rate limits and lockout; demo sign-in links; role templates and overrides;
numbering; settings; files (LocalFs); audit; UOM master and work calendar; catalogue read/search; parties; price
lists with tier resolution and the commercial engine; enquiries and customer messages; quotes (header, lines,
snapshots, totals, versions, review/approve/reject/send/won/cancel/delete-draft, issued revision, ReportLab PDF);
approvals with `sales.quote.review`; tasks, issues, reminders, Inbox; deterministic briefings (Today, delta,
rollover); the Demo assistant as a durable `agent.run` with polling, server-built cards and grounding (scenario C:
"prepare Nordhaus's usual oak tray quote" → draft → "change it to 300"); web shell, login, Today, Inbox, quote
list and workspace, review page, enquiries, customer messages, assistant composer — desktop and phone, light and
dark.

Exit criteria (PLAN Slice 1): scenario C API + e2e desktop/phone — passed; scenario D engine + UI/API/PDF
agreement — `tests/integration/documents/test_output_channels_agree.py` and `tests/integration/sales/test_quote_lines.py`; scenario F subset (IDOR
matrix, 40-way numbering, optimistic 409) — passed; A subset and B subset — passed in `tests/integration/briefings`
and `tasks`; keyboard journey and axe in both themes on all 24 manifest routes — passed; screenshots inspected and
defects fixed — done (see section 7). PARITY_MATRIX: 40 rows implemented, 13 in progress, 647 planned (Slice 2–6).

---

## 10. Checkpoint 2 — web completion and showcase motion (2026-11-02)

Design: `docs/superpowers/specs/2026-11-02-frontend-showcase-and-completion-design.md`; build guide (file map,
recipes, motion contract, design-system swap seams): `docs/superpowers/specs/2026-11-02-checkpoint-2-build-guide.md`.
Evidence: `docs/evidence/checkpoint-2/`. No backend change; no migration.

What runs (all against the existing API, every figure from the server, honest states everywhere):
- **Showcase surfaces (motion-system §2):** sign-in choreography (GSAP entrance ≤ 900 ms, four-board material
  composition with ≤ 12 px pointer parallax, Lenis story section, dark theme, phone layout); Today greeting reveal
  (once per briefing version, ≤ 700 ms, skipped offline/stale/reduced/hidden tab); route transitions
  (`(app)/template.tsx`); sliding sidebar indicator; lazy Three.js material viewer on the product record
  (real L × W × T, swatch albedo + normal map, drag/keys/presets, demand rendering, static fallback).
- **Products:** catalogue list (URL-state filters, server facets with exclude-self counts, stats fact strip, price
  column by currency when permitted), product record with Overview / Specification / Packaging / Prices /
  Material tabs, completeness rules, taxonomy, price lists and price-list items.
- **Sales:** hub "my work in motion" (status counts, quotes in review, messages waiting, open enquiries);
  customers list, customer record (edit drawer with 409 three-way merge, add contact, quotes of the customer),
  new-customer form (Idempotency-Key, 422 field errors).
- **Settings:** hub with workspace modes; profile (account facts, preferences incl. motion, password change,
  current session); company settings (every registered setting, typed editor when allowed, revisions); reference
  data (currencies, UOMs, work calendar); integrations; audit log (keyset pages, filters).
- **Operations / Finance:** honest overviews naming the slice each sub-area arrives in; no fabricated figures.
- **Design system additions:** PageHeader, FactStrip, RecordHeader, SectionCard, KeyValueGrid, FacetGroup, AreaNav;
  `--font-display` token; procedural fixture swatches and their generator.

Verification at this checkpoint is in §7 (rows dated 2026-11-02).
