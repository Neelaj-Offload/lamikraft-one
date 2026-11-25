# Build state

**Checkpoint 7a — CRM programme modules 1–3 (leads, customers and samples, proforma invoices) on `main` via
`lane/crm-leads`, 2026-11-25** (section 16). Checkpoint 6 (section 15) and earlier remain below.

Resume rule: a new session reads `AGENTS.md` and `CODEX_HANDOFF.md`, then `docs/PLAN.md`, this file and
`docs/architecture/*`, and continues from
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

Slice 6: merge `lane/s6-handover` onto Checkpoint 6, decide and verify Pillow 13, then execute
`docs/superpowers/briefs/s6-acceptance.md` on `lane/s6-acceptance`. The A–N matrix at 1440/834/390 px,
loaded-page isolation/accessibility/control sweeps, final audits and evidence remain unverified.

## 3. Blocked

None.

## 4. Delivery slices and remaining work

This is the delivery plan. Implemented scope through Slice 5 is recorded in Checkpoints 1–6 (§§9–15);
Slice 6 acceptance is next. Carried product gaps remain explicit in those checkpoint sections.

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
| Implemented (verified) | implemented scope recorded in Checkpoints 1–6 (§§9–15); carried product gaps and final acceptance remain explicit |
| Simulated (Demo) | AI and vision, STT/TTS, WhatsApp, local `.eml` email and finance accounting acknowledgement/reconciliation. Every simulated external effect remains labelled Demo; no live provider credential or business-policy choice has been invented. |
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
| 2026-11-04 | CP3 | API suite on `lane/s2-merge` 17a2f99 | `npm run test:api` | 1313 passed, 0 failed | scratchpad `test-api-final.log` / `junit-final.xml` |
| 2026-11-04 | CP3 | check on 17a2f99 + evidence spec | `npm run check -- --keep-going` | 7/7 PASS (ruff; pytest unit+contract 545; alembic heads 1; api:check; web lint; typecheck; vitest 53 files / 611 tests) | scratchpad `check-final.log` |
| 2026-11-04 | CP3 | e2e on the same tip | `LK_NEXT_BUILD_CPUS=2 NODE_OPTIONS=--max-old-space-size=2048 npm run test:e2e -- --workers=1` (own database, production build, demo world `--slice 2`) | 193 passed, 0 failed, 395 skipped (project-scoped / opt-in) | scratchpad `e2e-final-1.log`; earlier runs on the four-lane merge found the defects listed in `docs/lanes/merge-s2.md` |
| 2026-11-04 | CP3 | evidence screenshots | `LK_E2E_EVIDENCE=cp3 npm run test:e2e -- --no-build e2e/evidence-cp3.spec.ts --project=desktop` | 64 PNGs, 16 screens × 1440/390 × light/dark | `docs/evidence/checkpoint-3/` |
| 2026-11-04 | CP3 | migrations | `alembic upgrade head` → `downgrade -1` → `upgrade head`; `alembic check` on `lk_wt8` | chain 0009 → 0015, heads 1, no pending operations | console |
| 2026-11-04 | CP4a | API suite on `lane/s3-merge` ca7cb96 | `npm run test:api` | 1479 passed, 7 skipped (live-only `test_golden_live`), 0 failed, 38 min 45 s | scratchpad `s3a-test-api.log` / `s3a-junit.xml` |
| 2026-11-04 | CP4a | channels suite after the demo-media fix (8228d17) | `pytest tests/integration/channels tests/contract/channels tests/unit/channels` | 100 passed | scratchpad `s3a-channels-final.log` |
| 2026-11-04 | CP4a | check on 8228d17 | `npm run check -- --keep-going` | 7/7 PASS (ruff; pytest unit+contract 633; alembic heads 1; api:check; web lint; typecheck; vitest 56 files / 628 tests) | scratchpad `s3a-check-final.log` |
| 2026-11-04 | CP4a | e2e on 8228d17 | `LK_NEXT_BUILD_CPUS=2 NODE_OPTIONS=--max-old-space-size=2048 npm run test:e2e -- --workers=1` (build from the first run, own database, `--slice 2`) | 203 passed, 0 failed, 436 skipped; SSE asserted in scenario C (desktop, phone); `scenarios/k-whatsapp.spec.ts` 4/4 | scratchpad `s3a-e2e-final.log`; the first run found the defects in `docs/lanes/merge-s3a.md` |
| 2026-11-04 | CP4a | evidence screenshots | `LK_E2E_EVIDENCE=cp4a npm run test:e2e -- --no-build e2e/evidence-cp4a.spec.ts --project=desktop` | 24 PNGs, 6 screens × 1440/390 × light/dark | `docs/evidence/checkpoint-4a/` |
| 2026-11-04 | CP4a | migrations | `alembic downgrade 0015` → `upgrade head`; `alembic check` on `lk_wt8` | chain 0015 → 0016 → 0017 → 0018, heads 1, no pending operations | console |
| 2026-11-04 | CP4 | API suite on `lane/s3-merge` c8863a4 | `npm run test:api` | 1571 passed, 7 skipped (live-only `test_golden_live`), 0 failed, 59 min 55 s (stage 2a on 6cdf822: 1556 passed) | scratchpad `testapi2.log` (stage 2a `testapi1.log`) |
| 2026-11-04 | CP4 | check on 46cf18e | `npm run check -- --keep-going` | 7/7 PASS (ruff; pytest unit+contract 681; alembic heads 1; api:check; web lint; typecheck; vitest 60 files / 661 tests) | scratchpad `check4.log` (run on d6acfe7 failed lint on a ref read during render, fixed in 46cf18e) |
| 2026-11-04 | CP4 | e2e on d6acfe7 | `LK_NEXT_BUILD_CPUS=2 NODE_OPTIONS=--max-old-space-size=2048 npm run test:e2e -- --workers=1` (own database, production build, `--slice 2`) | 219 passed, 0 failed, 474 skipped; scenario C with SSE (desktop, phone), B 2/2, J-voice 8/8, C screen capture 2/2, K-WhatsApp 4/4, axe sweep light and dark incl. `/today/changes`, `/today/all` | scratchpad `e2e3.log`; runs 1–2 found the defects in `docs/lanes/merge-s3.md` |
| 2026-11-04 | CP4 | targeted e2e on 46cf18e (after the lint fix) | `npm run test:e2e -- --workers=1 e2e/scenarios/b-briefing-stability.spec.ts e2e/scenarios/j-voice.spec.ts e2e/scenario-c.spec.ts` (fresh build) | 16 passed, 0 failed | scratchpad `e2e4.log` |
| 2026-11-04 | CP4 | evidence screenshots | `LK_E2E_EVIDENCE=cp4 npm run test:e2e -- --no-build e2e/evidence-cp4.spec.ts --project=desktop` | 24 PNGs, 6 screens × 1440/390 × light/dark | `docs/evidence/checkpoint-4/` |
| 2026-11-04 | CP4 | migrations | `lk db migrate --revision 0018` → `migrate`; `lk db heads`; `alembic check` on `lk_wt8` | chain 0018 → 0019 → 0020 → 0021, heads 1; `alembic check` reports only the migration-only expression index `uq_vision_capture_conversation_sha` (ADR-061) | console |
| 2026-11-05 | CP5 | API suite after each lane on `lane/s4-merge` | `npm run test:api` on 76bc019 / 6505e56 / c4210a3 | 1612 / 1654 / 1688 passed, 7 skipped (live-only), 0 failed (54.6 / 56.4 / 53.9 min) | scratchpad `s4-oi-testapi.log`, `s4-prod-testapi.log`, `s4-pql-testapi.log` (+ junit) |
| 2026-11-05 | CP5 | API suite on the final tree d3eb52b | `npm run test:api` | 1688 passed, 7 skipped (live-only `test_golden_live`), 0 failed, 51.5 min | scratchpad `s4-final-testapi.log` / `s4-final-junit.xml` |
| 2026-11-05 | CP5 | check on d3eb52b | `npm run check -- --keep-going` | 7/7 PASS (ruff; pytest unit+contract 706; alembic heads 1; api:check 399 paths; web lint; typecheck; vitest 63 files / 685 tests) | scratchpad `s4-check2.log` (also 7/7 on 81b2d14, `s4-check1.log`) |
| 2026-11-05 | CP5 | e2e on 2a4d0ad | `LK_E2E_EVIDENCE=cp5 LK_NEXT_BUILD_CPUS=2 NODE_OPTIONS=--max-old-space-size=2048 npm run test:e2e -- --workers=1` (own database, production build, `--slice 4`) | 283 passed, 0 failed, 650 skipped (project-scoped / opt-in), 16.9 min; scenario I, `p-procure-to-pay` 4/4, `production/work-order-journey` 4/4, axe sweep light and dark incl. the Slice-4 routes with fixture records | scratchpad `s4-e2e5.log`; runs 1–3 (266/6, 268/3, 272/2) found the defects in `docs/lanes/merge-s4.md` |
| 2026-11-05 | CP5 | targeted e2e on d3eb52b (after the cause-label fix) | evidence-cp5, axe sweep, production journey, scenario I, procure-to-pay (fresh build) | 210 passed, 0 failed, 534 skipped, 11.8 min | scratchpad `s4-e2e6.log` |
| 2026-11-05 | CP5 | evidence screenshots | `e2e/evidence-cp5.spec.ts` in the run above | 52 PNGs, 13 screens × 1440/390 × light/dark | `docs/evidence/checkpoint-5/` |
| 2026-11-05 | CP5 | migrations | `lk db migrate --revision 0021` → `migrate`; `lk db heads`; `alembic check` on `lk_wt8` | chain 0021 → 0022 → 0023 → 0024 → 0025, heads 1; `alembic check` reports only `uq_vision_capture_conversation_sha` (ADR-061) | console |
| 2026-11-06 | CP6 | full API on `210684a` (backend unchanged through `1a81e99`) | `npm run test:api` | 1772 passed, 7 live-only skips, 2 known warnings, 0 failed; 84 min 28 s | `D:\lk-wt\s5-merge-testapi.log` |
| 2026-11-06 | CP6 | fresh check on `1a81e99` | `npm run check -- --keep-going` | 7/7 PASS; 743 unit/contract; one head; API matches; lint; typecheck; 68 Vitest files / 708 tests | `D:\lk-wt\s5-merge-check-final.log` |
| 2026-11-06 | CP6 | final full browser gate on `1a81e99` | `LK_E2E_EVIDENCE=cp6`, build CPUs 2, Node heap 2048 MB; `npm run test:e2e -- --workers=1` | 314 passed, 754 project-scoped/opt-in skips, 0 failed; 14.5 min | `D:\lk-wt\s5-merge-e2e-final.log`; failed initial run and targets in `docs/lanes/merge-s5.md` |
| 2026-11-06 | CP6 | evidence and local restore | 16 screens × 1440/390 × light/dark; actual Docker backup/rehearsal during e2e setup | 64 PNGs with index; all nine restore checks pass; temporary DB dropped | `docs/evidence/checkpoint-6/README.md`; final e2e log |

