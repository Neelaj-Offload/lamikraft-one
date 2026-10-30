# Lane report: web — Slice 1, wave 1 (web foundation)

Branch `lane/s1w1-web` (worktree `D:\lk-wt\web`, env slot 5). This lane has no migration and no backend
changes. Status: **done for this wave**. `npm run check -- --keep-going` passes every step (ruff, pytest unit and
contract 72 passed, alembic heads = 1, api:check, web lint, web typecheck, web vitest).

## Implemented (all under `apps/web/`)

### 1. Design system (`src/components/ui/**`)
- `button.tsx`: `Button` (primary, secondary, quiet, danger; 44 px on coarse pointers, 36 px with a mouse; pending
  label instead of a spinner) and `IconButton` (required accessible name). The props type allows only `onPress` or
  `type="submit"`, and a disabled button requires `disabledReason`, which becomes its accessible description.
- `link.tsx`: `Link` and `LinkButton` (React Aria links routed through the Next router; real `<a href>`).
- `text-field.tsx` (`TextField`, `TextArea`), `number-field.tsx` (`NumberField` for DecimalStr: a text input with
  `inputMode="decimal"`, normalised on blur, never parsed to a float, with a formatted money or quantity preview),
  `select.tsx` (`Select`, `ComboBox`), `choice.tsx` (`Checkbox`, `Switch`, `RadioGroup`), `search-field.tsx`,
  `date-picker.tsx` (business dates stay `YYYY-MM-DD`; instants are edited as wall time in the session zone, with
  the zone shown, and saved as UTC `Z`).
- `dialog.tsx` (`Dialog`: a centred modal that is a bottom sheet on phones; `Drawer`: 480/640 px end drawer that is
  full screen on phones; 220 ms in, 160 ms out, flat `--lk-scrim`, no blur), `menu.tsx` (`Popover`, `Menu`,
  `MenuItem`, selectable `MenuSection`), `tabs.tsx` (`NavTabs` as a link `<nav>` with `aria-current`, plus an
  ARIA `Tabs` for in-page panels), `tooltip.tsx`.
- `toast.tsx`: a `toast` API wrapping `UNSTABLE_Toast`, with receipt links (success and info dismiss after 6 s;
  warnings and errors stay until closed), plus `LiveAnnouncer` fed by `src/lib/a11y/announcer.ts`.
- `badge.tsx`: `Badge`, `StatusPill` (dot plus text), `DemoBadge`, `NotConnectedBadge`.
- `data-table.tsx` and `data-table-model.ts`: a native `<table>` with caption, `th scope`, sortable header buttons
  with `aria-sort`, right-aligned tabular numbers and row selection (row and page checkboxes). It has
  `OffsetPagination` ("Showing 51–100 of 312") and `KeysetPagination`. Below 768 px it renders a linked list built
  from column `mobile` roles; `mobileCell` keeps the phone row free of nested links.
