# Checkpoint 6 evidence — Slice 5 (2026-11-06)

64 screenshots, 16 screens at 1440 and 390 CSS px in light and dark. Captured from the production build of `1a81e99` in the final full browser run: **314 passed, 754 scoped/opt-in skips, 0 failed**. Every PNG was rewritten by that final run.

The demo world was seeded with `--slice 5 --anchor-date 2026-10-12`, followed by a synthetic migration dry run, database/storage backup and a real restore rehearsal. Runtime API/worker time is system time in this runner; canonical-morning acceptance is still a Slice-6 check. No actual legacy export or live provider credential is used.

PowerShell command (from the worktree root):

```powershell
$env:LK_NEXT_BUILD_CPUS='2'
$env:NODE_OPTIONS='--max-old-space-size=2048'
$env:LK_E2E_EVIDENCE='cp6'
npm run test:e2e -- --workers=1
```

| Screen | Route | Person | 1440 light | 1440 dark | 390 light | 390 dark |
|---|---|---|---|---|---|---|
| finance-overview | `/finance` | Ananya | [PNG](finance-overview-1440-light.png) | [PNG](finance-overview-1440-dark.png) | [PNG](finance-overview-390-light.png) | [PNG](finance-overview-390-dark.png) |
| finance-invoices | `/finance/invoices` | Ananya | [PNG](finance-invoices-1440-light.png) | [PNG](finance-invoices-1440-dark.png) | [PNG](finance-invoices-390-light.png) | [PNG](finance-invoices-390-dark.png) |
| finance-receipts | `/finance/receipts` | Ananya | [PNG](finance-receipts-1440-light.png) | [PNG](finance-receipts-1440-dark.png) | [PNG](finance-receipts-390-light.png) | [PNG](finance-receipts-390-dark.png) |
| finance-receipt | `/finance/receipts/<RCPT_MAISON>` | Ananya | [PNG](finance-receipt-1440-light.png) | [PNG](finance-receipt-1440-dark.png) | [PNG](finance-receipt-390-light.png) | [PNG](finance-receipt-390-dark.png) |
| finance-ageing | `/finance/ageing` | Ananya | [PNG](finance-ageing-1440-light.png) | [PNG](finance-ageing-1440-dark.png) | [PNG](finance-ageing-390-light.png) | [PNG](finance-ageing-390-dark.png) |
| finance-exceptions | `/finance/exceptions` | Ananya | [PNG](finance-exceptions-1440-light.png) | [PNG](finance-exceptions-1440-dark.png) | [PNG](finance-exceptions-390-light.png) | [PNG](finance-exceptions-390-dark.png) |
| finance-accounting-sync | `/finance/accounting-sync` | Ananya | [PNG](finance-accounting-sync-1440-light.png) | [PNG](finance-accounting-sync-1440-dark.png) | [PNG](finance-accounting-sync-390-light.png) | [PNG](finance-accounting-sync-390-dark.png) |
| production-what-if | `/operations/production/what-if` | Deepa | [PNG](production-what-if-1440-light.png) | [PNG](production-what-if-1440-dark.png) | [PNG](production-what-if-390-light.png) | [PNG](production-what-if-390-dark.png) |
| cut-plan-offcuts | `/operations/cutting/<CUT_PLAN_WALNUT>` | Deepa | [PNG](cut-plan-offcuts-1440-light.png) | [PNG](cut-plan-offcuts-1440-dark.png) | [PNG](cut-plan-offcuts-390-light.png) | [PNG](cut-plan-offcuts-390-dark.png) |
| samples | `/sales/samples` | Meera | [PNG](samples-1440-light.png) | [PNG](samples-1440-dark.png) | [PNG](samples-390-light.png) | [PNG](samples-390-dark.png) |
| finance-invoice | `/finance/invoices/<scenario-M draft>` | Ananya | [PNG](finance-invoice-1440-light.png) | [PNG](finance-invoice-1440-dark.png) | [PNG](finance-invoice-390-light.png) | [PNG](finance-invoice-390-dark.png) |
| settings-migration | `/settings/migration` | Priya | [PNG](settings-migration-1440-light.png) | [PNG](settings-migration-1440-dark.png) | [PNG](settings-migration-390-light.png) | [PNG](settings-migration-390-dark.png) |
| migration-run | `/settings/migration/runs/<synthetic run>` | Priya | [PNG](migration-run-1440-light.png) | [PNG](migration-run-1440-dark.png) | [PNG](migration-run-390-light.png) | [PNG](migration-run-390-dark.png) |
| settings-backups | `/settings/backups` | Priya | [PNG](settings-backups-1440-light.png) | [PNG](settings-backups-1440-dark.png) | [PNG](settings-backups-390-light.png) | [PNG](settings-backups-390-dark.png) |
| cut-plan-from-offcut | `/operations/cutting/<scenario-O plan>` | Deepa | [PNG](cut-plan-from-offcut-1440-light.png) | [PNG](cut-plan-from-offcut-1440-dark.png) | [PNG](cut-plan-from-offcut-390-light.png) | [PNG](cut-plan-from-offcut-390-dark.png) |
| sample-lineage | `/sales/samples/<scenario-O sample>` | Meera | [PNG](sample-lineage-1440-light.png) | [PNG](sample-lineage-1440-dark.png) | [PNG](sample-lineage-390-light.png) | [PNG](sample-lineage-390-dark.png) |

Base screens are captured by `e2e/evidence-cp6.spec.ts`. The invoice, migration/backup, offcut and lineage records are captured in their real scenario sessions by `m-finance`, `m-migration` and `o-offcut-lineage-what-if`. Migration first proves `401 mfa_required`, then confirms a genuine TOTP. The sample link points to the exact issued challan; optional absent custom-product/quote links remain honest empty states.

Visual review by the integrator: finance-overview (390 dark), finance-invoice (1440 light), migration-run (390 light), settings-backups (1440 dark), cut-plan-from-offcut (390 dark), sample-lineage (390 light), production-what-if (1440 light). Selected views are legible in both themes; the invoice shows its draft label and blockers, and the backup page shows actual restore facts. These are viewport captures: some long workflow sections are below the phone fold. The desktop what-if date segments wrap in its narrow grid. Final Slice-6 evidence should focus those workflow sections and review field sizing.

Functional evidence and all failed/targeted runs: [`../../lanes/merge-s5.md`](../../lanes/merge-s5.md). Gate logs: `D:\lk-wt\s5-merge-testapi.log`, `s5-merge-check-final.log`, `s5-merge-e2e-final.log`. Broader open scope is recorded in BUILD_STATE §15.
