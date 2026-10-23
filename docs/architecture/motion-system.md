# Motion system

Status: frozen in Slice 0. Decision record: `docs/DECISIONS.md` ADR-032.

The owner's goal is an Awwwards-level experience built with Motion (Framer Motion's successor package `motion`),
GSAP, parallax and Three.js. The build prompt requires restraint: small 150–220 ms transitions for drawers and
state changes, a waveform only while recording or speaking, no ambient animated AI orb, no neon purple gradients,
no glass panels, and reduced-motion support. This document reconciles the two: **expressive choreography lives on
a short list of showcase surfaces; dense operational screens stay fast and calm; everything honours
`prefers-reduced-motion` and a user preference.**

Libraries in the web scaffold (`apps/web/package.json`): `motion` 14.1.0, `gsap` 3.15.0 with `@gsap/react` 2.1.2,
`three` 0.186.1 with `@react-three/fiber` 9.8.1 and `@react-three/drei` 10.7.9, `lenis` 1.3.26.

---

## 1. Principles

1. **Motion explains change.** Every animation answers "what just happened, where did it go, what is next": an item
   arriving, a document being generated, pieces being nested. Nothing loops for decoration.
2. **Real material, not effects.** Showcase visuals use the company's actual laminate and wood swatch imagery from
   product media (or committed fixture swatches in the demo world), rendered with real lighting. No synthetic neon,
   gradients, glass or mascots.
3. **Work first.** Motion never blocks input, never delays data, never hides content from assistive technology and
   never moves a list the user is reading or listening to.
4. **One timing language.** All surfaces share the tokens in §4 (`apps/web/src/lib/motion/tokens.ts`, mirrored as
   CSS custom properties in `src/app/globals.css`).
5. **Opt-out is total.** Reduced motion (OS or in-app) removes all non-essential motion, including WebGL camera
   movement, parallax, smooth scrolling and staggered entrances.

## 2. Where expressive motion is allowed

| Surface (route) | Tier | What moves | Limits | Reduced motion |
|---|---|---|---|---|
| Sign-in (`/login`) | Showcase | entrance timeline (GSAP) of the wordmark, a layered composition of real swatch textures with pointer parallax, form fade-up; optional Lenis smooth scroll for the short story section below the fold | timeline ≤ 900 ms, runs once per load; pointer parallax ≤ 12 px translation; the form is interactive from first paint | static composition, no parallax, no Lenis, form visible immediately |
| Today greeting (`/today`) | Showcase | greeting and the one factual overview sentence reveal by line (transform + clip), then the first ≤5 briefing items enter with a 40 ms stagger | ≤ 700 ms total; once per briefing version on first view; never on polls, revisits of the same version or while a voice pin is active | text and items rendered in place |
| Briefing updates (`/today`) | Showcase-lite | "N updates" pill slides in (200 ms); applying updates animates only affected rows with FLIP (Motion layout) | ≤ 320 ms; never re-sorts without the user pressing Show; never during Listen to my day | pill appears; rows swap in place |
| 3D material and product viewer (`/products/[productId]/media`, "Material" view) | Showcase | Three.js slab or board rendered at the product's real L×W×T from specifications, textured with the decor swatch from product media (albedo; normal/roughness maps only if supplied); orbit by drag, keys and buttons; labelled "Material preview — not a product photo" | `frameloop="demand"`; no auto-rotate; camera eases ≤ 600 ms on preset views; lazy-loaded (§5) | static rendered image of the default view; orbit replaced by preset-view buttons without animation |
| Cut-plan nesting playback (`/operations/cutting/[planId]`) | Showcase | optional Play control animates pieces into their server-computed placements in placement order, board by board, with pause, step and speed (0.5×–2×) | ≤ 6 s per board at 1×; geometry and metrics come only from the server; never auto-plays | step-through list with the final layout shown immediately |
| Document generation reveal (quote/challan/cut-plan PDF ready) | Showcase-lite | skeleton page → document page reveal when the server confirms the rendered file | 400 ms; progress reflects real job status from polling, never a fake percentage | document appears without transition |
| Page and route transitions (all `(app)` routes) | System | cross-fade + 8 px rise | 180 ms enter, 150 ms exit; content is server-rendered and readable before hydration | none |
| Drawers, sheets, dialogs, menus, rail | System | slide/scale + fade (Motion) | 220 ms enter, 160 ms exit (150–220 ms band from the build prompt) | instant |
| Voice recording / speaking waveform (composer, Listen) | System | live audio level bars | only while recording or speaking; stops on interrupt | static level meter |

