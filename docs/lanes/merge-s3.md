# Lane report: Slice-3 merge, stage 2 (integrator)

Branch `lane/s3-merge` (continuing from stage 1 = Checkpoint 4a, `74c8cd5`), worktree `D:\lk-wt\integ`, env slot 8.
Stage 1 is `docs/lanes/merge-s3a.md`. Stage 2 merges `lane/s3-voice-vision` (stage 2a) and `lane/s3-briefings`
(stage 2b) and declares Checkpoint 4.

**Status: DONE_WITH_CONCERNS** — Checkpoint 4; every gate green on the final tree; concerns under "Open items".

## Steps

| # | Step | Commit | Result |
|---|---|---|---|
| 1 | Merge `lane/s3-voice-vision` d028019 (report `voice-vision-s3.md`, branched from CP3 10c8514) | `fa19410` | migration 0030 → `0019_voice_vision_slice3` (down 0018); conflicts below |
| 2 | Voice/vision integrator requests (lane report section 4) | `6cdf822` | new `0020_slice3_stage2_cross_lane_links`; ADR-061; api:generate 279 paths; targeted pytest 117 + 6 passed, channels integration 52 passed; check 7/7 |
| 3 | Stage-2a report; full `test:api` on `6cdf822` | `ab07d4e` | 1556 passed, 7 skipped, 0 failed (58 min 55 s) |
| 4 | Merge `lane/s3-briefings` a3199be (report `briefings-s3.md`, from 74c8cd5) | `a9834a3` | migration 0035 → `0021_briefings_slice3` (down 0020); no conflicts; api:generate 282 paths |
| 5 | Briefings integrator requests 1–2 (Listen through the voice module, read-back) | `c8863a4` | web lint, typecheck, vitest 60 files / 660; targeted pytest 106 passed (briefings, voice, WhatsApp C, work contracts) |
| 6 | Full `test:api` and check on `c8863a4` | — | 1571 passed, 7 skipped, 0 failed (59 min 55 s); check 7/7 |
| 7 | e2e runs 1–2 → fixes | `d6acfe7` | run 1: 209 passed / 5 failed; run 2: 218 / 1; defects below |
| 8 | Lint fix (provider without refs during render) | `46cf18e` | check 7/7; targeted e2e below |
| 9 | Evidence, docs, merge `main` 1c29a84 | see "Gates (Checkpoint 4)" | — |

## Migration chain

`0015_slice2_cross_lane_links` (main) → `0016_agents_slice3` → `0017_channels_slice3` → `0018_slice3_cross_lane_links`
→ `0019_voice_vision_slice3` (lane placeholder 0030; `corrects_turn_id` removed from `voice_utterance`, it moved to the
turn) → `0020_slice3_stage2_cross_lane_links` (integrator: `agents_turn.corrects_turn_id`, `transcript_meta`,
`vision_request_id`) → `0021_briefings_slice3` (lane placeholder 0035; `briefings_version_text`,
`briefings_summary_push`). `alembic heads` = 1; `migrate --revision 0018` → `migrate` (head) round trip on `lk_wt8`.
`alembic check` reports only the lane's expression index `uq_vision_capture_conversation_sha`, which by design lives in
the migration only (ADR-061, consequences). 

## Conflict decisions (stage 2a, voice-vision)

- `backend/app/platform/system/router.py`: both — the agents lane's `checks["ai"]` and the voice lane's
  `readiness.run_checks()` registry. `checks.ai` was not moved onto `register_readiness_check` (optional request).
- `openapi.json` / `schema.d.ts`: HEAD at the conflict, regenerated in step 2 (264 → 279 paths).
- `features/assistant/use-assistant.ts` auto-merged: the lane's `SendOptions` / `SendResult` (`clientUtteranceId`,
  `submit`) sit on top of the agents lane's SSE `run-stream.ts`. Reconciled by reading: the exchange id stays local
  (`localId`), the run is patched onto it, and the SSE effect keys on that exchange id, so voice turns stream like typed
  ones; polling remains the fallback. `composer.tsx` keeps `VoiceControls` isolated; its doc comment now says SSE.

## Integrator requests applied (voice-vision report section 4)

