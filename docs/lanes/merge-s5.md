# Lane report: Slice-5 merge (integrator)

Branch `lane/s5-merge`, worktree `D:\lk-wt\integ`, env slot 8, continuing the Claude handoff at Task 1 step 6. All changes stay local. The runtime source at `1a81e99` is the same as `210684a` / `5574038`; this continuation changed only browser test setup/locators before the checkpoint docs.

**Status: DONE_WITH_CONCERNS** — Checkpoint 6. Every gate is green for this checkpoint; carried scope and evidence-mapping concerns remain below.

## Steps

| # | Step | Commit | Result |
|---|---|---|---|
| 1 | Finance merge | `0c11d77` | 1734 API tests passed (handoff evidence, `D:\lk-wt\s5-fin-testapi.log`) |
| 2 | Migration merge | `00f83ae` | 1757 API tests passed (handoff evidence, `D:\lk-wt\s5-mig-testapi.log`) |
| 3 | Capabilities merge | `7cda0a9` | Prior API run interrupted; not accepted as a complete gate |
| 4 | Integration e2e, evidence, seed and ADR work preserved | `e9fdad3` | WIP from the handoff, verified by the gates below |
| 5 | Handoff merges; cost-rollup determinism | `93cffdd`, `210684a`, `5574038` | Query explicitly orders `DomainEvent.seq`; initial check 7/7 on `5574038` |
| 6 | Full merged API | `210684a` | **1772 passed, 7 skipped, 0 failed**, 2 known warnings, 84 min 28 s |
| 7 | First full e2e | `210684a` | 309 passed, 2 failed, 754 skipped, 3 serial cases not run, 17.7 min (defects 1–2 below) |
| 8 | Scenario M MFA setup | `698a38c` | Targeted migration/backup: **2 passed**, real MFA refusal + TOTP confirmation, 39.2 s |
| 9 | Scenario O checkbox interaction | `27c8782` | Offcut case + four production prerequisites passed; newly reached sample assertion failed (5/1, 1 not run) |
| 10 | Scenario O sample lineage | `0d28798` | Sample case passed; target 6/1 exposed the previously blocked what-if locator |
| 11 | Scenario O what-if picker | `1a81e99` | Targeted what-if: **1 passed**, 4.0 s |
| 12 | Final check | `1a81e99` | **7/7 PASS**, 743 unit/contract tests; one head; API matches; lint; typecheck; 68 Vitest files / 708 tests |
| 13 | Final full e2e + CP6 evidence | `1a81e99` | **314 passed, 0 failed, 754 skipped**, 14.5 min |
| 14 | Checkpoint docs and fast-forward | see git log | BUILD_STATE §15, PARITY, evidence index, this report, handoff and completion-program entry |

## Migration chain and merge decisions

`0025_slice4_cross_lane_links` → `0026_finance_slice5` → `0027_migration_slice5` → `0028_capabilities_slice5`. Earlier integration renumbered lane placeholders 0080, 0050 and 0090. No revision already on main was changed; one head was confirmed by both checks and the e2e migration reached 0028.

Shared registries, finance fixture keys, seed `--slice 5`, the migration dry run and backup/rehearsal setup were already integrated before this continuation. Generated API files were unchanged by `npm run api:generate` in the handoff; the fresh `api:check` matches the final app. ADR-066–069 remain accurate: issuance/approval/numbering gates, exact migration archives and backup prerequisites, offcut claim at work-order release, sample dispatch from the sales consumer, read-only what-if and the integrated e2e world.

## Browser defects found and fixed

