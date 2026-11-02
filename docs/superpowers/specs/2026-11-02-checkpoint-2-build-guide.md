# Checkpoint 2 build guide: how to build, extend or re-skin the web surfaces

Companion to `2026-11-02-frontend-showcase-and-completion-design.md` (the "what" and "why"). This file is the
"how": written so that any agent or developer, without this session's context, can reproduce a screen, add the
next one, or swap the visual layer for a design system. Every rule here is already enforced by a test or a
lint; where it is not, the file that owns the decision is named.

## 0. Ground rules (read before touching `apps/web`)

1. `apps/web/AGENTS.md` first: this Next.js (16.4, App Router, Turbopack) differs from training data. Its docs
   are at `node_modules/next/dist/docs/01-app/` (repo root). `params` and `searchParams` are Promises.
2. **A server page never calls a function from a `"use client"` module.** It may *render* a client component.
   URL-state parsers therefore live in plain modules named `list-state.ts` or `detail-state.ts`
   (examples: `features/sales/list-state.ts`, `features/products/detail-state.ts`). Breaking this rule renders
   as "Something went wrong" with `Attempted to call X() from the server`.
3. Banned patterns are enforced by `src/lib/design-lint.test.ts`: CSS gradients, `backdrop-blur`,
   purple/violet/fuchsia, `animate-spin|ping|bounce`, `rounded-full` on buttons, `outline-none`, "AI-powered",
   `three`/`@react-three/*` outside `features/material-viewer/**`, `gsap` outside `lib/motion/gsap.ts` and
   `lib/motion/showcase/**`, `lenis` outside `app/(auth)/login/**`, Next server helpers inside client files.
   Money code (`lib/format/money.ts`, `decimal.ts`, `number-field.tsx`, `format.tsx`) never converts strings to
   floats. Elsewhere, parse URL integers with `Number.parseInt` as `list-state.ts` does.
4. Every `page.tsx` has an entry in `src/lib/routes.ts` (`routes.test.ts` fails otherwise). Primary areas keep
   their sidebar order; `context` routes form an area's sub-navigation (`AreaNav`).
5. All copy lives in `src/messages/<area>.ts`. No strings in components.
6. Every data screen has the five states from `components/ui/states.tsx`: `Loading` (after 150 ms),
   `ErrorState` (with retry), `EmptyState` (real copy and a next step), `NotAvailable` (404), `PermissionDenied`.
7. Figures come only from the server. Counts go in a `FactStrip`, never in KPI cards. Nothing is estimated.
8. Controls for commands the server does not offer (`capabilities.<action>.allowed`) are absent, not disabled.
9. Verification commands (run from `apps/web`):
   `npx eslint .` · `npx next typegen && npx tsc --noEmit -p tsconfig.json` · `npx vitest run` ·
   `npm run check -- --keep-going` from the repo root for the full gate (backend included).

## 1. File map of this checkpoint

```
apps/web/src
├─ app/(app)/template.tsx                 route transition (Motion, 180/150 ms, enter only on client navigation)
├─ app/(auth)/login/                      sign-in showcase: page.tsx, login-showcase.tsx, material-stage.tsx,
│                                         story.tsx, use-lenis.ts   (Lenis allowed here only)
├─ app/(auth)/(centered)/                 the centred layout for demo-sign-in and sign-out
├─ app/(app)/{products,sales/parties,settings,operations,finance}/**   thin server pages (metadata + parsing)
├─ components/ui/                         page-header, fact-strip, record-header, section-card, key-value-grid,
│                                         facet-group  (+ the Slice-1 primitives)
├─ components/shell/area-nav.tsx          an area's sub-navigation from the route manifest
├─ components/shell/primary-nav.tsx       sidebar; the current-item background is a Motion layoutId
├─ features/products/**                   catalogue list, record (5 tabs), completeness, taxonomy
├─ features/price-lists/**                price-list list and detail
├─ features/parties/**                    customers list, record (edit drawer, add contact), create form
├─ features/sales/sales-hub.tsx           "my work in motion"
├─ features/settings/**                   hub, profile, company settings, reference data, integrations, audit
├─ features/areas/area-overview.tsx       honest Operations / Finance overviews
├─ features/material-viewer/**            swatches.ts (decor → swatch), types.ts, geometry.ts, orbit.ts,
│                                         material-scene.tsx (three), material-preview.tsx (lazy wrapper)
├─ lib/motion/showcase/                   greeting-reveal.tsx, reveal-gate.ts, login-entrance.ts (GSAP)
├─ lib/motion/{gsap.ts,lazy-canvas.tsx,motion-config.tsx,tokens.ts,use-motion-preference.ts}
└─ messages/{products,parties,settings,areas,auth,sales}.ts
apps/web/public/swatches/                 procedural fixture swatches (+ README.md); scripts/gen-swatches.py
```

## 2. Recipe: add a list screen

1. Register the route in `lib/routes.ts` (`navGroup: "context"` if it belongs in the area's sub-navigation;
   `requiredPermission` is a module prefix such as `"parties."`).
2. `features/<area>/types.ts`: hand types mirroring the backend read models (`backend/app/modules/<m>/schemas.py`).
3. `features/<area>/parse.ts`: a runtime reader per type (`need/str/int/dec`, `pageOf`); paths via `safeAppPath`.
4. `features/<area>/list-state.ts` (plain module): `xListStateFrom(searchParams)` and `xListHref(state)`; page
   size 25; offsets rounded to the page size.