## 3. Where it is not allowed

Operational screens stay calm: product lists and detail tabs (except the opt-in Material view), quote workspace and
line grid, configurator results, review pages, challan builder, imports workbench and review, Inbox lists, inventory,
procurement, production, logistics and finance tables, settings, forms, print views, PDF previews, error,
permission-denied, empty and offline states.

Allowed there: micro state transitions ≤ 150 ms (hover, focus ring, press, toggle, checkbox), a 600 ms background fade
on a row that just saved, skeleton opacity pulses while loading, toast slide-in, and drawers per §2.

Banned everywhere:
- ambient animated AI orbs, robot mascots, avatars or "thinking" blobs;
- CSS gradients, neon or purple/violet/fuchsia colours, glass and `backdrop-filter`/`backdrop-blur`
  (WebGL lighting on real textures is shading, not a CSS gradient);
- infinite animations outside skeleton loading and active recording/speaking;
- auto-rotating 3D, autoplay video or sound;
- scroll-jacking or Lenis on any `(app)` route; parallax on text or on data;
- staggered entrances of more than 5 elements, or any stagger in tables;
- animating layout properties (`width`, `height`, `top`, `left`, `margin`) instead of transforms;
- motion that reorders a list during an active spoken briefing, or that delays input or navigation;
- decorative percentage meters and fake progress.

`apps/web/src/lib/design-lint.test.ts` enforces the banned patterns (gradients, `backdrop-blur`, purple utilities,
`animate-` infinite utilities outside the allowlist, `rounded-full` buttons, lucide `Bot*` icons) and the import
rules in §5.

## 4. Tokens

| Token | Value | Use |
|---|---|---|
| `duration.instant` | 0 ms | reduced motion, programmatic state |
| `duration.micro` | 120 ms | hover, press, toggles |
| `duration.fast` | 150 ms | route exit, menus closing |
| `duration.base` | 180 ms | route enter, default transitions (`--default-transition-duration`) |
| `duration.slow` | 220 ms | drawers and sheets entering |
| `duration.emphasis` | 320 ms | FLIP of updated briefing rows |
| `duration.reveal` | 400 ms | document generation reveal |
| `duration.choreo.max` | 700 ms (Today), 900 ms (sign-in) | showcase timelines only |
| `ease.standard` | `cubic-bezier(0.2, 0, 0, 1)` | most transitions (`--ease-standard`) |
| `ease.enter` | `cubic-bezier(0, 0, 0, 1)` | elements arriving (`--ease-enter`) |
| `ease.exit` | `cubic-bezier(0.3, 0, 1, 1)` | elements leaving (`--ease-exit`) |
| `spring.snappy` | stiffness 500, damping 40 | Motion layout (FLIP), toggles |
| `spring.gentle` | stiffness 220, damping 30 | drawers, sheets |
| `stagger.step` | 40 ms, max 5 items | Today first five items only |
| `parallax.max` | 12 px | sign-in only |

## 5. Implementation rules

- **Ownership by library**: CSS transitions for micro states; Motion (`motion/react`, `LazyMotion` with
  `domAnimation` and `m` components) for component, layout, drawer and route transitions; GSAP (`@gsap/react`
  `useGSAP`) only for multi-element showcase timelines (sign-in, Today greeting, cut-plan playback, document reveal);
  Three.js (`@react-three/fiber`, `drei`) only in the material viewer; Lenis only on `/login`.
- **Import boundaries** (lint-enforced): `three`, `@react-three/*` only under `src/features/material-viewer/**`;
  `gsap` only under `src/lib/motion/showcase/**` and the showcase features listed in §2; `lenis` only under
  `src/app/(auth)/login/**`.
- **Lazy loading**: the material viewer is a `next/dynamic` import with `ssr: false`, loaded only when the user opens
  the Material view and the canvas enters the viewport (IntersectionObserver); GSAP is dynamically imported by the
  showcase components. Neither is in any route's initial bundle.
