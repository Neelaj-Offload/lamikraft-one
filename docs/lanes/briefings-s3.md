# Lane report: briefings-3 (Slice 3, wave 3b)

Branch `lane/s3-briefings` (from the Slice-3 stage-1 merge tip `74c8cd5`, CP4a), worktree `D:\lk-wt\sales`, env slot 6
(API 8060, web 3060, databases `lk_wt6` / `lk_wt6_test` / `lk_wt6_e2e`). Brief: `docs/superpowers/briefs/s3-briefings.md`.
Status: **deliverables 1–5 implemented and tested on Demo** (Demo phraser, Demo WhatsApp provider through the real
signed webhook, labelled silent Demo voice); live phrasing is proven only against a fake provider. The slot database
held the commercial branch's chain, so `lk_wt6` and `lk_wt6_test` were dropped, recreated, migrated to head and
reseeded (`lk seed demo --anchor-date 2026-10-12`) before testing.

## 1. What was built

| # | Deliverable | Where | Notes |
|---|---|---|---|
| 1 | Listen to my day | `briefings/service.pin_script`, `GET /api/v1/briefings/pins/{pin_id}/script` (`briefings_get_pin_script`); web `features/briefing/listen/**` | Pressing Listen pins the version on screen (existing `POST …/pins`, `briefings.pin.started/ended`); the server returns the narration **in the pin's stable order**: an intro (greeting + overview sentence), one segment per pinned item (deterministic lead "Second. Decision." + body), an outro. Bodies are the version's validated phrasing (kind `narration`) or the template body built from the same visible facts; rows no longer visible are skipped without renumbering. Each item segment carries `readback` (title, record label, amounts) for voice confirmations. Web: `createListenSession` state machine (pin → script → speak segment by segment; pause/resume/stop act on the player at once and are recorded with the position via `PATCH …/pins/{id}`; finishing PATCHes `completed`, which acknowledges the heard version with method `voice`; leaving the page stops the pin). `ListenPanel`: play / pause / resume / stop, the words being read as text, Escape stops, every control 44 px on every pointer, `SpeakingWaveform` moves only while speaking (transform-only, Motion) and is a static meter under reduced motion. While listening Today hides the "N updates" pill, never re-sorts (the server serves the pinned version) and the greeting reveal is inactive. |
| 1a | Speech seam | `listen/speech.ts`, `listen/speech-context.tsx` | `SpeechPort {label, speak(text) → clip, stop(), readback(values)}` matches the voice lane's `speak(text) → {url}` / `stop()` contract; `demoSpeech()` returns a labelled ("Demo voice") **silent** clip timed by text length; `createClipPlayer` plays real clips through `Audio` and times silent ones. `SpeechProvider` is where the integrator plugs the voice lane's `useSpeech()` (request 1). |
| 2 | LLM phrasing | `briefings/phrasing.py`, `engine/overview.compose_template`, `engine/recommend.sentence_template`; jobs `briefings.phrase_version`, `briefings.collect_phrasing`; table `briefings_version_text` | Consumes `agents.phrasing` (`phrase`, `submit_batch`, `collect_batch`). The overview sentence, every recommendation sentence ("{label}. {reason}") and every narration body are built as `{{a1}}` templates from the **stored, visible, redacted facts**; substituting the slots gives exactly the deterministic text (property test). The validator (agents) rejects model numerals, new names, dates, dropped amounts, >2 sentences → template text, `ai_status = unavailable`, "Standard wording". A new version enqueues phrasing (deterministic text is served first, `ai_status = not_used`); a precomputed version (trigger `precompute`, version 1) goes through **Message Batches** (submit, collect every minute for up to an hour, then per call). Cache: the agents fact-hash cache; every briefing template code carries the AI mode (`…:demo` / `…:live`) so a Demo echo is never served as live wording. After an outage a later open re-phrases (at most every 5 minutes). `BriefingView.ai_status` = `not_used` / `demo` / `ok` / `unavailable`; `OverviewView.text_source` + `standard_sentence`; `RecommendationView.text` + `text_source`. Phrasing never creates a version. |
| 3 | Delta view, all items, item page | web `src/app/(app)/today/{changes,all,items/[itemId]}/`, `features/briefing/{changes-view,all-items-view,item-page-view}.tsx`; `GET /api/v1/briefings/items/{issue_id}` (`briefings_get_item`) | Routes `today-changes` (`?since=last_ack|yesterday|last_workday`, over the Slice-1 `GET /briefings/delta`; issues grouped by family, each change with its kind, time, actor, before → after and the record link; keyset "Show more"), `today-all` (every section and the snoozed items, filtered by section and kind, in the server's order), `today-item` (the item, its suggestion, the Explain text, reasons, rule version and evidence links; 404 → "not in today's briefing any more"). The Explain dialog links to the item page. |
| 4 | WhatsApp summary + cross-channel acks | `briefings/summary.py`; jobs `briefings.whatsapp_summary`, schedule `briefings.whatsapp_summaries_due` (5 min); `POST /api/v1/briefings/summary` (`briefings_create_summary`); table `briefings_summary_push`; channels `replies.register_button_handler` | One summary per member and work date, built from the same visible, overlaid briefing (overview sentence, at most three titles; finance/costing/price-exception families never travel), sent through the **real channels outbox** (`outbound.queue_message(purpose="daily_briefing")`): an interactive message with "Got it" / "Open Today" inside the 24-hour window, else the approved UTILITY template `lk_daily_briefing`. Gates checked and recorded first (working day, active link with a live session, `daily_briefing` opt-in, window or template), then re-checked by the sender. A skip is recorded with its reason and audited (`briefings.summary.skipped`), and is not final (linking or opting in, then asking again, sends it). "Got it" acknowledges the summarised version as the linked member (method/channel `whatsapp`, idempotent on the wamid); a web acknowledgement marks the summary acknowledged and `channels.ack_sync` voids the armed "Got it"; "Open Today" always answers with a fresh 15-minute review link. Today shows the summary state ("sent at 09:31 (Demo, not delivered to a phone) · Seen on WhatsApp") and a "Send to WhatsApp" button. Scheduled at the member's shift start on working days for members with a linked identity. |
| 5 | Scenario B | tests below; `e2e/scenarios/b-briefing-stability.spec.ts` | |

Migration: `backend/migrations/versions/0035_briefings_slice3.py` (placeholder 0035, `down_revision = "0018"`; distinct
from voice's 0030–0034): `briefings_version_text` (UNIQUE(version_id, language); status ready/pending; ai_status
demo/ok/unavailable; overview, item_texts, narration as JSONB) and `briefings_summary_push` (UNIQUE(company, user,
work_date); queued ⇒ outbox id), both with forced fail-closed RLS. Narration needs no storage of its own: bodies live in
`briefings_version_text.narration`, the pinned order in the existing `briefings_pin.ordinal_map`.

## 2. Scenario B test table

| Scenario B item (PARITY) | Test |
|---|---|
| B1 source change after generation invalidates/refreshes the recommendation, stable id | existing `integration/briefings/test_source_change_invalidates_recommendation.py::test_stable_issue_id_and_stale_recommendation`; phrasing of the new version re-phrases only changed texts: `test_listen_and_phrasing.py::test_live_phrasing_rewords_without_changing_facts_and_caches_by_fact_hash` |
| B3 no reorder during an active spoken briefing | `integration/briefings/test_voice_pin_no_reorder.py::test_pinned_order_and_ordinal_resolution` (extended: the narration keeps its order and ordinals across a new version); `test_listen_and_phrasing.py::test_listen_script_keeps_the_pinned_order_and_reads_back_values` (pause/resume/complete → voice ack of the heard version); web `listen/listen.test.tsx`; e2e `scenarios/b-briefing-stability.spec.ts` (rows and the pill unchanged while a new version lands during a pin; Escape stops; reduced motion → static meter) |
| B4 snoozed/handled survives reload and channel switching | `integration/briefings/test_snooze_persists_across_reload_and_whatsapp.py::test_snooze_reload_and_whatsapp_sync` (extended: the summary leaves the snoozed item out; "Got it" on WhatsApp shows as seen on the web; second press refused; idempotent per day), `::test_web_acknowledgement_marks_the_summary_and_voids_its_buttons`, `::test_summary_needs_a_link_opt_in_and_a_working_day`, `::test_scheduled_summary_runs_at_shift_start_for_linked_members` |
| B5 midnight / weekend / shift boundary | existing `test_versions_and_actions.py::test_midnight_rollover`, `::test_sunday_is_non_working`; new `test_listen_and_phrasing.py::test_rollover_ends_yesterdays_listening_and_phrases_the_new_day`; Sunday and shift-start rules of the summary in the B4 tests above |
| B6 AI outage behaves explicitly | `integration/briefings/test_ai_outage_template_text.py::test_standard_wording_label` (extended: circuit open → `unavailable`, template overview/recommendations/narration, no version written); `test_listen_and_phrasing.py::test_validator_rejection_shows_standard_wording`, `::test_listen_after_an_outage_speaks_the_template_wording`, `::test_demo_phrasing_runs_the_validated_path_and_is_labelled_demo`, `::test_pre_shift_batch_phrases_a_precomputed_briefing` |

Unit: `tests/unit/briefings/test_phrasing_templates.py` (overview template property over 150 fact combinations, every
recommendation rule, narration body, validator rejections, sentence case). Contract: the forced-RLS check now counts
the two new tables.

## 3. Decisions

- **Phrasing is a background job, never a request-path call.** The response always carries the deterministic text
  first (`ai_status = not_used` until phrased), so an outage can never slow or block Today (design §6 step 15).
- **The fact hash is keyed by AI mode too** (`template_code` suffix `:demo`/`:live`): the agents cache is shared by
  every mode, and the Demo phraser's echo would otherwise be served as validated live wording after go-live.
- **Count facts are lower case in templates** and `sentence_case` restores the capital at sentence starts, so the
  model may move a count inside a sentence without producing "In short: Two …".
- **Rows show model wording only when phrased live** (`ai_status = ok`); Demo wording equals the template text, so
  rows keep the deterministic label in demo and no visible text changes for Slice-1 users.
- **`ai_status` follows the overview**: `unavailable` whenever the overview fell back to the template (outage,
  refusal or validator rejection), which is when the header's "Standard wording" badge shows.
- **A summary skip is not final** for the day; a queued summary is (one per member and work date). Quiet hours and
  personal summary times are not modelled (no prefs table yet): the push goes at shift start.
- **Narration bodies are per version, the order per pin**: the version text stores one body per issue; the pin's
  ordinal map gives the order and the spoken ordinal words, so the same phrasing serves "initial" and "full" pins.
- **"Got it" needs a channels hook**: channels had no way for another module to own a button kind; a small registry
  (`register_button_handler(kind, fn)`) was added to `channels/whatsapp/replies.py` (shared-file touch) and briefings
  registers `briefing_ack` in `on_load`.

## 4. Integrator requests

1. **TTS wiring (voice lane):** wrap the app (or Today) in `SpeechProvider` with an adapter over the voice lane's
   `useSpeech()` (`speak(text) → {url}` → `{url, durationMs, silent: false}`, `stop()`, `readback(values)`); until
   then Listen uses the labelled silent Demo voice. Optionally feed real audio levels to `WaveformBars`.
2. **Read-back before a voice confirmation:** every item segment carries `readback` values; the voice lane's
   confirm-by-voice flow (push-to-talk "approve the second item") should speak `speech.readback(segment.readback)`
   before confirming. This lane has no voice commands, so nothing here confirms by voice.
3. Renumber `0035_briefings_slice3.py` onto the chain after `0018` (and after voice's revisions); no other lane
   touches the two tables.
4. Shared-file touches (small, additive): `channels/whatsapp/replies.py` (button-handler registry),
   `tests/contract/tasks/test_work_contracts.py` (table count 18 → 20), `apps/web/src/lib/routes.ts` (3 routes),
   `apps/web/src/lib/api/query-keys.ts` (`briefings.delta`, `briefings.item`), `apps/web/src/lib/test-support/briefing.ts`
   (`standard_sentence`), `backend/openapi.json` + `schema.d.ts` (regenerate after the merge).
5. PARITY_MATRIX: SCN-B3, SCN-B4, SCN-B6 can move to implemented with the tests in section 2.
6. Channels (optional): template quick replies arrive as `button` messages, which inbound does not handle yet, so a
   template summary (window closed) carries no "Got it"; the member acknowledges on the web.
7. Agents (optional): the phrasing cache could key by provider mode itself; briefings already tags its template codes.

## 5. Not done / limits

- No live Claude call and no real TTS: live phrasing is proven against a fake provider (call log rows, cache, batch,
  validator); Listen is proven with the silent Demo voice.
- No LLM Explain elaboration (design §11 item 2): Explain stays deterministic (not in this brief's deliverables).
- Quiet hours and personal summary times (`briefings_user_prefs`) are not built; the summary goes at shift start.
- On-demand "What should I handle today?" over WhatsApp is the agents' `get_daily_briefing` path, unchanged here.

## 6. Gate output (2026-11-04, slot 6)

`npm run check -- --keep-going` on the final tree — **7/7 PASS**:

```
backend: ruff check              PASS
backend: pytest unit + contract  PASS   638 passed
alembic heads == 1               PASS
api:check                        PASS   backend/openapi.json matches the app (267 paths)
web: lint                        PASS
web: typecheck                   PASS
web: vitest                      PASS   57 files, 640 tests
```

`npm run test:api` (full backend suite, LK_ENV=test) at 11e6433: **1,495 passed, 7 skipped, 0 failed** (52 min; the 7
skips are `test_golden_live`, live only). After it only web files changed (the Listen toggle and stop ordering).

`npm run test:e2e -- e2e/scenarios/b-briefing-stability.spec.ts --project=desktop` (production build with
`LK_NEXT_BUILD_CPUS=2 NODE_OPTIONS=--max-old-space-size=2048`, API + worker + `next start` on the e2e ports):
**2 passed**. Two defects found by it and fixed: Pause and Resume were separate buttons, so keyboard focus was lost
on toggle and Escape no longer reached the panel (now one toggle element); a stop refreshed Today before the pin's
PATCH had committed, so the pinned version came back (the refresh now waits for the pin to end). The full e2e suite
was not run in this lane (the stage-2 integrator runs it).

`npm run api:generate` — committed (`backend/openapi.json`, `apps/web/src/lib/api/schema.d.ts`). No dev server was
left running.
