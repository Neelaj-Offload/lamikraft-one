# Lane brief: Slice 3 — WhatsApp channel (Cloud API adapter, Demo provider, enrolment, outbox, review links)

Branch `lane/s3-whatsapp` from `main`. Module owner: `backend/app/modules/channels/**` (new), the webhook route
`backend/app/platform/http/...` or `modules/channels/webhook.py` mounted at `/api/v1/webhooks/whatsapp`,
`apps/web/src/features/channels/**`, `src/app/(app)/settings/whatsapp/**`, `src/app/(app)/r/[token]/**`,
copy `src/messages/channels.ts`. Never push; small named commits; never two test suites at once; never leave dev
servers running.

## Contracts (read first)
1. `docs/design/source/agent_voice_whatsapp.md` §15 WhatsApp (every rule: webhook GET/POST, signature, inbox,
   processing, identity, message types, enrolment and sessions, outbound, reconciliation, consent, customers and
   vendors, review links, demo mode, live mode), §4 channel tables (`channel_account`, `channel_identity`,
   `channel_enrolment`, `channel_session`, `webhook_inbox`, `webhook_rejection`, `inbound_event`,
   `channel_message`, `message_status_event`, `outbox_message`, `channel_consent`, `wa_template`,
   `review_link`), §16 endpoints (Channels table), §17 events (`channels.*`), §18 scenario C via WhatsApp.
2. `docs/architecture/events.md` §3.8 channels (payloads and consumers; `channels.message.status_changed` →
   `sales.quote_delivery_status`; `channels.message.delivery_unknown` → tasks escalation; customer messages become
   `sales_customer_message` rows through `sales.service.record_customer_message`), `permissions.md`
   (`channels.*`), `api-conventions.md`, `conventions.md`, `fixtures.md`.
3. `docs/PLAN.md` Slice 3 "WhatsApp" bullet and scenario K; `docs/BUILD_STATE.md` §5 decision 7 and §6
   credentials (`LK_WHATSAPP_*` env already in `.env.example`); `backend/app/core/config.py` (settings),
   `backend/app/platform/system/integrations.py` (add the `whatsapp` integration def with the three checks:
   Graph API, handshake, signed event), `backend/app/platform/jobs` (worker jobs), `platform/events` (outbox
   dispatcher), the existing agents turn creation (`agents/service.py create_turn`, `router.py`) for turning an
   inbound text into a turn with `input_mode = wa_text`, the approvals module for action refs and proposals.
4. Meta's WhatsApp Cloud API reference for payload shapes and error codes (verify at build time; keep a versioned
   error-code table in `channels/error_codes.py` with the date checked).

## Deliverables
1. **Tables and migration** `backend/migrations/versions/0022_channels_slice3.py`,
   `down_revision = "0009_agents_slice1"` (the integrator reparents it), with RLS and company scope, encrypted
   `channel_message.body` through the platform's data-encryption helper, append-only consent log, uniqueness as
   in §4.
2. **Webhook** `GET` (hub.mode/verify_token constant-time, 200 + challenge, `handshake_ok_at`) and `POST` (raw
   body ≤4 MB, `X-Hub-Signature-256` HMAC-SHA256 with `compare_digest` against current and previous secret, 403 +
   `webhook_rejection` on failure, inbox insert + enqueue + 200 within 500 ms, 500 on DB failure). Public route
   (no session), CSRF-exempt by design, rate-limited.
3. **Processing worker**: typed payload parsing (`messages`, `message_template_status_update`), fan-out to
   `inbound_event` keyed by wamid or wamid+status+timestamp (replay = no-op), ignore unknown `phone_number_id`
   and groups, identity matching (BSUID first, then wa_id; `user_id_update` suspends), serial per identity in
   `provider_ts` order with late flags, message types (text → turn; audio → media fetch with 5-minute URL,
   ≤10 MB, SHA-256 check, STT through the voice module's adapter interface — call it through a small protocol so
   this lane does not depend on the voice lane's files, with a Demo transcript when absent — and "I heard: …";
   image/document bounded and stored `provenance=external`; interactive replies → action refs with no model;
   unsupported → polite reply). Unknown/revoked/suspended senders get the generic "not linked" reply.