## 8. Next executable step

After the Checkpoint-6 fast-forward, complete Task 2 in `CODEX_HANDOFF.md`: merge the handover/audit branch,
verify the Pillow 13 trial with check and full API gates, and refresh SMTP/voice configuration docs. Then execute
the Slice-6 acceptance brief (Task 3). Keep integrations Demo; owner decisions and credentials remain in §§5–6.
The AP vendor-bill consumer and other carried gaps are not silently treated as delivered.

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
- Resolved: the Next.js 16.4.4 upgrade is on the merged tree; both CP6 production builds passed without a security-nudge retry.
- `queryKeys.sales.quotes()` has no `party_id` slot; the customer record uses an inline key under the same prefix.
  Add the parameter to the factory. [web]
- `UiPreferencePatch` in `lib/session/preferences.ts` names only theme/sidebar/rail; the profile page passes the
  wider patch (motion, density, shortcuts) through a typed cast in `features/settings/api.ts`. Widen the type. [web]
- Procedural fixture swatches stand in for product media (`public/swatches/README.md`); replace through
  `features/material-viewer/swatches.ts` when catalogue media land. [catalogue, web]
- The sign-in headline uses Fraunces (OFL, `@fontsource-variable/fraunces`, loaded on `/login` only); the owner's
  design system may replace it through `--font-display` in `globals.css`. [design]

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

