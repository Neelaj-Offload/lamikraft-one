# API conventions

Status: frozen in Slice 0. Implements `docs/PLAN.md` canonical contracts 6 (API) and 7 (Auth).
Code anchors: `backend/app/main.py` (`API_PREFIX = "/api/v1"`), `backend/app/core/errors.py`,
`backend/app/core/http/{authz_decl,middleware,pagination,deps,errors}.py`, `backend/app/core/money.py`.

---

## 1. Topology and paths

- Same origin. The browser calls `/api/v1/**` on the web origin; Next.js `rewrites.beforeFiles` forwards to
  FastAPI at `LK_API_INTERNAL_URL` (`http://127.0.0.1:<api port>`). No CORS middleware exists; startup
  rejects a wildcard origin. Always `127.0.0.1`, never `localhost` (cookie jars and Origin checks differ).
- Business routes: `/api/v1/<module>/<resource>[/{id}[/<sub-resource>|/<action>]]`, where `<module>` is the
  module name from [conventions.md](conventions.md) §2 (e.g. `/api/v1/sales/quotes/{quote_id}/transitions`,
  `/api/v1/catalogue/products`, `/api/v1/briefings/today`).
- Documented exceptions (exhaustive):

| Path | Owner | Why |
|---|---|---|
| `GET /api/v1/health/live`, `GET /api/v1/health/ready` | system | probes; `live` checks the process only; `ready` checks DB `SELECT 1` (2 s), Alembic at head and storage. AI and channel keys are **not** readiness inputs (they report through `integration_status`). |
| `GET /api/v1/session/bootstrap` | ui | the single session/state bootstrap (§8) |
| `GET|POST /api/v1/webhooks/whatsapp` | channels | provider webhook route kind (§10) |
| `/api/v1/_test/**` | test support | mounted only when `LK_ENV=test` |

- Self-service endpoints live under the owning module, e.g. `/api/v1/identity/me`, `/api/v1/identity/me/password`,
  `/api/v1/identity/me/sessions`, `/api/v1/identity/me/delegations`, `/api/v1/identity/me/preferences`.
- Resources nest under their owning module: `/api/v1/orders/sales-orders/from-quote/{quote_id}`, not
  `/api/v1/sales/quotes/{id}/convert-to-order`.
- Path segments are kebab-case plural nouns; JSON fields are snake_case; query parameters are snake_case.

## 2. Route declarations (`x-authz`)

Every `/api/**` route declares exactly one kind via `openapi_extra` or startup fails
(`app/core/http/authz_decl.py`):

| Kind | Helper | Meaning |
|---|---|---|
| `public` | `public(reason)` | no session (login, health, password-reset request, invitation inspect) |
| `authenticated` | `authenticated()` | any signed-in actor; the service applies record rules (own briefing, own preferences, self-service) |
| `permission` | `requires("sales.quote.read", ...)` | named permission keys, validated against the registry at startup |
| `webhook` | `webhook("whatsapp")` | signature-verified provider callback (§10) |
| `test_support` | `test_support()` | test-only; absent unless `LK_ENV=test` |

The declaration documents intent; enforcement happens in services (`ActorContext.require`, `ScopedRepository`),
so a declaration is never the only guard. Self-service routes are `authenticated` and need no permission key.

## 3. Errors: problem+json

Every non-2xx response is `application/problem+json`:

```json
{
  "type": "https://lamikraft.one/problems/version_conflict",
  "title": "This record changed since you opened it",
  "status": 409,
  "code": "version_conflict",
  "detail": "Reload to see the latest version.",
  "request_id": "0192...",
  "errors": [{"loc": ["body", "lines", 0, "quantity"], "msg": "...", "code": "not_integer"}]
}
```

Codes are lower snake_case from a central enum exported in OpenAPI. Validation responses never echo input
values (the 422 handler strips `input` and `ctx`).

