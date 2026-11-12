# Building screens in Lamikraft One (`apps/one`)

The working contract for anyone, person or agent, who builds or changes a screen here. Read it fully before writing code.

## What this app is

`apps/one` is the rebuilt web app for Lamikraft One, the ERP for Lamikraft (precision-crafted kitchen and display products: chopping boards, platters, risers). It replaces `apps/web` screen for screen. The **URLs and the API are unchanged**; the **flow, layout, copy and look are new**. The bar is premium, awards-level work on every screen: clear hierarchy, strong typography, confident spacing, meaningful motion, sharp copy.

- Same stack as the old app: Next.js 16.4 App Router, React 19, TypeScript strict, Tailwind 4, `react-aria-components` (RAC), TanStack Query, `openapi-fetch`.
- Next.js 16 is not the Next.js you may remember: `params` and `searchParams` are Promises (`await` them), `proxy.ts` replaces middleware. When unsure, read `node_modules/next/dist/docs/`.
- `docs/meetings/README.md` holds the team's agreed vocabulary and business flow. It outranks your assumptions.

## Two aliases, one data layer

| Alias | Points to | Use it for |
|---|---|---|
| `~/…` | `apps/one/src/…` | Everything you write: `~/ui`, `~/shell/*`, `~/screens/*`, `~/lib/*` |
| `@/…` | `apps/web/src/…` (the old app, **read-only**) | The data layer: `@/features/<x>/api`, `types`, `parse`, `model`, `list-state`, command hooks; `@/lib/api/*`, `@/lib/format/*`, `@/lib/session/*`, `@/lib/routes`, `@/lib/hooks`, `@/lib/cx` |