---

## 11. Checkpoint 3 — Slice 2 (legacy parity) on `lane/s2-merge` (2026-11-04)

Merged in this order (lane reports under `docs/lanes/`): platform-2 (`platform-s2.md`), catalogue + imports
(`catalogue-s2.md`), commercial-2 (`commercial-s2.md`), cutting (`cutting-s2.md`), challans (`challans-s2.md`), the
commercial configurator follow-up; the merge, its conflict decisions and the defects it fixed are in
`docs/lanes/merge-s2.md`. Migration chain `0009` → `0010_platform_slice2` → `0011_catalogue_slice2` →
`0012_commercial_slice2` → `0013_cutting_slice2` → `0014_challans_slice2` → `0015_slice2_cross_lane_links`;
`alembic heads` = 1. `openapi.json` / `schema.d.ts` regenerated (243 paths). Decisions ADR-052…058.

### Implemented (verified) — new at this checkpoint
- **Platform:** TOTP MFA with recovery codes (privileged at sign-in, step-up on MFA-flagged actions), invitations and
  password resets (demo `.eml`), custom roles with inheritance and deny, overrides UI, role simulator, user admin
  (invite, deactivate, reactivate), delegation, leave, access requests, notes, attachments, activity, global search
  page and `/` dialog, S3 adapter (moto contract), image variants, isolation matrix.
- **Catalogue and imports:** product create/edit/archive with section editors, media (upload, primary, soft delete,
  restore), taxonomy management with rename aliases and delete-or-reassign, completeness rules, lookups, customer
  types table, party archive/restore, import workbench for all seven types (preview, validation, batched commit,
  quarantine and recheck, rollback, demo reset).
- **Commercial:** price-list edit/activate/retire/duplicate, item supersede and history, FX rates with second-person
  approval and policy, full quote state machine (revise, extend validity, archive, corrections), revision compare
  and restore, duplicate, currency change without relabelling, owner change, CSV exports, custom products with
  promotion, samples, quote settings, quote configurator.
- **Cutting:** MaxRects + guillotine packer with exact metrics, saved plans, sync and job calculation, exports (CSV,
  PDF, SVG), true-scale board canvas, grain locks, board verification.