- **WebGL hygiene**: one canvas per page; device-pixel ratio clamped to [1, 1.75]; textures ≤ 2048 px WebP from
  `file_object` renditions (authenticated same-origin URLs, never `next/image`); render on demand, pause when the tab is
  hidden, dispose geometries, materials and textures on unmount; a static image fallback when WebGL is unavailable or
  context creation fails.
- **No layout thrash**: animate `transform` and `opacity` only (plus `clip-path` for text reveals); measure before
  mutate (Motion layout / FLIP); `will-change` only for the duration of an animation; no forced synchronous layout in
  animation frames.
- **Server truth**: playback and reveals visualise server data; they never compute geometry, totals or progress.
- **Accessibility**: animated regions never trap focus; `aria-live` announcements for updates are text, not motion;
  the cut-plan placement table remains the authoritative accessible view; the 3D viewer has a text summary and keyboard
  controls.

## 6. Reduced motion

Effective preference = **reduced** if the OS reports `prefers-reduced-motion: reduce` **or** the user's in-app
preference is `reduced` (`identity.user_preference` ui section, mirrored to the `lk_ui` cookie as
`motion=full|reduced` and rendered server-side as `<html data-motion>`). The in-app preference can reduce motion but
never re-enable motion the OS asked to reduce. Default preference: `full`.

When reduced:
- CSS: transition and animation durations collapse to 0.01 ms (already in `globals.css`) so end events still fire.
- Motion: `MotionConfig reducedMotion="always"` at the root.
- GSAP: timelines are not created; elements render in their final state (`gsap.matchMedia` gate).
- Three.js: no camera tweening, a single static render, preset views switch instantly.
- Parallax, Lenis, staggers, playback animation and the greeting reveal are disabled; the waveform becomes a static
  level meter.
- `prefers-reduced-transparency` and `forced-colors` are respected by the token set (no translucent overlays).

## 7. Performance budgets

| Budget | Target |
|---|---|
| Frame rate | 60 fps (≤16.7 ms per frame) for every animation on the reference machines (this Windows development laptop and a mid-range 2024 Android phone in Chrome); no long tasks > 50 ms during an animation |
| Interaction | INP ≤ 200 ms; animations never block input handlers |
| Loading | LCP ≤ 2.5 s on `/today` and `/login` (production build, local API); the greeting text is in the server HTML and readable before any animation; CLS ≤ 0.05 |
| Initial JS (gzip) per `(app)` route | ≤ 180 KB including Motion's lazy feature bundle (≤ 20 KB); no GSAP, Three.js or Lenis |
| Showcase routes (gzip) | initial ≤ 220 KB; deferred ≤ 300 KB (GSAP ≤ 30 KB; three + fiber + drei chunk ≤ 250 KB, loaded only on demand; Lenis ≤ 5 KB on `/login`) |
| Textures | ≤ 1 MB each, ≤ 4 per viewer |
| Memory | material viewer ≤ 150 MB GPU/JS heap growth; fully released on unmount |

Budgets are checked by the integrator at each slice: `next build` output against the table, a Chrome performance trace
of the showcase routes, and the Playwright checks in §8.

## 8. Tests (planned)

- `apps/web/src/lib/motion/preference.test.ts`: OS reduce wins; in-app reduce applies; cookie parsing round-trips.
- `apps/web/src/lib/design-lint.test.ts`: banned patterns and import boundaries.
- `apps/web/e2e/responsive/n-reduced-motion.spec.ts`: with `reducedMotion: 'reduce'` emulated and with
  `data-motion="reduced"`, `document.getAnimations()` is empty 100 ms after navigation on every manifest route; the
  Three.js chunk is never requested; Today renders its items without stagger.
- `apps/web/e2e/scenarios/b-briefing-stability.spec.ts`: during an active voice pin, polling updates never move rows.
- `apps/web/e2e/visual/capture.spec.ts`: screenshots captured with animations disabled.
- `apps/web/e2e/scenarios/h-cutting-canvas.spec.ts`: playback is optional, pausable, keyboard operable and ends in the
  server layout.
- `apps/web/e2e/scenarios/n-material-viewer.spec.ts`: viewer lazy-loads only after opening the Material view, renders a
  static fallback without WebGL, and disposes on navigation.