Rules:
1. **Never edit anything under `apps/web`, `backend`, or generated files.** Never import an old *view* component (`@/components/**`, old `*.tsx` views in `@/features/**`). Import only non-visual modules: hooks, API calls, types, parsers, models, state helpers, message strings you choose to reuse.
2. If the hook you need lives inside an old view file, write a small new hook in `apps/one/src/data/<area>.ts` using `api` / `unwrap` / `requestUntyped` from `@/lib/api/client` and types from `@/lib/api/schema`. Reuse the old query keys (`@/lib/api/query-keys` or the feature's own keys) so caches stay consistent.
3. Money and quantities are **decimal strings**. Never convert them to numbers for arithmetic; format them with `Money`, `Qty` (`~/ui`) or `@/lib/format/money`.
4. Mutations follow the old code exactly: same endpoint, same body, `Idempotency-Key` where the old code sends one, same optimistic-version handling (409 conflicts), same cache invalidation. Old command hooks (`use-*-command.ts`) already do this and already raise toasts on the shared queue: prefer them.

## How to rebuild a screen

1. **Read the old screen first**: the old `page.tsx` under `apps/web/src/app/…` and the feature view it renders. List (for yourself) every piece of data shown, every action, every permission or `capabilities` check, every state (loading, empty, error, conflict, offline), every validation rule. The new screen must keep **all working functionality**; nothing real may be dropped, and nothing fake may be added.
2. **Redesign the flow, do not transplant it.** Ask: what is the one job of this screen? Who does it and how often? What do they need first? Then lay it out again from nothing (see UX rules).
3. **Write new copy** (see Voice). Do not copy the old labels unless they are already the best words.
4. Put the screen in `apps/one/src/screens/<area>/<screen>.tsx` (plus small sibling files for its parts). The route file `apps/one/src/app/…/page.tsx` stays thin: read `params` / `searchParams`, set `metadata`, render the screen. Replace the stub (`LK-STUB`) completely.
5. A server page never *calls* a function from a `"use client"` module; it only renders client components. URL-state parsers (`list-state.ts`) are plain modules and fine to call on the server.

## UX rules

- **One screen, one job.** The old app clumps too much into single sections. Separate it: a list is only a list; a record opens on a summary and moves depth into views.
- **Record screens** (`RecordHeader` from `~/shell/page`): breadcrumb, code, title, status badge, a `FactStrip` of 3 to 5 facts, the primary action plus a `Menu` for the rest. Below it, `Tabs` with `href` tabs driven by `?view=` (for example Overview, Lines, Documents, Activity). Each view shows one kind of thing. Overview answers "where does this stand and what is next?" and nothing else.
- **List screens**: `PageHeader` (title, one-line lead, primary action) → one filter row (`SearchField` + `ChipLink`s or `SegmentedLinks`; all filter state in the URL, using the old `list-state` helpers) → `DataTable` inside `GlassPanel padding="none"` → `Pagination` + `PageSummary`. At most 6 columns on desktop; choose a `primary` column; rows link to the record. Phones get cards automatically.
- **Hub screens** (`/sales`, `/operations`, `/finance`, `/products`, `/settings`): not a link farm. A serif `display` header, the 3 or 4 numbers that matter (`StatTile` with `href`), then "needs attention" (real data only), then the area's screens as quiet tiles with a one-line description each.
- **Forms**: `FormSection` per topic, two-column field grid, `FormActions` sticky footer (ghost Cancel, primary verb). Long creation flows become steps (one decision per step) with a visible step indicator. Validate on submit and on blur; errors say what happened and what to do. Cross-field errors go in a `Banner` at the top.
- **Actions**: one primary button per screen (variant `primary`, gold) at most; secondary actions `inverse` or `secondary`; rare ones in a `Menu`. Destructive or irreversible actions open `ConfirmDialog` / `ReasonDialog` whose confirm button names the verb ("Cancel order", never "OK").
- **No dead controls.** Render a control only when the person may use it (`capabilities` in the response, permission keys from `useSession()`) and the endpoint exists. If the old app did not offer it, neither do you. No "coming soon".
- **States**: loading = skeletons shaped like the content (`DataTable loading`, `LoadingBlock`, `Skeleton*`); error = `ErrorBlock` in place with retry (`QueryView` does all three); empty = `EmptyState` that leads with the next action ("Add your first customer"), never a bare "No data".
- **Demo labels stay**: integrations that are simulated (AI, WhatsApp, email, accounting) keep a visible "Demo" `Badge` exactly where the old app showed one.
- **Density**: comfortable by default. Give content air: `gap-5`/`gap-6` between panels, panels `padding="md"` or `"lg"`. Dense tables are for genuinely tabular data only.

## Vocabulary (from the team's meetings)

| Say | Not | Notes |
|---|---|---|
| Lead | Prospect | A party with status `prospect`: has not bought, no sample sent |
| Customer | Party | A party that bought or received a sample. "Party" never appears in the UI |
| Enquiry | | An incoming request from a lead or customer |
| Quotation | Quote | In all UI copy (code and URLs keep `quote`) |
| Sample | | Taken from stock; today every sample goes to a customer |
| Custom product | | Its own kind of item, beside catalogue products |
| Stock | Inventory | "Stock", "Stock movements", "Stock take" |
| Purchase order (PO) | | In-house orders to suppliers |
| Lamikraft One | the app, the system | The product's name. The assistant is "Lamikraft" |

## Voice

Short, confident, specific, benefit-led. Sentence case everywhere. "You" for the reader. No exclamation marks, no emoji, no em dashes, no filler ("simply", "just", "seamlessly", "powerful"), no jargon the shop floor would not say.

- Titles name the thing: "Quotations", "Kitchen & Co." Leads say what the screen is for or its state in one sentence: "Every price you have offered, newest first."
- Buttons are verbs with objects: "Create quotation", "Send to customer", "Record receipt".
- Empty states lead with the action: "Add your first chopping board, platter or riser."
- Errors say what happened and what to do: "This quotation changed while you were editing. Reload to see the latest version."
- Numbers are formatted before display ("₹22,302", "1.5k") and set in tabular figures.
- Overlines (`t-overline`) are the only uppercase text.
- Write real, particular sentences. If a line could sit on any other product's screen, rewrite it.

## The design system in this app

The look in one line: warm paper or warm black, frosted glass floating over it, one gold accent, serif headlines, ink pills. Both themes ship together and both must be right.

- **Tokens** (`src/styles/tokens.css`, generated): colours `--ground --surface --glass --ink --ink-2 --ink-3 --line --gold --gold-strong --gold-soft --leaf* --amber* --ember* --cobalt* --inverse --on-inverse`; spacing `--space-1…24`; radii `--radius-xs…2xl, pill`; shadows; durations; easings. **Never write a raw colour.** Never write `[data-theme="dark"]` selectors: tokens already switch.
- **Type**: `t-display-xl|lg|md|sm` (Instrument Serif; one `<em>` word per headline at most), `t-h1…h4`, `t-body-lg`, `t-body`, `t-body-sm`, `t-label`, `t-caption`, `t-overline`, `t-stat-xl`, `t-stat`, `t-stat-sm`, `t-code`, `t-code-sm`. There are **no Tailwind text-size classes** in this app.
- **Tailwind** is for layout only: flex, grid, gap, padding, margin, width, responsive variants (`sm: 640`, `md: 768`, `lg: 1024`, `xl: 1280`). Colour utilities exist only for tokens: `text-ink`, `text-ink-2`, `text-ink-3`, `text-gold-strong`, `bg-surface`, `bg-gold-soft`, `border-line`, `border-line-strong`, and the status families. Radius `rounded-xs…2xl`, `rounded-pill`. Shadows `shadow-panel`, `shadow-lift`, `shadow-overlay`.
- **Colour meaning**: gold = "act here" and nothing else. `leaf` good/done, `amber` waiting/attention, `ember` problem/destructive, `cobalt` information. Every status also carries a word or icon. The aurora and the orb belong to AI only.
- **Components**: import from `~/ui` (see `src/ui/index.ts`; read a component's file for its props). Page frames from `~/shell/page` (`Page`, `PageHeader`, `PageSection`, `Split`, `RecordHeader`), states from `~/shell/states` (`QueryView`, `ErrorBlock`, `LoadingBlock`, `NotPermitted`). Layout helpers in CSS: `.stack`, `.split`, `.tiles`, `.stretched`.
- If a component you need does not exist, compose it from `GlassPanel` and tokens inside your screen folder. Do **not** edit `src/ui`, `src/shell`, `src/styles`, `src/app/layout.tsx` or `globals.css`; report the gap instead.
- Glass nests once at most; an inner surface is `variant="solid"` or `"outline"`. One `inverse` panel per screen at most.
- Icons: `Icon` with a name from `src/ui/icon.tsx`. Line icons only.

### Component notes (read before you fight them)

- **Navigation is flat.** The left-side menu lists every screen as a top-level item under a plain group heading. Never build nested, tree or accordion navigation anywhere (owner's instruction). Inside a record, use `Tabs`; inside an area, the menu and the pill row already exist.
- `DataTable`, `Pagination`, `Banner`, `KeyValue`, `FactStrip`, charts and `GlassPanel` have no `"use client"`: a server page may pass them functions (`cell`, `rowHref`, `hrefFor`). Sorting by `onSort` and `onRowAction` need a client parent; prefer `sortHref` and `rowHref`.
- `Tabs` with `href` render links (`aria-current="page"`); you render the content for the selected view. Without `href` they are an in-page tablist with `TabPanel`.
- `Tooltip` attaches to React Aria controls. For a `next/link`, `ButtonLink` or `TextLink` child pass `focusable`.
- Fields use `validationBehavior="aria"`: `isRequired` only announces. Your screen (or the API's 422 response) must supply the error text through `error`.
- `DecimalField` takes and emits decimal strings; `Qty` takes `{ value, uom }`; `Money` takes `{ amount, currency }`. Check the component file when unsure.
- `SearchField` `shortcut` defaults to off; the top bar already owns "/".
- `ConfirmDialog` / `ReasonDialog`: return a promise from `onConfirm` and the dialog shows a spinner, closes on success and stays open on failure (you show the error).
- `FormActions` stacks its buttons on phones: give it at most two buttons there (move the rest into a `Menu`).
- `toast` (from `~/ui`) is the same queue the old command hooks use; do not show a second toast for a mutation whose hook already raises one.
- The demo world is a laminate exporter ("Crown Decor (Demo)": sheets, decors, EUR/GBP customers). Lamikraft's own products are kitchen and display pieces. Keep copy true for both: say "products", "items", "units" unless the data itself names the thing.

### Demo people for screenshots (`--user`)

`SAHIL` management, sees most things (default) · `MEERA` sales · `RAVI` operations · `DEEPA` production · `ANANYA` finance · `PRIYA` admin (users, roles, backups, migration). If a screen shows "not part of your role" in a screenshot, shoot it again as the right person.

Screenshot tips: add `--slice` for tall screens (1500px slices that stay legible). In Git Bash, paths that begin with `/` are rewritten by the shell; the scripts undo this, so pass them normally.

## Motion

Liquid and unhurried. The language lives in `src/styles/app.css` and `~/lib/motion`.

- Entrances: add `rise` to panels and headers, `rise-plain` to rows and small items; stagger siblings with `style={riseIndex(i)}` (40ms steps, capped at 8). `PageHeader`, `RecordHeader` and `PageSection` already rise.
- KPIs count up with `CountUp`. Charts draw themselves. Selection thumbs and ink bars slide.
- Hover: interactive glass lifts 2px (`interactive` on `GlassPanel`, or `.lift`). Nothing else moves on hover. Press scales to .97 (built into buttons).
- No parallax, no bounce on enter, no looping decoration on data screens.
- Reduced motion (system setting or the user's preference) is handled by those classes. If you write a custom animation, give it the same treatment in both `@media (prefers-reduced-motion: reduce)` and `:root[data-motion="reduced"]`.

## Accessibility and responsiveness

- Exactly one `h1` per screen (the page frames render it); headings in order; landmarks from the shell.
- Every control has a visible label or an `aria-label`; icon-only buttons use `IconButton` with `label`.
- Everything works by keyboard: Tab order follows reading order, Escape closes overlays, focus is visible and returns to the trigger.
- Colour is never the only signal. Text contrast at least 4.5:1 in both themes (token pairs already pass; do not put `ink-3` on tinted fills).
- Design for 360px first, then 768, 1024, 1440, 1920. No horizontal page scroll at any width. Touch targets at least 44px on phones. Long names and numbers wrap or truncate with a `title`.

## Checking your work

A dev server is already running at `http://127.0.0.1:3200` (never `localhost`) against the real API with the demo world. **Do not start, stop or restart servers, and do not run builds, tests, installs or git commands.**

From `D:\lk-wt\one\apps\one`:

- `node scripts/check.mjs src/screens/<area> "src/app/(app)/<area>"` — type-check and lint, showing only your paths. Run it when a group of screens is written and again at the end. Fix everything in your paths.
- `node scripts/shots.mjs --only <path>[,<path>…] --out shots/<name>` — screenshots at 1440 and 390 wide of your routes, signed in as the demo owner, plus `report.json` listing console errors, failed API calls and horizontal overflow. Then **Read the PNG files and judge them** against the bar; fix what falls short and shoot again. Add `--theme dark` for one pass in dark. Use `--url "<path>?view=lines"` for views behind query strings and for records the script could not find. Both scripts wait for a machine-wide lock: run them one at a time and do not run them in a loop (at most 6 screenshot runs per builder).
- `node scripts/stubs.mjs --check` lists routes that are still stubs.

Before you report, look at every one of your screens at both widths and ask: is it obvious what this screen is for in two seconds? Is there exactly one thing that draws the eye first? Would a designer sign it? Does every word earn its place?

## Reporting

Return a short report: screens built (route → file), UX and copy decisions worth knowing, anything from the old screen you could not carry over and why, gaps in `~/ui` you worked around, check and screenshot status, and what you could not verify.