- **Challans:** challans as documents (numbering, transitions, revisions, PDF, print view, CSV, returns, internal note),
  returnables sweep.
- PARITY_MATRIX: 436 implemented, 18 in progress, 246 planned, 1 deferred.

### Simulated (Demo)
Email (invitations, resets) as `.eml` files in the demo outbox; S3 only through the moto contract (LocalFs in dev);
everything listed as Demo at Checkpoint 2 stays Demo.

### Backlog / not in Slice 2
Inventory movement for challans (Slice 4), cut-plan release and work-order links (Slice 4), `ops.cut_plans` and
`ops.returnables` task rules, SMTP delivery.

### Open items carried (owners in brackets)
- An expired quote review leaves the quote in `internal_review` with no open approval (no `on_expired` handler);
  the expiry sweep is off outside production (ADR-057). [sales, approvals]
- `challans.challan.issued` carries `sample_id = null`: a challan cannot yet reference the sample it ships. [challans, sales]
- Web party forms offer only the three built-in customer types; company-defined types (`/settings/customer-types`)
  are not offered or shown yet; `pricing_price_list.customer_type` is not yet a foreign key. [parties web, pricing]
- Imports write prices through `pricing.service` primitives, not `import_standard_price`; `imports/bridges.py` reads
  pricing tables instead of a pricing `active_price_exists`. [catalogue, commercial]
- Media thumbnails use originals (variants exist only for new uploads); configurator rows do not show
  `primary_image`; line `media_snapshot` has no file ids (FG-QLN-13). [catalogue, sales, web]
- `INTERIM(api-generate)` untyped adapters remain in settings, collab, search, catalogue, cutting, pricing. [web]
- MFA step-up is enforced in platform services and wherever `require_recent_auth` is used; the FX policy screen
  needs the step-up dialog for users without MFA. [commercial web]
- Price lists: `LK_E2E_ADMIN` gates the management half of `e2e/commercial/price-lists.spec.ts`. [e2e]
- Carried from Checkpoints 1–2 and still open: fixture times are absolute (seed with `--anchor-date 2026-10-12`);
  `tasks_issue` advisory-lock ordering; CSRF verifier in a threadpool; approvals `get` visibility; composer Enter;
  `queryKeys.sales.quotes()` has no `party_id` slot; `UiPreferencePatch` width.

## 12. Checkpoint 4a — Slice-3 stage 1 (agents runtime + WhatsApp) on `lane/s3-merge` (2026-11-04) — intermediate

