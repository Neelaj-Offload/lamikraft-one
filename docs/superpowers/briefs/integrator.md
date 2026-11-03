# Lane brief: integrator (any slice)

Parameters given at launch: the merge branch (`lane/sN-merge`), the worktree and env slot, the ordered list of
lane branches with their reports, and the base (`main` at a named commit). Never push; commit locally after each
merged lane; never rewrite history; never run two test suites at once; never leave dev servers running.

## Procedure
1. Read every lane report (`docs/lanes/<lane>.md`): migrations, events, keys.py requests, integrator requests,
   concerns, gate output. Read `docs/lanes/merge-s1w2.md` and `docs/lanes/merge-s2w1.md` for the house style.
2. Merge lanes in the given dependency order. After each: reparent and renumber the lane's migrations into one
   linear chain continuing `main`'s (never rewrite a revision already on `main`; update `down_revision`s and any
   test naming revisions; `alembic heads` = 1), union shared files (`keys.py`, seeds in clock order, manifests,
   permission and event registries, `routes.ts`, `query-keys.ts`, messages), apply small safe integrator requests,
   run `npm run test:api`, commit.
3. Web conflict policy: keep the shell, design-system components and showcase pieces from `main`; take lane
   domain logic and forms; wire `PageHeader`/`AreaNav`/`RecordHeader`/`FactStrip` chrome and the Material tab where
   a lane replaced a `main` screen; keep every `routes.test.ts` and `design-lint.test.ts` invariant; a server page
   never calls a `"use client"` function.
4. `npm run api:generate` committed; `npm run check -- --keep-going` 7/7; `npm run test:e2e -- --workers=1`
   (own database; `LK_NEXT_BUILD_CPUS=2 NODE_OPTIONS=--max-old-space-size=2048`; retry once if `next build` stops
   on a security nudge); browser screenshots of the new screens at 1440 and 390 px, light and dark, into
   `docs/evidence/checkpoint-N/` with a README.
5. `docs/PARITY_MATRIX.md`: move rows whose named test passes on the merged branch; `docs/BUILD_STATE.md`:
   a new checkpoint section with the verification table, implemented/simulated/backlog lists and carried open
   items; `docs/DECISIONS.md` for decisions taken in the merge.
6. Report `docs/lanes/merge-sN.md`: steps with commits, migration chain, conflict decisions, gate output, defects
   fixed, open items with owners, applied vs deferred lane requests.

Final message: branch tip, gate counts, decisions, anything not finished with the reason.