| Request | Status | Where / test |
|---|---|---|
| 1 renumber 0030 | applied (0019) | — |
| 2 routing table vision model + quota (drop ImportError seams) | applied | `vision/service.py`; `integration/vision/test_vision_agents_wiring.py::test_the_routing_table_sets_the_vision_model_and_quota_and_the_call_log_names_its_owner` |
| 2 `AiCallLog.user_id` / `correlation_id` | applied (trace id via `ingress_correlation_id`) | same test |
| 2 `input_mode="voice"`, `corrects_turn_id`, `transcript_meta` on the turn | applied (0020; moved off `voice_utterance`) | `integration/voice/test_voice_api.py::test_agent_c_voice_path_same_result`, `::test_correction_after_submission_is_a_new_turn_that_revises_the_draft` |
| 2 router `screen_question` / `visual_extraction` → vision | applied | `test_vision_agents_wiring.py::test_router_sends_a_screen_question_with_an_attached_screenshot_to_vision`, `::test_a_screen_question_without_a_screenshot_stays_on_the_normal_path` |
| 2 confirmed extraction taints the run (`untrusted_payload`) | applied (`TurnCreate.extraction_id`; web ExtractionCard passes it) | `::test_a_confirmed_extraction_reaches_the_run_as_untrusted_data_and_taints_it` |
| 2 read-back before a voice confirm/approve | applied in `approvals.decide(channel="voice")` / `DecideIn.channel` | `integration/channels/test_customers_and_quote_send.py::test_a_voice_approval_of_the_quote_send_needs_a_fresh_readback` |
| 2 DPDP approval gates live capture | applied (403 `dpdp_approval_required`; capabilities report it) | `::test_live_capture_needs_the_recorded_dpdp_approval` |
| 2 a ReadbackCard kind | deferred — no spoken approve exists in the assistant yet; the server seam is the guard [agents web] |
| 3 `register_transcriber` | applied (unconditional) | `::test_the_voice_module_is_the_whatsapp_transcriber`; channels integration 52 passed incl. `test_scenario_c_whatsapp.py` voice note |
| 4 composer / `use-assistant` merge | applied (above) | e2e at stage 2b |
| 5 shared-file touches; regenerate API | applied (279 paths) | check 7/7 |
| 5 `checks.ai` → `register_readiness_check` | deferred — optional, behaviour identical [agents] |
| section 5 `verify_gemini` → `POST /admin/ai/verify` | applied (`vision` in the response) | `integration/agents/test_slice3_api.py::test_ai_status_usage_and_verify_in_demo` |
| Gemini price row in the routing price table | deferred — no Gemini price recorded; vision usage shows unpriced [owner] |

## Conflict decisions and requests (stage 2b, briefings)

The merge had no conflicts: `routes.ts` (`today-changes`, `today-all`, `today-item`), `query-keys.ts`
(`briefings.delta`, `briefings.item`), the work-contracts table count (20), `lib/test-support/briefing.ts` and channels
`register_button_handler` merged as the lane wrote them; `openapi.json` / `schema.d.ts` regenerated (282 paths).

| Request (briefings report section 4) | Status | Where / test |
|---|---|---|
| 1 Listen through the voice lane's TTS | applied: `features/briefing/listen/voice-speech.tsx` (`VoiceSpeechProvider` on Today, one stable port over `POST /voice/speech`; Demo TTS labelled "Demo voice" stays the default; no `voice.speech.use` or TTS off → silent Demo voice; a browser autoplay block keeps the timing). The voice lane has no `useSpeech()` hook; the adapter calls `createSpeech` | `listen/voice-speech.test.tsx`; `e2e/scenarios/b-briefing-stability.spec.ts` |
| 1 real audio levels for `WaveformBars` | deferred — optional; the Demo clip is silent [web voice] |
| 2 read-back before a voice confirmation | applied as far as the app allows: paused on an item, "Read back the details" speaks `speech.readback(segment.readback)` on its own player and shows the sentence; no spoken approve exists yet (the server guard is `approvals.decide(channel="voice")`, ADR-061) | `listen/voice-speech.test.tsx` |
| 3 renumber 0035 | applied (0021) | — |
| 4 shared files; regenerate API | applied (282 paths) | check 7/7 |
| 5 PARITY SCN-B3, B4, B6 | applied | `docs/PARITY_MATRIX.md` |
| 6 template quick-reply `button` messages in channels inbound | deferred — needs armed payloads on template sends as well as inbound handling, not small; "Got it" works inside the window, the web acknowledges otherwise [channels] |
| 7 phrasing cache keyed by provider mode | deferred — optional; briefings tags its template codes with the mode [agents] |

## Defects found and fixed in the merge (stage 2b, by the e2e runs)

