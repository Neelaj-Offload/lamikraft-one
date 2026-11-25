# Codex handoff — Lamikraft One (2026-11-06)

Continued by Codex after the Claude Code handoff. Read `AGENTS.md` first (rules and commands), then this file.
This file remains authoritative for the ordered continuation tasks; Checkpoint 6 is recorded in BUILD_STATE §15.

## CRM programme (2026-11-25, current work) — read this first

The owner asked to finish the Sales CRM module by module with the old data, then host. Order and specs:
`docs/superpowers/specs/2026-11-25-leads-module-design.md` (programme context), `...-customers-samples-design.md`,
`...-proforma-invoices-design.md`; meeting notes in `docs/meetings/`. Work happens on `lane/crm-leads` in the main
checkout and lands on `main` by fast-forward per checkpoint (BUILD_STATE §16).

| # | Module | State |
|---|---|---|
| 0 | `apps/one` rebuild merged | done |
| 1 | Leads (pipeline, activities, follow-ups, `lk import leads`) | done, verified |
| 2 | Customers + samples (auto-promotion, past samples, customer facts) | done, verified |
| 3 | Proforma invoices | done, verified |
| 4 | Products (design × decor × size) + stock categories (sample / inventory / exhibition), NL/US warehouses, WIP | done, verified (BUILD_STATE §17) |
| 5 | E-commerce stock sync: Amazon first (Demo until developer approval), then Flipkart, website | done, verified (BUILD_STATE §18) |
| 6 | Hosting: Vercel (web) + Railway Singapore (API, worker, Postgres), `*.vercel.app` first | prepared (`docs/runbooks/hosting.md`); waiting on the owner for GitHub push and Railway access |

New `apps/one` screens register their routes in `apps/one/src/lib/routes.ts`, never in `apps/web`. Run pytest as
`uv run --locked python -m pytest` (Smart App Control blocks the `pytest.exe` shim). Owner inputs still open: the
four lead owners' emails for the real import; company identity and bank details for documents.

## TL;DR — is the app finished?

**No. Checkpoint 6 is verified and merged on `main`; handover integration and Slice 6 acceptance remain, together with the explicit product gaps below. No completion percentage is asserted.**

| Slice | Content | Where it is | State |
|---|---|---|---|
| 0–4 | kernel, auth, briefings, quotes, full legacy parity, agents/voice/vision/WhatsApp (Demo), orders, inventory, production, procurement, QC, logistics | `main` @ Checkpoint 6 | **Done, verified** (BUILD_STATE §9–§14) |
| 5 | finance, migration dry-run/apply, backup + restore rehearsal, offcut reuse, sample lineage, what-if | `main` via `lane/s5-merge` @ `7368da7` | **Implemented (verified)** within BUILD_STATE §15 scope; open gaps carried |
| 6 (part) | dependency audits + handover docs (`docs/handover/*`, root `README.md`) | `lane/s6-handover` (worktree `D:\lk-wt\work`, slot 4) | Done on its branch; merge after CP6 |
| 6 (rest) | A–N acceptance matrix at 3 widths, isolation/red-team, axe on every route, dead-control crawl, final evidence, PARITY 100 %, final BUILD_STATE | not started (brief: `docs/superpowers/briefs/s6-acceptance.md`) | **To do** → **Checkpoint 7** |

## Branches and worktrees (all local, no remote)

| Branch | Worktree / slot | Tip | Notes |
|---|---|---|---|
| `main` | `D:\Lamikraft ERP` / 0 (web 3200, API 8200) | CP6 `7368da7` plus continuation docs | The plan says each checkpoint lands on `main` by fast-forward |
| `lane/s5-merge` | `D:\lk-wt\integ` / 8 (web 3080, API 8080) | CP6 `7368da7` plus continuation docs | 3 lanes merged: finance `0c11d77`, migration `00f83ae`, capabilities `7cda0a9`. Migrations renumbered `0026_finance_slice5` → `0027_migration_slice5` → `0028_capabilities_slice5`. `e9fdad3` = the integrator's uncommitted work, committed as WIP for safety: scenario-M migration/backup e2e (`m-migration.spec.ts`, `support/mfa.ts`), `o-offcut-lineage-what-if.spec.ts`, `evidence-cp6.spec.ts`, e2e seed at `--slice 5` + dry run + backup in `scripts/dev.mjs`, ADR-066…069 in `DECISIONS.md` |
| `lane/s6-handover` | `D:\lk-wt\work` / 4 | `364b5d5` | `docs/handover/{index,setup,providers,remaining-work,security-audit}.md`, `README.md`, `uv.lock` patches (certifi, pyasn1, pypdf). Report: `docs/lanes/handover-s6.md` |
| `lane/s6-handover-pillow13` | — | `ad73c7a` | Pillow 12.3 → 13.0 trial (fixes 39 advisories); partial tests passed, full gates not run |
| `lane/s5-finance`, `-migration`, `-capabilities` | `identity`/1, —, `sales`/6 | merged | Lane reports in `docs/lanes/*-s5.md` (on `lane/s5-merge`) |
| older `lane/s1*`…`s4*`, `chore/next-security-upgrade` | various | merged | Leave alone; clean-up is optional (`git worktree remove` only when clean and merged) |