1. **M — wrong authentication fixture.** Test-support sessions intentionally carry MFA strength (`identity.http._STRENGTH`). Signing in again with that helper did not produce the expected confirmation prompt. The case now opens a real Demo-link session before enrolling in another session, restores the original lower-strength cookies, proves `401 mfa_required`, confirms a real TOTP and reads the report. Backups reuse that genuinely verified session. The reconciliation assertion now targets the Source card on the run detail, where that fact is displayed. No production authentication policy changed.
2. **O — hidden checkbox pointer target.** React Aria's input is covered by its visible checkbox box. The case uses Space and asserts the checked state before saving; the real save and packing result remain asserted.
3. **O — overly broad lineage assertion.** A catalogue sample legitimately has no custom-product or quote link. The case selects its generated challan number and verifies that exact link/href and dispatch timeline, instead of forbidding every `Not linked yet` label.
4. **O — Select accessible name.** The product button's name includes the selected-value placeholder before its label. The anchored `^Product` locator never matched; the case now matches the Product label within the name.

Each distinct cause was corrected on its first fix attempt. Failed targets and newly reached serial cases are retained in the table/logs; no failure was hidden with a skip, force click or larger timeout.

## Gates and evidence

| Gate | Result | Log |
|---|---|---|
| `npm run test:api` | 1772 passed, 7 live-only skips, 2 known warnings, exit 0; backend source unchanged by subsequent test fixes | `D:\lk-wt\s5-merge-testapi.log` |
| `npm run check -- --keep-going` | 7/7 PASS, exit 0 on `1a81e99` | `D:\lk-wt\s5-merge-check-final.log` |
| `npm run test:e2e -- --workers=1` | 314 passed, 0 failed, 754 skipped, exit 0; fresh production build and `lk_wt8_e2e` | `D:\lk-wt\s5-merge-e2e-final.log` |
| Initial e2e and targets | 309/2; M 2/0; production + O 5/1 then 6/1; what-if 1/0 | `s5-merge-e2e.log`, `s5-fix-m-e2e.log`, `s5-fix-o-e2e.log`, `s5-fix-lineage-e2e.log`, `s5-fix-whatif-e2e.log` under `D:\lk-wt\` |
| Backup rehearsal | real Docker restore, all nine checks pass, temporary DB dropped on each e2e setup | final e2e log |
| Screenshots | 64 PNGs, 16 screens × 1440/390 × light/dark, with an index and representative visual review | `docs/evidence/checkpoint-6/` |

Build limits: `LK_NEXT_BUILD_CPUS=2`, `NODE_OPTIONS=--max-old-space-size=2048`. Evidence flag `LK_E2E_EVIDENCE=cp6`. The API warnings are google-genai's Python 3.17 deprecation and the expected decompression-bomb rejection warning. Browser skips are project-scoped/opt-in and dynamic routes without fixture records; this is not final all-route/all-width acceptance. The supervisor stopped its API, worker and web after each run.

## Integrator requests and open items

- Applied: migration renumbering, finance receipt keys, seed at Slice 5, migration/backup browser journey, capability browser checks, sample-linked challan consumer, ADRs and the anchored `/backups/` ignore rule (already fixed by `bf8279e`).
- Finance: AP vendor-bill consumer, manual invoice-line UI, CSV reconciliation input, dedicated finance configuration UI, cross-currency allocations, native statutory accounting and agent tools remain open. Demo acknowledgements are labelled; no live credentials were supplied.
- Migration: opening-balance poster unregistered; legacy documents as live sales records, candidate invitations, grain-lock materialization, non-suggested party picker and authorized remote-media proof remain open. Only the synthetic export is proven.
- Capabilities: stateless calculator offcuts, saved what-if scenarios, dedicated offcut-reuse label and agent tools remain open. Other carried Slice-3/4 gaps remain in BUILD_STATE §§11–15.
- PARITY advances only demonstrated Slice-5 scope. Broader finance/platform rows stay partial. Eighteen previously implemented browser-only rows are marked in progress because their named cases are absent from the current files (UI-13/32/52/54/55/57/58/59/61/62/63/66/68, REUSE-03/08, LP-06.6, LP-11.4, SCN-L1). This is an evidence-reference finding, not an observed product regression; Slice 6 must map real passing coverage or add checks.
- Final A–N at all three widths, authenticated route sweeps, dead controls, motion/performance evidence, audits, handover merge and Pillow 13 decision remain Tasks 2–3 in CODEX_HANDOFF.md.
