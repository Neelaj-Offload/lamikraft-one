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