- `description-list.tsx`, `format.tsx` (`Money`, `Quantity`, `LocalDateTime`, `LocalDate`, `RelativeTime`),
  `skeleton.tsx`, and `states.tsx`: `StateView`, `EmptyState`, `Loading` (appears after 150 ms), `ErrorState`
  (reads problem+json, shows the request id and Retry; renders Offline on a network error and a calm "not available
  yet" when the endpoint does not exist), `Offline`, `Stale`, `Conflict` (409 three-way hint), `PermissionDenied`,
  `NotAvailable`, `Success`.
- `styles.ts` (shared class recipes) and `icons.tsx` (a small set of hand-drawn SVG icons; no icon dependency).
- Tokens (`src/app/globals.css`): added `--lk-on-danger` (6.44:1 light, 7.68:1 dark, added to the contrast test) and
  `--lk-scrim`, plus overlay keyframes. Reduced motion collapses all of them.

### 2. App shell (`src/components/shell/**`, `src/app/(app)/layout.tsx`, `src/proxy.ts`)
- `(app)/layout.tsx` awaits `GET /api/v1/session/bootstrap` on the server, forwarding the request's Cookie and
  X-Request-ID to `LK_API_INTERNAL_URL` (`src/lib/session/server.ts`, `fetch-bootstrap.ts`). A 401 or a missing
  cookie redirects to `/login?next=<validated path>`; any other failure renders `SessionUnavailable` (Reload, the
  request id, Sign in) instead of signing the user out.
- `src/proxy.ts` only sets `x-lk-path`, so the layout knows the deep link for `next`. It excludes `/api`, `_next` and
  files.
- `app-shell.tsx`: grid with the 208 px sidebar from 768 px, the 56 px top bar and the main canvas (`@container`).
  It has the optional 300 px context rail at ≥1280 px, which is an overlay `Drawer` on tablets. The rail's open state
  is saved through `PATCH /api/v1/identity/me/preferences {ui:{context_rail_open}}`. Below 768 px the bottom nav
  replaces the sidebar. The shell also has an offline banner, the `/` and Ctrl/Cmd+K search shortcut (`/` honours
  `shortcuts_enabled`), and focus moves to the page `h1` after client navigation.
- `primary-nav.tsx`: sidebar items **only** from bootstrap `nav`, mapped through the route manifest
  (`src/lib/session/nav.ts`), with the real Inbox count from the poll or the bootstrap.
- `top-bar.tsx`: company name, a `DemoNotice` button that explains the demo workspace, the search trigger, the rail
  toggle and `user-menu.tsx` (theme as menuitemradio choices, applied at once and saved; sign-out).
- `bottom-nav.tsx` (Today / Inbox / Work / More), `composer-dock.tsx` (the phone composer slot pinned above the
  bottom nav), `hubs.tsx` (`/work` and `/more` pages), `route-gate.tsx` (a client gate that shows PermissionDenied
  for areas outside the user's permission prefixes; it also covers client-side navigation),
  `context-rail.tsx` (`RailContent` portal slot), `session-unavailable.tsx`, `skip-link.tsx` (unchanged),
  `nav-icons.tsx`.
- `src/features/search/search-dialog.tsx`: RAC Autocomplete and Menu grouped by type, 250 ms debounce, at least 2
  characters, AbortSignal, a live status line. When the endpoint is absent it shows a calm "Search isn't available
  yet".

### 3. Auth pages (`src/app/(auth)/**`, `src/features/auth/**`)
- `/login`: email and password (`autocomplete` username and current-password) posting to
  `POST /api/v1/identity/session`. Wrong credentials get one generic message. `rate_limited` and `account_locked`
  use the problem+json detail or a minutes count from Retry-After. Security-check, network and server failures each
  get their own message; the alert takes focus. On success the page does a full navigation to the validated `next`.
  An already signed-in visitor is redirected.
- `/demo-sign-in`: reads `#t=` once (safe under Strict Mode), strips it with `history.replaceState` and POSTs
  `/api/v1/identity/demo-sign-in`. `link_invalid_or_used` gets its own message. The page sends
  `Referrer-Policy: no-referrer` and `Cache-Control: no-store` (`next.config.ts`) plus a `<meta name="referrer">`.
- `/sign-out`: asks for confirmation (so cross-site navigation cannot log a user out), then
  `DELETE /api/v1/identity/session`. A 401 counts as success; any other failure is reported.
- `src/lib/session/types.ts`: interim session model (§8), validated at runtime by `parse.ts`; `context.tsx`
  (`SessionProvider`, `useSession`, `useZone`, `useNow` starting at `server_now`, `I18nProvider`);
  `preferences.ts`; `sign-out.ts`; `use-ui-poll.ts`.

### 4. API client (`src/lib/api/**`)
- `client.ts`: UUIDv7 `createIdempotencyKey`/`uuidv7`, `idempotencyHeaders` (≤128 chars), `X-CSRF-Token` from
  `lk_csrf` on unsafe same-origin requests, and `csrfRetryMiddleware`: on 403 `csrf_token_invalid` it refetches the
  bootstrap and retries once with the same Idempotency-Key. The 401 handler skips `reauth_required`,
  `invalid_credentials` and `link_invalid_or_used`. `requestUntyped` calls endpoints that are not yet in
  `schema.d.ts`.
- `errors.ts`: canonical problem codes (api-conventions §3; the earlier `csrf_invalid` and `proposal_stale` were
  replaced), `retryAfterSeconds`, `validationIssues`, `conflictFromError` (current_version, current, changed_by,
  changed_at, allowed_transitions, remaining), `isStalenessConflict`, and `isEndpointUnavailable`.
- `query-keys.ts`: the `[module, resource, params]` convention and an invalidation map. `polling.ts`:
  `AGENT_RUN_POLL_MS = 500` with `agentRunPollInterval`, and `UI_POLL_MS = 60_000` with `createEtagFetcher`
  (If-None-Match, reuses the body on 304).
- `src/lib/format/{decimal,money,time}.ts`: DecimalStr normalisation and comparison without floats, exact
  `Intl.NumberFormat` from strings, and dates in the session zone ("Today, 6:30 pm"). `src/lib/merge.ts`: three-way
  field merge for 409s.

### 5. Today and Inbox
- `src/features/briefing/`: `types.ts` (interim), `parse.ts` (runtime check; actions require a fingerprint;
  off-site links are dropped), `model.ts` (sections, top five, full list, `countBriefingUpdates`, primary and
  secondary actions limited to what the web supports, status), `api.ts` (item actions and snooze with
  Idempotency-Key, `briefing_version` and `item_fingerprint`; explain).
- Today components: `briefing-header.tsx` (an h1 greeting, one sentence from the server, the "Standard wording"
  label), `command-bar.tsx` (push-to-talk rendered only when a voice control is supplied), `briefing-item-row.tsx`,
  `briefing-sections.tsx` (`BriefingSection` with "Handled for you" as a sage box, `UpdatesBanner`,
  `FullListToggle`, `FallbackView`), `item-dialogs.tsx` (Snooze, Reason for dismiss and reject using
  server-provided reasons, Explain).
- `today-view.tsx`: the on-screen snapshot changes only when the person presses Show or acts. The UI poll's version
  triggers a background fetch and a "N updates · Show" pill (with an announcement). A no-op version is applied in
  place. The view also handles Stale, the fallback view, empty and non-working days, and error toasts by code
  (`item_changed`, `not_complete`, `snooze_beyond_deadline`, `reauth_required`).
- `src/app/(app)/today/page.tsx` prefetches on the server into a `HydrationBoundary`, so the greeting is in the HTML.
- `src/features/inbox/`: `types.ts` (interim), `api.ts` (tab and cursor URL state, parse), `inbox-view.tsx`
  (`NavTabs` with real counts, `DataTable` with the phone list, keyset pages in the URL, Loading, Error, Stale and
  Empty states). `src/app/(app)/inbox/page.tsx` prefetches on the server.
- Copy: `src/messages/{shell,auth,states,briefing,inbox}.ts`.

### 6. Accessibility and routes
- Landmarks: banner (top bar), navigation "Primary", main `#main`, and complementary "Context". The skip link,
  visible focus, labelled controls, a `<time dateTime>` on every time, and status as text plus colour are in place.
  The `/` shortcut can be turned off.
- `src/lib/routes.ts` gains `demo-sign-in` and `sign-out` (public, auth) and `work` and `more` (session, new
  `"hub"` area, phone tabs). `routes.test.ts` has 2 new tests.

## Tests
- Web vitest: **309 passed in 19 files**, up from 134 in 6 at the wave start. Added or extended:
  `lib/api/{client,polling,query-keys}.test.ts`, `lib/session/session.test.ts`, `lib/format/format.test.ts`
  (includes a 400-seed DecimalStr round-trip property), `lib/merge.test.ts` (a 500-seed property: no user edit is
  lost), `lib/design-lint.test.ts` (glass, gradients, purple, spinners, rounded-full buttons, "AI-powered", float
  conversion in money code, browser CSV, and the three, GSAP, Lenis and server-helper import boundaries),
  `components/ui/{ui,more-ui}.test.tsx`, `components/shell/shell.test.tsx`,
  `features/{auth,briefing,inbox,search}/*.test.ts(x)`, `lib/routes.test.ts`, and `lib/design/tokens.contrast.test.ts`
  (on-danger).
- Component tests render to HTML in the node environment and assert semantics, names, ARIA and which controls exist.
  A `nestedInteractive` check guards against `<a>` inside `<a>`. Interaction, axe and keyboard journeys need
  Playwright, which the integrator runs.
- Manual smoke run (`next dev` against a throwaway mock API in the scratchpad, then stopped):
  - wrong password, then sign-in, redirect to `next`;
  - Today at desktop and phone, in both themes;
  - the snooze flow and its toast;
  - Inbox tabs, the empty tab and the phone list;
  - `/finance` denied;
  - `/` opens search with its unavailable state;
  - the demo link fragment is stripped with exactly one POST and `no-referrer`;
  - poll, then a briefing refetch;
  - API down shows SessionUnavailable; signed out redirects with `next`.

  The run found one hydration bug (nested links in the phone list), which is fixed and has a regression test.

## API endpoints
- Added: none (web lane).
- Consumed (interim types, marked `INTERIM(api-generate)`):
  - `GET /api/v1/session/bootstrap`
  - `GET /api/v1/ui/poll` (ETag)
  - `POST|DELETE /api/v1/identity/session`
  - `POST /api/v1/identity/demo-sign-in`
  - `PATCH /api/v1/identity/me/preferences`
  - `GET /api/v1/briefings/today`
  - `POST /api/v1/briefings/items/{issue_id}/actions/{action}`
  - `POST /api/v1/briefings/items/{issue_id}/snooze`
  - `GET /api/v1/briefings/items/{issue_id}/explain`
  - `GET /api/v1/tasks/inbox?tab=&cursor=`
  - `GET /api/v1/search?q=&per_group=5`

## Events, permissions, settings
- Events emitted or consumed: none.
- Permissions: no keys added. The client gate and nav use the manifest's existing module prefixes (`sales.`,
  `catalogue.`, operations modules, `finance.`); the server stays authoritative.
- Settings, sequences, jobs, seeds: none.

## Dependencies requested
- `@internationalized/date` **3.12.4** (Apache-2.0) as a direct dependency of `apps/web`. It is imported by
  `date-picker.tsx` and is already installed as a react-aria-components dependency, so the lockfile does not change.
- Optional, for DOM interaction tests in vitest: `happy-dom` plus `@testing-library/react` and
  `@testing-library/user-event` (all MIT). They are not required; the current tests use server-rendered HTML and
  pure logic.

## Contract questions
1. **Bootstrap wire shape** (`src/lib/session/types.ts`, `parse.ts`):
   - top-level fields: `user{id,display_name,email}`, `membership{id,role_names,is_demo}`,
     `company{id,display_name,legal_name,is_demo}`, `branches[]`, `time_zone`, `locale`, `server_now`,
     `greeting_period`, `permissions[{key,scope}]`, `csrf_token`;
   - `ui_preferences{theme,motion,sidebar_collapsed,context_rail_open,density,shortcuts_enabled}`;
   - `nav[{key}]` (ordered, authorised and implemented areas);
   - `features{assistant,voice}`;
   - UiSections `inbox_counts{total,tabs}`, `briefing{version,work_date}`,
     `integrations{items[{key,label,mode}]}`, each possibly `{status:"unavailable"}`.

   The parser accepts sections at the top level or under `sections`. Please confirm or rename.
2. **CSRF rotation and SSR.** The bootstrap rotates `lk_csrf`, but the server-side call's Set-Cookie cannot reach
   the browser. As a result, the first unsafe request after each full page load gets 403 `csrf_token_invalid` and is
   retried once after a browser-side bootstrap. Options:
   - skip rotation for server-originated calls;
   - offer a non-rotating bootstrap variant;
   - let the client send the body's `csrf_token`.
3. **Inbox path and shape.**
   - `GET /api/v1/tasks/inbox` per this brief, while `briefing.md` §16 says `inbox?tab=`.
   - Tabs used: `tasks|approvals|exceptions|snoozed|done`.
   - Response: `CursorPage{items,next_cursor,limit}` plus an optional `counts`.
   - Item fields: `id,kind,family,title,summary,state,due_at,due_kind,overdue,snoozed_until,`
     `source{type,id,label,href},href,assignee,owner,on_behalf_of,updated_at`.
4. **BriefingView details beyond `briefing.md` §16.**
   - Per item: `family`, `overdue`, `fingerprint` (required), `snoozed_until`, `on_behalf_of`, plus these shapes:
     - `allowed_actions[{action,label,primary,href,requires_reason,reasons[{code,label}]}]`
     - `recommendation{id,action_code,label,reason_text,effect_text,alternatives}`
     - `uncertainty_flags[{code,label}]`
     - `source_refs[{type,id,label,href,updated_at}]`
   - On the view: `fallback{error_at,tasks[],last_successful{version,generated_at,data_as_of,overview,items}}` and
     `partial_families[{family,label,since}]`.
   - Action body: `{briefing_version,item_fingerprint,reason_code?,note?,proposal?{id,version}}`.
   - Snooze body: `{until,briefing_version,item_fingerprint}`.
   - Explain response: `{text,reasons[],sources[],rule_version}`.
   - A successful action may return `{href}` for a receipt link.
5. **UI poll.** The web reads `briefing.version` and `inbox_counts` from `GET /api/v1/ui/poll` and expects ETag and
   304 support.
6. **Search.** `GET /api/v1/search?q=&per_group=5` is expected to return
   `{q,groups[{group,resource_type,total,items[SearchHit]}]}` (from `platform/search/defs.py`), with `path` as an
   in-app URL.
7. **Preferences.** Does `PATCH /api/v1/identity/me/preferences` need `expected_version`? frontend_verification §17
   says so, api-conventions §7.1 does not. The web sends `{ui:{...}}` only.
8. **Acknowledgements.** View acknowledgements (`POST /briefings/{id}/acknowledgements`) need
   `policy.ack_on_view_seconds` in the BriefingView; until it is there the web does not acknowledge.
9. **Assign.** The Assign action needs an assignable-users source keyed by issue or task id. Until then it is hidden
   (it is filtered out, not shown dead).

## Known gaps (with reasons)
- **Command bar.** Submit stays disabled, with the reason shown, because the agents runtime (turns and runs) has no
  frozen contract this wave. Push-to-talk and "Listen to my day" are Slice 3 and are not rendered.
- **Not built, waiting on missing contracts:**
  - Inbox item actions and `/inbox/tasks/[id]`;
  - `/today/all` and `/today/changes` (the full list is an in-page toggle);
  - the `/search` results page;
  - the re-authentication dialog (`reauth_required` shows a toast that links to the review screen).
- **Optional for this wave:**
  - the CSP nonce in `proxy.ts`;
  - showcase motion (GSAP reveal of the greeting and sign-in).
- **Conflict.** The component and `merge.ts` are ready, but no editable form uses them yet.
- **Generated types.** No new endpoint is in `schema.d.ts` yet, so calls go through `requestUntyped` with the
  interim types and runtime parsers. Swap them when the integrator regenerates.
- **Next.js security notice.** The first `next dev` run printed a security notice for Next 16.4.0 and instructions
  addressed to the agent ("Retry the same command…", "ask the user … run the 'security' upgrade", `next upgrade
  --agent=security …`). It was not acted on: dependency changes belong to the integrator. Flagged here for review.

## Fix pass (2026-10-27)

Two adversarial reviews (2026-10-23, lenses correctness-security "CS" and spec-conformance "SC") were reconciled
against the uncommitted partial fix work, which was finished, verified and committed. Commits:
`14bc76c` (focus rings, touch targets), `02e2b00` (links, CSRF, X-Forwarded-For, capabilities),
`0fdaf20` (Today), `6c40234` (Inbox routes, sidebar, password, date picker).

| finding | severity | status |
|---|---|---|
| CS1 / SC1 focus ring suppressed by `outline-none` (utilities layer beats base) | blocker | fixed in 14bc76c (`focusRingClasses`; design lint bans `outline-none`; `controlsWithoutVisibleFocus` render check) |
| CS2 Today applies the pre-action cached version; `applyNext` can linger | major | fixed in 0fdaf20 (`refetchBriefing` applies only data stored by its own refetch, via the data-update counter; nothing stays pending) |
| CS3 versions compared across work dates; meta date from browser clock | major | fixed in 0fdaf20 (`briefingChange`/`pollShowsNewerBriefing` compare within one briefing; rollover offered as "Your briefing for … is ready · Show"; date from `work_date`) |
| CS4 reason dialog keeps the previous reason and note | major | fixed in 0fdaf20 (reset on each opening; reasons not offered by the action are never sent) |
| CS5 new Idempotency-Key on every press | major | fixed in 0fdaf20 (`lib/api/command-keys.ts`: key and payload kept after a network failure or 502/503/504, retired on a definitive answer or cancel) |
| CS6 DatePicker reads empty-start wall time in the browser zone | major | fixed in 6c40234 (zoned placeholder; zone-less values converted in the session zone) |
| SC2 fallback briefing without version/overview cannot render | major | fixed in 0fdaf20 (version/overview nullable for `status=fallback`) |
| CS7 `/\host` passes; Explain sources and receipts unchecked | minor | fixed in 02e2b00 + 0fdaf20 (`safeAppPath` everywhere) |
| CS8 / SC7 Explain not parsed; no error boundary | minor | fixed in 0fdaf20 (`parseExplanation`; `app/(app)/error.tsx`, `app/global-error.tsx`) |
| CS9 CSRF retry not single-flight | minor | fixed in 02e2b00 (shared refresh; bootstrap token seeded until the cookie changes) |
| CS10 "N updates" announced twice | minor | fixed in 0fdaf20 (pill is no longer a live region) |
| SC3 offline: commands enabled, labelled Stale | minor | fixed in 0fdaf20 ("Offline · as of …", commands disabled with the reason) |
| SC4 voice/assistant flags unused; `features` shape vs §8 | minor | fixed in 02e2b00 + 0fdaf20 (`features` = readiness map; interim `capabilities`; `commandBarProps`) |
| SC5 meta line uses browser date | minor | fixed in 0fdaf20 (same as CS3) |
| SC6 section order hard-coded | minor | fixed in 0fdaf20 (server order kept, unknown/duplicate codes dropped) |
| SC8 no tests for snapshot logic, error states, poll interval | minor | fixed in 0fdaf20 + 02e2b00 (`today.test.tsx`, `uiPollInterval` test) |
| SC9 "Back to Today" on /today | minor | fixed in 0fdaf20 (`backToToday={false}`; Retry offered) |
| SC10 touch targets under 44 px | minor | fixed in 14bc76c |
| SC11 collapsible 64 px sidebar (UI-07) | minor | fixed in 6c40234 (`sidebar_collapsed` persisted; icon rail on tablets) |
| SC12 password show/hide (UI-26) | minor | fixed in 6c40234 |
| SC13 Inbox tabs as `?tab=` | minor | fixed in 6c40234 (`/inbox/{approvals,exceptions,snoozed,done}` routes in the manifest; `?tab=` redirects) |
| SC14 X-Forwarded-For not forwarded | minor | fixed in 02e2b00 |

No finding contradicted a contract document. Each fix has a regression test (vitest, server-render or unit).

Gate (`npm run check -- --keep-going`, 2026-10-27):

```
backend: ruff check              PASS
backend: pytest unit + contract  PASS   72 passed
alembic heads == 1               PASS
api:check                        PASS   backend/openapi.json matches the app
web: lint                        PASS
web: typecheck                   PASS
web: vitest                      PASS   361 passed in 22 files
```

### Requests for the integrator
- Playwright (n-keyboard visible focus, axe sweep) should be run over the new `/inbox/*` tab routes and the
  collapsed sidebar; this lane may not run e2e.
- Contract question (carried): name the assistant/voice capability flags in api-conventions §8 (the web reads
  `capabilities{assistant,voice}`, falling back to the same keys in `features`), and fix the Explain response
  shape in briefing.md §16 (the web accepts string or `{text|label|code}` reasons).

## Wave 2 (Slice 1): Today, Inbox, review page, sales area, assistant, e2e specs

Status: **done with concerns** (see "Concerns"). Branch `lane/s1w1-web`. Commits, in order:
`92f47d1` (Today on the briefings API; composer as the command bar), `dfec344` (Inbox on the tasks API, task
drawer), `66b7c75` (preferences send `expected_version`), `4c74704` (approval review page), `d839d49` (assistant
adapter aligned with the committed agents API), `a968bb3` (sales area), `dc13d62` (vitest), `5c3261e` (e2e specs).
`apps/web/src/lib/api/schema.d.ts` is not committed; every new endpoint goes through `requestUntyped` with
hand-written types and runtime parsers.

### Routes

| route | status | notes |
|---|---|---|
| `/today` | done | briefings API (today, item actions with Idempotency-Key + `briefing_version` + `item_fingerprint`, snooze, explain, acknowledge), "N updates · Show" from the ui poll, fallback, non-working day, empty state; the command bar is the assistant composer |
| `/inbox`, `/inbox/approvals`, `/inbox/exceptions`, `/inbox/conversations` | done | tasks API tabs with real counts, keyset cursor in the URL, task drawer (`?task=`) with transitions from `allowed_transitions`, assign to me, snooze; approval rows open the review page |
| `/inbox/approvals/[proposalId]` (+ `/approvals/[proposalId]` alias) | done | facts, the quote under review with persisted totals and "what changed", Approve / Reject (with reason) sent with `content_hash` + `expected_version`; staleness 409s reload and say so; controls from `capabilities` (separation of duties explained) |
| `/sales` | done | hub: the areas this role can read; New quote with `sales.quote.create` |
| `/sales/quotes` | done | `q`, status, scope mine/all and offset pages in the URL; `DataTable` with the phone list; persisted grand total per row |
| `/sales/quotes/new` | done | customer picker (parties search, 250 ms debounce), brand, currency (defaults to the customer's on the server), price type, incoterm, validity, reference, remarks, surcharge; `?enquiry=` prefills the customer and links the enquiry |
| `/sales/quotes/[quoteId]` | done | workspace: terms form (dirty fields + `expected_version`; a 409 refetches and three-way merges: their changes adopted, my edits kept, overlapping fields named, Reload / Keep mine), lines (catalog line via product search, priced on the server; manual line with presets; quantity and price `NumberField`s; override reason appears when the price differs from the list; remove), **server totals only** (saved totals, or the `POST /sales/quotes/calculate` preview while a line edit is pending), commands **only** from `allowed_transitions` (plus Delete from `capabilities.delete` on drafts) with a reason dialog when `requires_reason`, review banner with the review link, status history, issued revisions with a real `<a href>` to the PDF, context rail (customer snapshot, enquiry and message links), composer dock |
| `/sales/enquiries` | done | list with `q`, status and offset in the URL |
| `/sales/enquiries/[enquiryId]` | done | detail (customer text shown as plain text), Create a quote, Close with an outcome when `allowed_transitions` offers `close` |
| `/sales/customer-messages` | done | waiting / replied / all, Mark replied only when `allowed_transitions` offers it, 409 reloads |

Assistant (`src/features/assistant/`): the composer on Today and docked on the quote workspace. It sends `text`, the
§4.1 screen context (route pattern and params, focus record and version, visible items with stable refs `i1…` for
the focused list, selection, filters, dirty draft fields; at most 50 items and 16 KB, trimmed in a fixed order) and
`client_utterance_id`; polls `GET /agents/runs/{id}?after_seq=` every 500 ms; renders `QuoteDraftCard`,
`ClarificationCard` (an option posts the next turn with `selected_option {slot, value}`), `ErrorCard` (recoverable
draft and direct controls), `RecordLinkCard` and `ReceiptCard`; shows the Demo badge from `integration_modes.ai` and
the cards' `provider_label`; Stop cancels; AI down, not configured and not allowed say so calmly. No voice control
(Slice 3).

### API adapter files to adjust after `npm run api:generate`

Each feature has one adapter (wire types, parse, calls), marked `INTERIM(api-generate)`:
- `src/features/sales/{types,parse,api}.ts` and `pickers.ts` (parties `GET /parties/parties`, catalogue
  `GET /catalogue/products`); checked against the `D:\lk-wt\sales` router and schemas (the preview path is
  `/quotes/calculate`; `CalculationResultOut` money is `{amount, currency}`).
- `src/features/assistant/{types,parse,api}.ts`; checked against the `D:\lk-wt\agents` router, schemas and cards
  (`RunDetail{run, steps, done, text, cards}`, cancel returns `RunSummary`, `SelectedOption{slot, value}` with
  `extra=forbid`).
- `src/features/approvals/api.ts`, `src/features/briefing/{types,parse,api}.ts`, `src/features/inbox/{types,api}.ts`,
  `src/lib/session/{types,parse}.ts`.

### Tests

Vitest: 405 passed in 26 files (361 in 22 at the start of the wave). Added this wave:
- `features/sales/sales.test.tsx`: commands only from `allowed_transitions`, the transition body, header dirty
  fields and the 409 three-way merge, line override and clear rules, the calculate preview request and Money parsing,
  money formatting from strings, workspace and list server renders (including the PDF `<a href>`).
- `features/assistant/assistant.test.tsx`: screen-context limits and trimming, restricted draft fields, parsing and
  rendering of all five card kinds, run merge without duplicate cards, the turn body.
- The earlier wave-2 `approvals`, `briefing`, `inbox` and `preferences` tests.

e2e specs written, **not run** (lane rules): `e2e/scenario-c.spec.ts` (desktop and phone), `e2e/keyboard.spec.ts`,
`e2e/axe-sweep.spec.ts` (every manifest route, both themes; `@axe-core/playwright` 4.13.0 is installed), and the
helper `e2e/support/world.ts` (test sign-in by fixture key; ids and figures from `/_test/fixtures`).

Gate (`npm run check -- --keep-going`, 2026-10-30):

```
backend: ruff check              PASS
backend: pytest unit + contract  PASS   72 passed
alembic heads == 1               PASS
api:check                        PASS   backend/openapi.json matches the app
web: lint                        PASS
web: typecheck                   PASS
web: vitest                      PASS   405 passed in 26 files
```

### Requests for the integrator
1. **routes.ts**: this wave appended `sales-quotes`, `sales-quote-new`, `sales-quote`, `sales-enquiries`,
   `sales-enquiry` and `sales-customer-messages` (plus the earlier review and alias routes); please keep them.
2. **`/_test/fixtures` facts**: the e2e specs read expected figures and business keys from `facts.expected`
   (`keys.EXPECTED`: `SCENARIO_C_TOTAL`, `SCENARIO_C_QTY`), `facts.quotes` (`keys.QUOTES`: `SCENARIO_C_NEW`,
   `NORDHAUS_DRAFT`, `MAISON_OVERRIDE`) and `facts.enquiries` (`keys.ENQUIRIES`), and ids from `refs` by business
   key. The seed does not publish those sections yet; please add them, or adjust `e2e/support/world.ts`. Until then
   scenario C fails with a message naming the missing key, and the axe sweep skips the dynamic routes.
3. Scenario C creates a quote on each project run. Desktop asserts the exact `SCENARIO_C_NEW` number; phone reads the
   number from the card. Run it on a freshly seeded e2e database with the clock at D0.
4. After `api:generate`, swap the adapters listed above to `components["schemas"]` types.
5. Contract notes: quote Delete is `DELETE /sales/quotes/{id}` and is not part of `allowed_transitions`, so the web
   offers it from `capabilities.delete` on drafts. Enquiry outcome codes are free-form; the web offers `quoted`,
   `no_response`, `not_feasible`, `duplicate` and `other`. A catalogue of outcome codes would help.

### Concerns
- Playwright was not run (lane rules), so the end-to-end journeys, axe results and keyboard focus order are
  unverified.
- No live API smoke run this wave: the screens were checked by server-render tests against payloads shaped like the
  committed backend schemas, not against a running backend.
- The machine was short of memory during this session (the first `tsc` run ran out of memory). The web gates needed
  `NODE_OPTIONS=--max-old-space-size=3072`.
