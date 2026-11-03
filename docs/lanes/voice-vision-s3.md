# Lane report: vision (Gemini) and voice (Slice 3, wave 3b)

Branch `lane/s3-voice-vision` (from `main` 10c8514, CP3), worktree `D:\lk-wt\work`, env slot 4 (API 8040, web 3040,
databases `lk_wt4` / `lk_wt4_test` / `lk_wt4_e2e`). Brief: `docs/superpowers/briefs/s3-vision-voice.md`. Status:
**deliverables 1–6 implemented on the Demo adapters and tested; the Gemini adapter is tested against a fake
transport only. No live Gemini, STT or TTS call was made (no key, no vendor chosen — BUILD_STATE §5 #5 and #6).**
Hindi and Hinglish are labelled **Untested** everywhere they appear.

The slot's databases held the challans branch (a divergent revision `0010`); they were dropped, recreated, migrated
to this branch's head and reseeded (`lk seed demo --anchor-date 2026-10-12`) per `docs/runbooks/local-dev.md`.

## 1. What was built

| # | Deliverable | Where | Notes |
|---|---|---|---|
| 1 | Gemini adapter | `backend/app/modules/agents/providers/gemini_vision.py` | Sync `google-genai` 2.29.0 client per call (`HttpOptions(timeout=ms, retry_options=attempts 1, httpx_client=…)`), `client.models.generate_content` with `system_instruction`, `response_mime_type="application/json"`, `response_json_schema` per kind, `max_output_tokens` 512 (screen) / 2,048 (extraction), `temperature 0`, `thinking_level LOW`, `media_resolution` medium (screen) / high (extraction) / low (classification). No tools, no function calling. Timeout 8 s (screen) / 20 s (extraction). Every failure (timeout, connect, HTTP status, non-STOP finish such as SAFETY, unparseable or empty JSON) → `VisionUnavailable` → "Vision unavailable — enter details". Key only from `GEMINI_API_KEY` on the server. `verify()` classifies a 1×1 PNG for the `ai.gemini` integration check (registered from the vision manifest). |
| 1 | Demo adapter | `backend/app/modules/agents/providers/demo_vision.py` | Extraction from a fixture table by SHA-256: the seeded `app/modules/vision/fixtures/demo-delivery-note.png` → DN-4471, 08/10/2026, Shree Timber Traders → Lamikraft Works, three lines (40 / 25 / 3), with the vehicle number (0.55) and the third quantity (0.62) deliberately uncertain. Unknown images → every field empty, confidence 0 (all confirmation fields; never invented). Screen answers only from the re-read screen facts; data/action questions hand off. |
| 1 | Contract | `backend/app/modules/vision/contract.py` | Field specs per kind (purchase order, bill, delivery note, handwritten list) + screen answer; JSON schemas use only the keywords Google documents as supported; `parse_extraction` drops unknown keys, clamps confidences, nulls missing values. |
| 2 | Masked screenshot | web `src/lib/screen-capture/{mask,capture}.ts`; backend `vision/service.py` | Client capture of the app's own DOM (never `getDisplayMedia`): a deep clone where every `[data-restricted]`, `[data-private]` and `input[type=password]` becomes an opaque block of the same size and layout (the live page is untouched), wrapped in an SVG `foreignObject` with the page's same-origin CSS and theme variables, drawn ≤ 1568 px, WebP stepped down to ≤ 1.5 MB (PNG where WebP cannot be encoded), SHA-256. Server: WebP/PNG only, ≤ 1.5 MB, ≤ 1568 px, stored as `file_object` purpose **`screen_capture`**, `restricted`, deduplicated per (user, conversation, SHA-256), purged after **24 h** (`vision.captures.purge`, every 15 min) or at once when the chip is removed; the call log and `vision_request` reference it by hash only. `screen_capture.enabled` company setting (default true in demo, **false in live**) is mandatory; `assistant.screen_share = ask|auto` preference (default ask). `data-restricted` added to the product cost card and the `bank_details` setting values (the custom-product costing section already had it). |
| 3 | Instant answers + extraction | `vision/service.py`, `vision/router.py`; web `features/voice/{use-screen-share.ts,extraction-card.tsx}` | `POST /vision/screen-answers`: masked screenshot + the **re-read** screen context (`agents.context.ground_screen_context` + `platform.sources`), figures not in the re-read records replaced by "see screen" (`grounding.check_claims`), hand-off when data or an action is needed (the client then sends the question as a normal assistant turn). `POST /vision/extractions` → `ExtractionCard`: confident values shown, uncertain/missing ones are empty confirmation fields (the model's reading is only a hint); `POST /vision/extractions/{id}/confirm` requires every confirmation field explicitly, never writes records. Everything is tainted (`vision_request.tainted` is CHECK-forced true). Quota `vision_calls_per_user` (60/day default). |
| 4 | Voice backend | `backend/app/modules/voice/**` | `voice_utterance` (PK = client UUIDv7, `turn_id` unique), `voice_speech`, `voice_readback`. `POST /voice/transcriptions` (≤ 60 s measured for WAV / recorder duration for compressed, ≤ 10 MB, webm / ogg-opus / mp4 / wav by magic bytes) → `{text, language, confidence, segments}`; idempotent on the utterance id (no re-transcription). `POST /voice/utterances` (browser fallback transcript, only when enabled), `POST /voice/utterances/{id}/submit` (one agents turn with `client_utterance_id` = utterance id; resend returns the same turn and run; corrections carry `corrects_turn_id`), `POST /voice/speech` (stores audio, `url` same-origin, owner session only, valid 5 min, no token), `GET /voice/speech/{id}/audio`, `POST /voice/readbacks`, `GET /voice/capabilities`. Adapters: Demo (fixture SHA-256 → transcript; unknown recordings get the scripted phrase flagged `simulated`, confidence 0), browser marker ("Browser fallback", off by default), vendor stub (`not_configured`). Audio purged after 7 days (`voice.audio.purge`, hourly). Integrations `voice.stt`, `voice.tts`. Readiness check `voice`: production with only the browser fallback → 503. `readback.py`: deterministic text (customer, status, quantity + UOM, unit price + currency, total, valid-until / issued / prepared date in the user's zone) and `require_presented_readback` (10-minute, consumed once, record unchanged). Bootstrap `capabilities.voice` true when an STT path exists. |
| 5 | Web voice | `src/lib/voice/**`, `src/features/voice/**`, `src/messages/voice.ts`; composer mounts `VoiceControls` | Push-to-talk (hold, or tap to toggle; keyboard via react-aria press; 44 px), utterance id on press, recording indicator + waveform only while recording (static level meter under reduced motion), Esc/Cancel discards, `NotAllowedError`/`NotFoundError` inline (alert), focus to the text box, voice off until "Try the microphone again", editable final transcript ("Demo transcript — not from your recording" when simulated; "Untested" language note), partial transcripts (browser fallback) greyed and not sendable, Send once (the button is disabled while the assistant is busy; a resend reuses the id), "Correct what I said" → the next recording is a correction turn, spoken replies (switch, Demo silent clip) stopped by push-to-talk, typing in the composer or Stop, read-back block after a voice-drafted quote, offline → IndexedDB "Queued draft — not sent", reviewed and sent on reconnect with the same id. "Look at my screen" + removable "Masked screenshot attached" chip; "Read a photo or document" → ExtractionCard. |
| 6 | Scenario C via voice, J | backend + e2e | §2. |

Migration: `backend/migrations/versions/0030_voice_vision_slice3.py` (revision `0030`, `down_revision = "0015"` — the CP3
head; placeholder per the completion program, the integrator renumbers). It also widens
`ck_file_object_purpose_values` with `screen_capture`.

**Gemini model id**: `gemini-3.8-flash` is listed (badge "New") on Google's models page
(`ai.google.dev/gemini-api/docs/models` → `aistudio.google.com/docs/models`), checked **2026-11-04**; `gemini-3.6-flash`
is the current "Stable" Flash. `LK_MODEL_VISION` keeps the routing default `gemini-3.8-flash`. Google's docs now
lead with the Interactions API and call `generateContent` "legacy" but "fully supported"; the adapter uses
`generateContent` because it is stateless (the Interactions API stores interactions by default — 55 days on the paid
tier — unless `store=false`), which suits the DPDP gate. Structured-output keywords used are those the page lists as
supported (`type` arrays for null, `enum`, `minimum`/`maximum`, `maxItems`, `required`). Image types: PNG, JPEG,
WebP (and PDF for documents); inline requests ≤ 20 MB. SDK note: `google-genai` 2.29.0 serialises
`thinkingConfig.thinking_level` in snake case (proto3 JSON accepts both spellings).

## 2. Tests

| Item | Test |
|---|---|
| Gemini request shape, parse, failures (timeout, connect, 429, 503, SAFETY, unparseable, empty), classification, 8 s / 20 s | `tests/contract/agents/test_gemini_vision_adapter.py` (13) |
| Vision schemas, parsing, Demo fixture and Demo never inventing values | `tests/unit/vision/test_vision_units.py` |
| Captures restricted / deduplicated / bounded, generic upload refused | `integration/vision/test_vision_api.py::test_masked_capture_is_restricted_deduplicated_and_bounded` |
| Company switch mandatory, off in live | `::test_company_switch_is_mandatory_and_off_by_default_in_live` |
| Screen answer from re-read context, hand-off, call log by hash | `::test_screen_answer_uses_reread_context_and_hands_off_actions` |
| Unsupported figures replaced | `::test_unsupported_figures_in_a_screen_answer_are_replaced` |
| Foreign capture 404, removed capture gone | `::test_unauthorised_context_and_foreign_captures_reveal_nothing` |
| Extraction card: uncertain fields empty, confirm required, untrusted payload | `::test_extraction_card_marks_uncertain_fields_for_confirmation`, `::test_unknown_image_in_demo_is_all_confirmation_fields` |
| Live without key → 409; provider timeout → manual entry | `::test_live_mode_without_a_key_fails_visibly`, `::test_provider_timeout_degrades_to_manual_entry` |
| Quota, 24 h purge | `::test_daily_quota_stops_vision`, `::test_captures_are_purged_after_24_hours` |
| Scenario C via voice (same tools, card, read-back text) | `integration/voice/test_voice_api.py::test_agent_c_voice_path_same_result` |
| SCN-J1 corrected transcript never submits twice | `::test_same_utterance_id_one_turn` |
| Correction = new turn with `corrects_turn_id`, revises the draft | `::test_correction_after_submission_is_a_new_turn_that_revises_the_draft` |
| Ambiguous customer by voice → clarification (SCN-J2 voice part) | `::test_ambiguous_customer_by_voice_asks_for_clarification` |
| Read-back required before a voice confirm (missing, consumed, expired, changed) | `::test_voice_readback_required_before_confirm` |
| Hinglish labelled untested, same path | `::test_hinglish_recording_is_labelled_untested_and_takes_the_same_path` |
| Magic bytes / 60 s / UUIDv7 | `::test_recordings_are_checked_by_magic_bytes_size_and_length` |
| Speech owner-only, 5 min, no token, text not stored | `::test_speech_is_owner_only_and_short_lived` |
| 7-day audio purge | `::test_audio_is_purged_after_seven_days` |
| Browser fallback off by default and labelled | `::test_browser_fallback_is_off_by_default_and_labelled_when_on` |
| Vendor not_configured; production readiness with only the browser fallback | `::test_vendor_adapter_fails_visibly_and_production_needs_more_than_the_browser` |
| Capabilities (Demo, Untested hi-IN/Hinglish); other user's utterance 404 | `::test_capabilities_are_demo_with_untested_hindi_and_hinglish`, `::test_another_users_utterance_is_not_found` |
| Audio containers, Demo STT/TTS, vendor stub, read-back money words | `tests/unit/voice/test_voice_units.py` |
| Lane contracts (CHECKs = enums incl. `file_object.purpose`, forced RLS, always-tainted CHECK, routes/permissions/operationIds, registrations) | `tests/contract/voice/test_lane_schema.py` |
| tts-interrupt, offline-queue, recorder errors, browser language | web `src/lib/voice/voice.test.ts` |
| Mask rule, downscale, waveform/static meter, VoiceControls markup, ExtractionCard (no pre-fill) | web `src/features/voice/voice.test.tsx` |
| J in the browser (fake media device; mic denied; interrupt; offline draft) | `apps/web/e2e/scenarios/j-voice.spec.ts` |
| `masked_regions_are_blacked_out_and_capture_is_explicit` | `apps/web/e2e/scenarios/c-screen-capture.spec.ts` |

## 3. Decisions

- **Vision is its own module** (`app/modules/vision`, owner `vision`) next to the two provider files the brief
  assigns in `agents`; the orchestrator (agents-owned, edited heavily by the agents lane) is not touched. Instant
  answers and extractions have their own endpoints; a hand-off is the client sending the question as a normal turn.
- `screen_capture` is a **company setting** key (`screen_capture.enabled`; setting keys are snake_case, so not the
  dotted `agents.screen_capture_enabled` of the brief), read/managed with `org.settings.read` / `org.settings.manage`.
- Vision permission: `agents.assistant.use` (no vision key exists in the frozen catalogue). Speech: `voice.speech.use`.
- Captures accept PNG as well as WebP (Safari cannot encode WebP from a canvas).
- `voice_utterance` PK = the client UUIDv7 (globally unique); per-conversation uniqueness is the agents turn's
  `(conversation_id, client_utterance_id)`.
- The Demo STT answers an unknown recording with its scripted phrase, flagged `simulated` and labelled in the UI
  ("Demo transcript — not from your recording"), so scenario C is demonstrable with a real or fake microphone without
  pretending to recognise speech.
- A correction is spoken again (a new utterance); typed corrections go through the normal text path.
- Read-back for a draft says "Prepared <date>" (drafts have no `valid_until` yet).
- Voice config lives in `voice/config.py` (`LK_VOICE_*`), not in `core/config.py`.
- Module readiness hook `app/platform/system/readiness.py` (`register_readiness_check`), so `/health/ready` gains
  checks without modules editing the router again.

## 4. Integrator requests

1. Renumber/reparent `0030_voice_vision_slice3.py` after agents `0020` and WhatsApp `0022` (`lk db reparent`).
2. **agents-s3 seams** (not on this branch):
   - `vision/service.py` already calls `agents.routing.resolve(uow).model_for("vision")` and the `vision_calls_per_user`
     quota when `app.modules.agents.routing` exists (ImportError-guarded), and sets `AiCallLog.user_id` /
     `correlation_id` when those columns exist — verify both after the merge (`test_daily_quota_stops_vision` patches
     the quota; add one assertion against the routing table).
   - `agents_turn` has no `input_mode`, `corrects_turn_id` or `transcript_meta` (design §4). `voice_utterance` keeps
     them for now; once agents adds the columns, pass `input_mode="voice"`, `corrects_turn_id` and
     `transcript_meta={provider, language, confidence, edited, original_text}` from `voice.service.submit_utterance`
     to `create_turn`.
   - Orchestrator: route `screen_question` / `visual_extraction` (router classification) to the vision service, and
     feed a confirmed extraction into a run with `vision.service.untrusted_payload(uow, request_id)` (the
     `{"untrusted": true, ...}` block; the run must be tainted). Today the client sends a summary of the confirmed
     values as a normal turn ("Ask the assistant to use these details"), which is **not tainted** server-side.
   - Agents/approvals: call `voice.readback.require_presented_readback(uow, subject_type, subject_id, action=...)` before
     executing any confirm/approve whose channel is voice; a ReadbackCard kind could replace the composer's read-back
     block.
   - In live mode also require the recorded DPDP approval (`routing` `dpdp`) before honouring `screen_capture.enabled`.
3. **WhatsApp**: `voice/manifest.py` `on_load` registers `voice.service.whatsapp_transcriber` through
   `channels.whatsapp.stt.register_transcriber` (ImportError-guarded). It uses the configured STT adapter and falls back
   to the channel's Demo transcriber for unknown (simulated) recordings — run the WhatsApp voice-note tests after merge.
4. **Composer stage-2 merge**: this lane changed `features/assistant/composer.tsx` (import, two refs, `beforeSend` /
   `interrupt` in submit, `<VoiceControls>` mount, `ref` on the root) and `use-assistant.ts` (`send` gains
   `SendOptions{clientUtteranceId, submit}` and returns `SendResult | null`; exchange ids are separate from utterance
   ids). The agents lane changed the polling/SSE part of `use-assistant.ts` only; the two should merge cleanly.
5. Shared-file touches (small, additive): `app/platform/files/{models,service}.py` (`screen_capture` purpose),
   `app/platform/identity/preferences.py` (`assistant.screen_share`, `hinglish` speech language),
   `app/platform/system/router.py` + new `readiness.py`, `app/modules/ui/service.py` (voice flag),
   `features/products/product-prices.tsx` and `features/settings/setting-card.tsx` (`data-restricted`),
   `backend/openapi.json` + `schema.d.ts` (regenerate after the merge). `checks.ai` from the agents lane can move onto
   `register_readiness_check`.
6. PARITY moves: SCN-J1 → implemented (`tests/integration/voice/test_voice_api.py::test_same_utterance_id_one_turn`;
   the planned path `tests/integration/voice/test_transcript_idempotency.py` was not used), SCN-J3 → implemented once
   the e2e spec passes in the integrator's run (`e2e/scenarios/j-voice.spec.ts`; its "stock-movement card shows
   'Not committed (offline)'" part waits for Slice 4), SCN-C4 voice part (`test_agent_c_voice_path_same_result`).
7. Owner decisions unchanged: STT/TTS vendor (§5 #5) and DPDP (§5 #6). Implementing the vendor = `voice/adapters/vendor.py`
   (+ a recorded en-IN / hi-IN / Hinglish phrase set before the "Untested" labels go).

## 5. Not done / limits

- No live Gemini/STT/TTS call. CP3 has no verify endpoint; the `ai.gemini` routine (`vision/manifest.py::verify_gemini`,
  a 1×1 PNG classification) is registered on the integration definition — wire it into agents-s3's
  `POST /admin/ai/verify` (integrator). The live checks once a key exists: that verify and one extraction of the demo
  delivery note.
- The screenshot is a DOM rasterisation: cross-origin images and web fonts do not render inside the SVG; layout and
  text do. A canvas that the browser taints, or no WebP/PNG encoder, gives "The screenshot couldn't be taken".
- `assistant.screen_share = auto` is stored and reported but nothing triggers an automatic capture until the router
  classifies `screen_question` (integrator request 2).
- Offline drafts cover voice transcripts; typed messages offline keep the existing "You're offline. Your message
  wasn't sent." There is no stock-movement card yet (Slice 4).
- Compressed recordings' durations are the recorder's (bounded by the 10 MB cap); only WAV is measured.

## 6. Gate output

`npm run check -- --keep-going` on the final tree — **7/7 PASS**:

```
backend: ruff check              PASS
backend: pytest unit + contract  PASS   588 passed
alembic heads == 1               PASS
api:check                        PASS   backend/openapi.json matches the app
web: lint                        PASS
web: typecheck                   PASS
web: vitest                      PASS   55 files, 628 tests
```

`npm run test:api` (full backend suite, LK_ENV=test, slot 4, 44 min): **1,382 collected — 1,379 passed, 3 failed**. The
three were this lane's: `tests/integration/system/test_integrations.py` (2: the integration key list now includes
`voice.stt` / `voice.tts`; the test's `KEYS` updated) and `test_voice_readback_required_before_confirm` (two
read-backs presented in the same clock instant; the latest is now chosen by `presented_at, id`). After the fix
both files were rerun: **24 passed**; the full suite was not rerun (44 min on this machine).

`npm run api:generate` — committed (`backend/openapi.json` 258 paths, `apps/web/src/lib/api/schema.d.ts`).

e2e (`npm run test:e2e`, own database `lk_wt4_e2e` seeded `--slice 2`, `next build` with `LK_NEXT_BUILD_CPUS=2`
`NODE_OPTIONS=--max-old-space-size=2048`, desktop + phone):
- `e2e/scenarios/j-voice.spec.ts` — **8/8 passed** (fake media voice turn sends once and reads back "Total EUR
  5,760.00."; mic denied keeps the text path and focuses the text box; Stop interrupts speech; offline transcript is a
  "Queued draft — not sent", no card, sent on reconnect).
- `e2e/scenarios/c-screen-capture.spec.ts` — **2/2 passed** (no background capture, no `getDisplayMedia`, masked
  count ≥ 1, the restricted region's pixel in the uploaded WebP is the dark mask while the live page still shows the
  sentinel, ≤ 1568 px and ≤ 1.5 MB, chip removable, Demo answer, screenshot used once).
- Regression with the new composer: `e2e/scenario-c.spec.ts`, `e2e/axe-sweep.spec.ts`, `e2e/keyboard.spec.ts` —
  **147 passed, 169 skipped** (project filters), 0 failed.

The first e2e attempt waited for the machine-wide e2e lock (held by the integrator's run in `integ`); the first real
run failed on locator strictness only (the page's announcer repeats status text) and on the React-aria switch's hidden
input; locators were scoped to the "Voice and screen" group and the mic-error focus deferred until the press settles.
All servers started by the e2e orchestration were stopped by it; no dev server was started by this lane.
