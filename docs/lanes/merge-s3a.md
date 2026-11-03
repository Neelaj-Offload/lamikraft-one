# Lane report: Slice-3 merge, stage 1 (integrator)

Branch `lane/s3-merge` (from `main` 10c8514 = Checkpoint 3; `main` c488990 merged in), worktree `D:\lk-wt\integ`,
env slot 8. Status: **DONE_WITH_CONCERNS** — every gate green on the final tip; concerns are under "Open items".
This is stage 1 of the two-stage Slice-3 integration (completion program, "CP3 reached"): an **intermediate state
(Checkpoint 4a)**, not Checkpoint 4. Stage 2 (voice/vision, briefings) is a later integrator run on this branch.

## Steps

| # | Step | Commit | Result |
|---|---|---|---|
| 1 | Merge `lane/s3-agents` e0f6065 (report `agents-s3.md`) | `dc061f3` | migration 0020 → `0016_agents_slice3` (down 0015); ADR-052 → ADR-059; unions below; api:generate 250 paths; targeted pytest (unit, contract, `integration/agents`, evals) all passed, 7 live-only skips |
| 2 | Merge `lane/s3-whatsapp` 9e78698 (report `whatsapp-s3.md`) | `1366164` | migration 0022 → `0017_channels_slice3` (down 0016); lane contract test names the new revision; unions below |
| 3 | Integrator requests: `input_mode` wiring, step-up, SSE and WhatsApp e2e, evidence spec | `4e0288b` | new `0018_slice3_cross_lane_links`; api:generate 264 paths; channels + agents API tests green after the step-up fix |
| 4 | check run 1 → fixes | `ca7cb96` | ruff import order (my edit), two e2e typecheck errors (`noUncheckedIndexedAccess`) |
| 5 | Merge `main` (docs-only c488990) | `b63e4c4` | — |
| 6 | Full `test:api` on ca7cb96 | — | **1479 passed**, 7 skipped, 0 failed (38 min 45 s) |
| 7 | e2e run 1, axe sweep `/r/[token]`, ADR-060 | `28d84f3` | 199 passed / 1 failed (my spec's locator); fixes below |
| 8 | Demo voice-note defect + spec fixes | `8228d17` | targeted e2e 10/10; channels suite 100 passed |
| 9 | Final e2e, evidence, check, docs | docs commit | see "Gates" |

## Migration chain

`0015_slice2_cross_lane_links` (main) → `0016_agents_slice3` (lane placeholder 0020) → `0017_channels_slice3` (lane
placeholder 0022) → `0018_slice3_cross_lane_links` (integrator: `agents_turn.input_mode` String(20) NOT NULL default
`text`, CHECK `text|voice|wa_text|wa_voice|card_action`). Both lane files were renamed and their revision,
`Revises:` and `down_revision` rewritten; nothing on `main` was touched. `alembic heads` = 1; `downgrade 0015` →
`upgrade head` and `alembic check` (no pending operations) verified on `lk_wt8`. Stage-2 lanes (`0021_voice_slice3`
and the briefings placeholder) reparent after `0018`.

## Shared-file unions and conflict decisions

- `tests/contract/system/test_route_authz.py`: `PATH_EXCEPTIONS` gains `receipts`/`traces` → agents and
  `review-links` → channels; the `PUT /org/settings/{key}` matrix lists `agents.ai_routing.manage` beside platform-2's
  `identity.mfa.manage`.
- `apps/web/src/lib/routes.ts`: `settings-ai`, `settings-ai-trace` (auto-merged) and `settings-whatsapp`, `review-link`
  appended after the Slice-2 routes; `query-keys.ts`: agents keys (receipt, trace, aiStatus, aiUsage) + `channels`
  keys; invalidations `agents.receipt_undone`, `agents.ai_verified`, `org.setting_changed` → AI status,
  `channels.changed` beside the Slice-2 entries.
- Settings hub: AI and WhatsApp hints added to main's Slice-2 hint list; `messages/settings.ts` union.
- `.env.example` / `config.py`: WhatsApp's six live settings plus `_APP_SECRET_PREVIOUS`, `_API_VERSION`,
  `_LIVE_OUTBOUND`, `_DEV_ALLOWLIST` (auto-merged); documented `NEXT_PUBLIC_LK_ASSISTANT_SSE` (commented).
- `docs/DECISIONS.md`: the agents lane's ADR-052 (SSE) collided with platform-2's ADR-052 → **ADR-059**; code comments
  in `features/assistant/*` renumbered. The lane report keeps its original number.
- `openapi.json` / `schema.d.ts`: taken from HEAD at each conflict and regenerated (250 → 264 paths).

## Integrator requests applied in the merge

1. **`input_mode` to `create_turn` (WhatsApp request 3).** Neither lane had the field on the agents turn (agents-s3
   kept the Slice-1 `TurnCreate`). Added `TurnInputMode` to `TurnCreate`/`TurnOut` and `agents_turn.input_mode`
   (migration 0018); `wa_*` modes only in a WhatsApp conversation (422 `input_mode_channel`);
   `channels/whatsapp/replies.submit_turn` passes the message's recorded mode. Tests:
   `integration/agents/test_slice3_api.py::test_turn_input_mode_defaults_to_text_and_whatsapp_modes_need_a_whatsapp_conversation`,
   turn assertions in `integration/channels/test_scenario_c_whatsapp.py` (text → `wa_text`, voice note → `wa_voice`).
   ADR-060. The voice lane should send `input_mode: "voice"`.
2. **Platform-2 step-up meets channels.** `channels.account.manage` is MFA + RA in the frozen catalogue; platform-2's
   `require_step_up` now enforces the MFA flag, so three channels tests failed with `mfa_required`. The channels test
   client presents an MFA session by default (`x-test-mfa`), and `test_verify_needs_a_recent_sign_in_and_the_admin_key`
   now also asserts `mfa_required` without one. The web admin cards need the step-up dialog (open item).
3. **SSE proven in the browser** (agents request; ADR-059 updated). `e2e/scenario-c.spec.ts` records the page's run
   requests: on the production build, desktop and phone, the run arrived over `/agents/runs/{id}/events` (200,
   `text/event-stream`) and no polling `GET /agents/runs/{id}` was made before the draft card rendered. **Result: SSE
   is proven; it stays the default; `NEXT_PUBLIC_LK_ASSISTANT_SSE=0` remains only as a kill switch.**
4. **WhatsApp scenario K/C e2e** (none existed): `e2e/scenarios/k-whatsapp.spec.ts` through the Demo simulator — link
   with a one-time code via the signed webhook, scenario C by text (figures, "Review quote" → bound `/r/<token>` link →
   quote workspace), a used button refused, a demo voice note transcribed and drafted, STOP/START. Desktop only (the
   demo number is per user).
5. Axe sweep covers `/r/[token]` in its invalid-link state (a valid link redirects at once).
6. Agents shared-file touches (readiness `checks.ai`, routes, query keys, hub hint) merged as written.

## Defects found and fixed in the merge

1. **Demo voice notes never worked across processes** (found by the new e2e): the simulator registered fixture audio in
   the API process's memory, but the worker downloads it, so every voice note in dev or e2e answered "I could not
   download that voice note (the link expired)". The single-process pytest suite hid it. `demo_provider.lookup_media`
   falls back to the fixture registry by the content-derived media id; unit test
   `test_fixture_voice_notes_resolve_in_a_process_that_did_not_register_them`.
2. Channels admin endpoints vs platform-2 MFA step-up (above).
3. My own spec mistakes on the first run: linked numbers are a list (not a table), WhatsApp totals are plain
   "EUR 5,760.00", the token regex ran into the bubble's timestamp, 30 s per test was too short.

## Lane requests: applied / deferred

| Request | Status |
|---|---|
| Agents 1: reparent 0020 | applied (0016) |
| Agents 2: renumber ADR-052 | applied (ADR-059) |
| Agents 3: shared-file touches; regenerate API | applied (264 paths) |
| Agents 4: briefings consume `agents.phrasing`; vision uses `routing` / `quotas` | in place for stage 2 (not this run) |
| Agents 5: Next 16.4.0 nudge | not applicable (16.4.4 installed; no agent-addressed tooling text acted on) |
| Agents 6: `(company_id, correlation_id)` indexes | deferred — demo volume [platform] |
| Agents: prove SSE in e2e | applied — proven |
| WhatsApp 1: renumber 0022 | applied (0017) |
| WhatsApp 2: shared files (`PATH_EXCEPTIONS`, routes, query keys, hub, env/config) | applied |
| WhatsApp 3: `input_mode` → `create_turn` | applied (0018, ADR-060) |
| WhatsApp 3: `channels_message` rows in the trace timeline | deferred — optional, needs a trace section design [agents, channels] |
| WhatsApp 4: voice lane `register_transcriber` | for stage 2 (voice lane) |
| WhatsApp 5: who may hold `channels.identity.manage` | owner decision (unchanged: no template) |
| WhatsApp 6: briefings push through `outbound.queue_message` | for stage 2 (briefings lane) |
| WhatsApp 7: `sales.quote_delivery_status` | deferred [sales] |
| WhatsApp 8: `tasks.rules` family for delivery unknown | deferred [tasks] |
| WhatsApp 9: `channels/crypto.py` → `app/platform` | deferred [platform] |
| WhatsApp 10: `node_modules` | not needed in this worktree (16.4.4, Fraunces present) |

## Gates (final tip `8228d17` + docs; the docs commit adds no code)

- `npm run test:api` on `ca7cb96`: **1479 passed**, 7 skipped (`test_golden_live`, live-only), 0 failed, 1 warning
  (PIL decompression-bomb test), 38 min 45 s. After it only `channels/whatsapp/demo_provider.py`, a channels unit test
  and e2e specs changed; the whole channels suite was rerun on `8228d17`: **100 passed**.
- `npm run check -- --keep-going` on `8228d17`: **7/7 PASS** — ruff; pytest unit + contract 633 passed; alembic heads
  == 1; api:check; web lint; web typecheck; web vitest 56 files / 628 tests.
- `npm run test:e2e -- --workers=1` (production build from run 1 with `LK_NEXT_BUILD_CPUS=2`,
  `NODE_OPTIONS=--max-old-space-size=2048`; web sources unchanged since; own database `lk_wt8_e2e`; demo world
  `--slice 2`): **203 passed, 0 failed**, 436 skipped (project-scoped and opt-in), 9.7 min. Includes scenario C with
  the SSE assertion on desktop and phone, `scenarios/k-whatsapp.spec.ts` 4/4, and the axe sweep in light and dark over
  every manifest route incl. `/settings/ai`, `/settings/whatsapp`, `/r/[token]`.
- Evidence: `docs/evidence/checkpoint-4a/` (24 PNGs, README).
- On the way: e2e run 1 199/1 (spec locator), targeted re-runs 7/1, 7/1, 8/1, 10/0. Free memory stayed around
  0.6 GB during `test:api`; no run died.

## Docs

`docs/PARITY_MATRIX.md` (Checkpoint 4a note; SCN-K1/K2/K3 and SCN-C5 implemented, SCN-C4 and SCN-J2 in progress),
`docs/BUILD_STATE.md` (header, §2, §7 rows, §8, new §12 marked intermediate), `docs/DECISIONS.md` (ADR-059 with the
e2e proof, ADR-060), `docs/evidence/checkpoint-4a/README.md`.

## Open items (owners)

See `docs/BUILD_STATE.md` section 12. Created or surfaced by this merge: WhatsApp admin step-up dialog [channels web];
`channels.identity.manage` template grant [owner]; trace timeline with channel messages [agents, channels];
correlation-id indexes [platform]; delivery-status consumer and tasks rule [sales, tasks]; "Demo • Demo" provider
label on Settings → AI [agents web]; no live Anthropic or Meta call made [owner, credentials].
