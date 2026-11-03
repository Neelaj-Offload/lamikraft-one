# Lane report: WhatsApp channel (Slice 3, wave 3a)

Branch `lane/s3-whatsapp` (from `main` c94a13d), worktree `D:\lk-wt\catalogue`, env slot 3 (API 8030, web 3030,
databases `lk_wt3` / `lk_wt3_test`). Brief: `docs/superpowers/briefs/s3-whatsapp.md`. Status: **deliverables 1–13
implemented and tested on the Demo provider through the real signed webhook route, and in live mode against a fake
Graph API transport. No call to Meta was made (no credentials).**

## 1. What was built

| # | Deliverable | Where | Notes |
|---|---|---|---|
| 1 | Tables + migration | `backend/app/modules/channels/models.py`, `backend/migrations/versions/0022_channels_slice3.py` | 14 tables (`channels_` prefix): account, identity, enrolment, session, webhook_inbox, webhook_rejection, inbound_event, message, message_status_event, outbox_message, consent, template, review_link, action_ref. Forced fail-closed RLS on the 12 tenant tables; `webhook_inbox` / `webhook_rejection` are RLS-exempt (no company at ingress; the worker resolves it from `phone_number_id`). Append-only: `message_status_event`, `consent`. `channels_message.body_encrypted` = AES-256-GCM with `LK_DATA_ENCRYPTION_KEYS` (`channels/crypto.py`, kid-prefixed, rotation-ready). Uniqueness as design §4 (partial uniques on BSUID / wa_id / provider message id; event key per account; status event per (account, wamid, status, ts); outbox idempotency key per company; template (account, name, language); token hash; nonce). |
| 2 | Webhook | `channels/webhook.py` (`/api/v1/webhooks/whatsapp`, authz kind `webhook`: CSRF-exempt, no session) | GET: `hub.mode=subscribe` + constant-time verify token → 200 + challenge, `handshake_ok_at` recorded; else 403. POST: streamed raw body ≤ 4 MB (413), `X-Hub-Signature-256` HMAC-SHA256 over the exact bytes with `compare_digest` against current **and** previous secret (`LK_WHATSAPP_APP_SECRET_PREVIOUS`); missing/invalid → 403 + `webhook_rejection` (reason, addr HMAC, body hash; never the payload). Valid → inbox row + `wa.inbox.process` job in one short transaction → 200; DB failure → 500. Rate-limited per remote address through identity's Postgres counter (20 000 signed / 100 rejected per 10 min). |
| 3 | Processing worker | `whatsapp/inbound.py`, `whatsapp/payloads.py` | Typed Cloud API payloads (`messages`, `message_template_status_update`); fan-out to `inbound_event` (wamid; wamid:status:ts; tpl:id:event:time) with ON CONFLICT DO NOTHING → replay = no-op. Unknown `phone_number_id` → inbox `ignored`; groups ignored. Each event in its own transaction, in provider-ts order, serial per sender (advisory lock); `late` flagged; `last_inbound_at` keeps the max. Identity: BSUID first, then wa_id (learns BSUID); `user_id_update` / `user_changed_user_id` / number changes suspend. Text → agents turn as the linked user; audio → media lookup (5-minute URL, bearer), ≤ 10 MB, SHA-256 checked, STT through `whatsapp/stt.py` (a registration seam; Demo transcriber by fixture SHA-256) → "I heard: …" → the same turn (`wa_voice`); image/document → stored as the user's restricted file, message `provenance=external`; interactive replies → action refs, no model; other types → polite reply. Unknown / revoked / suspended senders → generic "not linked" (at most hourly, no data, no tools). Media fetches and turn creation run **after** the processing transaction commits (no transaction held across a network call). |
| 4 | Enrolment and sessions | `whatsapp/enrolment.py`, `whatsapp/identity.py`, `POST /api/v1/channels/whatsapp/enrolments` | Recent sign-in required in every mode except the explicit demo mode (fail closed; see §4a) (`org.stepup.require_recent_auth` on the RA flag of `channels.identity.manage`); each code records the mode it was issued under. 8-digit code, keyed HMAC stored, 10 minutes, a new code cancels the previous; wa.me link prefilled `LINK <code>`; the code is never stored in the message log (`LINK ••••••••`). Wrong codes: 5 per sender per 10-minute window, then "Too many wrong codes". A match activates the employee identity, starts a session (7 days idle / 30 absolute) and records `assistant_replies` opted-in. A reassigned number revokes the previous holder (sessions + armed buttons). Revocation by the user/admin, `identity.membership.deactivated` and `identity.user.credentials_changed` (reset kinds) revoke sessions and void armed action refs. |
| 5 | Outbox sender | `whatsapp/outbound.py` (`wa.outbox.send`, max_attempts 1) | Row written in the cause's transaction; claim `FOR UPDATE SKIP LOCKED`; gates: identity active (system notices allowed to any sender), consent, 24-hour window or approved template (paused/disabled/rejected/pending → `blocked` with `template_<status>`; briefing pushes outside the window need a UTILITY template), live-outbound flag and the development allowlist (outside production every live recipient must be listed). `POST /{api_version}/{phone_number_id}/messages` with `biz_opaque_callback_data` = outbox id; commit `sending` → call with no transaction → record: 2xx → `accepted` + wamid; timeout/reset/5xx/2xx-without-id → `unknown` (never resent); 429 / not-processed codes → `pending` with business-time backoff (the sweep re-enqueues); 4xx validation → `failed`; policy codes → `blocked`. Documents: the bound quote revision is re-rendered, hash-checked and uploaded before the send. |
| 6 | Reconciliation | `whatsapp/reconcile.py` (`wa.outbox.reconcile`, every 60 s) | Match by wamid or `biz_opaque_callback_data` (status before the send response), else `pending_match` (retried; ignored after 1 h). Rank accepted < sent < delivered < read < played; `failed` only below delivered; every event kept. Provider evidence resolves an `unknown` outbox to `accepted`. `unknown` with no status after 15 minutes → `escalated`, `channels.message.delivery_unknown`, and an Inbox task for the owner (written after commit in the owner's own context). "Resend as new message": `POST …/outbox/{id}/resolve {action: resend, confirm: true}` → a new row with a new idempotency key; the old one is closed. Also purges raw inbox payloads after 30 days. |
| 7 | Consent | `whatsapp/consent.py`, `PUT /api/v1/channels/whatsapp/consents` | Append-only log; STOP / UNSUBSCRIBE / "band karo" / "बंद करो" opt out of proactive purposes (daily briefing, marketing) with a confirmation; START opts back in; replies to the user's own messages stay allowed. Proactive purposes need `opted_in`. |
| 8 | Customers and vendors | `inbound._handle_customer`, `tools.py`, `send_approval.py` | A sender matching a party contact phone becomes a `customer` identity (separate from employees); inbound → `sales.service.record_customer_message` (channel `whatsapp`, owner's Inbox, `origin_ref=channels.message:<id>`), stored `external`; **no AI reply**. `prepare_quote_send` (registered through the manifest `tools` list) binds recipient identity, server-built text and the issued revision's PDF SHA-256 into a `channels.message.send` proposal (2-day expiry); only another person's approval (`channels.message.send`, must be able to read the quote) queues the document; a revised quote or changed PDF → 409 `document_changed`. |
| 9 | Review links | `channels/review_links.py`, `POST /api/v1/review-links/{token}/resolve`, web `/r/[token]` | 32-byte token (SHA-256 stored), 15 minutes, single use for `decide` (view: 20 uses), bound user (another user → 403 `review_link_wrong_user`), 410 `review_link_expired` / `review_link_used`; the page resolves once (Strict-Mode safe) and `router.replace`s to the canonical screen through `safeAppPath`. WhatsApp "Review quote" / approve / reject buttons answer with a fresh link — decisions happen on the web. |
| 10 | Demo provider | `whatsapp/demo_provider.py`, `POST …/demo/inbound`, `GET …/demo/thread` | Records sends (`wamid.demo.*`), then posts **signed** sent/delivered/read statuses through `webhook.ingest_signed` — the function the route calls (signature check, inbox, worker, reconciliation all real). Demo accounts: phone number id `demo-<company>`, WABA `demo-waba-<company>`, display `+910000000000`; replies prefixed "Demo:", messages flagged `simulated`; UI label "Demo — not connected". The simulator sends from a per-user demo number (`99…`) through the same ingest. Fixture voice notes and templates are in the provider. |
| 11 | Live mode | `whatsapp/cloud_api.py`, `whatsapp/accounts.py`, config | Required settings: `LK_WHATSAPP_{PHONE_NUMBER_ID, WABA_ID, ACCESS_TOKEN, APP_SECRET, VERIFY_TOKEN, API_VERSION}`; any missing → `not_configured` (labelled, listed for admins). "Connected" only when Graph check (`GET /{v}/{pnid}`), handshake and a signed event have all succeeded → `channels.account.verified`. Admin endpoints: account (+ verify, recent sign-in), messages `state=unknown|failed|blocked|escalated`, outbox resolve, templates list + sync. The `channels.whatsapp` integration definition gets its verification through `register_integration` in `on_load` (no edit to the platform file). |
| 12 | Web | `apps/web/src/features/channels/**`, `src/app/(app)/settings/whatsapp/page.tsx`, `src/app/(app)/r/[token]/page.tsx`, `src/messages/channels.ts` | Settings › WhatsApp (route `settings-whatsapp`, context tab): honest status line; "Link my WhatsApp" card (code shown once, grouped, expiry, wa.me button in live mode); linked numbers with consent switches and Unlink (confirmed); the simulator (demo only, polls every 2 s, reply buttons, demo voice notes); admin: account checks + Run checks, messages needing attention with Resend (confirmed) / Close, templates + Sync. Built on `PageHeader` / `AreaNav` / `SectionCard` / `DataTable`. Typed client from the regenerated schema (no `requestUntyped`). |
| 13 | Scenario K / C tests | `backend/tests/{unit,integration,contract}/channels/**` | §2 below. |

Error-code table: `backend/app/modules/channels/error_codes.py`, **Graph API v26.0 (introduced 2026-07-29; v25.0
2026-02-18, v24.0 2025-10-08), checked against developers.facebook.com on 2026-11-03** (`GRAPH_API_VERSION`,
`ERROR_TABLE_CHECKED`). Meta notes that error titles are being deprecated; classification uses `code` only.

## 2. Scenario K (and C) test table

| PLAN scenario K item | Test |
|---|---|
| signature rejection (missing, wrong, re-serialised body) + rejection row without payload | `integration/channels/test_webhook.py::test_k_signature_rejection_writes_a_rejection_row_without_the_payload` |
| secret rotation (previous secret accepted) | `test_webhook.py::test_previous_secret_is_accepted_during_rotation`; unit `test_signature_is_byte_exact_and_accepts_either_secret` |
| replay / duplicate delivery → one business effect | `test_webhook.py::test_k_replay_of_a_delivery_has_one_business_effect` |
| out-of-order status; failed never overrides delivered | `test_scenario_k.py::test_k_out_of_order_status_never_lowers_the_rank_and_failed_does_not_override_delivered`, `::test_k_failed_applies_below_delivered` |
| status before the send response | `test_scenario_k.py::test_status_before_the_send_response_matches_by_biz_opaque`, `::test_unmatched_status_is_pending_match_until_the_message_exists` |
| employee unlink | `test_scenario_k.py::test_k_employee_unlink_revokes_the_session_and_voids_armed_buttons`, `::test_deactivation_revokes_through_the_event` |
| expired approval | `test_scenario_k.py::test_k_button_for_an_expired_approval_does_nothing` |
| opt-out | `test_scenario_k.py::test_k_opt_out_confirms_and_blocks_proactive_messages_but_not_replies`; customers `test_customers_and_quote_send.py::test_customer_stop_opts_out_with_a_confirmation` |
| closed window | `test_scenario_k.py::test_k_closed_window_blocks_with_a_reason`, `::test_closed_window_with_an_approved_template_sends_and_paused_blocks`, `test_customers_and_quote_send.py::test_quote_send_outside_the_window_is_blocked_with_the_reason` |
| simulated delivery labelled | `test_scenario_k.py::test_k_simulated_statuses_are_labelled_and_reach_read_through_the_webhook` |
| real status only from provider evidence | `test_live_mode.py::test_live_outbound_needs_the_flag_and_the_allowlist_and_statuses_are_real` (accepted ≠ delivered; delivered only from a signed provider status; `simulated=false`) |
| unknown never resent; escalation + confirmed resend | `test_scenario_k.py::test_k_unknown_outcome_is_never_resent_and_escalates_after_15_minutes`, `::test_resend_as_new_message_needs_confirmation_and_a_new_key` |
| throttle backoff / validation failure | `test_scenario_k.py::test_throttle_backs_off_and_the_sweep_requeues_when_due`, `::test_validation_error_fails_without_retry` |
| live: not_configured, Connected after 3 checks | `test_live_mode.py::test_live_mode_is_not_configured_while_a_setting_is_missing`, `::test_connected_only_after_graph_handshake_and_signed_event`, `::test_verify_needs_a_recent_sign_in_and_the_admin_key` |
| scenario C via WhatsApp text, review link | `test_scenario_c_whatsapp.py::test_c_whatsapp_text_drafts_the_quote_and_review_link_redirects` (LK-QT-2026-0009, EUR 24.00 × 240 = EUR 5,760.00, buttons, single-use button, bound review link) |
| scenario C via WhatsApp voice note | `test_scenario_c_whatsapp.py::test_c_whatsapp_voice_note_echoes_the_transcript_and_drafts` |
| scenario C through the simulator API | `test_scenario_c_whatsapp.py::test_c_simulator_thread_shows_the_conversation_with_the_demo_label` |

Also: enrolment/identity rules (11 tests in `test_identity_and_enrolment.py`), customers and the approved quote send
(5), review links / templates / admin list (3), unit (16 functions, 39 cases incl. the Cloud API adapter over an
httpx mock transport), lane contracts (9: operationIds and authz kinds, catalogued event payloads, tool input, CHECKs
mirror enums, forced RLS, exempt tables, append-only triggers, no wall clock, encrypted bodies). Web:
`features/channels/channels.test.tsx` (5).

## 3. Decisions

- **One configured number serves both purposes** until owner decision 7 names a customer-service number:
  `ensure_account(purpose="customer_service")` resolves to the same account; customer and employee identities stay
  separate rows (`kind`), and customers never reach the assistant.
- **Who may link a phone:** `channels.identity.manage` (C, RA) is granted to no role template in the frozen catalogue
  (admin only). Linking one's **own** number therefore needs `agents.assistant.use` plus, outside demo mode, a recent sign-in (the RA
  flag of `channels.identity.manage` is enforced); `channels.identity.manage` governs everyone's identities
  (`?scope=all`, revoke others). See integrator request 5.
- Wrong enrolment codes are counted **per sender** (5 per 10-minute window in `rate_limit_counter`), not per
  enrolment, so a stranger cannot burn another user's code; `channels_enrolment.attempts` records the sender's
  failures at the moment of the successful link.
- Approve / reject over WhatsApp always answer with a `decide` review link (design: "sensitive decisions go only
  through review links"); a voided ref (proposal expired, decided, changed) answers "Nothing was done."
- `channels.message.delivery_unknown` → the escalation task is created directly through `tasks.service.create_task`
  in the owner's context (after commit, `origin=automation`), because the tasks lane owns `tasks.rules`.
- The deactivation consumer subscribes to the catalogued `identity.membership.deactivated` (the brief's
  `identity.user.deactivated` does not exist) and to `identity.user.credentials_changed` (resets, not routine password changes).
- Channel turns: `client_utterance_id = uuid5(namespace, wamid)` (idempotent per wamid); the run's
  `correlation_id` is the inbound event's, so audit rows, events and the run share it. `input_mode`
  (`wa_text`/`wa_voice`/`card_action`) is recorded on `channels_message` because Slice-1 turns have no such field.
- Demo deliveries are recognised by the `demo-` phone number id; statuses by the `wamid.demo.` prefix.
- Development secrets: in demo mode without `LK_WHATSAPP_APP_SECRET` / `VERIFY_TOKEN`, deterministic values are
  derived from `LK_SECRET_KEY`; live mode without them verifies nothing (fails visibly).

## 4. Integrator requests

1. Renumber `0022_channels_slice3.py` (revision `0022`, `down_revision = "0009"` — the id of `0009_agents_slice1` on
   this branch) and reparent it onto the merged chain.
2. Shared-file touches (small, additive): `tests/contract/system/test_route_authz.py` (`PATH_EXCEPTIONS` gains
   `"review-links": "channels"`), `apps/web/src/lib/routes.ts` (`settings-whatsapp`, `review-link`),
   `apps/web/src/lib/api/query-keys.ts` (`channels` keys + `channels.changed` invalidation),
   `apps/web/src/features/settings/settings-hub.tsx` + `src/messages/settings.ts` (hub hint), `.env.example` +
   `backend/app/core/config.py` (`LK_WHATSAPP_APP_SECRET_PREVIOUS`, `_API_VERSION`, `_LIVE_OUTBOUND`,
   `_DEV_ALLOWLIST` and the six live settings), `backend/openapi.json` + `schema.d.ts` (regenerate after the merge).
3. **agents-s3 interfaces** (not on this branch, coded against Slice 1): once `lane/s3-agents` merges, pass
   `input_mode` (`wa_text`, `wa_voice`, `card_action`) to `create_turn` in `channels/whatsapp/replies.submit_turn`
   (the value is on `channels_message.input_mode`), and add `channels_message` rows (by `correlation_id`) to the
   trace timeline in `agents/trace.py` if wanted. The reply already uses the run's server-built cards
   (`Run.assistant_turn_id` → `Turn.cards`), unchanged by agents-s3. The turn's correlation id is the inbound event's
   UUIDv7, which satisfies agents-s3's "UUIDv7 at ingress" rule.
4. Voice lane: register the real STT adapter with `app.modules.channels.whatsapp.stt.register_transcriber(fn)` in
   the voice manifest's `on_load` (signature `(data, mime_type, sha256) -> Transcript`); the Demo transcriber stays the fallback.
5. Permissions (owner/integrator): decide whether the employee template should grant `channels.identity.manage`
   (frozen `permissions.md` gives it to no template); this lane uses `agents.assistant.use` + RA for own linking.
6. Briefings lane: a WhatsApp briefing push is `outbound.queue_message(..., kind="template", purpose="daily_briefing",
   template_id=<lk_daily_briefing>)` or a session message inside the window; the sender enforces opt-in + window or
   approved UTILITY template. `channels.ack_sync` (voids acknowledge buttons on a web ack) is in place.
7. Sales lane: `sales.quote_delivery_status` (consumer of `channels.message.status_changed`, events.md §2) is not built here.
8. Tasks lane: optionally replace the direct `create_task` for delivery-unknown with a `tasks.rules` family.
9. `channels/crypto.py` (field encryption with `LK_DATA_ENCRYPTION_KEYS`) is a candidate for `app/platform`.
10. This worktree's `node_modules` had Next 16.4.0 against the 16.4.4 lockfile; `npm install` synced it (lockfile unchanged).

## 4a. Security

- **Enrolment step-up fails closed** (coordinator review, 2026-11-04). The first version required a recent sign-in
  only when `account.mode == "live"`, so any other mode value skipped re-authentication. Now:
  1. `enrolment.create` requires a recent sign-in whenever `account.mode != "demo"` — the safe mode is named
     explicitly; live and any unknown or future mode need step-up. Demo mode skips it so demo sign-in links (which
     carry no recent authentication) can link the simulator's synthetic number.
  2. `channels_enrolment.mode` (NOT NULL, CHECK demo/live) records the mode a code was issued under. `try_link`
     rejects a demo-issued code unless the account is still demo **and** the delivery is simulated (a `demo-…`
     phone number id); the code is cancelled, the failure counts against the sender and
     `channels.enrolment.rejected` is audited.
  3. `accounts.ensure_account` cancels every outstanding code of the account on a mode or phone-number switch
     (`enrolment.cancel_pending`, audited `channels.enrolment.cancelled`).
  Tests: `integration/channels/test_identity_and_enrolment.py::test_unknown_mode_requires_recent_auth`,
  `::test_demo_enrolment_rejected_on_a_live_account`, `integration/channels/test_live_mode.py::test_codes_invalidated_on_the_mode_switch`
  (plus `::test_live_enrolment_needs_a_recent_sign_in`).
- Other controls: signatures over raw bytes with `compare_digest` (current + previous secret); rejections store no
  payload; enrolment codes and review-link tokens are stored only as keyed/plain hashes and never logged (the code
  is masked in the message log); a phone number alone never carries authority (active identity + live session +
  the user's own permissions); buttons are single-use nonces bound to one identity and voided on unlink, suspension
  and proposal changes; message bodies are encrypted at rest; customers never reach the assistant; an unknown send
  outcome is never resent automatically.

## 5. Not done / limits

- No live Meta call (no credentials, no public HTTPS URL). Live behaviour is proven against `httpx.MockTransport`;
  the live checks to run once credentials exist are `POST /api/v1/channels/whatsapp/account/verify`, the
  subscription handshake from Meta's dashboard and one signed event.
- The 500 ms webhook budget is met by design (one insert + one job insert) but is not asserted by a timing test.
- Vendor identities: the `vendor` kind exists, but inbound matching only links party contacts as `customer` (no vendor party type yet).
- No e2e spec for `whatsapp-k` (the e2e runs belong to the integrator; `/r/[token]` is skipped by the axe sweep for lack of a fixture token).

## 6. Gate output

See §6 at the end of the lane (filled after the final runs).