| Code | HTTP | Notes |
|---|---|---|
| `validation_failed` | 422 | `errors[{loc,msg,code}]` |
| `unauthenticated` / `session_expired` | 401 | client redirects to `/login?next=` (relative paths only) |
| `reauth_required` | 401 | step-up re-authentication (recent-auth permissions) |
| `mfa_required` | 401 | session stage `mfa_pending` / `mfa_enrollment_required` |
| `permission_denied` | 403 | visible record, forbidden action; never includes field values |
| `cross_site_request`, `origin_mismatch`, `csrf_token_invalid` | 403 | CSRF guard (§7); client refetches bootstrap and retries once on `csrf_token_invalid` |
| `not_found` | 404 | also for records outside the actor's scope (no existence leak) |
| `version_conflict` | 409 | body: `current_version`, `current` (redacted representation), `changed_by`, `changed_at` |
| `invalid_transition` | 409 | body: `allowed_transitions` |
| `proposal_changed`, `approval_stale`, `item_changed`, `recommendation_stale` | 409 | every staleness conflict is 409 with the fresh object where safe (never 412) |
| `not_complete` | 409 | Mark handled on an incomplete obligation; body `remaining` |
| `not_configured` | 409 | capability needs configuration (tax profile, provider) |
| `insufficient_stock`, `reserved_stock_conflict`, `fx_unavailable`, `price_ambiguous` | 409 | domain conflicts (Slices 2/4) |
| `pin_ended` | 410 | stopped/expired briefing pin |
| `payload_too_large` | 413 | upload limits |
| `unsupported_media_type` | 415 | sniffed type mismatch, SVG, macro documents |
| `idempotency_key_reused` | 422 | same key, different request hash |
| `snooze_beyond_deadline` | 422 | body `max_until` |
| `mandatory_control` | 422 | a preference tried to weaken policy |
| `uom_conversion_missing`, `excess_return`, `party_link_required` | 422 | domain validation |
| `rate_limited` | 429 | `Retry-After` header |
| `service_unavailable` | 503 | readiness failure (no internal detail) |

## 4. Decimals, money and quantities

- `DecimalStr` (`app/core/money.py`) is the only decimal field type: JSON Schema
  `{"type": "string", "pattern": "^-?\\d{1,14}(\\.\\d{1,6})?$"}` in **both** request and response components;
  floats are rejected with 422 on input and can never be produced on output.
- Money: `{"amount": "<DecimalStr>", "currency": "INR"|"EUR"|"USD"|"GBP"}`. Quantity: `{"value": "<DecimalStr>", "uom": "<uom code>"}`.
- Contract test `backend/tests/contract/test_openapi_decimals.py::test_money_and_quantity_fields_are_strings`
  walks every input and output component; generated TypeScript never exposes `number` for money or quantities.
- Totals are always server-computed and persisted; responses carry the persisted figures, never client math.

## 5. Capabilities and transitions

Every detail response (and list rows where actions are offered inline) carries:

```json
"capabilities": {
  "update": {"allowed": true, "reason_code": null},
  "delete": {"allowed": false, "reason_code": "issued_documents_cannot_be_deleted"},
  "export": {"allowed": true, "reason_code": null}
},
"allowed_transitions": [
  {"action": "submit_review", "to_status": "internal_review", "requires_reason": false},
  {"action": "cancel", "to_status": "cancelled", "requires_reason": true}
]
```

Computed by the server from permission scope, ownership and state through the module's `ResourcePolicy.rules`.
The UI hides actions the actor can never perform and shows state-blocked actions disabled with the reason.
Global permission keys drive navigation only. Restricted fields are **absent** from responses (optional in the
schema) and listed in `redacted_fields`; the client never masks data itself.

## 6. Concurrency and idempotency

- Editable resources carry `version`. PATCH/PUT bodies send dirty fields plus `expected_version`; a mismatch is
  409 `version_conflict` with the current redacted representation for a three-way merge. `If-Match` is not used.
- Unsafe commands accept an `Idempotency-Key` header (≤128 chars, UUIDv7 recommended, minted when the user
  initiates the action and reused on every retry). It is **required** on execute, convert, post, issue, send,
  approve/decide and import-commit commands and optional elsewhere.
  - Stored in `idempotency_key` inside the business transaction with the request hash and the redacted response;
    expires after 48 h.
  - Same key + same hash: the stored response is replayed with `Idempotent-Replayed: true` (only while the actor
    still holds the permission; otherwise 403). Same key + different hash: 422 `idempotency_key_reused`.
    A concurrent duplicate blocks on the conflicting transaction, then replays.

