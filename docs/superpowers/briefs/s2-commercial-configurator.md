# Lane brief: Slice 2 — commercial configurator follow-up

Branch `lane/s2w1-commercial`, continuing its last commit 8ff21bd; worktree `D:\lk-wt\sales`, env slot 6. Never
push; small named commits; never two test suites at once; never leave dev servers running.

## State at launch
The commercial-2 lane ended without a report and left an uncommitted product configurator on disk:
`backend/app/modules/sales/configurator.py`, `backend/tests/integration/sales/test_configurator.py`, and edits to
`sales/router.py`, `sales/service.py`, `tests/integration/sales/test_custom_products.py`. Its committed work
(custom products, samples, price lists, FX rates, quote settings, quote revise/extend/archive/correct, duplicate,
currency change, revision compare/restore, CSV exports, e2e specs written but not run) is being merged by the
Slice-2 integrator.

## Scope
1. Read the uncommitted diff and the commit history of the branch; work out what the configurator is meant to do
   from `docs/PLAN.md` Slice 2 ("custom products with promotion"), `docs/PARITY_MATRIX.md` and
   `CURRENT_STATE_SPEC.md`; finish it, with tests, and its web entry point if the PLAN calls for one.
2. Run the branch's Playwright specs from 8ff21bd once against this slot and fix what fails in this lane's code.
3. Write the missing report `docs/lanes/commercial-s2.md` covering the whole lane (both the committed work and this
   follow-up): what was built, parity rows with test names, migrations, events and `keys.py` additions, integrator
   requests, gate output.

## Verification
`npm run test:api`, `npm run check -- --keep-going` 7/7, `npm run api:generate` committed.
