# Lane brief: Slice 6 — acceptance, isolation and handover

Branch `lane/s6-acceptance` from `main` (after the Slice-5 checkpoint). Owner: `apps/web/e2e/**`,
`backend/tests/acceptance/**`, `docs/evidence/final/**`, `docs/handover/**`, `docs/PARITY_MATRIX.md` statuses,
`docs/BUILD_STATE.md` final sections, `README.md`. Fixes to product code are allowed only for defects this lane
finds, each in its own commit naming the scenario. Never push; never two test suites at once.

## Contracts
`docs/PLAN.md` Slice 6 and the acceptance scenarios A–N in `OPUS_5_5_BUILD_PROMPT.md`; `docs/PARITY_MATRIX.md`
(every row must map to code and a passing named test, or carry an honest `deferred` with a reason);
`docs/architecture/motion-system.md` §7–§8 (budgets and the planned motion tests); `docs/design/source/
frontend_verification.md` (verification strategy, states catalogue, dead-control crawl); `docs/superpowers/specs/
2026-11-02-checkpoint-2-build-guide.md`.

## Deliverables
1. **A–N matrix**: one Playwright spec per scenario under `e2e/scenarios/` at 1440, 834 and 390 px (the three
   projects in `playwright.config.ts`), signed in as the fixture people the scenario names, asserting on server
   facts from `/_test/fixtures`; the backend acceptance counterparts under `backend/tests/acceptance/`.
2. **Isolation**: cross-channel isolation (A, E, F): restricted and peer users never see a planted sentinel
   through summaries, search, tools, exports, direct URLs, WhatsApp renders or agent payloads; the injection
   red-team suite (prompt injection through customer messages, attachments and extraction output never reaches a
   send or execute path).
3. **Sweeps**: axe on every manifest route in both themes (extend `e2e/axe-sweep.spec.ts` candidates for every
   dynamic segment); the dead-control crawl (every button and link in the manifest routes either acts, navigates or
   is absent — no dead controls); the reduced-motion spec from motion-system §8; `pip-audit` and `npm audit` with
   each finding resolved or recorded with a reason.
4. **Evidence**: screenshots of every major workflow at the three widths in light and dark under
   `docs/evidence/final/`, with an index; a Chrome performance trace of `/login` and `/today` against the budgets.
5. **Handover docs** under `docs/handover/`: setup, provider configuration guide (every integration, every env
   variable, Demo vs live), migration runbook, backup and restore runbook, the exact remaining-work list (what is
   Demo, what needs credentials, what needs a business decision from `BUILD_STATE` §5), and `README.md` at the root.
6. `docs/PARITY_MATRIX.md` 100 % rows with status and evidence; `docs/BUILD_STATE.md` final checkpoint with the
   verification table.

## Verification and report
Full `npm run check`, `npm run test:api`, `npm run test:e2e` (all projects) green; `docs/lanes/acceptance-s6.md`
with every scenario's result. Final message: counts per scenario, defects fixed, and the remaining-work list.
