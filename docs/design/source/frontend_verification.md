> Design-workflow output (2026-10-12), kept as source material. Where it conflicts with docs/architecture/*, the architecture docs win.

# Frontend application, design system and verification strategy

# Frontend application, design system and verification strategy

## 0. Scope and boundaries
- **Owns:** `apps/web` (Next.js), the design system, frontend–backend contract conventions, a small backend `ui` module (session bootstrap, UI preferences, recent records, polling, link resolution), the test-support contract, and the verification strategy for the whole system (A–N mapping).
- **Depends on contracts implemented elsewhere:** identity (session, CSRF, permissions), briefings, tasks/inbox, agents/voice/channels, search, records (notes, attachments, activity, relations) and the domain modules. Each contract I need is stated below.
- Slice tags such as **[S1]** refer to the build order (§20).

## 1. Stack (exact versions locked in package-lock.json)
- **Framework:** next 16.4.0 (App Router, Turbopack, `typedRoutes: true`, `output: 'standalone'`, `poweredByHeader: false`) with react and react-dom 19.3.0.
- **TypeScript: pin 5.9.x, not 7.0.2.**
  - TS 7 ships no JavaScript compiler API.
  - openapi-typescript 7.13 declares a peer dependency of `typescript ^5.x`, and eslint-config-next/typescript-eslint also need the API.
  - Next 16.4 type-checks with the project-local `tsc` CLI either way.
  - Revisit when TS 7.1 ships its new API.
- **Styling:** tailwindcss 4.3.3 with @tailwindcss/postcss, plus tailwindcss-react-aria-components 2.2.0 (state variants).
- **Primitives:** react-aria-components 1.22.1 is the only primitive library. It brings @internationalized/date for zone-aware dates.
- **Data:** @tanstack/react-query 5.104.2 and openapi-fetch 0.17.0; openapi-typescript 7.13.0 as a dev dependency.
- **Forms:** react-hook-form with @hookform/resolvers and zod 4.6.6. Verify the zod-4 resolver at install.
- **Fonts and icons:**
  - @fontsource-variable/manrope 5.3.0 (SIL OFL 1.1).
  - @fontsource-variable/noto-sans-devanagari (OFL), loaded by unicode-range only.
  - lucide-react for icons.
- **Not used:** no chart library, no state library (React state, Query and the URL are enough), no CSS-in-JS, no analytics or third-party scripts.
- **Test tooling:** @playwright/test 1.64.0, @axe-core/playwright 4.13.0, and vitest 5.0.3 (node environment, pure logic only).
- **Lint:** the eslint CLI with eslint-config-next flat config, since `next lint` no longer exists.

## 2. File layout
**apps/web/**
- **Config:** `next.config.ts`, `src/proxy.ts`, `playwright.config.ts`, `vitest.config.ts`, `eslint.config.mjs`, `postcss.config.mjs`.
- **`src/app/`:** routes (§4). There is no `app/api/**`; that namespace is reserved for FastAPI.
- **`src/api/`:**
  - `openapi.json` and `schema.d.ts` (generated and committed).
  - `browser.ts` (browser client) and `server.ts` (`server-only` client).
  - `middleware.ts`: CSRF, Idempotency-Key, X-Request-ID and problem normalisation.
  - `errors.ts`.
- **`src/queries/<domain>.ts`:**
  - `queryOptions` factories that take an api client argument.
  - Mutation helpers.
  - `invalidation.ts`.
- **`src/components/`:** `ui/` (primitive wrappers), `shell/`, `record/`, `data/`, `format/`, `states/`.
- **`src/features/`:** today, inbox, assistant, voice, search, quotes, products, cutting, challans, imports, settings, and later areas.
- **`src/lib/`:**
  - `routes.ts` (route manifest), `nav.ts`, `can.ts`.
  - `time.ts`, `money.ts`.
  - `merge.ts`, `local-drafts.ts`, `dirty-guard.ts`, `shortcuts.ts`.
- **Other:** `src/styles/tokens.css` and `globals.css`; `src/messages/en.ts` holds all UI copy.
- **`e2e/`:** `fixtures/`, `scenarios/`, `responsive/`, `a11y/`, `visual/`, `global-setup.ts`.

**backend/**
- `app/modules/ui/{models,schemas,service,router,policies}.py`
- `app/testsupport/router.py`, mounted only when `APP_ENV=test`.
- `app/tools/export_openapi.py`

## 3. Contract with FastAPI
**Same origin**
- The browser calls `/api/v1/**` on the app's own origin. In `next.config`, a `rewrites.beforeFiles` rule forwards it to `${BACKEND_INTERNAL_URL}/api/:path*`.
- FastAPI has no CORS middleware.
- Server components call `BACKEND_INTERNAL_URL` directly and forward Cookie, X-Request-ID and X-Forwarded-For. The backend trusts XFF only from configured proxy addresses.

**`proxy.ts`**
- Its matcher excludes `/api`, `_next/*` and static files. Next buffers proxy-matched request bodies only up to 10 MB, so uploads must bypass it.
- It does three things only:
  - Redirects to `/login?next=` when the session cookie is absent. This is an optimistic check; the real one is the bootstrap call.
  - Sets a per-request CSP nonce.
  - Sets an `x-lk-path` request header.
- **CSP:**
  - `default-src 'self'`; `script-src 'self' 'nonce-…' 'strict-dynamic'`.
  - `img-src 'self' data: blob:`; `media-src 'self' blob:`; `connect-src 'self'`.
  - `frame-ancestors 'none'`; `object-src 'none'`.
  - `Permissions-Policy: microphone=(self), camera=(self)`.

**Session**
- An HttpOnly, SameSite=Lax cookie: `__Host-lk_session` in production, `lk_session` in dev/test.
- Never readable by JavaScript and never placed in a URL. Downloads are plain same-origin links.
- The `next` login parameter must be a relative path; reject values starting with `//` or `/\`.

**CSRF (signed double-submit)**
- The backend sets a readable `lk_csrf` cookie containing a random value plus an HMAC of the session id.
- Client middleware echoes it as `X-CSRF-Token` on POST, PUT, PATCH and DELETE.
- The backend also rejects a foreign `Origin` and `Sec-Fetch-Site: cross-site`.
- On `csrf_invalid` the client refetches bootstrap and retries once.

**Types**
- `uv run python -m app.tools.export_openapi apps/web/src/api/openapi.json`, then `openapi-typescript` produces `schema.d.ts`.
- `npm run api:check` fails CI if the generated files drift.

**Errors (RFC 9457 problem+json, with `code` and `request_id`)**

| Code | HTTP | Extra fields / notes |
|---|---|---|
| `validation_failed` | 422 | `errors[{loc, msg, code}]` |
| `version_conflict` | 409 | `current`, `current_version`, `changed_by`, `changed_at` |
| `permission_denied` | 403 | |
| `not_found` | 404 | Also used for records outside the user's scope |
| `session_expired` | 401 | |
| `reauth_required` | 401 | |
| `csrf_invalid` | — | Client refetches bootstrap and retries once |
| `rate_limited` | 429 | `Retry-After` |
| `proposal_stale` | 412 | |

**Concurrency:** editable resources carry `version`. PATCH sends only dirty fields plus `expected_version`.

**Capabilities**
- Every detail response includes `capabilities: {action: {allowed, reason_code?}}` and, for stateful documents, `allowed_transitions`. The server resolves both using ownership, scope and state.
- The UI hides actions that can never be allowed. Actions blocked by state are shown disabled with the reason.
- Global permission keys (a typed enum in OpenAPI) drive navigation only.

**Redaction:** restricted fields are absent from responses (optional in the schema). The client never masks data itself.

**Numbers**
- Money is `{amount: string, currency: 'INR'|'EUR'|'USD'|'GBP'}`; quantities are `{value: string, uom}`.
- No client arithmetic. Formatting uses `Intl.NumberFormat(locale, {style: 'currency', currency}).format(decimalString)`, which formats decimal strings exactly.
- A lint test forbids `parseFloat` and `Number(` in money and quantity code.

**Commands** send an `Idempotency-Key` created when the user initiates the action and reused on any retry.

## 4. Route map (`src/app`)
**Root:** `layout.tsx` (html `lang`, `data-theme` from the `lk_ui` cookie, fonts, Providers including RAC `RouterProvider` and `I18nProvider`), `global-error.tsx`, `not-found.tsx`.

**(auth) [S1]:** `/login`, `/login/mfa`, `/forgot-password`, `/reset-password/[token]`, `/invite/[token]`.

**(app)** uses the shell layout. `/` redirects to `/today`.

**Today [S1]**
- `/today`
- `/today/all`: every section, with filters.
- `/today/changes?since=last_ack|yesterday`: source-linked delta view.
- `/today/items/[itemId]`: explanation and evidence.

**Inbox** (list plus detail split layout)
- [S1] `/inbox`, `/inbox/approvals`, `/inbox/exceptions`, `/inbox/done`, `/inbox/tasks/[taskId]`, `/inbox/approvals/[proposalId]`.
- [S3] `/inbox/conversations[/[conversationId]]`.

**Sales**
- `/sales` [S1]: my work in motion.
- `/sales/parties[/new|/[partyId]/{contacts,quotes,orders,samples,prices}]`: minimal [S1], full [S4].
- `/sales/quotes[/new]` and `/sales/quotes/[quoteId]` (Document tab) [S1].
- `…/review?proposal=` [S1].
- `…/revisions` and `…/revisions/compare?from=&to=` [S2].
- `…/preview` [S1].
- `/sales/custom-products[/new|/[id]/{costing,samples}]` [S2].
- `/sales/enquiries`, `/sales/samples`, `/sales/orders[/[id]/{fulfilment,documents}]` [S4].

**Products**
- `/products` [S1 read, S2 full]: filters and pagination synced to the URL.
- `/products/new`, `/products/[productId]/{pricing,packaging,specifications,media,costing}`.
- `/products/taxonomy`, `/products/price-lists[/[id]]`, `/products/completeness` [S2].

**Operations**
- [S2] `/operations/cutting[/new|/[planId]]`, `/operations/cutting/grain-locks`, `/operations/challans[/new|/[challanId]/returns]`.
- [S4] `/operations` (home), `/operations/inventory[/movements|/stock-takes|/[productId]]`, `/operations/reservations`, `/operations/purchasing/{requisitions,orders,receipts}[/[id]]`, `/operations/production/{work-orders,boms}[/[id]]`, `/operations/quality[/[id]]`, `/operations/dispatch[/[id]]`, `/operations/returns[/[id]]`.
- [S5] `/operations/cutting/offcuts`.

**Finance [S5]:** `/finance`, `/finance/{invoices,credit-notes,receipts}[/[id]]`, `/finance/exceptions`, `/finance/ageing`, `/finance/accounting-sync`.

**Settings**
- [S1] `/settings`, `/settings/profile` (password, MFA, sessions, preferences, shortcuts), `/settings/company`.
- [S2] `/settings/users[/invite|/[userId]]`, `/settings/roles[/[roleId]|/simulate]`, `/settings/templates`, `/settings/sequences`, `/settings/imports[/new|/[jobId]]`, `/settings/audit`.
- [S3] `/settings/channels`, `/settings/automations[/[id]]`, `/settings/integrations`.
- [S1 minimal, S4 full] `/settings/briefings`.
- [S5] `/settings/branches`, `/settings/policy`, `/settings/migration`.

**Cross-cutting**
- [S1] `/search?q=`, `/work` (phone hub), `/more` (phone), `/go/[entityType]/[businessKey]` (resolves to the canonical URL).
- [S2] `/activity`.
- [S3] `/r/[ref]`: short-lived action reference. An expired link shows an explicit expiry page.

**(print), chrome-less:** `/print/quotes/[id]` [S1], `/print/challans/[id]` and `/print/cut-plans/[id]` [S2]. Each has print CSS and a Back link.

**Shared rules**
- **Canonical tab segments on every detail screen:** default (Overview/Document), `/related`, `/history`, `/notes`, `/attachments`, plus domain tabs.
- **Tabs are links**, rendered as a `<nav aria-label>` with `aria-current`, not an ARIA tablist.
- **Drawers and rail via search parameters:** `?panel=product:<id>|party:<id>|line:<id>|edit:<section>` and `?rail=assistant|details`.
- **URL identifiers:** detail routes use UUIDs. `/go` resolves business keys such as product_key and quote_number for voice, search and WhatsApp.
- **Route manifest:** every `page.tsx` has an entry in `lib/routes.ts` (path, label, area, required permission, slice, fixture parameters). The manifest is the single source for navigation, breadcrumbs, the axe sweep, the dead-control crawl and screenshots. A vitest test fails when a page lacks an entry.
- **Navigation shows only routes that are authorised and implemented.**

## 5. Rendering, data and caching
**Caching**
- All (app) routes are dynamic because they read cookies. `cacheComponents` stays off; there is no `use cache` and no fetch caching.
- The Next server never caches per-user data.
- Private media are not passed through the `next/image` optimiser, which would put authenticated images in a shared server cache. They render as `<img>` pointing at authenticated same-origin rendition URLs.

**Server components** (layouts and page shells)
- `(app)/layout.tsx` awaits `GET /session/bootstrap`. On 401 it redirects to login with a validated `next`; otherwise it renders the shell with authorised navigation, so there is no flash of unauthorised items.
- Pages prefetch their primary queries into a request-scoped QueryClient and render `<HydrationBoundary>`. The same `queryOptions` factories run on the client.

**Client components**
- Tables, forms, composer and canvases are client components.
- All writes go from the browser through openapi-fetch. There are no Server Actions and no Next route handlers, so FastAPI is the single write path shared with the agent tools.

**Query policy**
- `staleTime`: 30 s for lists, 10 s for details.
- GET requests retry at most twice on network errors or 5xx, never on 4xx.
- Mutations retry only after a network failure, and only with the same Idempotency-Key.
- `invalidation.ts` maps each mutation to the query keys it invalidates (for example `quotes.detail(id)`, `quotes.list`, `today`, `inbox.count`).

**Live updates**
- `GET /poll?briefing_version=&inbox_version=` runs every 60 s while the tab is visible, with ETag/304.
- Agent runs stream over SSE at `/agent/runs/{id}/events`. The backend sends `Cache-Control: no-cache, no-transform` so Next compression does not buffer the stream. Polling the run status is the fallback.

**Optimistic updates** apply only to reversible personal or draft actions (snooze, acknowledge, draft line edits, preferences). Approvals, sends, stock and finance show a pending state and then the server receipt.

**Time:** bootstrap returns `server_now`, the user's `time_zone` and `locale`. All rendering uses these rather than the browser's zone, which keeps hydration consistent and tests deterministic.

## 6. Shell, navigation and responsive behaviour
**Desktop (≥1280 px)**
- Grid of `208px | 1fr | 300px` (the rail column is optional).
- **Sidebar:**
  - Wordmark.
  - Today, Inbox (with its real count), Sales, Products, Operations, Finance, Settings.
  - User block (name and role) opening a menu.
  - Collapses to a 64 px icon rail with tooltips; the state is persisted.
- **Top bar (56 px):**
  - Company name, shown as plain text when the user has a single membership; a switcher appears only when there are several.
  - Search trigger ("Search… /").
  - "Demo workspace" label, with an explanation, when in demo mode.
  - Theme toggle and rail toggle.

**Area layouts:** each renders a contextual subnavigation (a horizontal nav under the area title; a scrollable chip row on phones), filtered by permission.

**Tablet (768–1279 px):** the sidebar collapses to the icon rail, and the context rail becomes an overlay drawer.

**Phone (<768 px)**
- **Bottom navigation:** Today, Inbox, Work, More (56 px plus the safe-area inset).
  - Work: authorised areas, recently opened records and my drafts.
  - More: Settings, Search, Activity, Profile, Theme, Sign out.
- **Composer:** inline on Today. Elsewhere a floating 56 px "Ask" button above the bottom nav opens it in a bottom sheet.
- **Panels:** full-screen sheets.

**Path back to Today:** the sidebar or bottom nav is always present. Print, `/r`, `/go`, error and permission-denied pages have an explicit "Back to Today".

**Denied routes**
- An unauthorised area shows a PermissionDenied view that names the missing capability and shows no data.
- A record outside the user's scope shows "Not found or not available to you", so its existence is not leaked.

## 7. Canonical detail screen (`DetailLayout`)
**RecordHeader**
- Business key in mono, title, status badge (text and colour).
- Owner via OwnerField; reassigning is offered only with the capability.
- Key facts taken from server values.
- A primary action plus a "More" menu built from `capabilities` and `allowed_transitions`.

**Tabs**
- **Overview:** current state.
- **Related:** linked documents, grouped.
- **History:** who did what, when, and at which version.
- **Notes:** the autosaved internal note (§11).
- **Attachments:** real drag-and-drop plus a file picker, authenticated download, soft delete.

**Context rail**
- Assistant with an object-context chip such as "LK-QT-2026-0012 · v3".
- Related-documents summary and recent activity.

**Contracts (records module)**
- `GET /records/{type}/{id}/relations`, `GET /records/{type}/{id}/activity`.
- `GET|PUT /notes/{type}/{id}`.
- `GET|POST /attachments`.
- Opening a detail screen fires `POST /me/recent-records` (fire-and-forget).

## 8. Today [S1; voice parts S3]
**Data:** `GET /briefings/today` returns:
- Snapshot id and version, `generated_at`, `is_fallback`, `last_successful_at`.
- Greeting period, plus the overview sentence and the counts it was built from.
- Sections, `top_item_ids` (at most 5), and items whose actions are decided by the server.

**Composition (desktop)**
1. **Greeting and meta.**
   - `h1` "Good morning, Meera.", with the greeting period computed by the server in the user's zone.
   - Meta line "Monday, 12 October · Updated 9:00 AM".
   - A compact forest "Listen to my day" button on the right.
2. **Overview sentence.** One factual sentence from a backend template. Its counts come from queries, and the client never composes it. "Three decisions need you. The rest is moving." appears only when the records support it.
3. **Command bar.** Label "Ask about your day, or tell me what to do", a textarea, a mic button and Send, plus at most four role chips that submit real commands.
4. **Columns.** Two columns at ≥1280 px with the rail closed; one column otherwise.
   - **Left:** "Needs you now" and "Plan for today", showing the top 5 by rank.
   - **Right:**
     - "Since your last visit": at most 5 changes, timestamped and source-linked.
     - "Handled for you": a sage box linking to the resulting records.
     - "Coming next".
   - Empty sections are omitted.
   - "See all work for today (N)" links to `/today/all`.
5. **Briefing item row.** Rows separated by rules, not cards.
   - Status dot with a text label.
   - Problem title and a fact summary in tabular numerals.
   - A sage "Suggested: …" strip.
   - A "Why?" disclosure with the rule-based priority reason, expected effect, alternatives and uncertainty flags (for example "Estimate — capacity unknown").
   - Evidence links such as "Quote LK-QT-… · Updated 8:45 AM".
   - One primary control and a "More actions" menu containing only server-provided actions (Assign, Snooze, Mark handled, Explain, Reject…).
   - A thumbnail only when the record has real media.
6. **Updates.** When polling sees a newer version, a "3 updates · Show" pill appears (aria-live polite). The list never reorders by itself, and while Listen is active the view stays pinned to the narrated snapshot.
7. **Listen to my day.**
   - Narration segments carry stable item references.
   - Controls: Play, Pause, Resume, Stop speaking.
   - The item being read is highlighted with `aria-current`.
   - The waveform appears only while speaking.
   - "Open the second item" is resolved through `{briefing_snapshot_id, ordinal}`.
8. **Snooze and Mark handled.**
   - Snooze shows "Deadline still {due}".
   - Mark handled: the server verifies completion; otherwise it requires a dismissal reason, if the user has that capability.
9. **Fallback.** A banner: "Today's briefing couldn't be prepared (9:02 AM). Showing your current tasks and the last briefing from Fri 9:00 AM." with Retry.
10. **Phone.** 28 px greeting, full-width Listen button, composer pinned above the bottom nav, sections stacked.
11. **New employee.** Shows assigned work and onboarding only, with no invented history.

## 9. Assistant, cards and canvases [S3; quote review S1]
**Composer request:** `POST /agent/conversations/{id}/messages` with:
- `client_message_id`
- `text`
- `context: {object_refs: [{type, id, version}], briefing_snapshot_id?}`

**Stream events:** `status`, `text_delta`, `card`, `clarification`, `error`, `done`.

**Cards** (OpenAPI discriminated union `AgentCard.type`)
- **Types:**
  - `quote_draft`, `proposal`, `record_list`, `cut_plan`, `stock_movement_proposal`, `receipt`.
  - `clarification`: the smallest useful question, with choice buttons and free text.
  - `error`: the cause plus "Open recoverable draft".
  - Unknown types fall back to a title and an Open link.
- **Anatomy:**
  - Type label; business key and version.
  - Server facts (quantity, unit price, total).
  - Evidence chips, for example "Export price list EXP-EUR-2026 · 1 Oct".
  - State, for example "Draft — not sent".
  - One primary and one secondary control.
- **Rules:**
  - A superseded proposal shows "Superseded by v4" and its approval is disabled.
  - Text produced by the demo adapter is labelled "Demo".
  - No agent personas, avatars or orb.

**Rail:** "Prepared for you" (runs with their receipts), today's conversation, and the object-scoped assistant on detail screens.

**Quote review (`/sales/quotes/[id]/review`)**
- **Left pane:** an HTML rendering of the same server document model the PDF uses.
- **Right pane:**
  - **Changes** against the base revision or proposal: added, removed and changed lines with before→after quantity and price; totals deltas come from the server.
  - **Evidence:** price list and its date, carton check, MOQ advisory.
  - **Policy:** decision, approvers and expiry.
- **Controls:** Approve, Reject and Request changes, bound to `{proposal_id, version}`.
- **Separation of duties:** the initiator sees "Another approver is required."
- **Re-authentication:** `reauth_required` opens a re-authentication dialog.

**Currency change dialog**
- Offers "Reprice from {currency} price list" or "Convert at approved rate {rate, source, date}". There is no relabel option.
- If the FX rate is unknown, the dialog explains why and blocks the change.

**Cutting canvas (`/operations/cutting/[planId]`) [S2]**
- **Geometry:** an SVG whose `viewBox` is in millimetres (2440×1220), so proportions are exact. It shows a scale bar, 100 mm ticks, the margin band and kerf gaps.
- **Pieces:** labelled with SKU and size, with a rotation marker and a grain hatch on locked decors.
- **Navigation:**
  - Zoom and pan by wheel, pinch, +/−, arrow keys, Fit, and 1:1, implemented in a small hook that rewrites the `viewBox`.
  - A board navigator grouped by decor and thickness.
- **Selection and metrics:**
  - Selecting a piece and selecting its placement-table row are linked both ways, using roving keyboard focus.
  - An unfit-pieces list.
  - Metrics and their definitions come from the server only.
- **Editing:** changes edit the inputs and re-run the server optimiser; there is no client-side geometry.
- **Accessibility:** the placement table is the authoritative accessible view; the SVG is `role="img"` with a summary label.

**Product screens**
- Primary material image (renditions) and a swatch strip from the record's media.
- Specifications are rendered from server field descriptors per category (`{key, label, type, unit, group, required}`), which also generate the zod form.
- Original source strings are shown as provenance.

## 10. Voice (frontend) [S3]
**`voiceMachine.ts` (pure reducer) states:**
1. idle
2. requesting_permission → denied, or
3. recording → cancel (back to idle), or
4. transcribing, with partial text shown in grey
5. transcript_ready (editable)
6. submitting
7. awaiting_response
8. speaking
9. idle

**Rules**
- `client_message_id` is minted when recording starts and reused for the final transcript; a final transcript replacing partials never sends anything by itself.
- Send is disabled while submitting.
- Starting a recording, pressing Stop or pressing Escape stops playback immediately.
- **Microphone denied:** show "Microphone blocked — type instead"; the text path stays fully usable.
- **Offline:** the text is kept as a local draft labelled "Saved on this device — not sent". Commit controls are disabled with the reason.
- **Consequential numbers:** read back as a structured confirmation card.

**Capture:** MediaRecorder audio is uploaded to the backend STT adapter. There is no dependency on browser SpeechRecognition.

**Waveform:** mounted only while recording or speaking; with reduced motion it becomes a static level meter.

## 11. Forms, concurrency and notes
**Forms [S1]**
- react-hook-form with zod schemas typed as `satisfies z.ZodType<Schemas['QuoteHeaderUpdate']>`.
- Client-side validation is for UX only. A server 422 maps by `loc` to fields.
- An error summary at the top links to each field, and focus moves to the first invalid field.

**Fields**
- MoneyField and QuantityField are text inputs with `inputMode="decimal"`, validated as decimal strings (up to 14 integer and 4 fractional digits) and formatted on blur.
- The RAC NumberField is used for integers only.
- DatePicker is zone-aware.

**Dirty guard**
- `AppLink` checks a dirty registry and asks for confirmation.
- `beforeunload` is registered.
- A dirty-form snapshot in sessionStorage allows restore.

**Line edits**
- Commit on Enter or blur.
- The server returns the recalculated document; totals show "Recalculating…" until then.
- There are no client-side totals.

**409 conflict merge (`lib/merge.ts`, a pure function)**
1. **Inputs:** `base` is the version the user started from, `mine` is the dirty fields, `theirs` is `current` from the 409 response.
2. A field changed only by them is adopted, with a notice such as "Remarks updated by Meera at 10:42".
3. A field changed only by me is kept.
4. A field both changed to the same value is not a conflict.
5. A field both changed to different values goes to a ConflictDialog, where the user picks Mine, Theirs, or edits.
6. The base and `expected_version` become `current`, and the user must press Save again.
7. Nothing is ever overwritten silently.

**Collection lines:** each line has its own version; on a 409 that line reloads with an inline message.

**Conflict-aware autosaved notes [S1]** (one internal note per record)
- **When it saves:** 1 s after typing stops, on blur, and on `visibilitychange` (fetch with `keepalive`). One request is in flight at a time and the latest text is queued.
- **Request:** `PUT {body, expected_version}`.
- **Status line** (live region): "Saving…", "Saved 10:42", "Offline — kept on this device", "Not saved — Retry", "Conflict".
- **On 409:** a panel shows their text with author and time next to mine. Options:
  - Keep mine: re-save against the new version.
  - Use theirs.
  - Combine: an editable merge.
- **Unsaved text** is mirrored to `localStorage` under `lk:note:{userId}:{type}:{id}`. On reload the user is offered a restore with its timestamp. The copy is cleared after a successful save and on logout.
- **Visibility:** read-only without the capability, and never printed in PDFs.

## 12. Global search [S1]
**Opening:** `/` (when not typing in a field) or Ctrl/Cmd+K opens SearchDialog. It is an RAC Autocomplete with a SearchField and a Menu grouped by entity type.

**Behaviour**
- 250 ms debounce, at least 2 characters, stale requests cancelled with AbortController.
- An empty query shows recent searches (with a clear control) and recently opened records.

**Results**
- Each result shows title, business key, subtitle and status.
- Enter opens the canonical URL. "See all results" goes to `/search?q=`, which paginates per group.
- Submitting or selecting calls `POST /search/recent`.
- Results and group totals are permission-filtered on the server.

**Shortcuts** can be turned off in preferences (WCAG 2.1.4).

**Contract:** `GET /search?q=&types=&per_group=5` and `GET|POST|DELETE /search/recent`.

## 13. Tables and drawers
**DataTable**
- A native `<table>` with a caption, `th scope`, sortable header buttons with `aria-sort`, and right-aligned tabular numbers.
- Sorting, filtering and pagination are server-side and synced to the URL. Pagination shows real totals.
- A per-column `priority` drives the phone view: a list of rows (title, key, status, amount) linking to the detail screen.

**Inline-edit cell**
- Shows a button such as "Edit quantity, 240 pcs" that becomes a field.
- Enter saves, Escape cancels.
- Optimistic only on drafts, with rollback on error.

**Drawer**
- An RAC Modal anchored right, 480–640 px wide.
- Escape closes it and focus returns to the trigger.
- On phones it is a full-screen sheet.

## 14. Design system [S1]
**Tokens:** defined in `tokens.css` and mapped through Tailwind `@theme inline`. `--color-*: initial` removes the default palette, so purple and neon utilities do not exist.

| Token | Light | Dark |
|---|---|---|
| canvas | #F6F5F0 | #121614 |
| surface | #FFFFFF | #1A201D (raised #222924) |
| ink | #202723 | #E9ECE6 |
| ink-muted | #55605A (≈6.0:1 on canvas) | #A9B2AB |
| primary (forest) | #214C3C (white text ≈9.7:1) | #7FB89A with #0E1712 text |
| accent (sand, decorative only; ≈2.4:1, never text or the sole state cue) | #C8A064 | #D9B57A |
| border (separators) | #E0E4DC | #2C3530 |
| border-control (≥3:1 on white and canvas) | #7D8780 | #6B7670 |
| sage (suggestion strip) | #EDF2EA | #1F2B24 |
| warning text / background | #8A5A00 / #FBF3E4 | #E8B65A / #2A2416 |
| danger text | #A63A2B | #F08A7A |
| focus ring | 2 px forest + 2 px offset | 2 px #E3C48F |

**Theme**
- The `lk_ui` cookie holds theme, sidebar and rail state. The root layout renders it server-side as `<html data-theme>`.
- `system` resolves through CSS `prefers-color-scheme`.
- Preferences are persisted in `user_ui_preferences`; FastAPI sets the cookie on login and on PATCH.
- The result is no flash of the wrong theme and no inline script.

**Typography**
- **Body:** Manrope Variable, self-hosted (OFL; the licence ships in `public/licences`). Fallbacks: Noto Sans Devanagari, then the system-ui stack.
- **Mono:** a system stack, used only for identifiers.
- **Numerals:** a `.num` class (`tabular-nums`) on Money, Quantity, Dimension and numeric table columns.
- **Scale:**
  - Greeting: `clamp(28px, 3vw, 40px)`, weight 700, -0.02em.
  - Section labels: 12 px, weight 600, uppercase, 0.08em, ink-muted.
  - Item title: 18 px, weight 650.
  - Body: 15 px; tables: 14 px.

**Shape**
- 4 px spacing grid.
- Radius: 8 px on controls, 12 px on cards.
- Buttons: 36 px tall, 44 px under `pointer: coarse`; 8 px radius, no pills.
- Cards are reserved for proposals, documents and distinct decisions.

**Motion**
- 150 / 180 / 220 ms with `cubic-bezier(.2,0,0,1)`, for drawers, menus and state changes.
- `prefers-reduced-motion` sets durations to 0 ms.

**Banned patterns** (enforced by `design-lint.test.ts` scanning `src/`)
- `backdrop-blur` (glass panels).
- Gradients.
- Purple, violet and fuchsia colours.
- Infinite animations outside skeleton and recording states.
- "AI-powered"-style copy.
- `rounded-full` buttons.
- lucide `Bot*` icons.

The KPI-card-wall rule goes on the review checklist.

## 15. State catalogue (`StateView`, banners and toasts; each with real copy and a real action)
- **Loading:** layout-shaped skeletons, shown after 150 ms.
- **Empty:** explains why, and offers the next permitted action.
- **Error:** what failed, the request id, and Retry.
- **Offline:** commits disabled with the reason; drafts kept locally and labelled.
- **Stale:** the last-updated time and Retry.
- **Conflict:** see §11.
- **Success:** a toast plus a persistent receipt link.
- **Permission denied.**
- **Not available:** for missing or out-of-scope records.
- **Demo:** "Simulated — nothing was sent".
- **Not connected:** for integrations.

**No dead buttons**
- Button props are a TypeScript union that requires `onPress`, `href` or `type="submit"`.
- A disabled button requires a `disabledReason`, which is rendered as its accessible description.
- Toast uses RAC `UNSTABLE_Toast`, wrapped behind our own component.

## 16. Accessibility
- **Structure:** skip link; landmarks (banner, nav "Primary", main, aside "Assistant").
- **Focus:**
  - On client-side navigation, focus moves to the page `h1` and the Next route announcer reads the title.
  - RAC dialogs trap focus and restore it on close.
  - A visible focus ring everywhere.
- **Content:**
  - Every control is labelled.
  - Status uses text as well as colour.
  - Tables are semantic.
- **Touch and layout:** 44 px targets on coarse pointers; layouts reflow down to 320 px.
- **Language:** `lang` follows the user's language, with `lang="hi"` spans for Hindi transcripts.
- **Live regions:** toasts, voice state and autosave status.
- **Preferences:** reduced motion is respected; a `?` dialog lists shortcuts, which can be turned off.

## 17. Backend `ui` module [S1]
**Tables**

`user_ui_preferences` (user-owned, so no `company_id`)

| Column | Type / constraint |
|---|---|
| id | uuid7 PK |
| user_id | FK to users, UNIQUE |
| theme | CHECK in (system, light, dark), default system |
| sidebar_collapsed | bool |
| context_rail_open | bool |
| density | CHECK in (comfortable, compact) |
| shortcuts_enabled | bool, default true |
| created_at / updated_at / created_by / updated_by | standard audit columns |
| version | int |

`recent_record_views`

| Column | Type / constraint |
|---|---|
| id | uuid7 PK |
| company_id | tenant scope |
| user_id | FK |
| entity_type | text |
| entity_id | uuid |
| viewed_at | timestamptz |

- Constraints: UNIQUE `(company_id, user_id, entity_type, entity_id)`; INDEX `(company_id, user_id, viewed_at DESC)`.
- Pruned to 50 rows per user in the same transaction as each insert.

**Endpoints**
- `GET /session/bootstrap` returns:
  - User and membership; company and branches.
  - `time_zone`, `locale`, `server_now`, `greeting_period`.
  - `permissions[{key, scope}]` and preferences.
  - Demo and channel status.
  - Inbox count and briefing version.
  - CSRF rotation.
- `GET|PATCH /me/ui-preferences`: PATCH takes `expected_version` and sets the `lk_ui` cookie.
- `GET|POST /me/recent-records`.
- `GET /poll`.
- `GET /links/resolve?type=&key=`: returns 404 when the record is not readable.

**Invariants**
- Recent records are re-checked in batch against each module's read policy, so records the user can no longer read disappear.
- Preferences can never change permissions or mandatory controls.
- Preference changes are audit-logged.

**Events:** none emitted (UI state is not a business event) and none consumed.

**Test-support router** (exists only when `APP_ENV=test`; a contract test asserts 404 in every other environment)
- Create a tenant from a template, with its own clock.
- Log in as a user (sets the session cookie).
- Set a tenant's clock.
- Emit a domain event.
- Set provider fault modes (ai, stt, tts, whatsapp: ok, fail or slow).
- Return fixture references.

## 18. Verification strategy
**Test layers**
1. **Backend unit (pytest with hypothesis).** Pure rules: commercial math, MOQ, surcharge, price selection, packer invariants, priority ranking, workday and zone boundaries, state transitions, CSV escaping and alias normalisation.
2. **Backend integration against real PostgreSQL.**
   - pgserver bundles PostgreSQL 16.2 and has a Windows wheel, so no Docker is needed.
   - A session fixture starts a cluster in `.pytest_pg/`, runs `alembic upgrade head` once and builds a seeded template database.
   - Each test gets a fresh database via `CREATE DATABASE … TEMPLATE`.
   - Concurrency tests use parallel connections.
3. **Contract tests.**
   - An OpenAPI snapshot and a check that money is serialised as strings.
   - Provider adapters (WhatsApp, STT/TTS, LLM, and S3 via moto): the same suite runs against the demo and live adapters, using `httpx.MockTransport` and recorded fixtures.
   - Test-support is absent outside the test environment.
4. **Web unit (vitest, node).** `merge.ts`, `voiceMachine`, navigation filtering, money formatting, the invalidation map, route-manifest coverage, token contrast (parses `tokens.css`: text ≥4.5:1, UI ≥3:1) and design-lint.
5. **End-to-end (Playwright 1.64).**
   - **Projects:** desktop 1440×900, tablet 834×1194 with touch, phone 390×844 with `isMobile` and touch, all on Chromium; an optional WebKit phone smoke run.
   - **`webServer`:** the backend test server (pgserver, migrations, demo adapters) on :8100, and `next build && next start` on :3100.
   - **Isolation:** a new tenant per test, which also exercises company scoping, so tests can run in parallel workers (4 locally, 2 in CI).
   - **Determinism:**
     - Tenant clock fixed at 2026-10-12T03:30Z (Monday 09:00 IST), plus `page.clock.setFixedTime`.
     - Seeded fictional fixtures:
       - Customers: Nordhaus, Maison, Berg & Co.
       - Product: oak tray at EUR 24 with carton 24.
       - Users: Sahil (management), Meera (sales), Ravi (restricted sales), Arjun (operations), Priya (finance), Admin.
       - An empty tenant.
     - No passwords in the repository: tests log in through test-support, plus one real-login test using a generated password.
   - **Base fixture:** fails a test on page errors, console errors or unexpected 5xx responses.
   - **Accessibility:**
     - AxeBuilder with the wcag2a, wcag2aa, wcag21aa and wcag22aa tags.
     - Runs on every manifest route × 3 viewports × 2 themes, plus open dialog, drawer and search states.
     - Zero violations.
   - **Screenshots:**
     - `e2e/visual/capture.spec.ts` writes `test-results/screens/{viewport}/{theme}/{route}.png` and a contact sheet, with animations disabled and fonts loaded.
     - They are inspected at each slice; pixel diffs are not a CI gate.
   - **Structural checks:**
     - Touch-target sizes.
     - A dead-control crawler.
     - A path to Today on every route.
     - A tabular-figures check: "1111" and "0000" must render at equal width.

**Commands**
- `npm run check`: eslint, tsc, vitest and `uv run pytest backend/tests/unit -q`. Target under 2 minutes.
- `npm run test:api`: backend integration and contract suites.
- `npm run api:generate` / `npm run api:check`.
- `npm run test:e2e`, `npm run test:e2e:smoke`, `npm run test:a11y`, `npm run screens`.

**CI tiers**
- **Pull requests:** check, test:api, api:check, build, the E2E smoke subset (desktop and phone) and a11y.
- **Main and nightly:** the full A–N matrix on all three viewports, with the screenshots as an artifact.
- **Slice completion** requires that slice's scenarios to pass on the full matrix, with the evidence recorded in `docs/BUILD_STATE.md`.

## 19. Scenario → test map
Backend paths are under `backend/tests`; E2E paths are under `apps/web/e2e`.

**A — Today scope and isolation**
- `integration/briefings/test_briefing_scope.py`
- `integration/security/test_isolation_matrix.py`: a restricted user against briefing, search, agent tools, CSV/PDF export, GET by id, notes, attachments and activity; responses must contain no sentinel strings.
- `scenarios/a-today-scope.spec.ts`:
  - Meera sees a correct greeting, at most 5 items, source links that resolve and "Today, 5:00 PM".
  - Sahil sees cross-team decisions.
  - Ravi has no Finance nav, `/finance` is denied, Meera's quote URL is "not available", search returns no group for her customer, and the sentinel text is absent from the DOM.

**B — Briefing stability**
- `unit/briefings/test_workday_boundaries.py`: hypothesis over instants around 00:00 IST, weekends and shifts.
- `integration/briefings/test_source_change_refresh.py`
- `integration/briefings/test_ai_outage_fallback.py`
- `scenarios/b-briefing-stability.spec.ts`:
  - A source change during Listen does not reorder the list and shows "1 update".
  - Applying it keeps the same item id with a refreshed recommendation.
  - Snooze survives a reload.
  - An acknowledgement over WhatsApp syncs to the web.
  - The weekend boundary behaves explicitly.
  - An AI fault shows the fallback banner.

**C — Nordhaus quote path**
- `integration/sales/test_nordhaus_quote_path.py`
- `contract/agents/test_prepare_quote_tool.py`
- `scenarios/c-nordhaus-quote.spec.ts`:
  - The command produces a card showing 240, €24.00, €5,760.00, "Draft — not sent" and the Demo label.
  - Review shows the matching line.
  - A next-action item appears.
  - After a catalogue price change, the snapshot is unchanged and an explicit notice is shown.

**D — Commercial rules**
- `unit/commercial/test_quote_math.py`
- `integration/documents/test_output_channels_agree.py`
- `scenarios/d-commercial-rules.spec.ts`:
  - The surcharge toggle moves the server total from 4,800 to 5,200.
  - The CSV is parsed and agrees.
  - The advisory shows 216 / 9 cartons.
  - A zero price shows "unavailable".

**E — Currency and costing**
- `integration/pricing/test_currency_switch.py`
- `integration/security/test_costing_redaction.py`
- `scenarios/e-currency-costing.spec.ts`

**F — Ownership, approval and numbering**
- `integration/security/test_quote_idor.py`: parametrised over every quote sub-endpoint.
- `integration/agents/test_proposal_authority.py`
- `integration/sequences/test_concurrent_numbering.py`
- `scenarios/f-ownership-approval.spec.ts`

**G — Imports and search**
- `integration/imports/test_reimport_idempotent.py`, `test_quarantine.py`
- `unit/exports/test_csv_formula_escape.py`
- `integration/catalogue/test_filter_pagination.py`
- `integration/search/test_custom_product_name.py`
- `scenarios/g-imports-search.spec.ts`

**H — Cutting**
- `unit/cutting/test_packer_properties.py`
- `integration/cutting/test_plan_persistence.py`
- `scenarios/h-cutting-canvas.spec.ts`: SVG rectangles do not overlap and stay inside the margin; grain-locked pieces are not rotated; counts equal the table; a reload preserves results.

**I — Order to return**
- `integration/fulfilment/test_order_to_return.py`, `test_reservation_concurrency.py`, `test_duplicate_events.py`
- `scenarios/i-order-to-return.spec.ts`

**J — Voice**
- `integration/voice/test_transcript_idempotency.py`
- `scenarios/j-voice.spec.ts`: uses a fake media device; asserts exactly one message POST, a clarification card, interrupt stopping playback, a usable text path after mic denial, and an offline draft with no success receipt.

**K — WhatsApp**
- `contract/whatsapp/test_webhooks.py`
- `scenarios/k-whatsapp-demo.spec.ts`

**L — Legacy parity**
- `integration/legacy/test_parity_quotes_custom_challans.py`
- `integration/documents/test_pdf_unicode_pagination.py`
- `scenarios/l-legacy-parity.spec.ts`: includes a note conflict across two browser contexts.

**M — Migration and restore**
- `integration/migration/test_dry_run.py`
- `integration/ops/test_backup_restore_rehearsal.py`
- `scenarios/m-migration-report.spec.ts`

**N — Desktop, tablet and phone usability**
- `responsive/n-shell.spec.ts`, `n-keyboard.spec.ts`, `n-touch-targets.spec.ts`, `n-states.spec.ts`, `n-no-dead-controls.spec.ts`, `n-no-fabricated-metrics.spec.ts`
- `a11y/n-axe-sweep.spec.ts`
- `visual/capture.spec.ts`
- Web unit tests: `tokens.contrast.test.ts`, `design-lint.test.ts`, `routes.coverage.test.ts`

## 20. Slices
**S1**
- Scaffold, tokens, fonts and primitives.
- Shell, auth pages, bootstrap and the `ui` module.
- Today; Inbox tasks and approvals.
- Search; product read; party minimum.
- Quote vertical: configurator drawer, document, lines, commercial summary, review, preview/PDF.
- Notes, profile and preferences.
- Test infrastructure and test-support.
- Tests: A, C, D, and baseline N.

**S2**
- Products in full: forms, media, price lists, taxonomy, completeness.
- Imports, custom products, cutting canvas, challans.
- Users and roles; revisions, compare and duplicate; attachments and related; activity.
- Tests: E, F, G, H, L.

**S3**
- Assistant rail, streaming and cards.
- Voice and Listen to my day.
- WhatsApp channel settings, `/r` links, automations, integrations health.
- Tests: B, J, K.

**S4**
- Parties in full, enquiries, samples, orders, inventory.
- Purchasing, production, QC, dispatch, returns.
- Tests: I.

**S5**
- Finance, migration report, offcuts, what-if views, sample lineage.
- Tests: M.

**S6**
- Full matrix on all viewports, axe on every route, screenshot review, dead-control audit.
- Fixes, and evidence recorded.

## 21. Future scope
- Service-worker offline sync.
- Manual drag placement on the cutting canvas, with server validation.
- Hindi UI translation. Voice language preferences already exist, and UI copy is centralised in `messages/en.ts`.
- Saved table views.
- Push transport (SSE or websocket) for briefings and inbox.
- A pixel-diff gate on pinned Linux runners.
- A chart library, only when there is a real need.
- Adopting TypeScript 7.


## Decisions
- **Use react-aria-components 1.22 as the only headless primitive library; reject Radix.** — RAC covers what an ERP needs: ComboBox, DatePicker with time-zone-aware @internationalized/date, NumberField, Autocomplete (for the command palette and async search), Table, Menu, Modal, Tabs, plus unified press/touch handling. Radix lacks a combobox, date picker and number field, which would force mixing libraries. Toast is UNSTABLE_ in RAC, so it is wrapped behind our own component.
- **Keep the API same-origin: the browser calls /api/v1 and Next rewrites (beforeFiles) forward to FastAPI. No CORS, no Next route handlers, no Server Actions.** — Cookie sessions work without cross-origin configuration and downloads are plain links with no token in the query string. There is one write path (FastAPI), shared with the agent tools, and one OpenAPI contract. beforeFiles means no Next route can shadow /api.
- **Exclude /api, _next and static files from the proxy.ts matcher; proxy.ts only redirects missing sessions, sets the CSP nonce and passes the path header.** — Next 16 buffers request bodies of proxy-matched requests, up to 10 MB by default, which would silently truncate uploads. Real authentication happens in the bootstrap call and on every FastAPI endpoint.
- **CSRF uses an HttpOnly SameSite=Lax session cookie, a signed double-submit token (readable lk_csrf cookie echoed in X-CSRF-Token) and Origin/Sec-Fetch-Site checks.** — Layered protection that works with same-origin fetches, needs no server-side token store, and keeps the session unreadable to JavaScript.
- **Pin TypeScript 5.9.x rather than 7.0.2.** — TypeScript 7.0 has no JS compiler API. openapi-typescript 7.13 peers typescript ^5.x, and eslint-config-next needs the API. Next 16.4 type-checks through the local tsc CLI, so nothing is lost now; adopt TS 7 when 7.1's API lands and the tools support it.
- **Leave cacheComponents off; never cache per-user data on the Next server; never send private media through the next/image optimiser.** — Every app route depends on the session cookie, so there is nothing safely shareable to cache, and Cache Components would add Suspense constraints for no gain. Server-side caching of authenticated responses or images is a cross-user leak risk.
- **Server components prefetch into TanStack Query and hydrate; client components handle all interaction and mutations; briefings and inbox poll every 60 s; only agent runs use SSE.** — First paint of deep links is fast and the shell is authorised up front. The same queryOptions serve server and client. Polling is cheap, robust through rewrites and enough for briefing updates. SSE is needed only where streaming is required.
- **Detail tabs are route segments; drawers and the rail are driven by URL search parameters; detail URLs use UUIDs, with /go/[type]/[key] for business keys and /r/[ref] for short-lived action links.** — Every view and panel is deep-linkable and works with the back button without intercepting routes. UUID URLs are uniform and encoding-safe. The resolvers serve voice, search and WhatsApp links.
- **A typed route manifest (lib/routes.ts) is the single source for navigation, breadcrumbs, a11y sweeps, the dead-control crawl and screenshots; a vitest test requires every page.tsx to be registered.** — Guarantees every view is directly reachable and covered by the automated sweeps. Navigation can hide areas until they are actually implemented and authorised, so there are no dead links.
- **Money and quantities travel as decimal strings; the client never does arithmetic; totals always come from the server after each edit.** — Meets the Decimal-end-to-end and single-calculation requirements. Intl.NumberFormat formats decimal strings exactly. A lint test bans parseFloat/Number in money code.
- **Every detail response carries server-computed capabilities and allowed_transitions; global permission keys drive navigation only.** — Ownership, scope and state determine what is allowed on a particular record. Duplicating that logic in the client would drift and could expose actions the server then rejects.
- **Conflicts resolve with a deterministic field-level three-way merge: theirs-only changes are adopted, mine-only kept, true conflicts chosen per field, and an explicit re-save is required. Notes are one autosaved internal note per record with a manual conflict panel and a local unsaved mirror.** — No edit is ever silently overwritten, and the merge is a pure, unit-testable function. Keeping a single note per record matches legacy behaviour and keeps autosave simple.
- **Tables are native <table> elements with RAC controls inside; phones get a priority-driven row-list view.** — Semantic tables are the most robust for screen readers, while inline edits use accessible fields. The mobile list is a purposeful detail view rather than horizontal scrolling.
- **Tailwind v4 uses semantic CSS-variable tokens with the default palette removed (--color-*: initial). The theme and sidebar state are rendered from an lk_ui cookie mirrored from server-side preferences.** — Banned purple/neon utilities cannot exist. There is no flash of the wrong theme and no inline script, which keeps the CSP strict, and preferences persist across devices.
- **Fonts: self-hosted Manrope Variable (OFL 1.1), then Noto Sans Devanagari (unicode-range), then the system stack; system mono for identifiers; tabular-nums on all numerics.** — The licence allows self-hosting with no runtime third-party requests. Manrope has no Devanagari, which Hindi names and transcripts need, and per-glyph fallback covers ₹ if it turns out to be missing.
- **No chart library.** — No requirement needs charts; ageing and metrics are better served by semantic tables. This avoids an unused dependency and KPI-wall temptation.
- **End-to-end isolation is one tenant per test, created through a test-support router that exists only when APP_ENV=test, with a per-tenant fixed clock and fault injection. Integration tests use real Postgres via pgserver.** — Tests are parallel-safe, deterministic and exercise company scoping, with no Docker needed on this machine. Contract tests prove test-support is absent outside the test environment.
- **Screenshots are captured for inspection, not used as a pixel-diff gate. axe (WCAG 2.2 AA tags) runs on every manifest route in both themes and all three viewports with zero allowed violations.** — Pixel diffs are unreliable across Windows and Linux font rendering. Captures still support required visual inspection, and axe plus keyboard, touch-target and dead-control specs give objective gates.
- **Keyboard shortcuts ('/' and Ctrl/Cmd+K) can be turned off in preferences; a '?' dialog lists them.** — WCAG 2.1.4 requires single-character shortcuts to be disableable or remappable.

## Risks
- SSE through Next rewrites may be buffered by compression or proxy layers. Mitigation: the backend sends Cache-Control no-transform and X-Accel-Buffering: no; an E2E test asserts the first event arrives before the run completes; fall back to polling the run status.
- Large uploads through external rewrites must stream rather than buffer. Verify with an upload at the size limit in E2E early in S2; if it fails, switch to backend-issued presigned PUTs.
- RAC UNSTABLE_Toast and Autocomplete APIs may change. Mitigation: wrap them, pin the version, upgrade deliberately.
- TypeScript pinned to 5.x diverges from the 'latest' list; re-evaluate when TS 7.1 ships an API and openapi-typescript and eslint support it.
- Manrope's ₹ glyph coverage is unconfirmed (the fontsource unicode ranges are subset ranges, not proof of glyphs). Check with fontTools at implementation; the fallback font chain covers the gap either way.
- The route map is large. There is a risk of nav links to unbuilt screens; the manifest's slice flag and the dead-control crawler prevent shipping them.
- Windows-specific E2E friction (pgserver cluster startup, Playwright browsers, path lengths, WebKit media differences). Keep WebKit as optional smoke and document setup in docs.
- Hydration mismatches from time zones and relative times. Mitigation: render all times from bootstrap server_now and the user's zone, never the browser zone.
- Full-matrix E2E runtime could grow beyond acceptable CI time. Mitigation: tenant-per-test parallelism, smoke and full tiers, and running scenario specs per relevant viewport rather than every step on all three.
- Field-level redaction depends on every backend schema omitting restricted fields. The client cannot enforce it, so the isolation matrix and sentinel-string tests are essential.
- Shared record contracts (notes, attachments, relations, activity, search) span modules; if no platform designer claims them, the frontend slice blocks. Assign ownership in the platform design.

## Acceptance tests
- [A / e2e] apps/web/e2e/scenarios/a-today-scope.spec.ts: Meera at fixed Mon 09:00 IST sees 'Good morning, Meera.', at most 5 top items whose source links resolve, due shown as 'Today, 5:00 PM'; Sahil sees cross-team decision items
- [A / e2e] apps/web/e2e/scenarios/a-today-scope.spec.ts: restricted Ravi has no Finance nav, /finance shows PermissionDenied, Meera's quote URL shows not-available, search for her customer returns no group, sentinel strings absent from DOM
- [A / integration] backend/tests/integration/security/test_isolation_matrix.py: restricted user × {briefing, search, agent tools, CSV/PDF export, GET by id, notes, attachments, activity} returns 404/redacted with no sentinel leakage
- [A / integration] backend/tests/integration/briefings/test_briefing_scope.py: sales briefing only contains own authorised tasks with Asia/Kolkata due dates; management sees cross-team decisions
- [B / unit] backend/tests/unit/briefings/test_workday_boundaries.py: hypothesis over instants around 00:00 IST, weekends and shift starts produces the correct briefing day key
- [B / integration] backend/tests/integration/briefings/test_source_change_refresh.py and test_ai_outage_fallback.py: stable issue id, invalidated recommendation, snooze/handled persistence, deterministic fallback with timestamps
- [B / e2e] apps/web/e2e/scenarios/b-briefing-stability.spec.ts: source change during Listen does not reorder and shows '1 update'; Show keeps the item id with refreshed recommendation; snooze survives reload; WhatsApp ack syncs to web; weekend clock and AI fault behave explicitly
- [C / integration] backend/tests/integration/sales/test_nordhaus_quote_path.py: resolves Nordhaus and the oak tray, snapshots the EUR export price, total 5760.0000 EUR, scoped next-action task, snapshot unchanged after a catalogue price change
- [C / e2e] apps/web/e2e/scenarios/c-nordhaus-quote.spec.ts: command bar request yields a quote_draft card with 240, €24.00, €5,760.00, 'Draft — not sent' and a Demo label; review page line matches; next-action item appears in Today/Inbox
- [D / unit] backend/tests/unit/commercial/test_quote_math.py: recommended 216 at EUR 24 / carton 24; 4800 off→4800, on→5200; 5000 no surcharge; zero/missing price unavailable; non-EUR no fabricated threshold (hypothesis)
- [D / e2e] backend/tests/integration/documents/test_output_channels_agree.py plus apps/web/e2e/scenarios/d-commercial-rules.spec.ts: UI, API, PDF and CSV totals agree after the surcharge toggle
- [E / e2e] apps/web/e2e/scenarios/e-currency-costing.spec.ts: currency dialog offers only reprice or dated conversion, unknown FX blocks; sales user sees no Costing tab and the costing sentinel is absent from DOM and CSV
- [E / integration] backend/tests/integration/security/test_costing_redaction.py: costing absent from custom product responses, exports and captured model context
- [F / integration] backend/tests/integration/security/test_quote_idor.py: every quote sub-endpoint (lines, revise, status, notes, PDF, CSV, duplicate) returns 404 for another owner's ids
- [F / integration] backend/tests/integration/agents/test_proposal_authority.py and sequences/test_concurrent_numbering.py: revoked permission blocks execution; edited approved proposal needs re-approval; 50 parallel creates get unique numbers
- [F / e2e] apps/web/e2e/scenarios/f-ownership-approval.spec.ts: guessed URLs show not-available; approval card shows 'Approval no longer valid' after a change
- [G / e2e] apps/web/e2e/scenarios/g-imports-search.spec.ts: second import of the same XLSX reports no new rows; quarantine shows row numbers; thickness filter page 2 counts correct; '/' search finds custom product_name with deep link
- [G / unit] backend/tests/unit/exports/test_csv_formula_escape.py: hypothesis strings starting with = + - @ tab or CR are escaped
- [H / unit] backend/tests/unit/cutting/test_packer_properties.py: hypothesis: no overlaps, within margin bounds, gaps respected, grain-locked never rotated, required = placed + unfit, area metrics reconcile
- [H / e2e] apps/web/e2e/scenarios/h-cutting-canvas.spec.ts: SVG rectangles do not overlap and lie inside the usable boundary; grain-locked pieces have no rotation marker; canvas counts equal placement table; save/reload preserves inputs and results
- [I / integration] backend/tests/integration/fulfilment/test_order_to_return.py, test_reservation_concurrency.py, test_duplicate_events.py
- [I / e2e] apps/web/e2e/scenarios/i-order-to-return.spec.ts: double Accept creates one order; challan issue shows exactly one ledger movement; partial return linked to its original line; cancel shows a reversal entry
- [J / e2e] apps/web/e2e/scenarios/j-voice.spec.ts: fake media device; partial→final→edit→Send produces exactly one message POST; ambiguous customer gives a clarification card; interrupt stops playback; mic denial leaves a usable text path; offline shows a local-draft label and no success receipt
- [J / integration] backend/tests/integration/voice/test_transcript_idempotency.py: same client_message_id for partial and final creates one message; a corrected transcript updates the draft only
- [K / contract] backend/tests/contract/whatsapp/test_webhooks.py: signature rejection, replay, out-of-order status, duplicate gives a single effect, employee unlink, expired approval, opt-out and closed window, all from fixtures
- [K / e2e] apps/web/e2e/scenarios/k-whatsapp-demo.spec.ts: Settings shows Demo/Not connected; simulated thread labelled Demo; an expired /r/{ref} shows an explicit expiry page
- [L / e2e] apps/web/e2e/scenarios/l-legacy-parity.spec.ts: duplicate quote/custom/challan, two-context note conflict panel, URL-persisted filters, print preview, CSV line counts and creator names
- [L / integration] backend/tests/integration/documents/test_pdf_unicode_pagination.py: long document paginates with repeated headers, no lost text, € ₹ and Devanagari present, internal notes and costs omitted
- [M / integration] backend/tests/integration/migration/test_dry_run.py and ops/test_backup_restore_rehearsal.py: counts and totals reconcile, rerun without duplicates, no stock from legacy challans, restore proven on pgserver
- [N / e2e] apps/web/e2e/responsive/n-shell.spec.ts at 1440/834/390: sidebar vs icon rail vs bottom nav (Today, Inbox, Work, More), rail collapsed at tablet, visible path to Today on every manifest route
- [N / e2e] apps/web/e2e/responsive/n-keyboard.spec.ts: keyboard-only journey Today → '/' search → quote → review → approve, with visible focus and focus restored after dialogs
- [N / e2e] apps/web/e2e/responsive/n-touch-targets.spec.ts: every interactive element on tablet and phone is at least 44×44 px (inline text links allowlisted)
- [N / e2e] apps/web/e2e/responsive/n-states.spec.ts: empty, loading, error with request id, offline, stale, conflict, permission-denied and success states render real copy and actions
- [N / e2e] apps/web/e2e/responsive/n-no-dead-controls.spec.ts: crawler over manifest routes; links resolve, every control has an accessible name, safe controls produce an observable effect, disabled controls expose a reason
- [N / e2e] apps/web/e2e/responsive/n-no-fabricated-metrics.spec.ts: empty tenant shows no non-zero figures; seeded tenant's displayed counts equal API counts
- [N / e2e] apps/web/e2e/a11y/n-axe-sweep.spec.ts: axe wcag2a/aa/21aa/22aa on every manifest route × 3 viewports × light/dark plus open dialog/drawer/search, zero violations
- [N / e2e] apps/web/e2e/visual/capture.spec.ts: deterministic full-page screenshots per route, viewport and theme, plus a contact sheet; tabular-figure width check
- [N / unit] apps/web/src/styles/tokens.contrast.test.ts, src/lib/design-lint.test.ts, src/lib/routes.coverage.test.ts: token contrast thresholds, banned-pattern scan, every page registered in the manifest
- [invariant / unit] apps/web/src/lib/merge.test.ts and src/features/voice/voiceMachine.test.ts: three-way field merge never drops a user edit; voice reducer never emits two sends for one client_message_id
- [invariant / contract] backend/tests/contract/test_openapi_contract.py: OpenAPI snapshot matches the committed schema, money amounts serialise as strings, test-support routes return 404 outside APP_ENV=test
