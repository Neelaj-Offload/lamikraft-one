# Lane report: Slice-2 merge (integrator)

Branch `lane/s2-merge` (from `main` c94a13d; `main` merged in at the end), worktree `D:\lk-wt\integ`, env slot 8.
Status: **DONE_WITH_CONCERNS** — every gate green on the final tip; concerns are under "Open items".

## Steps

| # | Step | Commit | Result |
|---|---|---|---|
| 1 | Merge `lane/s2w1-platform` (report `platform-s2.md`) | `8496528` | 0010 kept; routes/query-keys unioned; main's settings hub kept with the platform routes; `/invite`, `/reset-password` no-referrer; `test:api` 1112 passed |
| 2 | Merge `lane/s2w1-catalogue` (report `catalogue-s2.md`) | `e82f4e6` | migration → 0011; products/parties screens merged (below); `test:api` 1188 passed; vitest 327 (touched areas) |
| 3 | Merge `lane/s2w1-commercial` 8ff21bd (no report then; commits read as the report) | `4cf4b2c` | migration → 0012; price-list screens merged; FX test MFA actor; `test:api` 1223 passed; vitest 569 |
| 4 | Merge `lane/s2w2-cutting` (report `cutting-s2.md`) | `84b5c2b` | migration → 0013; keys `CUT_PLANS`; Operations overview links cutting; `test:api` 1265 passed; vitest 584 |
| 5 | `npm run api:generate` | `5b4e4ef` | 228 paths, 493 schemas |
| 6 | check on the four lanes | `7963fbb` | first run: ruff import order in the costing test (fixed); then 7/7 |
| 7 | e2e on the four lanes, defects fixed | `47d10a2`, `336a09a`, `586e50b`, `cf1c4bd` | run 1: build stopped (stale `node_modules`, Next 16.4.0; `npm ci`); run 2: 145 passed / 26 failed; run 3: 168 / 4; run 4: 170 / 2; both fixed and re-run green (targeted) |
| 8 | Merge `lane/s2w2-challans` (report `challans-s2.md`) | `84d6b32` | migration → 0014; new 0015 cross-lane FKs; Kaveri seeded before Precision Edge; e2e at `--slice 2`; `test:api` 1308 passed; vitest 602 |
| 9 | Merge `lane/s2w1-commercial` follow-up 8ff21bd..359a7ba (configurator; report `commercial-s2.md`) | `17a2f99` | server-safe list-state modules kept; scenario C number assertion relaxed; api:generate 243 paths |
| 10 | Evidence spec; final gates; PARITY, BUILD_STATE, DECISIONS, evidence; merge `main` (docs-only 4609a3b..62d6447) | `d00e10e` docs, then the `main` merge | see "Gates" |

## Migration chain

`0009_agents_slice1` (main) → `0010_platform_slice2` → `0011_catalogue_slice2` → `0012_commercial_slice2` →
`0013_cutting_slice2` → `0014_challans_slice2` → `0015_slice2_cross_lane_links` (integrator: challan custom-line FK
to `sales_custom_product`, `sales_sample.challan_id` FK to `challans_challan`, both RESTRICT). Every lane migration
was renamed and reparented (revision, `Revises:` and `down_revision`); no revision already on `main` was touched.
`alembic heads` = 1; 0015 upgrade → downgrade → upgrade and `alembic check` verified on `lk_wt8`.

## Conflict decisions (web)

Policy (brief §3, ADR-056): one screen per route; main's shell, chrome and showcase pieces; the lanes' forms,
commands and domain logic.

- **Products list** `/products`: main's catalogue (facets, stats strip, price columns) + the lane's capability-gated
  Add product / Export CSV in the PageHeader (`productExportHref` moved to `features/products/api.ts`). The lane's
  list, list-state, completeness and detail components were removed; their tests were ported.
- **Product record** `/products/[id]`: main's record (RecordHeader, `?tab=` tabs, Material tab, rail) with the lane's
  `SectionEditor` around each read view (overview/master, specification, packaging), Archive/Restore in the header,
  and Media and History tabs when the server lists those sections. The cache holds the raw server record (the
  editors round-trip every field) and the view parses it with `select`. The server's `/products/{id}/{section}`
  paths redirect to the matching tab.
