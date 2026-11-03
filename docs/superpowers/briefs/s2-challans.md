# Lane brief: Slice 2 — challans as documents

Branch `lane/s2w2-challans` from `main` c94a13d; worktree `D:\lk-wt\work`, env slot 4. (The first launch gave this
brief inline; this file records it for resumption.) Never push; small named commits; never two test suites at
once; never leave dev servers running.

## Ownership
`backend/app/modules/challans/**`, `backend/app/seed/world/challans.py`, its tests, `apps/web/src/features/challans/**`
and the challan routes and pages. Shared registries (`keys.py`, seed runner, `routes.ts`, `query-keys.ts`,
messages, permission and event registries) take additive edits only.

## Scope
- Challans as documents with full legacy parity: every challan type, destination and field in
  `CURRENT_STATE_SPEC.md` and `OPUS_5_5_BUILD_PROMPT.md`; every challan row of `docs/PARITY_MATRIX.md` mapped to code
  and a named passing test.
- Validated state transitions; DC numbering through the platform numbering service (yearly reset, BUILD_STATE §5 #1);
  ReportLab PDF on the existing documents engine, print view, CSV export; summaries.
- The legacy challan-validation bug (PLAN §10.1) with a named regression test; IDOR and permission tests in the
  house style; optimistic-concurrency 409s.
- No stock movement: the challan movement policy belongs to Slice 4.
- Web: list, create, detail workspace with debounced edits that surface failures, PDF/print, CSV; build-guide §0
  ground rules (`docs/superpowers/specs/2026-11-02-checkpoint-2-build-guide.md`); Playwright specs for the main journey.

## Migration
`backend/migrations/versions/0010_challans_slice2.py` chained on `main`'s head; the integrator renumbers it.

## Verification
`npm run test:api`, `npm run check -- --keep-going` 7/7, `npm run api:generate` committed, the lane's e2e specs.
Report `docs/lanes/challans-s2.md`: what was built, parity rows with test names, migrations, events and `keys.py`
additions, integrator requests, gate output.