5. `features/<area>/api.ts`: `fetchX(params, signal)` through `requestUntyped(api, "get", "/api/v1/…", …)`.
6. Query key: add a factory to `lib/api/query-keys.ts` (`[module, resource, compact(params)]`); mutations add an
   `invalidationMap` entry.
7. Server page: parse the URL with the plain module, prefetch into a `QueryClient` (`serverGetJson`), render
   `<HydrationBoundary>` + the client view (pattern: `features/inbox/inbox-page.tsx`).
8. Client view: `PageHeader` (+ `AreaNav`), filters writing to the URL through `router.push(xListHref(...))`,
   `DataTable` with `mobile` roles, `OffsetPagination` with hrefs, `useScreenContribution` for the assistant.
9. Tests: `parse.test.ts` and `list-state.test.ts` (round trip, unknown values dropped).

## 3. Recipe: add a record screen

`RecordHeader` (back link, business key, title, `StatusPill`, meta with `MetaDot`, actions only from
`capabilities`), sections as `SectionCard` + `KeyValueGrid`/`DescriptionList`, `RailContent` for the rail,
`useRecentRecord(type, id, ready)`, `focus` contribution, `NotAvailable` on 404. Tabs that are URLs use
`NavTabs`; in-page panels use `Tabs` with the selection mirrored in `?tab=` (parser in a plain module).
Edits: `Drawer` form → `PATCH` with `expected_version` + `idempotencyHeaders(createIdempotencyKey())`; 409 →
`Conflict` (via `conflictFromError`) with reload; 422 → `errors[{loc,msg}]` mapped to fields.

## 4. Motion contract (what each piece must keep doing)

| Piece | File | Rule |
|---|---|---|
| Route transition | `app/(app)/template.tsx` | fade + 8 px rise, 180 ms enter; nothing on first load; nothing under reduced motion |
| Sidebar indicator | `components/shell/primary-nav.tsx` | one `layoutId`, spring 500/40 |
| Today reveal | `lib/motion/showcase/greeting-reveal.tsx` | ≤ 700 ms, once per `briefing_id:version` (sessionStorage, `reveal-gate.ts`), never offline/stale/reduced, skipped in a hidden tab, GSAP imported on demand, `[data-reveal="line"|"item"]` hooks in `briefing-header.tsx` / `briefing-item-row.tsx` |
| Sign-in entrance | `lib/motion/showcase/login-entrance.ts` | ≤ 900 ms once per load; form animates opacity only (stays interactive); `[data-entrance=…]` and `[data-board]` hooks |
| Sign-in parallax | `app/(auth)/login/material-stage.tsx` | ≤ 12 px, outer `[data-parallax]` wrapper (never the same element GSAP animates) |
| Smooth scroll | `app/(auth)/login/use-lenis.ts` | sign-in only, destroyed on unmount, off under reduced motion |
| Material viewer | `features/material-viewer/material-preview.tsx` | lazy (`next/dynamic` + IntersectionObserver), `frameloop="demand"`, dpr ≤ 1.75, camera eases ≤ 600 ms (`material-scene.tsx` CameraRig), presets instant under reduced motion, textures and materials disposed on unmount, static swatch fallback, caption "not a product photo" |

Reduced motion is `useIsMotionReduced()` (OS *or* in-app `data-motion="reduced"`); the server snapshot is
"reduced", so entrances start only after hydration and never hide server-rendered text first.

## 5. Swapping the visual layer for a design system

Everything visual is reached through three seams; a re-skin touches these and nothing in `features/`:

1. **Tokens** in `src/app/globals.css`: the `--lk-*` palette per theme (verified by
   `lib/design/tokens.contrast.test.ts`, which must still pass), fonts (`--font-sans`, `--font-display`), radii,
   shadows, easing and overlay keyframes. Tailwind sees only the semantic names (`bg-canvas`, `text-ink`,
   `border-border-strong`…); no component uses a raw colour.
2. **Recipes** in `src/components/ui/styles.ts` (`buttonClasses`, `inputClasses`, `linkClasses`,
   `sectionLabelClasses`, focus rings) and the primitives in `src/components/ui/*`. Replace a primitive's markup
   and classes; keep its props and accessibility contract (44 px targets on coarse pointers, visible focus,
   status = text + colour, labelled controls).
3. **Shell** in `src/components/shell/*` (widths and breakpoints: 208/64 px sidebar, 56 px top bar, 300 px rail,
   bottom navigation below 768 px).

The showcase pieces (§4) are additive: they animate attributes (`data-entrance`, `data-reveal`, `data-board`)
and never depend on class names, so a new skin keeps the choreography unless it removes the hooks. The
swatches are replaced by changing `features/material-viewer/swatches.ts` only.

## 6. What is intentionally not built (and where it would go)

- Product/price-list write forms: no backend endpoints yet (Slice 2). Add them to `features/products/` next to
  the read screens; the record already reads `capabilities`.
- Operations and Finance screens: backend Slices 4 and 5. Replace `AreaOverview` with real hubs then.
- Real product media: replace `swatchForDecor` with the product's renditions when `file_object` media exist.
- e2e for the new routes: extend `e2e/axe-sweep.spec.ts`'s `paramCandidates` with `productId`, `partyId` and
  `priceListId` from `/_test/fixtures` refs once the seed publishes them, and add an evidence spec for
  `docs/evidence/checkpoint-2/`.