## 7. Authentication, sessions and CSRF

- Opaque server-side sessions. Cookie `lk_session` in development/test, `__Host-lk_session` in production;
  HttpOnly, SameSite=Lax, Path=/, Secure in production. Only the SHA-256 of the 256-bit token is stored
  (`auth_session.token_hash`). Idle 12 h, absolute 7 days, recent-auth window 10 min (configurable within bounds).
  Rotation on login, MFA verification and password change; revocation applies on the next request.
- CSRF: synchronizer token. The server stores a hash of the CSRF secret on the session and sets a readable
  `lk_csrf` cookie; every unsafe method (`POST`, `PUT`, `PATCH`, `DELETE`) on `/api/**` must send it back in
  `X-CSRF-Token`. Additionally the Origin (else Referer) must equal `LK_PUBLIC_ORIGIN` and `Sec-Fetch-Site`
  must not be `cross-site`. Login (no session yet) relies on the Origin and Sec-Fetch-Site checks.
- Tokens never appear in URLs. The backend ignores `?auth=` and `?token=`. Reset, invitation and demo sign-in
  links carry their token in a `#t=` fragment; the page reads it, strips it with `history.replaceState`, POSTs it,
  and serves `Referrer-Policy: no-referrer`. Downloads are plain same-origin links authenticated by the cookie.
- Passwords: argon2id (argon2-cffi defaults) in a thread pool behind a semaphore of 4; length 12–256 with a
  common-password list. Rate limits (IP 30/10 min, email 10/10 min) and lockout counters live in Postgres;
  every failure returns the same generic message.
- No bootstrap admin: `lk admin create-first` creates the first admin once (refuses when one exists). Demo users
  sign in only through one-time links in the `is_demo` company.

### 7.1 Authentication endpoints (frozen 2026-10-23 for Slice 1)

| Method and path | Kind | Body / result |
|---|---|---|
| `POST /api/v1/identity/session` | public (Origin + Sec-Fetch-Site checked, rate-limited) | `{email, password}` → 200 `SessionInfo` and cookies `lk_session` + `lk_csrf`; 401 `invalid_credentials` (generic) or 429 `rate_limited`/`account_locked` |
| `DELETE /api/v1/identity/session` | authenticated | revokes the current session, clears cookies, 204 |
| `POST /api/v1/identity/demo-sign-in` | public (demo company only) | `{token}` from the `#t=` fragment → 200 `SessionInfo` + cookies; 401 `link_invalid_or_used` |
| `GET /api/v1/session/bootstrap` | authenticated (401 when signed out) | §8 payload; rotates `lk_csrf` |
| `GET /api/v1/identity/me` | authenticated | profile, memberships, preferences |
| `PATCH /api/v1/identity/me/preferences` | authenticated | typed preference sections (ui, locale, briefing, voice, assistant) |
| `POST /api/v1/_test/sign-in` | test support (`LK_ENV=test` only) | `{user_key}` (fixture key) → session cookies |

## 8. Session bootstrap

`GET /api/v1/session/bootstrap` (kind `authenticated`, also answers 401 cleanly for the login redirect) returns:
user and membership (display name, role names, `is_demo`), company and branches, `time_zone`, `locale`,
`server_now`, `greeting_period`, effective `permissions[{key, scope}]`, UI preferences (theme, motion, sidebar,
rail, density, shortcuts), integration modes for Demo/Not-connected labels, Inbox counts, current briefing
version, feature readiness flags for nav, and a rotated CSRF value. The `(app)` layout awaits it server-side so
navigation renders only authorised, implemented areas.

`features` (`dict[str, bool]`, `app/modules/ui/schemas.py::SessionBootstrap.features`) carries:
- one readiness flag per navigation area (`today`, `inbox`, `sales`, `products`, `operations`, `finance`,
  `settings`): true when one of the area's modules is installed (`app/modules/ui/service.py::area_readiness`);
- two capability flags, reserved names: `assistant` (typed commands to the agent can be sent) and `voice`
  (push-to-talk can be offered). The ui module does not emit them yet (they arrive with the agents lane); a
  missing key means false, and the web reads `capabilities{assistant,voice}` first, then these keys in
  `features` (`apps/web/src/lib/session/parse.ts`). Whoever implements the assistant or voice adds the key here,
  never a new top-level field.