**Gate evidence so far for Slice 5:** `test:api` after merge step 1 (finance) = 1734 passed (`D:\lk-wt\s5-fin-testapi.log`);
after step 2 (migration) = 1757 passed (`s5-mig-testapi.log`); after step 3 (capabilities) the run was **interrupted
at ~60 %** (`s5-cap-testapi.log`). e2e tsc/eslint on the new specs ran clean.

**Progress after the handoff (Claude Code, 2026-11-06), on `lane/s5-merge`:**
- `93cffdd` merged `main` (handoff docs) in. Task 1 step 1 ✔
- `.gitignore` `/backups/` was already anchored by `bf8279e` (migration lane); backups go to `backend/var/backups`
  (covered by `var/`). Task 1 step 2 ✔ — no change needed.
- `5574038` fixed the flaky rollup test (`.order_by(DomainEvent.seq)`); the file passes 7/7. Task 1 step 3 ✔
- `npm run api:generate` → no diff. Task 1 step 4 ✔
- `npm run check -- --keep-going` on `5574038` → **7/7 PASS** (ruff; pytest unit+contract 743 passed; alembic heads 1;
  api:check; eslint; tsc; vitest 68 files / 708 tests). Log `D:\lk-wt\s5-merge-check.log`. Task 1 step 5 ✔
- Task 1 steps 6–11 completed by Codex: full API **1772 passed / 7 skipped**, fresh check **7/7**, final e2e **314 passed / 754 skipped / 0 failed**. Logs: `s5-merge-testapi.log`, `s5-merge-check-final.log`, `s5-merge-e2e-final.log` under `D:\lk-wt`.
- Four separate scenario fixes: `698a38c` (M real MFA step-up), `27c8782` (O offcut keyboard toggle), `0d28798` (O actual sample challan), `1a81e99` (O product picker). Initial failed runs and their causes are retained in `docs/lanes/merge-s5.md`.
- CP6 evidence/docs committed as `7368da7` and fast-forwarded to `main`: 64 screenshots, BUILD_STATE §15, parity counts **453 implemented / 38 in progress / 212 planned (including 3 owner-input) / 1 deferred**, total 704. Eighteen stale browser case references remain acceptance evidence debt; broader product gaps remain explicit.
- **Resume at Task 2**, then Task 3. No test or dev servers left running at Task 1 completion.

## What to do next, in order

### Task 1 — Finish Checkpoint 6 (Slice 5) on `lane/s5-merge` — COMPLETE
Work in `D:\lk-wt\integ` (slot 8). Follow `docs/superpowers/briefs/integrator.md` steps 4–6; house style is
`docs/lanes/merge-s4.md`.

1. `git merge main` into `lane/s5-merge` (brings `AGENTS.md`/`CODEX_HANDOFF.md`; docs-only, as was done in `a823ea2`).
2. Anchor the ignore rule: in `.gitignore` change `backups/` to `/backups/`; confirm
   `git check-ignore -v "apps/web/src/app/(app)/settings/backups/page.tsx"` prints nothing.
3. Fix the known flaky test: `backend/tests/integration/production/test_costing_feasibility.py::test_rollup_is_deterministic_and_lists_missing_inputs`
   reads `production.cost_rollup.computed` events without `ORDER BY` — order the query (e.g. by outbox id / created_at).
4. `npm run api:generate` → commit if `backend/openapi.json` or `schema.d.ts` changed.
5. `npm run check -- --keep-going` → must be 7/7. If the slot-8 test DB is on a stale revision, drop/recreate it (see AGENTS.md pitfalls).
6. `npm run test:api > D:\lk-wt\s5-merge-testapi.log 2>&1` (background, ~75 min). Expect ≈1,800 passed, 7 skipped (live-only).
7. `LK_NEXT_BUILD_CPUS=2 NODE_OPTIONS=--max-old-space-size=2048 npm run test:e2e -- --workers=1`. The seed now runs at
   `--slice 5`, then `lk migration dry-run`, `lk backup create`, `lk backup restore-rehearsal` (needs `lk-postgres` up).
   Fix what fails; product fixes go in their own commits naming the scenario.