1. `/today/changes` returned 500: the server page called `deltaSinceFrom()` from the `"use client"` module
   `changes-view.tsx` (the brief's invariant). Moved to `briefing/slice3-api.ts`.
2. Listen pressed before the voice capabilities arrived stayed "Preparing" for ever (my provider): swapping the speech
   port rebuilt the Listen session and dropped the started one. `VoiceSpeechProvider` now provides one stable port
   that delegates to the voice chosen later (vitest `the provider's port`).
3. Spec interactions with the merged Today: `name: "Send"` also matched "Send to WhatsApp" (scenario C, both
   evidence specs: now `exact`); scenario B compared only the visible rows, but the voice specs that run earlier leave
   draft quotes that push the new reply below them — it now compares the rows and the overview sentence.

## Defects found and fixed in the merge (stage 2a)

1. `transcript_meta` written as JSON `null` (SQLAlchemy JSONB default) broke the object CHECK on every non-voice turn —
   `JSONB(none_as_null=True)`.
2. Vision call-log rows had no trace id for requests without an ingress correlation id — the agents
   `ingress_correlation_id` now supplies a UUIDv7 as for orchestrator rows.

## Gates (Checkpoint 4)

- `npm run test:api` on `c8863a4`: **1571 passed, 7 skipped** (`test_golden_live`, live only), **0 failed**, 2 known
  warnings, 59 min 55 s. After it only web files and e2e specs changed (`d6acfe7`); no backend file changed.
- `npm run check -- --keep-going` on `46cf18e`: **7/7 PASS** — ruff; pytest unit + contract 681 passed; alembic heads
  == 1; api:check; web lint; web typecheck; web vitest 60 files / 661 tests. (The run on `d6acfe7` failed web lint:
  the provider read a ref during render; `46cf18e` replaces it with a switchable port, behaviour unchanged.)
- `npm run test:e2e -- --workers=1` on `d6acfe7` (production build, `LK_NEXT_BUILD_CPUS=2`,
  `NODE_OPTIONS=--max-old-space-size=2048`, own database `lk_wt8_e2e`, `--slice 2`): **219 passed, 0 failed**, 474
  skipped (project-scoped and opt-in), 11.0 min. Includes scenario C with SSE (desktop, phone), `scenarios/b-briefing-
  stability.spec.ts` 2/2, `scenarios/j-voice.spec.ts` 8/8 (desktop, phone), `scenarios/c-screen-capture.spec.ts` 2/2,
  `scenarios/k-whatsapp.spec.ts` 4/4, and the axe sweep in light and dark over every manifest route incl.
  `/today/changes` and `/today/all` (`/today/items/[itemId]` skipped: no fixture id). Runs 1–2: 209/5 and 218/1
  (defects above).
- Targeted e2e on `46cf18e` (fresh production build, after the lint fix): `scenarios/b-briefing-stability.spec.ts`,
  `scenarios/j-voice.spec.ts`, `scenario-c.spec.ts` — **16 passed, 0 failed** (11 project-skipped), 2.3 min.
- Evidence: `docs/evidence/checkpoint-4/` (24 PNGs, README).

### Stage 2a

- Stage 2a: check 7/7 on the tree of `6cdf822` (ruff; pytest unit + contract 676 passed; heads 1; api:check; lint;
  typecheck; vitest 58 files / 645 tests). Full `test:api` started on `6cdf822` (report commit `ab07d4e` adds no
  code): **1556 passed, 7 skipped (`test_golden_live`), 0 failed**, 2 known warnings (google-genai
  DeprecationWarning, the PIL decompression-bomb test), 58 min 55 s. The briefings merge was started in the worktree
  after collection (at about 60 %); the final-tree run under "Gates (Checkpoint 4)" is the authoritative one.

## Docs

`docs/PARITY_MATRIX.md` (Checkpoint 4 note: SCN-B3, B4, B6, C4, J1 implemented; SCN-J3 in progress `3→4`),
`docs/BUILD_STATE.md` (header, §2, §7 rows, §8, new §13), `docs/DECISIONS.md` (ADR-061),
`docs/evidence/checkpoint-4/README.md`.

## Open items (owners)

See `docs/BUILD_STATE.md` section 13: no live Anthropic/Gemini/STT/TTS/Meta call [owner]; Gemini price row [owner];
spoken approve and ReadbackCard [agents web]; template quick replies [channels]; migration-only vision index [vision];
`checks.ai` registry, phrasing cache mode key [agents]; DOM screenshot limits [vision, voice]; quiet hours [briefings];
phone composer height [web voice, design]; axe skip of `/today/items/[itemId]` [web].