4. **Enrolment and sessions**: `POST /api/v1/channels/whatsapp/enrolments` after a recent authentication (step-up
   helper) → 8-digit code hashed, 10 minutes, 5 attempts, wa.me link prefilled "LINK <code>"; a matching inbound
   code activates the identity and starts a session (7 days idle / 30 absolute); revocation, deactivation
   (`identity.user.deactivated` consumer) and number reassignment revoke sessions and void armed action refs.
5. **Outbox sender**: row written in the same transaction as its cause; worker claims with `SKIP LOCKED`, checks
   identity active, consent for proactive purposes, 24-hour window or approved template (blocked with reason
   otherwise), live-outbound flag and dev allowlist; `POST /{api_version}/{phone_number_id}/messages` with
   `biz_opaque_callback_data` = outbox id; outcomes exactly as §15 (2xx accepted; timeout/reset/5xx → `unknown`,
   never auto-resent; 429/"not processed" → backoff; 4xx validation → failed).
6. **Reconciliation**: status webhooks matched by wamid or `biz_opaque_callback_data`, `pending_match` retry,
   rank order accepted < sent < delivered < read < played, `failed` only below delivered, every event kept;
   `unknown` with no status after 15 minutes → `channels.message.delivery_unknown` → Inbox escalation task with
   a confirmed "Resend as new message" (new idempotency key).
7. **Consent**: append-only; STOP/UNSUBSCRIBE/"band karo" opt out + confirmation; daily-briefing pushes need
   opted_in plus window or utility template.
8. **Customers and vendors**: separate identities (customer_service account), inbound → owner's Inbox as external
   content through `sales.service.record_customer_message`; no autonomous AI replies; `prepare_quote_send` tool
   (registered in the agents registry through the registry API, not by editing agents files) binding recipient,
   content and PDF hash; sends only through an approved proposal (`channels.message.send`).
9. **Review links** `/r/[token]`: 32-byte token stored hashed, 15 minutes, single use for decisions, requires a
   web login as the bound user, then redirects to the canonical screen; `POST /api/v1/review-links/{token}/resolve`.
10. **Demo provider**: records outbound messages and posts **signed** simulated statuses through the real webhook
    route; messages prefixed "Demo:" and flagged `simulated`; a simulator page in Settings › WhatsApp where an
    enrolled demo user chats (scenario C over WhatsApp demo); UI label "WhatsApp: Demo — not connected".
11. **Live mode**: required settings from env; `not_configured` when any is missing; "Connected" only after all
    three checks succeed (`channels.account.verified`); admin endpoints for account, verify, messages
    (`state=unknown|failed|blocked`), outbox resolve, templates list and sync.
12. **Web**: Settings › WhatsApp (route `settings-whatsapp`, context tab; admin views with
    `channels.account.manage`: account status and checks, unknown/failed/blocked messages with resolve,
    templates; everyone with `channels.identity.manage`: "Link my WhatsApp" enrolment card with the code and the
    wa.me link, linked identities with revoke, consent switches); the simulator (demo mode only); the review-link
    page. Build on `PageHeader`/`AreaNav`/`SectionCard`/`DataTable`; honest "Demo — not connected" badges from
    the integration status; copy in messages.
13. **Scenario K tests** (`docs/PLAN.md`): signature rejection, replay, out-of-order status, employee unlink,
    expired approval, opt-out, closed window — all with fixtures; duplicate delivery → one business effect;
    simulated delivery labelled; real status only from provider evidence. Scenario C over the WhatsApp demo.

## Verification
`npm run check -- --keep-going` 7/7, `npm run test:api`, `npm run api:generate` committed, web gates;
`docs/lanes/whatsapp-s3.md` (built, scenario K test table, decisions incl. the verified Cloud API version and
error-code table date, integrator requests, gate output). Final message: branch tip, counts, unfinished items.