- **Taxonomy**: the lane's manager with PageHeader + products area nav; readable with `catalogue.product.read`,
  manage controls only with `catalogue.taxonomy.manage` (main's read-only view removed).
- **Customers** `/sales/parties*`: main's screens; the record gains Archive/Restore from the server capabilities;
  customer types moved to `features/parties/customer-types.tsx` (`/settings/customer-types`).
- **Price lists**: main's list (URL filters) + the lane's New price list dialog; the detail is the lane's editor with
  RecordHeader chrome (main's read-only detail removed).
- **Settings**: main's hub lists the platform, imports, lookups, customer types, quote settings and FX rates routes
  with hints; imports, lookups, new product, custom products, samples, FX rates and quote settings get PageHeader.
- **Operations**: the overview marks cutting and challans Available (link for people with the key).
- **Auth**: platform's `/invite`, `/reset-password`, `/forgot-password`, `/two-step` moved into `(auth)/(centered)`,
  whose layout gives the `main` landmark.

Backend: `security/conftest.py` keeps platform's identity world; the costing test imports the sales world into its
module. `collab/test_internal_notes.py` (platform) kept; the challans note test moved to
`challans/test_challan_internal_notes.py`. `pricing.fx_policy.manage` is MFA-flagged and now enforced by platform's
step-up: the FX test uses an MFA-verified actor.

## Defects found and fixed in the merge

1. Five server pages called functions from `"use client"` modules (500 on `/search`, `/settings/users`,
   `/settings/lookups`, `/sales/custom-products`, `/sales/samples`); parsers moved to plain modules (the commercial
   follow-up made the same fix independently; its `list-state.ts` files were kept).
2. Platform auth pages lost their `main` landmark after Checkpoint 2 moved the auth layout (axe).
3. Product forms kept a server field error after the field was corrected, so native validation blocked the re-submit.
4. `approvals.expire_due` expired every seeded review five minutes into an e2e run (absolute fixture times):
   not scheduled outside production (ADR-057).
5. The cutting editor's 860 px table let its visually hidden inputs widen the phone layout viewport to ~880 px; the
   page rendered zoomed out and "Create plan" could not be pressed (`relative` + `contain:inline-size` on the scroller).
6. Lane e2e specs written but never run: strict-mode locators, hidden switch/checkbox inputs, the Nordhaus draft
   being in review at D0, the board canvas read before render, a 30 s budget for four imports.
7. Stale `node_modules` in the worktree (Next 16.4.0, no Fraunces): `npm ci` from the unchanged lockfile.

## Lane requests: applied / deferred

| Request | Status |
|---|---|
| All lanes: regenerate `openapi.json` / `schema.d.ts` | applied (243 paths at the end) |
| Platform: `/invite`, `/reset-password` no-referrer; DECISIONS §2 | applied (ADR-052/053) |
| Platform: replace `INTERIM(api-generate)` `requestUntyped` calls | deferred — typed calls across settings/collab/search/catalogue/cutting are a web refactor, not a merge step [web] |
| Platform: `/activity` in the More hub; `.env.example` S3 vars | deferred [web, platform] |
| Catalogue: `PRIYA` PersonKey | applied |
| Catalogue: pricing `active_price_exists`, imports through `import_standard_price`, price-list customer-type FK | deferred — changes the import quarantine semantics and tests [catalogue + commercial] |
| Catalogue: platform image variants for media thumbnails | deferred — variants are created at upload only; seeded/imported media would 404 [catalogue, platform] |
| Commercial: renumber, repoint FG-PRC-05/06, FG-QRV-01/05, LM-68, FG-CP-17 | applied |
| Commercial: challan FK to custom products; sample → challan FK | applied (0015) |
| Commercial: `challans.challan.issued` carries `sample_id` | partly — the field exists and is null; a challan has no sample reference yet [challans, sales] |
| Commercial: configurator shows `primary_image`, line `media_snapshot` file ids (FG-QLN-13) | deferred [sales, web] |
| Cutting: `keys.CUT_PLANS`, Operations hub link, PARITY rows, canonical-decor decision | applied (ADR-055) |
| Cutting: `ops.cut_plans` tasks consumer | deferred [tasks] |
| Challans: renumber; validate custom line; Precision Edge number; e2e `--slice 2`; repoint `l-legacy-parity` rows | applied |
| Challans: `ops.returnables` rules; recent records for challans | deferred [tasks, ui] |

## Gates (final, on `17a2f99` + the evidence spec; the docs and the `main` merge add no code)

- `npm run test:api`: **1313 passed**, 0 failed, 1 warning (PIL decompression-bomb test), 26 min 22 s.
- `npm run check -- --keep-going`: **7/7 PASS** — ruff; pytest unit + contract 545 passed; alembic heads == 1;
  api:check (`openapi.json` matches the app); web lint; web typecheck; web vitest 53 files / 611 tests.
- `npm run test:e2e -- --workers=1` (production build with `LK_NEXT_BUILD_CPUS=2`,
  `NODE_OPTIONS=--max-old-space-size=2048`; own database `lk_wt8_e2e`; demo world `--slice 2`): **193 passed,
  0 failed**, 395 skipped (project-scoped and opt-in specs), 7.1 min. Includes the lanes' written-not-run specs
  (catalogue, imports, commercial incl. 8ff21bd, cutting scenario H on desktop and phone, challans) and the axe
  sweep of every manifest route in light and dark, now with challan and cut-plan records.
- Evidence: `docs/evidence/checkpoint-3/` (64 PNGs, README).
- Earlier runs on the way (all recorded in the scratchpad logs): four-lane `test:api` 1112 → 1188 → 1223 → 1265;
  four-lane check 7/7 after one ruff fix; four-lane e2e 145/26 → 168/4 → 170/2 → targeted re-runs green;
  challans `test:api` 1305 + 3 re-run; memory stayed under 1 GB free during most runs (suites took 26–45 min), no
  run died.

## Open items (owners)

See `docs/BUILD_STATE.md` section 11 ("Open items carried"); the ones created by this merge: expired reviews leave
quotes in `internal_review` [sales, approvals]; `sample_id` on `challans.challan.issued` [challans, sales]; dynamic
customer types in party forms and the price-list customer-type FK [parties web, pricing]; imports through
`import_standard_price` [catalogue, commercial]; media variants and configurator images [catalogue, sales, web];
typed API adapters [web]; FX policy step-up dialog [commercial web]; Kaveri is created by the challans seed until a
procurement/parties seed owns it [fixtures].
