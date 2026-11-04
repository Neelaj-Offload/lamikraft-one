# Lane report: Slice-3 merge, stage 2 (integrator)

Branch `lane/s3-merge` (continuing from stage 1 = Checkpoint 4a, `74c8cd5`), worktree `D:\lk-wt\integ`, env slot 8.
Stage 1 is `docs/lanes/merge-s3a.md`. Stage 2 merges `lane/s3-voice-vision` (stage 2a) and `lane/s3-briefings`
(stage 2b) and declares Checkpoint 4.

**Status: stage 2a done; stage 2b (briefings) pending.**

## Steps

| # | Step | Commit | Result |
|---|---|---|---|
| 1 | Merge `lane/s3-voice-vision` d028019 (report `voice-vision-s3.md`, branched from CP3 10c8514) | `fa19410` | migration 0030 → `0019_voice_vision_slice3` (down 0018); conflicts below |
| 2 | Voice/vision integrator requests (lane report section 4) | `6cdf822` | new `0020_slice3_stage2_cross_lane_links`; ADR-061; api:generate 279 paths; targeted pytest 117 + 6 passed, channels integration 52 passed; check 7/7 |

## Migration chain (so far)

`0015_slice2_cross_lane_links` (main) → `0016_agents_slice3` → `0017_channels_slice3` → `0018_slice3_cross_lane_links`
→ `0019_voice_vision_slice3` (lane placeholder 0030; `corrects_turn_id` removed from `voice_utterance`, it moved to the
turn) → `0020_slice3_stage2_cross_lane_links` (integrator: `agents_turn.corrects_turn_id`, `transcript_meta`,
`vision_request_id`). `alembic heads` = 1; `migrate --revision 0018` → `migrate` (head) round trip on `lk_wt8`.
`alembic check` reports only the lane's expression index `uq_vision_capture_conversation_sha`, which by design lives in
the migration only (ADR-061, consequences). The briefings lane's placeholders reparent after `0020`.

## Conflict decisions (stage 2a)

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

## Defects found and fixed in the merge (stage 2a)

1. `transcript_meta` written as JSON `null` (SQLAlchemy JSONB default) broke the object CHECK on every non-voice turn —
   `JSONB(none_as_null=True)`.
2. Vision call-log rows had no trace id for requests without an ingress correlation id — the agents
   `ingress_correlation_id` now supplies a UUIDv7 as for orchestrator rows.

## Gates

- Stage 2a: check 7/7 on the tree of `6cdf822` (ruff; pytest unit + contract 676 passed; heads 1; api:check; lint;
  typecheck; vitest 58 files / 645 tests). Full `test:api` started on `6cdf822` (report commit `ab07d4e` adds no
  code): **1556 passed, 7 skipped (`test_golden_live`), 0 failed**, 2 known warnings (google-genai
  DeprecationWarning, the PIL decompression-bomb test), 58 min 55 s. The briefings merge was started in the worktree
  after collection (at about 60 %); the final-tree run under "Gates (Checkpoint 4)" is the authoritative one.