**Intermediate state, not a slice exit.** Stage 1 of the two-stage Slice-3 integration merges the two wave-3a lanes
onto Checkpoint 3; Checkpoint 4 (scenarios B, J, K and C via text, voice and WhatsApp; graceful AI outage) is declared
in stage 2, after `lane/s3-voice-vision` and `lane/s3-briefings` merge. Merged in this order (reports under
`docs/lanes/`): agents runtime (`agents-s3.md`), WhatsApp (`whatsapp-s3.md`); the merge, its decisions and the defects
it fixed are in `docs/lanes/merge-s3a.md`. Migration chain `0015_slice2_cross_lane_links` → `0016_agents_slice3` →
`0017_channels_slice3` → `0018_slice3_cross_lane_links` (integrator: `agents_turn.input_mode`); `alembic heads` = 1.
`openapi.json` / `schema.d.ts` regenerated (264 paths). Decisions ADR-059 (the lane's SSE ADR-052, renumbered) and
ADR-060.

### Implemented (verified) — new at this intermediate checkpoint
- **Agents runtime:** Anthropic adapter (contract-tested over a fake transport; no live call), routing table and
  `ai_routing` setting, Haiku request classifier (live only), Opus escalation rules and caps, per-task budgets, quotas
  with deterministic degradation, phrasing service with validator, fact-hash cache and batches (consumed by the
  briefings lane), numeric-claim grounding, taint, redaction canary, circuit breaker, AI usage store and Settings → AI,
  redacted trace view, draft receipts with Undo, golden evals on Demo, run progress over **SSE proven in the browser**
  (ADR-059: scenario C on the production build streams `text/event-stream` with no polling on desktop and phone).
- **WhatsApp channel (Demo through the real signed webhook):** webhook with byte-exact signatures and secret rotation,
  inbox and worker, replay safety, enrolment with one-time codes (step-up fails closed outside demo), sessions,
  outbox with window/template/consent gates, reconciliation and escalation of unknown outcomes, consent and STOP,
  customers and the approved quote send, single-use review links (`/r/[token]`), Settings › WhatsApp with the
  simulator; live mode proven only against a fake Graph transport.
- **Cross-lane:** a WhatsApp turn carries its `input_mode` (`wa_text` / `wa_voice` / `card_action`) into the agents turn.
- PARITY_MATRIX: SCN-K1, SCN-K2, SCN-K3, SCN-C5 implemented; SCN-C4 and SCN-J2 in progress (see the matrix note).

### Simulated (Demo)
Claude (Demo orchestrator and phraser; `LK_AI_MODE=demo`), WhatsApp (Demo provider, "Demo — not connected", simulated
statuses), demo STT for WhatsApp voice notes (fixture transcripts) until the voice lane registers a transcriber.

### Not in stage 1
Gemini vision, masked screenshot, push-to-talk and TTS (voice/vision lane); Listen to my day, delta view, LLM-phrased
briefings and the WhatsApp briefing push (briefings lane); `sales.quote_delivery_status`; vendor identities.

### Open items carried (owners in brackets)
- Settings › WhatsApp admin cards (Run checks, Sync templates) need the MFA step-up dialog: `channels.account.manage`
  is MFA + RA and platform-2 enforces it (ADR-060). [channels web]
- `channels.identity.manage` is granted to no role template; own-number linking uses `agents.assistant.use` + RA
  (WhatsApp lane decision). Owner to confirm. [owner, permissions]
- `channels_message` rows are not in the agents trace timeline yet (WhatsApp request 3, optional). [agents, channels]
- `(company_id, correlation_id)` indexes on `domain_event` / `audit_log` if traces get slow. [platform]
- `sales.quote_delivery_status` (consumer of `channels.message.status_changed`); a `tasks.rules` family for delivery
  unknown instead of the direct `create_task`; `channels/crypto.py` → `app/platform`. [sales, tasks, platform]
- No live call to Anthropic or Meta was made: `POST /api/v1/admin/ai/verify`, `test_golden_live`,
  `POST /api/v1/channels/whatsapp/account/verify`, the Meta handshake and one signed event are the live checks once
  credentials and the DPDP / WhatsApp decisions (§5 #6, #7) exist. [owner]
- Settings → AI shows the provider as "Demo • Demo" (label and mode badge both). Cosmetic. [agents web]
- Carried from Checkpoint 3 unchanged (section 11).

## 13. Checkpoint 4 — Slice 3 (agents, WhatsApp, vision, voice, briefings) on `lane/s3-merge` (2026-11-04)

Stage 2 of the Slice-3 integration merges the two wave-3b lanes onto Checkpoint 4a (section 12): voice/vision
(`docs/lanes/voice-vision-s3.md`) and briefings (`docs/lanes/briefings-s3.md`); the merge, its decisions and the defects
it fixed are in `docs/lanes/merge-s3.md`. Migration chain `0018_slice3_cross_lane_links` → `0019_voice_vision_slice3`
(lane placeholder 0030) → `0020_slice3_stage2_cross_lane_links` (integrator: `agents_turn.corrects_turn_id`,
`transcript_meta`, `vision_request_id`) → `0021_briefings_slice3` (lane placeholder 0035); `alembic heads` = 1.
`openapi.json` / `schema.d.ts` regenerated (282 paths). Decision ADR-061.

Slice-3 exit (PLAN.md): scenarios B, J and K; C via text, voice and WhatsApp Demo; graceful AI outage — see the
verification table (section 7) and the PARITY moves below.

### Implemented (verified) — new at this checkpoint
- **Vision (Demo; Gemini adapter contract-tested over a fake transport):** masked screenshot of the app's own DOM
  (restricted regions blacked out, never `getDisplayMedia`), stored restricted and purged after 24 h; instant screen
  answers from the re-read screen context with hand-off; photo/document extraction into a confirmation card (uncertain
  values are empty fields); the router sends `screen_question` to vision when a screenshot is attached; a confirmed
  extraction reaches a run only as untrusted data and taints it; live capture needs `screen_capture.enabled` **and**
  the recorded DPDP approval; vision model and quota from the routing table; `POST /admin/ai/verify` also verifies
  `ai.gemini`.
- **Voice (Demo STT/TTS):** push-to-talk with an editable final transcript, one turn per utterance id (resends
  replay), corrections as new turns (`corrects_turn_id` on the turn), voice turns `input_mode="voice"` with transcript
  facts, spoken replies interrupted by push-to-talk/typing/Stop, deterministic read-back, offline "Queued draft — not
  sent", mic denial keeping the text path; a voice approval (`approvals.decide(channel="voice")`) needs a fresh
  read-back; the voice module transcribes WhatsApp voice notes.
- **Briefings:** Listen to my day (pinned order, pause/resume/stop on the pin, completion acknowledges the heard
  version) speaking through the voice module (Demo voice by default) with a read-back of the paused item; LLM phrasing
  as a background job with the validator and template fallback ("Standard wording"); delta, all-items and item pages;
  the WhatsApp daily summary through the channels outbox with cross-channel "Got it".
- PARITY_MATRIX: SCN-B3, SCN-B4, SCN-B6, SCN-C4, SCN-J1 implemented; SCN-J3 in progress (`3→4`); SCN-J2 stays in
  progress.

### Simulated (Demo)
Claude (Demo orchestrator and phraser), Gemini (Demo vision from a fixture table; unknown images give empty
confirmation fields), STT (fixture transcripts; unknown recordings get the scripted phrase labelled "Demo transcript —
not from your recording"), TTS (silent clip labelled "Demo voice"), WhatsApp (Demo provider through the real signed
webhook). Hindi and Hinglish are labelled **Untested**.

### Open items carried (owners in brackets)
- No live Anthropic, Gemini, STT/TTS or Meta call was made: the live checks are `POST /api/v1/admin/ai/verify` (now
  both providers), one extraction of the demo delivery note, `test_golden_live`, the WhatsApp verify/handshake — once
  credentials and the decisions in §5 (#5 STT/TTS vendor, #6 DPDP, #7 WhatsApp) exist. [owner]
- No Gemini price row in the routing price table: vision usage shows unpriced in Settings → AI. [owner]
- No spoken "approve" exists in the assistant; the voice approval guard is a server seam (`DecideIn.channel`); a
  ReadbackCard kind is not built. [agents web]
- Template quick replies (`button` messages) are not handled by channels inbound, so a template daily summary carries
  no working "Got it" outside the 24-hour window. [channels]
- The lane's expression index `uq_vision_capture_conversation_sha` lives in the migration only; `alembic check`
  reports it (harmless). [vision]
- `checks.ai` could move onto `register_readiness_check`; the phrasing cache could key by provider mode. [agents]
- The DOM screenshot does not render cross-origin images or web fonts; compressed recordings' durations are the
  recorder's. [vision, voice]
- Quiet hours and personal summary times are not modelled (the summary goes at shift start). [briefings]
- On a phone the docked composer with the voice row takes about a third of the viewport (evidence
  `composer-voice-390-*`). [web voice, design]
- The axe sweep skips `/today/items/[itemId]` (issue ids are computed, not fixture records); the page is in the
  evidence screenshots only. [web]
- Carried from Checkpoint 4a (section 12) and Checkpoint 3 (section 11) unchanged.

## 14. Checkpoint 5 — Slice 4 (orders, inventory, production, procurement, quality, logistics) on `lane/s4-merge` (2026-11-05)

The Slice-4 integrator merges the three wave-4a lanes onto Checkpoint 4 (`main` 1ed0027) in dependency order:
orders/inventory (`docs/lanes/orders-inventory-s4.md`), production (`production-s4.md`) and procurement/quality/
logistics (`procurement-logistics-s4.md`); the merge, its decisions and the defects it fixed are in
`docs/lanes/merge-s4.md`. Migration chain `0021_briefings_slice3` → `0022_orders_inventory_slice4` (lane placeholder
0040) → `0023_production_slice4` (0070) → `0024_procurement_quality_logistics_slice4` (0060) →
`0025_slice4_cross_lane_links` (integrator: `quality_inspection.work_order_id` FK); `alembic heads` = 1.
`openapi.json` / `schema.d.ts` regenerated (399 paths). Decisions ADR-062 to ADR-065. The e2e world is seeded at
`--slice 4` (ADR-065).

Slice-4 exit (PLAN.md): scenario I incl. the no-oversell barrier test, a single posting per challan, replay safety and
ledger property tests — see the verification table (section 7) and the PARITY moves below.

### Implemented (verified) — new at this checkpoint
- **Sales orders:** one order per won quote (idempotent under concurrency and retry), confirm / hold / release /
  cancel, line cancellation, reserve and release, challan from the order, deliveries and returns recorded from the
  challan issue; feasibility per open line ("Can we deliver this?").
- **Inventory:** warehouses, bins, lots (measured dimensions), the append-only ledger with one posting per source
  event, projections that cannot go negative or oversell (database CHECKs), reservations under the same row lock as
  posting, persisted shortages with causes (order lines, work-order materials, late PO lines), reversal postings, pick
  lists, stock counts, adjustments and opening batches with separation of duties, transfers through in-transit, the
  nightly projection check; the challan movement policy behind the go-live switch.
- **Production:** versioned BOMs and routings approved by a second person, work orders (release reserves materials,
  blocked by a shortage and unblocked by the worker when stock arrives), issue / consume / return / output through WIP,
  QC inspection requested for QC-required output, cut-plan links that release the plan, measured offcut lots, capacity
  per work centre and day with overload state, deterministic cost rollups with missing inputs listed, read-only
  feasibility and what-if with procurement's open PO lines as supply.
- **Procurement, quality, logistics:** requisitions and purchase orders with separation of duties, partial goods
  receipts into QC hold, inspections (accepted + rejected add up; one posting per decision), three-way vendor bill
  match and the finance hand-off event, the overdue sweep; packing lists (Decimal CBM and weights, stale on packaging or
  order changes), shipments with cutoffs and dispatch through the challan, tracking, load suggestions.
- **Briefing families:** `ops.shortages`, `ops.picking`, `admin.stock_integrity`, `ops.production_dependencies`,
  `ops.receipts`, `ops.qc`, `ops.dispatch_cutoffs`.
- PARITY_MATRIX: SCN-I1…I4, LP-10.5, LP-10.6, REUSE-06, GAP-10, GAP-11, GAP-14, LM-78, LM-94, FG-REL-04, REUSE-05
  implemented; GAP-12 in progress (job work through challans not built).

### Simulated (Demo)
Unchanged from Checkpoint 4 (Claude, Gemini, STT/TTS, WhatsApp). Slice 4 adds no external provider: carrier APIs,
e-way bills and valuation stay backlog.

### Open items carried (owners in brackets)
- Approvals of adjustments, counts and opening batches are direct document actions, not proposals (ADR-014
  ApprovalTargets); the `mgmt.decisions` reservation-conflict item (fixtures §10) is not built. [inventory, briefings]
- Sales: a won → sent correction while an active order exists is not blocked yet (`orders.service.order_for_quote`). [sales]
- The ledger browser has no link for `work_order` sources (a transaction id). [inventory, production]
- Job-work operations through challans, QC rejects into rework work orders, a production subject handler for
  inspections, and authoring forms for BOM lines, routing operations and work centres are not built. [production, quality]
- Web: no create forms for adjustments, opening batches and transfers; count lines cannot be added from the UI;
  delivery evidence upload, container-profile management and requisition pagination are missing. [inventory web,
  logistics web, procurement web]
- Agent tools for stock, reservations, feasibility, what-if, purchasing and dispatch are not built. [agents + lanes]
- Valuation and costs on movements; vendor bills as AP documents (Slice 5 finance). [finance]
- `.gitignore` `backups/` also matches `apps/web/src/app/(app)/settings/backups/` (the migration lane's page is
  tracked, so it is safe, but new files there would be ignored); anchor the pattern at the Slice-5 merge. [migration]
- Some Slice-4 read models print quantities at the column scale ("short by 8.000000 sheets" on the shortages panel,
  "174.0000" planned minutes); trim them in the views. [inventory web, production web]
- The axe sweep skips Slice-4 records that are not fixtures (orders, requisitions, receipts, inspections, shipments,
  packing lists, pick lists, counts, adjustments, transfers) and `/today/items/[itemId]`; the scenario specs cover
  those screens. [web]
- Carried from Checkpoint 4 (section 13), 4a (section 12) and 3 (section 11) unchanged.

## 15. Checkpoint 6 — Slice 5 on `lane/s5-merge` (2026-11-06)

The merged runtime source is verified on `lane/s5-merge` through test-fix tip `1a81e99`; its backend is unchanged
from the full API gate at `210684a`. API: **1772 passed, 7 skipped, 0 failed**, 2 known warnings (84 min 28 s).
Fresh check: **7/7 PASS**, 743 unit/contract tests, one Alembic head, generated schema matches, 68 Vitest files /
708 tests. Full e2e: **314 passed, 754 project-scoped/opt-in skips, 0 failed** (14.5 min), fresh production build
with the required memory limits and one worker. Evidence: **64 PNGs** and index. Verification logs are in §7;
steps, every failed run and separate verified fixes are in `docs/lanes/merge-s5.md`.

### Implemented (verified) — new at this checkpoint

- Finance invoices/credit notes with draft labels, live issue blockers, second-person approval, numbering only at issue, delivered/creditable bounds and immutable issued documents. Receipts, bounded/reversible allocations, currency-separated ageing, balanced/inert CSV accounting handoff, Demo reconciliation and restricted margin exceptions.
- Migration source readers, alias reconciliation and quarantine; repeatable dry run with counts and historical totals by currency; catalogue apply through the workbench behind a rehearsed-backup gate; exact immutable legacy archives and reviewed party-link candidates. No stock movement is created from legacy challans.
- Snapshot-consistent database/storage backup, checksums and local restore rehearsal into a disposable database, including tenant isolation and cleanup checks. Settings reports require real MFA step-up.
- Measured offcut selection and packing, transactional work-order claim at release with double-claim refusal, and sample lineage through linked issued challans. Read-only what-if compares verified feasibility without persisting simulated results.
- Integration migrations form one chain: `0025` → `0026_finance_slice5` → `0027_migration_slice5` → `0028_capabilities_slice5`. ADR-066–069 describe the final integration decisions. The backups ignore pattern is anchored.

### Simulated (Demo)

AI, vision, STT/TTS and WhatsApp retain their labelled Demo adapters. Finance accounting acknowledgement/reconciliation is simulated; CSV generation is real. E-invoice verification has no live provider, so required issuance stays blocked. Email writes local `.eml` files. No owner credential or live business-policy choice has been invented.

### Open items carried (owners in brackets)

- Vendor bills as AP documents; manual invoice lines and CSV reconciliation input in the web; dedicated finance configuration screen; cross-currency allocations; `draft_invoice` / ageing agent tools; live accounting/e-invoice/GST rules. [finance, web, agents, owner]
- Migration opening-balance posting remains an unregistered seam; live legacy quote/challan/custom-product import, invitations from candidates, grain-lock materialization, a non-suggested party picker and authorized remote-media proof remain open. Only the synthetic export is proven. [migration, inventory, sales, web, owner]
- Saved what-if scenarios, offcuts in the stateless legacy calculator, a dedicated offcut-reuse label and capability agent tools remain open. [production, cutting, agents]
- The sample/challan lineage gap from Checkpoints 3–4 is resolved from the sales consumer; the event's `sample_id=null` no longer prevents dispatch of linked samples. Other carried items in §§11–14 remain open unless explicitly closed here.
- A static reference audit found 18 legacy browser case references absent from their current spec files; those rows are now in progress pending mapping. This is traceability debt, not proof that the behavior is absent. Slice 6 must map actual passing coverage or add checks; checked Python function references resolve. [acceptance]
- Final A–N coverage at all three widths, authenticated route sweeps, dead controls, motion/performance evidence, final audits, handover merge and Pillow 13 decision remain for Slice 6. [acceptance, integrator]

- The seed is anchored at D0, but the current e2e API/worker use system time after the seed process exits. Slice 6 must verify the canonical morning/date fixture and coordinate its MFA clock. [acceptance]
- Visual review: the what-if Needed by field wraps in the narrow desktop grid; phone captures of long forms show the top viewport. Review responsive field sizing and capture relevant workflow sections in final evidence. [web, acceptance]

## 16. Checkpoint 7a — CRM programme modules 1–3 on `lane/crm-leads` (2026-11-25)

Owner request of 2026-11-25: complete the Sales CRM module by module with the old data, host last (specs under
`docs/superpowers/specs/2026-11-25-*`, meetings under `docs/meetings/`). The rebuilt web app (`lane/web-rebuild`,
`apps/one`) is merged in. Gates: full API after modules 1–2 **1807 passed, 7 skipped, 0 failed** (61 min 37 s,
`D:\lk-wt\crm-m12-testapi.log`); after module 3 the sales, parties, orders, contract and unit suites **887 passed,
0 failed** (`D:\lk-wt\crm-m3-subset.log`). `npm run check` **10/10 PASS** (now includes `apps/one` lint, typecheck and
vitest; `D:\lk-wt\crm-leads-check.log`, ruff re-run clean after the PI commit). Browser checks against the slot-0 API
in the Claude preview: lead log/stage/lost flow with the follow-up task opened and cancelled in the database; past
sample promoting a lead; PI create → issue → PDF.

### Implemented (verified) — new at this checkpoint

- **Leads (module 1).** Pipeline stage (new → contacted → qualified → negotiating → won / lost with a required reason,
  DB check), priority, temperature, managed lead sources, interests, website, requirement, first contact; append-only
  activity log; one owner follow-up task per lead (`sales.lead_follow_up`, closed by the next activity, won, lost or
  archive); lead summary; list filters. `lk import leads` (dry run by default, re-runnable, keeps app edits): the
  owner's sheet loads **703 of 705** rows (2 rejected for a blank country). Migration `0029_leads_crm`.
- **Customers and samples (module 2).** A lead becomes a customer when a sample is dispatched to it, a quotation is
  won or an order is confirmed (outbox subscriptions in sales and orders). Samples can be entered as already sent
  with their real date; later steps take their real date (never future, never before the previous step). Customer
  facts: customer since (from the real first sample or win), last contact, won value per currency.
- **Proforma invoices (module 3).** From a sent/revised/won quotation's issued revision; draft terms; issue as
  `PI-YYYY-NNNN` with a PDF (identity frozen at issue, bank block per viewer under the restricted-number rule); cancel
  with a reason (`sales.proforma.reverse`); PIs sent earlier entered with their original number and date
  (`sales.proforma.import`, management). Migration `0030_proforma_invoices`.
- `apps/one` screens for all of the above; `apps/one/src/lib/routes.ts` layers this app's own routes over the shared
  manifest, so new screens never touch `apps/web`.

### Simulated (Demo) / not configured

Company identity and bank details are not configured in the demo company; PDFs print the labelled placeholder.

### Open items carried

- Module 4 (products design × decor × size, custom products in the menu, stock categories sample / inventory /
  exhibition, NL/US warehouses, factory work in progress), module 5 (Amazon first, Demo until the developer profile
  is approved, then Flipkart and the website), module 6 (hosting on Vercel + Railway Singapore). [CRM programme]
- Real import needs the four lead owners' work emails (Priyanka Khanna, Akshay Khanna, Priyanka Chatterjee, Priyanka
  Roy Rudra) as invited members. [owner]
- The Sales sub-navigation highlights "Customers" on a lead's record (path match without the query). [web]
- Windows Smart App Control is on: tests run as `python -m pytest`; turning it off is the owner's decision. [owner]
- e2e scenarios for the new screens are not written yet; acceptance (Slice 6) items from §15 remain open. [acceptance]
