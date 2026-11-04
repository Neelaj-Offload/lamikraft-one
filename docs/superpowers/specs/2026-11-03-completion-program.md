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
