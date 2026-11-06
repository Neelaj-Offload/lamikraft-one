# Completion program (Slices 2–6): waves, checkpoints and how to resume

Started 2026-11-03 on the owner's instruction "complete the entire app". The plan of record is `docs/PLAN.md`;
this file is the execution schedule and the resume rule for it. Each lane runs from a brief under
`docs/superpowers/briefs/`, in its own git worktree and env slot (`D:\lk-wt\<name>`, `LK_SLOT=N`), never pushes,
and ends with a lane report under `docs/lanes/`. Each slice ends with an integrator (brief `integrator.md`), a
full gate, evidence screenshots, a `BUILD_STATE` checkpoint and a local commit on `main`.

## Resume rule
A new session reads `docs/BUILD_STATE.md` (current checkpoint), this file (which wave is in flight), then the
lane reports of the wave. `git worktree list` shows the lanes; a lane whose report is missing is unfinished and is
restarted from its brief on its branch (the branch keeps its commits). All ten env slots are allocated below;
reuse a slot only when its worktree is clean and its lane is merged.

## Waves

| Wave | Lanes (brief → branch → worktree/slot) | Depends on | Checkpoint |
|---|---|---|---|
| 2a (done before this program) | platform-2, catalogue+imports, commercial-2, cutting on `lane/s2w1-*`, `lane/s2w2-cutting` (built 2026-10-30, unmerged) | CP1 | — |
| 2b | integrator `integrator.md` → `lane/s2-merge` → `integ`/8; challans `(brief inline in the launch)` → `lane/s2w2-challans` → `work`/4 | CP2 + 2a | **CP3** = Slice 2 on `main` (after challans merges; plus the commercial lane's uncommitted configurator in `sales`/6, to be finished by a short follow-up lane) |
| 3a | `s3-agents-runtime.md` → `lane/s3-agents` → `identity`/1; `s3-whatsapp.md` → `lane/s3-whatsapp` → `catalogue`/3 | CP2 (started early; reparented at merge) | — |
| 3b | `s3-vision-voice.md` → `lane/s3-voice-vision`; `s3-briefings.md` → `lane/s3-briefings` | CP3 | — |
| 3c | integrator → `lane/s3-merge` | 3a + 3b | **CP4** = Slice 3 |
| 4a | `s4-orders-inventory.md`, `s4-procurement-quality-logistics.md`, `s4-production.md` | CP4 | — |
| 4b | integrator → `lane/s4-merge` | 4a | **CP5** = Slice 4 |
| 5a | `s5-finance.md`, `s5-migration-backup.md` | CP5 | — |
| 5b | integrator → `lane/s5-merge` | 5a | **CP6** = Slice 5 |
| 6 | `s6-acceptance.md` → `lane/s6-acceptance` | CP6 | **CP7** = handover |

Rules that held so far and stay: at most three building lanes at once on this machine (memory); never two test
suites at once inside a lane; the Next 16.4.4 build runs with `LK_NEXT_BUILD_CPUS=2` and
`NODE_OPTIONS=--max-old-space-size=2048`; migrations from parallel lanes use placeholder numbers (0020+, 0030+,
0040+) and are renumbered by the integrator into one linear chain; Demo adapters stay the default until the owner
records the credentials and policy decisions in `BUILD_STATE` §5–§6.

## What "complete" will mean at CP7
Every `PARITY_MATRIX` row implemented with a passing named test or an honest `deferred` reason; scenarios A–N
green at three widths; every integration either live-verified or labelled Demo; handover docs; the remaining-work
list naming exactly what needs credentials or business decisions.

## Stopped 2026-11-03 (owner: "stop for now")

All four wave-2b/3a lanes were stopped mid-work. Their partial work is **uncommitted in the worktrees** (nothing
lost, nothing merged); resume each by relaunching its brief on its branch in the same worktree and telling it to
continue from the state on disk:

| Lane | Worktree / slot | Branch | State when stopped |
|---|---|---|---|
| Slice-2 integrator | `integ` / 8 | `lane/s2-merge` | platform lane merge in progress, 127 uncommitted files, 0 commits yet; it was running the backend tests |
| Challans | `work` / 4 | `lane/s2w2-challans` | module scaffolded, CRUD tests passing, fixing history flush before the detail read; 9 uncommitted files |
| Slice-3 agent runtime | `identity` / 1 | `lane/s3-agents` | 1 commit (Anthropic adapter with fake-transport contract tests), migration applied; 13 uncommitted files; next: routing table and setting, quotas, request classifier |
| Slice-3 WhatsApp | `catalogue` / 3 | `lane/s3-whatsapp` | tables and migration written (3 uncommitted files); next: outbound sender, reconciliation, enrolment, templates, webhook route, inbound processing |

`main` is at the Checkpoint-2 commits plus the Next 16.4.4 upgrade and these briefs; `npm run check` 7/7 and
`npm run test:e2e` 96/0 as of the last run on `main`.

## Resumed 2026-11-03 (owner: "complete the entirety of the app")

Relaunched from the stopped state, three building lanes at a time: the Slice-2 integrator (`integ`/8, continuing
the platform merge), challans (`work`/4, brief now recorded as `s2-challans.md`) and the Slice-3 agent runtime
(`identity`/1). Queued until a lane frees memory: Slice-3 WhatsApp (`catalogue`/3) and the commercial configurator
follow-up (`sales`/6, brief `s2-commercial-configurator.md`). Challans and the configurator merge into
`lane/s2-merge` after the four wave-2a lanes; CP3 is that branch on `main`.

## CP3 reached 2026-11-04; Slice 3 sequencing adjusted

`main` fast-forwarded to `lane/s2-merge` 10c8514 (Checkpoint 3, BUILD_STATE §11; test:api 1313, check 7/7, e2e
193/0). Agent runtime (`lane/s3-agents` e0f6065) and WhatsApp (`lane/s3-whatsapp` 9e78698) finished with reports.
Because the 3b lanes consume their interfaces (phrasing, `input_mode`, `register_transcriber`), the Slice-3
integration runs in two stages: stage 1 merges agents + WhatsApp onto CP3 as `lane/s3-merge` (`integ`/8) while
`lane/s3-voice-vision` builds from CP3 (`work`/4); `lane/s3-briefings` then branches from the stage-1 tip
(`sales`/6); stage 2 merges voice-vision and briefings and produces CP4.

## Stage 1 done 2026-11-04 (CP4a on `lane/s3-merge` 74c8cd5)

test:api 1479, check 7/7, e2e 203/0 with SSE proven in the browser (ADR-059) and scenario K through the Demo
simulator. `lane/s3-briefings` branches from 74c8cd5 in `sales`/6. Wave 4a's `lane/s4-orders-inventory` starts
early from the same tip in `identity`/1 (migration placeholders 0040+), because it is independent of voice and
briefings and the other two Slice-4 lanes build on it; it is merged after CP4 by the Slice-4 integrator.
- 2026-11-04: `lane/s5-migration` starts early from 74c8cd5 in `sales`/6 with the migration dry-run tooling and
  backup/restore parts of its brief (legacy entities are all Slice-2 and merged); its "new capabilities" part
  (offcut reuse, sample lineage, what-if views) waits for Slice 4 and is a follow-up on the same branch.
  Migration placeholder 0050+.
- 2026-11-04: orders/inventory finished (`lane/s4-orders-inventory` d2942ac, scenario I green, test:api 1521/0).
  Migration/backup finished (`lane/s5-migration` 45981fb, rehearsal 9/9). The two remaining wave-4a lanes branch
  from d2942ac so they call the real inventory posting service: `lane/s4-procurement-logistics` in `work`/4
  (placeholder 0060+) and `lane/s4-production` in `sales`/6 (placeholder 0070+).
- 2026-11-04: **CP4 on `main`** (fast-forward to `lane/s3-merge` 533f8b5; BUILD_STATE §13; test:api 1571/0,
  check 7/7, e2e 219/0 incl. SSE and scenarios B/C/J/K). `lane/s5-finance` starts early from
  `lane/s4-orders-inventory` d2942ac in `identity`/1 (placeholder 0080+): it needs orders and challans, not
  procurement or production. Remaining after the two Slice-4 lanes: the Slice-4 integrator (orders-inventory,
  procurement-logistics, production → CP5), then migration follow-up (new capabilities) and the Slice-5
  integrator (finance, migration → CP6), then Slice 6.

## Resumed 2026-11-04 (owner: "continue and finish everything")

The previous orchestrator stopped with three lanes mid-work and uncommitted edits on disk. Relaunched on their
branches in the same worktrees, continuing from the state on disk: `lane/s4-production` (`sales`/6: two test edits
and the lane report left), `lane/s4-procurement-logistics` (`work`/4: backend committed, web screens in progress),
`lane/s5-finance` (`identity`/1: module in progress, no commits). Next: the Slice-4 integrator once both Slice-4
lanes report (→ CP5), then the migration follow-up and the Slice-5 integrator (→ CP6), then Slice 6 (→ CP7).

## Paused 2026-11-04 (owner: "pause for now")

All three lanes stopped; no lane processes left running. Uncommitted work stays in the worktrees; resume each by
relaunching its brief on its branch in the same worktree, continuing from the state on disk:

| Lane | Worktree / slot | Tip | State when paused |
|---|---|---|---|
| Production | `sales` / 6 | `f3cb604` | code and tests committed; `npm run check` 7/7; full `test:api` was started and stopped (rerun it); lane report `docs/lanes/production-s4.md` untracked and unfinished |
| Procurement / quality / logistics | `work` / 4 | `f067626` | web screens and procure-to-pay e2e spec committed, tree clean; was about to run `npm run check`; then `test:api`, lane e2e, lane report |
| Finance | `identity` / 1 | `42d6b50` | module, manifest and seed committed; uncommitted edits in `accounting.py`, `ageing.py`, `common.py`, `invoices.py`, `seed/world/finance.py` and new untracked `tests/{unit,integration,contract}/finance/`; was running the accounting tests; web area, scenario M, gates and report not done |

## 2026-11-05: Slice-4 lanes done; integrator and new capabilities running

Lanes finished: production `lane/s4-production` 27f3697, procurement/logistics `lane/s4-procurement-logistics`
1c590ce, finance `lane/s5-finance` 0545c25 (the coordinator's rerun of its test:api found one stale settings test,
fixed in 4447092; the lane's first reported count was another lane's log from a shared scratchpad, withdrawn).
`lane/s5-migration` gained bf8279e (the Settings › Backups page had been ignored by an unanchored `backups/` rule).
Running: Slice-4 integrator `lane/s4-merge` (`integ`/8; three lanes merged at c4210a3, post-merge gates in progress)
and the migration brief's "new capabilities" part as its own lane `lane/s5-capabilities` from c4210a3 (`sales`/6,
placeholder 0090). The Slice-5 integrator merges finance, migration and capabilities onto CP5. Lanes now write
test logs to lane-named files under `D:\lk-wt\`, not the shared scratchpad.

## Paused 2026-11-06 for the Codex handoff

`lane/s5-merge` (`integ`/8) has all three Slice-5 lanes merged (migrations 0026–0028); the integrator's uncommitted
e2e/evidence/ADR work was committed as WIP `e9fdad3`. Post-merge gates were interrupted (`test:api` at ~60 % after
step 3); `check`, `test:e2e`, CP6 evidence, `merge-s5.md`, BUILD_STATE §15 and the PARITY moves are not done.
`lane/s6-handover` (`work`/4) is done and waits for CP6. The ordered task list for the next agent is in
`CODEX_HANDOFF.md` at the repository root; rules for any coding agent are in `AGENTS.md`.


## 2026-11-06: Checkpoint 6 verified and on main

`main` fast-forwarded to `lane/s5-merge` `7368da7`. Full API: 1772 passed / 7 skipped; fresh check: 7/7; final e2e: 314 passed / 754 skipped / 0 failed. Four scenario-test fixes are separate commits; failed attempts and scope limitations remain in `docs/lanes/merge-s5.md`. BUILD_STATE §15 and 64 indexed screenshots record CP6. PARITY_MATRIX remains honest about unbuilt features and 18 stale browser references. Task 1 is complete; next merge the handover/audit branch and validate Pillow 13, then execute Slice 6 acceptance. All external integrations remain Demo.
