# Checkpoint 2 design: showcase surfaces and the areas the backend already serves

Date: 2026-11-02. Status: approved by the owner's standing instruction ("complete the app, make the UI and
frontend as good as possible, Awwwards level, GSAP or Three.js") and executed autonomously under the assumptions
listed in §7. Contracts in `docs/architecture/*` win over this document where they disagree.

## 1. Intent

The owner wants Lamikraft One to feel like an award-grade product while remaining the calm, honest operational
tool the build prompt describes. Checkpoint 1 shipped the shell, sign-in, Today, Inbox and the quote vertical.
Four primary areas are still a bare heading (Products, Operations, Finance, Settings), the sign-in page is an
unstyled centred form, and none of the showcase motion frozen in `docs/architecture/motion-system.md` exists.
Meanwhile the backend already serves catalogue, parties, pricing, settings, integrations, audit and profile APIs
that have no screens.

Success means:

1. Every primary area opens onto a real screen backed by real data, or an honest state when its backend slice is
   not built yet. No fabricated metrics, no decorative KPI cards.
2. The showcase surfaces listed in motion-system §2 exist and respect every limit there: sign-in choreography,
   the Today greeting reveal, route transitions, the 3D material viewer.
3. `npm run check` stays green (lint, typecheck, vitest incl. the route-manifest and design-lint suites), and the
   new screens pass axe in both themes.

## 2. What "complete" means at this checkpoint

Slices 2–6 (full legacy parity, AI providers, inventory, finance, migration) are backend-first work measured in
weeks and are not completed here. This checkpoint completes the **web application against the API that exists**
and the **visual and motion system**. Backend write endpoints that do not exist (product create/edit, price-list
CRUD, imports) are not faked: the screens show the server's `capabilities`, and controls for unbuilt commands are
absent, not disabled.

## 3. Showcase surfaces (motion-system §2)

| Surface | Design |
|---|---|
| `/login` | Split editorial layout. Left: the wordmark, a two-line headline set in Fraunces (variable serif, OFL, loaded only on `(auth)`), the one-sentence intro and the form, interactive from first paint. Right (≥1024 px): a layered composition of four material swatches (oak, maple, ash, walnut) rendered as stacked boards with real shadows, pointer parallax ≤ 12 px. GSAP timeline ≤ 900 ms once per load: wordmark, headline lines (clip + rise), swatches settle, form fade-up. Below the fold a short "story" section (three beats: a briefing for each person, one assistant for every channel, every record one source) with Lenis smooth scroll. Reduced motion: static, no Lenis, no parallax. Dark theme equivalent. |
| `/today` greeting | `GreetingReveal` wraps the h1 and overview: each line reveals with clip-path + translateY, then the first ≤ 5 items enter with a 40 ms stagger; ≤ 700 ms total. Runs once per `briefing_id:version` (remembered in `sessionStorage`), never on polls or when a Stale/Offline state is on screen. Text is in the server HTML before any animation. |
| Route transitions | `(app)/template.tsx` with Motion: cross-fade + 8 px rise, 180 ms enter / 150 ms exit, transform and opacity only, disabled under reduced motion. |
| Material viewer | `/products/[productId]` gains a "Material" panel: a Three.js slab at the product's real L × W × T from `specification` (fallback to `size`), textured with the decor swatch (albedo + generated normal map), `frameloop="demand"`, orbit by drag, arrow keys and preset buttons (front, top, edge), camera eases ≤ 600 ms, lazy `next/dynamic` import gated by IntersectionObserver, static swatch image fallback. Labelled "Material preview — not a product photo". Reduced motion: single static render, instant presets. |
| Sidebar | Active item indicator slides between items (Motion `layoutId`), 180 ms; otherwise unchanged. |

Material imagery: the repository has no product media yet. Four **procedural fixture swatches** (oak, maple,
ash, walnut) are generated once by `apps/web/scripts/gen-swatches.py` (Pillow only) into
`apps/web/public/swatches/` as 1024 px WebP albedo and normal maps, committed, and labelled "illustrative fixture
swatch" in `public/swatches/README.md`. They stand in for product media until catalogue media lands in Slice 2;
the viewer reads the swatch by decor number through one mapping (`features/material-viewer/swatches.ts`), the
only place to change when real renditions exist.

## 4. Areas

Every area gets a contextual sub-navigation (`AreaNav`: `NavTabs` of the area's `context` routes the person may
open) under a shared `PageHeader` (title, intro, primary action). Lists keep filters and pagination in the URL
and are server-prefetched like the quote list. All detail screens record a recent record and contribute screen
context for the assistant.

