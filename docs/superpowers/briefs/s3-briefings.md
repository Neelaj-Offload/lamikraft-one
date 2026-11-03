# Lane brief: Slice 3 — briefings-3 (Listen to my day, phrasing, delta view, WhatsApp summary, acknowledgements)

Branch `lane/s3-briefings` from `main`. Module owner: `backend/app/modules/briefings/**` (extend),
`apps/web/src/features/briefing/**` (extend), new pages `src/app/(app)/today/{all,changes,items/[itemId]}/`,
copy additions to `src/messages/briefing.ts`. Never push; small named commits; never two test suites at once;
never leave dev servers running.

## Contracts (read first)
1. `docs/design/source/briefing.md` (the briefing design: sections on Listen, phrasing, delta, pins, channels)
   and `docs/lanes/work.md` (what Slice 1 built: deterministic engine, versions, acks, pins, delta API,
   fallback). `backend/app/modules/briefings/**` is the code you extend; `engine/overview.py` composes the
   template sentence with `template_code`/`template_version`.
2. `docs/architecture/ai-routing.md` §2 (phrasing row), §6 phrasing validator, §7 phrasing cache and Message
   Batches; the agents lane delivers `agents/phrasing.py` with a `PhrasingProvider` protocol (Demo and Anthropic);
   until it merges, code against the protocol in `backend/app/modules/agents/providers/base.py` style and ship a
   deterministic Demo implementation inside briefings behind the same protocol so your tests never need the
   other lane.
3. `docs/architecture/motion-system.md` §2 "Briefing updates" and "Voice recording / speaking waveform", §3
   (never reorder during an active spoken briefing); `events.md` §3.7 (`briefings.pin.started/ended`,
   `briefings.briefing.acknowledged` → `channels.ack_sync`); `permissions.md`; `docs/PLAN.md` Slice 3
   "Briefings-3" and scenario B; `apps/web/src/features/briefing/*` (Today view, header, sections, rows, dialogs,
   model, refresh) and the `GreetingReveal` contract (`docs/superpowers/specs/2026-11-02-checkpoint-2-build-guide.md`
   §4: the reveal never plays during a pin).
4. Voice playback: the voice lane delivers `POST /api/v1/voice/speech` and a web `useSpeech()` hook under
   `apps/web/src/lib/voice/`; code against that contract (`speak(text) → {url}`; `stop()`), with a Demo that
   produces a labelled silent clip, so Listen works in this lane's tests without the voice lane.

## Deliverables
1. **Listen to my day**: a server-built narration script per briefing version (deterministic text from the
   facts, then phrased by the phrasing provider under the validator with the template fallback), stable pins
   (`briefings.pin.started/ended`) so the list never re-sorts while a pin is active (existing pin rules), play /
   pause / resume / stop with a waveform only while speaking (static meter under reduced motion), keyboard
   operable, 44 px targets, read-back of consequential values before any confirm by voice (through the voice
   lane's `readback` contract; stub locally).
2. **LLM phrasing** of the overview sentence and item recommendations with the validator; on failure the template
   text labelled "Standard wording" (the Today header already shows the badge); phrasing cache keyed by fact hash
   + template version + language; pre-shift batch phrasing job using the provider's batch path (Demo:
   deterministic); `ai_status` on the briefing view already carries demo/unavailable.
3. **Delta view** `/today/changes?since=last_ack|yesterday` (route `today-changes`): source-linked list of what
   changed since the cursor (the Slice-1 delta API exists: `GET /briefings/delta`), grouped by family, each row
   with the record link and the change kind; `/today/all` (route `today-all`): every section with filters;
   `/today/items/[itemId]` (route `today-item`): the item's explanation and evidence (the Explain dialog's
   content as a page, deep-linkable).
4. **WhatsApp summary**: a daily summary message built from the briefing facts, sent only with opt-in
   (`channel_consent` purpose `daily_briefing`) through the channels lane's outbox contract (`enqueue_outbound
   (identity, kind="template"|"session", payload)`); code against a small protocol with a Demo implementation
   that records what would be sent; the integrator wires the real outbox. **Cross-channel acknowledgements**:
   `channels.ack_sync` consumer so an acknowledgement on the web marks the WhatsApp summary read and vice versa.
5. **Scenario B** (`docs/PLAN.md`): a source change after generation invalidates/refreshes the recommendation
   with a stable id and no reorder during an active spoken briefing; snoozed/handled state survives reload and
   channel switching; midnight/weekend/shift boundary and AI outage behave explicitly (the engine's existing
   tests cover rollover; add the Listen and phrasing cases).

## Migration
`backend/migrations/versions/0023_briefings_slice3.py`, `down_revision = "0009_agents_slice1"` (the integrator
reparents it), only if new columns are needed (narration script storage, phrasing cache).

## Verification
`npm run check -- --keep-going` 7/7, `npm run test:api`, `npm run api:generate` committed, web gates, the
`e2e/scenarios/b-briefing-stability.spec.ts` named in motion-system §8 written and run; `docs/lanes/briefings-s3.md`
(built, scenario B test table, decisions, integrator requests, gate output). Final message: branch tip, counts,
unfinished items with reasons.
