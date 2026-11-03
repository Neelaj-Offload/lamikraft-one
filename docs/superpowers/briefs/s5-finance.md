# Lane brief: Slice 5 — finance (invoices, credit notes, receipts, allocations, ageing, accounting handoff, margin)

Branch `lane/s5-finance` from `main` (after the Slice-4 checkpoint). Module owner:
`backend/app/modules/finance/**`, `apps/web/src/features/finance/**`, pages under `src/app/(app)/finance/**`
(replace the honest overview with the real area), copy `src/messages/finance.ts`. Never push; small named
commits; never two test suites at once; never leave dev servers running.

## Contracts (read first)
1. `docs/design/source/operations.md` §9 finance (invoice and credit-note drafts, issue gate on tax and provider
   configuration with labelled drafts still allowed, receipts, allocations, ageing, CSV adapter + Demo accounting
   adapter, reconciliation, margin policy and exceptions), §10–§12, §14 (scenario M).
2. `docs/PLAN.md` Slice 5 "Finance" and scenario M; `events.md` §3.11 (`finance.*`, `sales.quote.margin_below_threshold`
   ids only); `permissions.md` §7.8 (`finance.*`: approve never by the creator; issue gate), `conventions.md`
   (money, rounding policy: line-level HALF_UP to the minor unit), `docs/BUILD_STATE.md` §5 decisions 3, 4, 9, 10,
   14 (accounting system, e-invoice provider, company identity, rounding, HSN and financial-year start) — all stay
   Demo defaults with labelled drafts; `platform/system/integrations.py` (add `accounting` integration def),
   `platform/org/settings.py` (`bank_details`, `document_terms`, `company_identity` are printed on documents).
3. Existing modules: `modules/orders` and `modules/challans` (invoice suggestions from issued delivery challans:
   `finance.invoice_suggestion` consumer named in events §1), `modules/sales` (quote margin: costs of record from
   `modules/pricing` with `COST_GUARD`), `core/documents` (PDF engine), `core/csv_safe`, `platform/numbering`
   (financial-year numbering from April, `BUILD_STATE` decision 1), `modules/tasks` rules registry.

## Deliverables
- Invoices (`INV-FY-NNNN`, financial year from April) and credit notes drafted from issued challans/orders with
  server-computed totals; **issue gate**: tax profile and e-invoice provider not configured → issue blocked with
  `finance.invoice.issue_blocked` and the draft labelled "Draft — not valid for trade"; approve (never the
  creator), issue (RA + step-up), overdue scheduling; PDF (company identity, bank details, terms; labelled
  placeholders when not configured), CSV.
- Receipts (`RCPT-`), allocations to invoices (partial, over-allocation impossible), unallocated detection,
  ageing buckets (server-computed, company time).
- Accounting handoff: a `CSV` adapter (journal export with `csv_safe`) and a `Demo` adapter that records the
  export and returns a simulated acknowledgement; `finance.accounting_export.completed/failed`; reconciliation of
  exported vs acknowledged; integration status `accounting`.
- Margin policy: margin computed from costs of record (redacted without `pricing.cost.read`; never
  model-exposed); `sales.quote.margin_below_threshold` (ids only) and a finance exceptions list.
- Briefing families: invoice suggestions, overdue invoices, unallocated receipts, margin exceptions.
- **Web**: `/finance` hub with real figures (`FactStrip` from server summaries), `/finance/{invoices,credit-notes,
  receipts}` lists and records, `/finance/exceptions`, `/finance/ageing`, `/finance/accounting-sync`; the issue gate
  explained in plain copy; controls from `capabilities`.
- **Tests**: scenario M (finance part): draft → blocked issue with reasons → receipts and allocations never
  over-allocate → ageing → CSV export inert formulas → Demo handoff acknowledged and reconciled; separation of
  duties; IDOR matrix; cost redaction canary.

## Migration
`backend/migrations/versions/0040_finance_slice5.py`, `down_revision` = current head on `main`.

## Verification and report
`npm run check -- --keep-going` 7/7, `npm run test:api`, `npm run api:generate` committed, web gates;
`docs/lanes/finance-s5.md`. Final message: branch tip, counts, unfinished items with reasons.
