# Checkpoint 4 evidence — Slice 3 on the merged branch (2026-11-04)

24 screenshots of the screens the Slice-3 stage-2 lanes (voice/vision, briefings) added, at 1440 px and 390 px wide,
light and dark (`<screen>-<width>-<theme>.png`). Taken by `e2e/evidence-cp4.spec.ts` against the production build of
the final e2e run (`d6acfe7`), on a fresh demo world seeded at `--slice 2` with `--anchor-date 2026-10-12`:

```
LK_E2E_EVIDENCE=cp4 npm run test:e2e -- --no-build e2e/evidence-cp4.spec.ts --project=desktop
```

The stage-1 screens (Settings → AI, trace, Settings › WhatsApp, review link) are in `../checkpoint-4a/`.

| Screen | Route | Signed in as |
|---|---|---|
| today | `/today` (Listen to my day, What changed / All items / Send to WhatsApp, the composer with the voice and screen controls) | Meera |
| today-listen-paused | `/today` after Listen → Pause: the panel with "Demo voice", the words being read, Resume/Stop, the pinned-list note | Meera |
| today-changes | `/today/changes` (since your last visit; the seeded world has no changes in that window, so the honest empty state shows) | Meera |
| today-all | `/today/all` (every section and the snoozed items, filters) | Meera |
| today-item | `/today/items/<issue id>` (the first item of Meera's briefing: suggestion, why it is here, rule version, evidence) | Meera |
| composer-voice | `/today` scrolled to the "Voice and screen" group (Hold to talk, Look at my screen, Read a photo or document, Speak replies, "Speech: Demo") | Meera |

Inspected by the integrator: today-listen-paused (1440 light), today-item (390 dark), composer-voice (390 light) and
today-changes (1440 dark) checked by eye; both themes legible, no horizontal overflow at 390 px. Observation (open
item, not a defect of this merge): on a phone the docked composer with the voice row takes about a third of the
viewport above the tab bar. The flows behind these screens are exercised by `e2e/scenarios/b-briefing-stability.spec.ts`
(Listen pins the order; Escape stops; reduced motion), `e2e/scenarios/j-voice.spec.ts` (voice turn, mic denied,
interrupt, offline draft), `e2e/scenarios/c-screen-capture.spec.ts` (masked screenshot) and the axe sweep of the same
build (light and dark, including `/today/changes` and `/today/all`; `/today/items/[itemId]` is skipped there because
issue ids are computed, not fixture records).
