# Checkpoint 3 evidence — Slice 2 on the merged branch (2026-11-04)

64 screenshots of the screens Slice 2 added or changed, at 1440 px and 390 px wide, light and dark
(`<screen>-<width>-<theme>.png`). Taken by `e2e/evidence-cp3.spec.ts` against the production build used by the final
e2e run, on a fresh demo world seeded at `--slice 2` with `--anchor-date 2026-10-12`:

```
LK_E2E_EVIDENCE=cp3 npm run test:e2e -- --no-build e2e/evidence-cp3.spec.ts --project=desktop
```

| Screen | Route | Signed in as |
|---|---|---|
| products-list | `/products` (Add product / Export CSV from capabilities) | Priya (admin) |
| product-record | `/products/<OAK_TRAY>` (tabs incl. Material, Media, History; Edit master data; Archive) | Priya |
| product-media | `/products/<OAK_TRAY>?tab=media` | Priya |
| taxonomy | `/products/taxonomy` (manage controls) | Priya |
| price-list | `/products/price-lists/<EXP-EUR-2026>` (lane editor, RecordHeader) | Priya |
| imports | `/settings/imports/new` (types in dependency order) | Priya |
| users, roles | `/settings/users`, `/settings/roles` | Priya |
| security | `/settings/security` (password, two-step sign-in, sessions) | Meera |
| custom-products, samples | `/sales/custom-products`, `/sales/samples` | Meera |
| operations | `/operations` (cutting and challans Available) | Ravi |
| cut-plan | `/operations/cutting/<CUT-2026-0001>` (editor, results, true-scale canvas) | Ravi |
| challans, challan | `/operations/challans`, `/operations/challans/<DC-2026-0001>` | Ravi |
| search | `/search?q=oak` (grouped results) | Sahil |

Inspected by the integrator: product record, products list (phone) and cut plan (phone, dark) checked by eye; the cut
plan on the phone renders at device width after the scroller fix (before it, the page laid out at ~880 px and
rendered zoomed out). The axe sweep of the same build covered every manifest route in light and dark (see
`docs/lanes/merge-s2.md`, Gates).
