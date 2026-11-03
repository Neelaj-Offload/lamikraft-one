# Lane brief: Slice 3 — vision (Gemini) and voice (STT/TTS, push-to-talk, read-back)

Branch `lane/s3-voice-vision` from `main`. Module owner: `backend/app/modules/voice/**`,
`backend/app/modules/agents/providers/gemini_vision.py` + `providers/demo_vision.py` (only these two files in
agents), `apps/web/src/lib/voice/**`, `apps/web/src/features/voice/**`, the push-to-talk and transcript parts of
`apps/web/src/features/assistant/composer.tsx` (coordinate: the agents lane owns streaming/run parts of the
composer; keep your change to a `VoiceControls` component mounted by the composer), screen capture under
`apps/web/src/lib/screen-capture/**`, copy `src/messages/voice.ts`. Never push; small named commits; never two
test suites at once; never leave dev servers running.

## Contracts (read first)
1. `docs/architecture/ai-routing.md` §2 (vision rows), §3 (`screen_question`, `visual_extraction`), §4.2 masked
   screenshot (the full rule set), §5.2 Gemini adapter, §6 taint (vision output is untrusted), §9 tests.
2. `docs/design/source/agent_voice_whatsapp.md` §14 Voice (client and server), §4 `voice_utterance` table, §16
   endpoints (`/voice/transcriptions`, `/voice/speech`, `/voice/capabilities`), §18 scenario C via voice.
3. `docs/PLAN.md` Slice 3 "Vision" and "Voice" bullets; `docs/architecture/motion-system.md` (waveform only while
   recording or speaking; static level meter under reduced motion); `permissions.md` (`voice.speech.use`);
   `docs/BUILD_STATE.md` §5 decision 5 (STT/TTS vendor undecided → Demo adapter plus a labelled, off-by-default
   browser fallback; Hindi/Hinglish labelled untested) and §5 decision 6 (screenshots disabled in live until DPDP).
4. Platform files API (`backend/app/platform/files`) for storing audio and screen captures (`purpose`,
   `classification`, purge), the jobs module for purge jobs, `platform/system/integrations.py` for status defs
   (`ai.gemini` exists; add `voice.stt`, `voice.tts`).
5. Web: `docs/superpowers/specs/2026-11-02-checkpoint-2-build-guide.md` §0; `apps/web/src/features/assistant/*`
   (composer, `use-assistant`, cards, `screen-context.ts`); `lib/session/types.ts` (`capabilities.voice`,
   bootstrap `features.voice`).

## Deliverables
**Vision**
1. `gemini_vision.py`: sync `google-genai` client, model `LK_MODEL_VISION`, key server-side only; read-only,
   JSON response schema per extraction kind (purchase order, bill, delivery note, handwritten list, screen answer)
   with per-field confidence; timeouts 8 s (screen) / 20 s (extraction); failures → "Vision unavailable — enter
   details". `demo_vision.py`: deterministic fixtures (a seeded delivery-note image → known fields). Verify the
   Gemini model id against Google's docs at build time and record it in the lane report.
2. **Masked screenshot** (§4.2): client capture from the app's own DOM (never `getDisplayMedia`), clone with every
   `data-restricted`, password and `data-private` element replaced by an opaque block, downscale ≤1568 px, WebP
   ≤1.5 MB, SHA-256 dedupe per conversation, stored as `file_object` purpose `screen_capture` classification
   `restricted`, purged after 24 h, referenced by hash only in the call log; user preference
   `assistant.screen_share = ask|auto` (default ask) and company setting `agents.screen_capture_enabled` (default
   true in demo, false in live until DPDP); a removable "Masked screenshot attached" chip; a "Look at my screen"
   control. Add `data-restricted` to the restricted fields that exist (costing, bank details) if missing.
3. **Instant answers** for `screen_question` (Gemini, 8 s) with hand-off to Claude when data or an action is
   needed; **photo/document extraction** into a structured confirmation card (`ExtractionCard`, confirmed fields
   only then go to tools or direct forms; uncertain fields are confirmation fields, never defaults). The run is
   tainted.

**Voice**
4. Backend `modules/voice/`: `voice_utterance` table (client UUIDv7 primary key, unique per conversation),
   `POST /api/v1/voice/transcriptions` (≤60 s, ≤10 MB; webm, ogg-opus, mp4, wav checked by magic bytes; calls
   `STTAdapter.transcribe` → `{text, language, confidence, segments}`), `POST /api/v1/voice/speech`
   (`TTSAdapter.speak` stores audio, short-lived authenticated URL), `GET /api/v1/voice/capabilities`; adapters:
   `demo` (fixture hash → transcript; TTS returns a silent/fixture clip), `browser` marker (labelled "Browser
   fallback", off by default), one vendor adapter interface left unimplemented with a clear `not_configured`
   status; production readiness fails if only the browser fallback is configured; audio purged after 7 days;
   languages en-IN, hi-IN and Hinglish labelled "Untested"; `readback.py` deterministic read-back text (customer,
   quantity with UOM, unit price with currency, total, dates in the user's zone) — required before any confirm or
   approve by voice.
5. Web: push-to-talk (hold or tap-to-toggle, keyboard operable, 44 px), recording indicator + waveform only while
   recording (static meter under reduced motion), mic `NotAllowedError`/`NotFoundError` inline message with focus
   to the text field and voice kept off until retry, Esc/Cancel discards, utterance id created on press, partial
   transcripts greyed and never submittable, editable final transcript that sends once (resend returns the same
   turn), corrections after submission as a new turn with `corrects_turn_id`, optional spoken replies stopped by
   push-to-talk, typing or Stop, **offline drafts** in IndexedDB labelled "Queued draft — not sent" reviewed and
   sent on reconnect with the same id; the UI never shows a commit without a server receipt. Bootstrap
   `features.voice`/`capabilities.voice` true when an STT adapter (demo or vendor) is configured.
6. Scenario C via voice and the voice parts of scenario J (`docs/PLAN.md` acceptance): corrected transcript never
   submits twice; ambiguous customer prompts clarification; interrupt stops speech; mic denial and network loss
   keep text paths usable.

## Migration
`backend/migrations/versions/0021_voice_slice3.py`, `down_revision = "0009_agents_slice1"` (the integrator
reparents it).

## Verification
`npm run check -- --keep-going` 7/7, `npm run test:api`, `npm run api:generate` committed, web gates, e2e specs
for J written and run where the fixture world allows (fake media stream flags are already in
`playwright.config.ts`); `docs/lanes/voice-vision-s3.md` with what was built, tests, decisions, integrator
requests, gate output. Final message: branch tip, counts, unfinished items with reasons.