8. Evidence: `LK_E2E_EVIDENCE=cp6` with `evidence-cp6.spec.ts` → `docs/evidence/checkpoint-6/` + a `README.md` index
   (1440 and 390 px, light and dark), as in `docs/evidence/checkpoint-5/`.
9. Docs: write `docs/lanes/merge-s5.md`; add `docs/BUILD_STATE.md` **§15 Checkpoint 6** (implemented/simulated/open
   items, verification table rows) and update the header and §2 "In progress"; move `docs/PARITY_MATRIX.md` rows whose
   tests now pass on the merged branch (finance, migration, backup, offcut reuse, sample lineage, what-if; see each
   lane report's "parity" section); ADR-066…069 are already written (check they still match after fixes).
10. Commit, then fast-forward `main`: `git -C "D:\Lamikraft ERP" merge --ff-only lane/s5-merge`.
11. Append a dated line to `docs/superpowers/specs/2026-11-03-completion-program.md` and update this file's TL;DR.

### Task 2 — Merge the handover/audit branch onto CP6 ← start here
1. On `main` (or a short `lane/s6-acceptance` branch, see Task 3): `git merge lane/s6-handover`. Only `uv.lock`,
   `README.md`, `docs/handover/*`, `docs/lanes/handover-s6.md` change; no Slice-5 branch touches lockfiles, so no conflict is expected.
2. Decide Pillow 13 (recommended — 39 runtime advisories, reachable through image uploads): `git cherry-pick ad73c7a`,
   then `npm run check` + full `test:api`. If anything image-related breaks and cannot be fixed, revert and record it in
   `docs/handover/security-audit.md`.
3. Refresh `docs/handover/remaining-work.md` §6 ("Slice 5, to be confirmed at Checkpoint 6") and `docs/handover/index.md`
   (the runbooks `docs/runbooks/migration.md` and `backup-restore.md` are now on `main`).
4. Fix the doc findings from `docs/lanes/handover-s6.md`: SMTP is not built (`LK_EMAIL_MODE=smtp` answers 409) — correct
   `docs/runbooks/local-dev.md` and the `.env.example` comment; add the voice variables (`LK_VOICE_*`) to `.env.example`.

### Task 3 — Slice 6 acceptance → Checkpoint 7 (the big one)
Brief: `docs/superpowers/briefs/s6-acceptance.md` (read it fully). Branch `lane/s6-acceptance` from `main` after CP6.
Scenario definitions A–N are in `OPUS_5_5_BUILD_PROMPT.md`.

- Existing scenario specs (`apps/web/e2e/scenarios/`): b, c (screen capture), h, i, j, k, m (finance + migration), o, p;
  plus `scenario-c.spec.ts`, `catalogue/`, `commercial/`, `imports/`, `sales/`, `production/`, `challans.spec.ts`,
  `keyboard.spec.ts`, `axe-sweep.spec.ts`. **Missing as named scenario specs: A, D, E, F, G, L, N** — some are partly
  covered by the area folders; map them first, then fill gaps. Each must run in all three Playwright projects
  (1440 / 834 / 390 px).
- Isolation and prompt-injection red-team suites (brief deliverable 2); backend counterparts under `backend/tests/acceptance/`.
- axe on every manifest route in both themes (extend candidates in `axe-sweep.spec.ts`, incl. the Slice-4/5 records it
  still skips); dead-control crawl; reduced-motion spec (`docs/architecture/motion-system.md` §8).
- Re-run `pip-audit` and `npm audit` on the final tree (method in `docs/handover/security-audit.md`).
- Final evidence under `docs/evidence/final/` with an index; `PARITY_MATRIX.md` 100 % rows with status + evidence (or an
  honest `deferred` with reason); `BUILD_STATE.md` final checkpoint; `docs/lanes/acceptance-s6.md`.
- Gates green: `npm run check`, `npm run test:api`, `npm run test:e2e` (all projects). Fast-forward `main`.

### Task 4 — Known product gaps (not built; do after CP7 or as the owner prioritises)
Full list with owners: `docs/BUILD_STATE.md` §11–§14 "Open items carried" and `docs/handover/remaining-work.md` §4 and §7.
The most visible ones:
- Web forms missing: inventory adjustments, opening batches, transfers, adding count lines; BOM lines, routing
  operations, work centres; delivery-evidence upload; container profiles; requisition pagination.
- Job-work through challans; QC rejects → rework work orders; production subject handler for inspections.
- Agent tools for stock, reservations, feasibility, what-if, purchasing, dispatch, `draft_invoice`, `get_receivable_ageing`.
- Finance: vendor bills as AP documents (consumer of `procurement.vendor_bill.handed_off`), manual invoice lines in the
  UI, CSV reconciliation entry, cross-currency allocation, live accounting / e-invoice adapters.
- Migration: opening-balance poster not registered (needs one owner with inventory opening batches); legacy quotes/
  challans as live records; proven only on the synthetic export.
- Sales: block the won → sent correction while an active order exists (`orders.service.order_for_quote`).
- Quantities printed at column scale in some Slice-4 views ("8.000000 sheets", "174.0000 minutes").
- Approvals of adjustments/counts/opening batches are direct actions, not proposals (ADR-014).

### Needs the owner, not code (do not invent these)
`docs/BUILD_STATE.md` §5 (business decisions: numbering reset, approval thresholds, accounting system, e-invoice provider,
STT/TTS vendor, DPDP approval for sending data to Anthropic/Google, legal entity, company identity) and §6 (live
credentials: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, WhatsApp WABA/phone/token/app secret/verify token, STT/TTS key, S3,
SMTP). Until then every integration stays Demo and labelled.

## Frontend rebuild — `apps/one` on `lane/web-rebuild` (state on 2026-11-24)

The rebuilt web app (same URLs and API as `apps/web`, new flow, copy and look) lives in `apps/one`; the contract for
anyone changing a screen is `apps/one/BUILDING.md`. It is **not merged to `main`** and `apps/web` is untouched.

- **Screens:** all 132 routes are real screens; `node scripts/stubs.mjs --check` reports no stubs.
- **Static gates:** `node scripts/check.mjs --all` → TypeScript 0 errors, ESLint clean.
- **Sweep:** `node scripts/shots.mjs --all --user SAHIL` → 194 screenshots (1440 and 390 px, light), every page 200,
  no horizontal overflow, no console errors or failed API calls. Each area was also shot by its builder as the right
  demo person; most areas had one dark pass.
- **Not verified (be honest about these):**
  - Record screens the demo world has no data for: invoice, credit note, requisition, goods receipt, inspection,
    shipment, packing list, stock take, pick list, adjustment, transfer, import job, migration run, AI trace.
  - No mutation was exercised in the browser (issue, approve, receive, post, allocate, invite, step-up and so on).
    They reuse the old command hooks and endpoints, but that is by reading, not by running.
  - Content behind MFA step-up (migration, backups, audit) and anything that needs a custom role.
  - No `next build`, no Playwright suite and no axe run exist for `apps/one` yet; `apps/web/e2e` still targets the old UI.
- **Deliberate differences from the old app:** Profile no longer saves density / context-panel preferences (the new
  shell does not read them); password change lives under Security; the audit log offers MFA step-up when the server
  asks for it; actions the server disallows are hidden instead of shown disabled; lists that had no paging use the
  endpoints' existing `offset`.
- **Run it:** Docker up, then API + worker from `D:\Lamikraft ERP` (`node scripts/dev.mjs dev --no-web`, 8200) and
  `next dev` for `apps/one` on 3200 with `LK_API_INTERNAL_URL=http://127.0.0.1:8200` and
  `LK_PUBLIC_ORIGIN=http://127.0.0.1:3200`. The old web app cannot run at the same time (same port and origin).
- **Next:** exercise the mutations and the data-less record screens; give `apps/one` its own e2e, axe and build gates;
  then decide the cut-over from `apps/web`.

## Machine facts that will bite you
- Windows 11, 12 CPUs, **15.7 GB RAM** → never more than one heavy job (test suite, e2e, `next build`) at a time.
- `test:api` takes 70–80 min. Run it in the background with output to a log under `D:\lk-wt\`, and read the tail.
- Docker containers: `lk-postgres` (this project) and `crown-hr-pg` (another project — leave it alone).
- Port 8000 is another project's uvicorn; slot 0 therefore uses 3200/8200.
- Demo sign-in: `cd backend && uv run --locked python -m app.cli demo sign-in-link MEERA` (sales) or `SAHIL`
  (management), `ANANYA` (finance), `PRIYA` (admin) → open the printed link on `127.0.0.1:<web port>`.
