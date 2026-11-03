# Checkpoint 4a evidence — Slice-3 stage 1 on the merged branch (2026-11-04)

24 screenshots of the screens the agents-runtime and WhatsApp lanes added, at 1440 px and 390 px wide, light and dark
(`<screen>-<width>-<theme>.png`). Taken by `e2e/evidence-cp4a.spec.ts` against the production build of the final e2e
run, on a fresh demo world seeded at `--slice 2` with `--anchor-date 2026-10-12`:

```
LK_E2E_EVIDENCE=cp4a npm run test:e2e -- --no-build e2e/evidence-cp4a.spec.ts --project=desktop
```

This is an intermediate checkpoint: Checkpoint 4 follows in stage 2 (voice/vision and briefings lanes).

| Screen | Route | Signed in as |
|---|---|---|
| settings-ai | `/settings/ai` (provider status Demo, DPDP text, usage from the call log, routing) | Priya (admin) |
| trace | `/settings/ai/traces/<correlation id>` of a run the spec starts (Meera's scenario-C request, streamed over SSE) | Meera (participant) |
| settings-whatsapp | `/settings/whatsapp` (Demo — not connected, Link my WhatsApp, linked numbers, simulator) | Meera |
| settings-whatsapp-admin | `/settings/whatsapp` with the admin cards (account checks, messages needing attention, templates) below the fold | Priya |
| review-link-invalid | `/r/not-a-valid-token` (a valid link resolves once and redirects at once, so the honest error state is shown) | Meera |
| settings-hub | `/settings` (AI and WhatsApp entries with hints) | Priya |

Inspected by the integrator: settings-ai (1440 light), trace (390 dark), settings-whatsapp (390 light),
settings-whatsapp-admin (1440 dark) and review-link-invalid (1440 light) checked by eye; no overflow at 390 px, both
themes legible. The valid review-link redirect and the simulator conversation (link, text and voice drafts, used
button, STOP/START) are exercised by `e2e/scenarios/k-whatsapp.spec.ts`; the axe sweep of the same build covered every
manifest route in light and dark, including `/settings/ai`, `/settings/whatsapp` and `/r/[token]` (invalid state).