## 9. Lists and pagination

- Offset pages: `Page{items, total, limit, offset}` (`app/core/http/pagination.py`), `limit` default 50, max 200.
  Filters and scope are applied **before** LIMIT/OFFSET and the same WHERE clause feeds `total`.
  Ordering is stable with `id` as the final tie-break.
- Feeds (activity, change logs, inbox history, agent run steps) use keyset pages:
  `CursorPage{items, next_cursor, limit}`; cursors are opaque base64url of `(sort_key, id)`.
- Search: `q` is tokenised and matched with escaped ILIKE (plus pg_trgm ranking); regex is never built from input.
- List CSV exports use the same filters and scope as the list, through `app/core/csv_safe.write_csv`.

## 10. Webhook route kind

`/api/v1/webhooks/whatsapp`:
- `GET`: verification handshake (`hub.mode=subscribe`, constant-time `hub.verify_token` compare, echo
  `hub.challenge`; 403 otherwise; records `handshake_ok_at`).
- `POST`: no session, exempt from CSRF/Origin checks, raw body preserved (≤4 MB), `X-Hub-Signature-256`
  verified as `sha256=` + HMAC-SHA256(app secret, raw bytes) with `compare_digest` (current and previous secret
  during rotation). Invalid or missing signature: 403 and a `channels_webhook_rejection` row (no payload stored).
  Valid: insert `channels_webhook_inbox`, enqueue processing, return 200 within 500 ms; DB failure returns 500 so
  the provider retries. Both tables are RLS-exempt; the worker resolves the company through `channels_account`.
- The Demo WhatsApp provider posts signed payloads through this same route.

## 11. Files and downloads

`POST /api/v1/files` (multipart, rate-limited) streams to a temp file with per-purpose limits (images 15 MB,
documents 25 MB, imports 50 MB), computes SHA-256, sniffs magic bytes, rejects SVG/HTML/macro documents and
extension mismatches, and dedupes on `(company_id, sha256)`. Downloads: `GET /api/v1/files/{id}/content[?variant=]`,
authorised through the attaching parent (or creator-only for exports), with `nosniff`, `CSP: sandbox`, RFC 6266
`filename*`, `inline` only for images and PDFs, `private` cache with ETag (`no-store` when restricted).

## 12. Streaming and progress

Agent runs: `POST /api/v1/agents/conversations/{id}/turns` returns 202 with `run_id`; the client polls
`GET /api/v1/agents/runs/{run_id}?after_seq=` every 500 ms while the run is active (Slice 1). A Slice-0 spike
measures SSE through Next rewrites; if buffered, Slice 3 adds exactly one passthrough route handler
(`apps/web/src/app/stream/agent-runs/[id]/route.ts`) and polling remains the fallback. Briefing and Inbox state is
polled (`GET /api/v1/ui/poll`, ETag/304, 60 s while visible).

## 13. OpenAPI and generated types

- operationId: `<module>_<verb>_<noun>` in snake_case, unique and stable, e.g. `sales_list_quotes`,
  `sales_get_quote`, `sales_create_quote`, `sales_update_quote`, `sales_transition_quote`, `sales_export_quotes_csv`,
  `briefings_get_today`, `catalogue_list_products`, `approvals_decide_proposal`. Verbs: list, get, create, update,
  delete, archive, transition, export, run, issue, post, decide, resolve, upload, download, poll.
- Tags = module name. Export is deterministic (sorted keys) to `backend/openapi.json`; `openapi-typescript`
  generates `apps/web/src/lib/api/schema.d.ts`; `openapi-fetch` is the client.
- Generated files are regenerated (`npm run api:generate`), never hand-merged; `npm run api:check` fails on drift.
- OpenAPI is not served publicly in production.

## 14. Dates and times on the wire

Timestamps: RFC 3339 UTC with `Z` (`2026-10-12T03:25:00Z`). Business dates: `YYYY-MM-DD` in the documented local
zone. Zones: IANA names. Durations: ISO 8601 (`PT30M`) or integer seconds named `*_seconds`.