### Products (`catalogue`, `pricing`)
- `/products`: facts strip from `GET /catalogue/products/stats` (total, by status, changed in 7 days — plain
  text, no cards), search and facet filters (category, family, thickness, finish, status, completeness issue)
  from `GET /catalogue/products/facets` with exclude-self counts, the product table (`DataTable`, phone list),
  price column in the chosen currency only when the server sent `prices`.
- `/products/[productId]`: record header (key in mono, name, status, category path), tabs as links: Overview
  (decor, size, finish, packaging summary, completeness score with missing checks), Specification,
  Packaging, Prices (`GET /pricing/products/{id}/prices`, costs only with `pricing.cost.read`), Material (the
  viewer). Capabilities drive which controls exist (none in Slice 1: the catalogue has no write endpoints).
- `/products/completeness`: `GET /catalogue/products/completeness` as a rule table whose counts link to the
  filtered product list (`filter_path`).
- `/products/taxonomy`: categories and subcategories with product counts (`GET /catalogue/categories`).
- `/products/price-lists`, `/products/price-lists/[priceListId]`: lists with status, scope, currency and
  validity; the detail shows items (price, unit, MOQ, validity) with the breakdown columns only when present.

### Sales additions (`parties`)
- `/sales` hub becomes "my work in motion": real counts from `GET /sales/quotes/status-counts`, quotes waiting
  for review, customer messages waiting, enquiries open; each a link to the filtered list.
- `/sales/parties`: search and filters (role, status, country), table.
- `/sales/parties/[partyId]`: header (number, name, status, roles, owner), contacts, addresses, tax identifiers,
  quotes of this party (`GET /sales/quotes?party_id=` if supported, else a link to the filtered list).
- `/sales/parties/new`: create form (legal name, display name, country, currency, roles, customer type, one
  primary contact, one billing address), `POST /parties/parties` with an Idempotency-Key, then navigate to the
  party. Editing uses `PATCH` with `expected_version` and the shared Conflict state.

### Settings (`org`, `identity`, `system`, `audit`)
- `/settings`: hub listing the sections the person may open.
- `/settings/profile`: name, email, role, time zone (read-only from `GET /identity/me`); password change
  (`POST /identity/me/password`); preferences: theme, motion, density, shortcuts, sidebar and rail defaults
  (`PATCH /identity/me/preferences` with `expected_version`).
- `/settings/company`: `GET /org/settings` as sections; each editable with its typed fields when
  `capabilities.update.allowed`, saved with `PUT /org/settings/{key}` and the version; "Not configured" fields
  labelled as such; revisions on demand.
- `/settings/reference`: currencies, units of measure with conversions, my work calendar.
- `/settings/integrations`: `GET /system/integrations` with mode and verified state (admin); the Demo
  explanation for everyone else from the bootstrap `integrations` section.
- `/settings/audit`: keyset-paginated audit log with action-prefix, outcome and date filters (`audit.log.read`).

### Operations and Finance
No backend exists (Slices 4 and 5). Each page is an honest area overview: what the area will hold (from the
PLAN), the status "Planned — Slice N", and the one thing a person can do today (open Today or the Inbox). No
counts, no cards, no placeholder charts. The sidebar still lists them only when the bootstrap `nav` does.

## 5. Components added to the design system

`PageHeader`, `AreaNav`, `FactStrip` (inline facts separated by rules, tabular numerals), `RecordHeader`
(business key, title, status, meta), `FacetGroup` (checkbox facets with counts), `SectionCard` (a titled
bordered region for detail sections), `KeyValueGrid` (responsive description list for specification fields).
All follow `components/ui/styles.ts` recipes, 44 px targets on coarse pointers, focus rings, no pills.

## 6. Verification

- `npm run check -- --keep-going` green: eslint, `tsc`, vitest (routes manifest covers every new page; design
  lint sees no gradient, blur, purple, infinite animation, GSAP or three outside their allowed folders).
- New vitest files: `lib/motion/showcase/reveal.test.ts` (once-per-version gate), `features/products/*.test.tsx`
  (parsers and list state), `features/parties/parse.test.ts`, `features/settings/*.test.ts`.
- Browser pass on the dev server: `/login` (light/dark, 1440 and 390, reduced motion), `/today`, every new
  route; axe on the new routes through the existing sweep (`e2e/axe-sweep.spec.ts` iterates the manifest).
- Evidence screenshots into `docs/evidence/checkpoint-2/`.

## 7. Assumptions made without the owner

1. A display serif (Fraunces, OFL) on the sign-in page only; the application stays in Manrope.
2. Procedural fixture swatches stand in for product media and are labelled as such.
3. Operations and Finance stay honest overview pages until their slices land.
4. Checkpoint commits are local only (PLAN decision of 2026-10-12), never pushed.
