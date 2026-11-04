# Lane report: Slice 5 — finance (`lane/s5-finance`)

Worktree `D:\lk-wt\identity`, env slot 1 (API 8010, web 3010), branched early from `lane/s4-orders-inventory`
`d2942ac` (owner-sanctioned; the brief says "from main after the Slice-4 checkpoint"). It depends only on orders and
challans from Slice 4. Never pushed. Migration placeholder **0080**. The run was paused once by the owner and resumed
from the state on disk (nothing was redone).

## What was built

### Backend — `backend/app/modules/finance/`
| File | What |
|---|---|
| `models.py`, `enums.py` | `finance_invoice` (invoices **and** credit notes by `doc_type`; `draft_ref` `FD-NNNNN` at drafting, `document_number` only at issue, UNIQUE(company, doc_type, number); CHECKs: approver ≠ creator, number only when issued, issued ⇒ number + date + issued_at, credit note ⇒ original, cancelled ⇒ reason, amounts ≥ 0), `finance_invoice_line` (links to the SO line, challan, challan line and the credited invoice line; tax figures from the profile only), append-only `finance_invoice_status_history`, `finance_tax_profile` (business-entered rate + source, verified by a second person — CHECK verifier ≠ author), `finance_receipt`, append-only `finance_allocation` (reversal = negated row, UNIQUE `reverses_allocation_id`, CHECK one source and sign), `finance_invoice_suggestion` (UNIQUE challan), `finance_accounting_export` + `finance_accounting_sync_item`, `finance_margin_exception` (restricted figures) |
| `gate.py` | `check()` — the issue gate, evaluated on every read and again inside the issue transaction: approval of the current version by someone other than the creator, company identity (legal name, address, GSTIN), party billing details, tax profile chosen **and verified**, a **verified** e-invoice provider when the profile requires e-invoicing (none exists in Demo, so such invoices stay blocked), recomputed totals = stored totals, per SO line `qty ≤ delivered − invoiced + credited`, per challan line the same, for credit notes never more than creditable. Each blocker has a stable code and a fix path |
| `invoices.py` | drafts from an issued Outward challan (its not-yet-invoiced quantities at the order's prices), from an order's delivered-not-invoiced quantities, or manual lines; edits while draft; credit notes against issued invoice lines; table-driven transitions submit / approve (never the creator) / reject / issue (RA step-up) / cancel; a refused issue is recorded (history + `finance.invoice.issue_blocked`) and answered `issued: false` with the blockers; the issue locks the order / challan / credited lines (lock order document → lines) and assigns `INV-{fy}-NNNN` / `CN-{fy}-NNNN` (April financial year) in the same transaction; reads with live gate, capabilities, `allowed_transitions`, allocations, related documents |
| `receipts.py` | `RCPT-{fy}-NNNN`; allocations lock source then invoice and re-read both sums inside the lock — over-allocation is impossible (barrier test); same party and currency only; reversal once; receipt void reverses its live allocations; an issued credit note settles its original invoice first |
| `ageing.py` | ageing per (party, currency) as of a company-local date, buckets current / 1–30 / 31–60 / 61–90 / > 90, never summed across currencies, invoices without a due date flagged; the hub summary (counts, figures per currency, integration states, list capabilities); the exceptions list |
| `accounting.py`, `adapters/` | `csv` adapter (balanced journal through `core/csv_safe`; a missing account code blocks the document) and `demo` adapter (records the export, simulated acknowledgement `DEMO-ACK-…`, labelled); a document is exported at most once by a completed batch; reconciliation of exported vs acknowledged (Demo: against the simulated acknowledgement; CSV: from the accounting side's references and totals) listing every mismatch; status reads integration `accounting` (Demo — not connected) |
| `margin.py` | margin of an issued quote from the costs of record (latest cost version effective on the day, same currency and unit only — nothing converted or invented); `finance.margin_check` consumer of `sales.quote.issued` records a margin exception once per revision below `finance_policy.margin_threshold_percent` and emits `sales.quote.margin_below_threshold` (ids only); figures are `COST_GUARD` (`pricing.cost.read`, `model_exposure="deny"`) |
| `suggestions.py` | `finance.invoice_suggestion` consumer of `challans.challan.issued`: one suggestion per issued Outward challan to a customer (replays change nothing; migration/import challans skipped); dismiss with a reason |
| `config.py` | tax profiles: create (MFA + RA), verify by a second person (MFA, never the author) |
| `documents.py` | invoice / credit-note PDF (company identity, bank details with the restricted-field rule, invoice terms; labelled placeholders when not configured; drafts watermarked "DRAFT - NOT VALID FOR TRADE" and labelled "Draft — not valid for trade"; "Tax: Not calculated — no tax profile"); list CSV through `csv_safe` |
| `jobs.py` | `finance.overdue_sweep` and `finance.unallocated_sweep` (every 15 min, per company, company time, once per document via `*_notified_on`) |
| `rules.py` | briefing families via the `tasks.rules` consumer: `fin.invoice_suggestions`, `fin.invoice_approvals` (approval candidates exclude the creator; blocked issue → task for the creator), `fin.overdue_invoices`, `fin.unallocated_receipts`, `fin.accounting_sync`, `mgmt.margin_exceptions` (costing sensitivity; ids and names only); completion checks |
| `readers.py`, `policies.py`, `events.py`, `schemas.py`, `common.py`, `router.py`, `manifest.py` | source readers (no margin values), resource policies (company-level finance records; lines/history through their invoice), sequences and settings (`finance_policy`, `finance_account_mapping`), 36 operations on 29 paths under `/api/v1/finance` |

Outside the module (minimal): `platform/system/integrations.py` (`accounting` description; new `e_invoice` integration, Demo), `platform/org/settings.py` (`document_terms.invoice`), `platform/events/catalogue_data.py` + `docs/architecture/events.md` §2/§3.11/§4 (Slice-5 finance events, payloads ids/codes/dates only), `modules/tasks/rules/consumer.py` (`SLICE5_TRIGGERS` from `finance.rules.EVENT_FAMILIES`) and `modules/tasks/responsibility.py` (queues `fin` → finance, `mgmt` → management), `seed/world/finance.py`, `tests/integration/system/test_integrations.py` (the new key).

### Web — `apps/web/src/app/(app)/finance/**`, `src/features/finance/**`, `src/messages/finance.ts`
| Route | Screen |
|---|---|
| `/finance` | hub replacing the honest overview: `FactStrip` from the server summary (drafts, waiting for approval, issue blocked, open, overdue, to invoice, unallocated receipts, margin exceptions, sync attention), receivables per currency, the issue gate explained in plain copy, accounting / e-invoice "Not connected (demo)", tax profiles count, invoice suggestions (draft / dismiss with a reason) |
| `/finance/invoices`, `/finance/credit-notes` | lists (search, status, open / overdue in the URL, pagination, CSV link, honest empty states) |
| `/finance/invoices/[id]`, `/finance/credit-notes/[id]` | workspace: label, the issue check (every blocker in plain words with its fix link), tax profile picker on drafts, totals, bill-to, lines, settlements, related documents, history; actions only from `allowed_transitions` / `capabilities` (submit, approve, send back, issue, cancel, create credit note); PDF link |
| `/finance/receipts`, `/finance/receipts/[id]` | list + "Record receipt" dialog (capability-driven); detail with allocation to the party's open invoices, allocation reversal, void |
| `/finance/ageing` | ageing table with the as-of date in the URL, totals per currency, no-due-date note |
| `/finance/exceptions` | blocked issues, overdue, unallocated, export failures, reconciliation mismatches; margin exceptions (figures only with cost access) |
| `/finance/accounting-sync` | Demo notice, status and account-code completeness, CSV / Demo export, journal download, Demo reconciliation, tax profiles (verify by a second person) |
Routes in `src/lib/routes.ts` (six context routes + three detail routes), query keys `finance.*`, invalidation `finance.changed`.

## Migration
`backend/migrations/versions/0080_finance_slice5.py`, `down_revision = "0040"` (this branch's head, the Slice-4
placeholder). Ten tenant tables with forced RLS, enum CHECKs, append-only allocations and status history, immutable
draft ref / receipt number, party, amount and currency, and a trigger freezing an issued document (number, date, party,
currency, totals, due date, status, tax profile) and its lines. Upgrade → downgrade → upgrade and `alembic check`
clean on `lk_wt1`.

## Scenario M (finance part) — test table
| Step | Test | Result |
|---|---|---|
| End to end: suggestion → draft → blocked issue with reasons → configuration → approval by a second person → `INV-2026-27-0001` → receipts never over-allocate → ageing → CSV blocked without codes, inert formulas → Demo handoff acknowledged and reconciled → still Demo — not connected | `tests/integration/flows/test_scenario_m_finance.py::test_scenario_m_finance` | pass |
| Draft allowed, issue blocked without a verified tax profile, number only at issue (design acceptance name) | `tests/integration/finance/test_issuance_gate.py::test_draft_allowed_issue_blocked_without_verified_tax_profile_and_number_assigned_only_at_issue` | pass |
| Separation of duties (service, capability, DB CHECK) | `test_issuance_gate.py::test_approval_is_never_by_the_creator`, `test_briefing_rules.py::test_approval_task_is_never_offered_to_the_creator` | pass |
| Invoiced ≤ delivered; issued documents frozen; credit notes bounded and settle the original | `test_issuance_gate.py::test_invoiced_quantity_never_exceeds_delivered`, `::test_issued_documents_and_their_lines_are_frozen`, `::test_credit_note_bounded_by_creditable_and_settles_the_original`, `::test_cancel_and_invalid_transitions` | pass |
| Allocations bounded and ageing per currency (design acceptance name) | `tests/integration/finance/test_allocations.py::test_allocations_bounded_and_ageing_per_currency` | pass |
| **Never over-allocate under concurrency** (committed DB, 8 threads, barrier) | `test_allocations.py::test_concurrent_allocations_never_over_allocate` | pass |
| Append-only allocations, reversal once, receipt void | `test_allocations.py::test_reversal_once_append_only_and_receipt_void` | pass |
| CSV journal inert + mapping blocks + reconciliation mismatch; Demo acknowledged and reconciled | `tests/integration/finance/test_accounting.py` (2 tests, incl. `fin.accounting_sync`) | pass |
| Cost redaction canary (sales sees null figures; never in model context, event payload, reader or briefing facts) | `tests/integration/finance/test_margin.py` (2 tests) | pass |
| Suggestions once per challan (replays), approvals, overdue / unallocated sweeps once, Ananya's briefing holds the Maison receipt, nothing reaches sales | `tests/integration/finance/test_briefing_rules.py` (3 tests) | pass |
| PDFs (draft label + placeholders; issued identity + terms), CSV inert | `tests/integration/finance/test_documents.py` (3 tests) | pass |
| IDOR / permission matrix over HTTP | `tests/integration/finance/test_idor.py` (4 tests) | pass |
| Lane contracts (enum CHECKs, RLS, append-only, frozen triggers, events ids-only, FY sequences, every route permissioned, blocker codes) | `tests/contract/finance/test_lane_schema.py` (6 tests) | pass |
| Pure rules (buckets, HALF_UP rounding, balanced inert journals, transition table) | `tests/unit/finance/test_finance_pure.py` | pass |
| Web (URL state, blocker copy for every code, hub, gate listing, transitions from the server) | `apps/web/src/features/finance/finance.test.tsx` (4 tests) | pass |
| UI path | `apps/web/e2e/scenarios/m-finance.spec.ts` | see Gates |

## Security
- Finance records are company-level: personas without finance keys (sales, operations, warehouse) get 403 on every
  finance list and 403/404 on records; management reads and approves but cannot draft, record, issue or export;
  finance cannot approve its own drafts (service rule, capability, `approver_not_creator` CHECK, approval task
  candidates). Unknown ids and invoice ids on credit-note routes are 404 (`test_idor.py`).
- Step-up: issue RA; receipt void RA; export RA; configuration MFA + RA; tax-profile verify MFA (never the author).
- Money never leaves through events (contract test on catalogue fields), readers carry ids/names/codes; margin values
  are `COST_GUARD` with `model_exposure="deny"`; bank account numbers follow `org.bank_account.read` on PDFs.
- No agent tools were added (`draft_invoice`, `get_receivable_ageing` are not in this brief's deliverables).

## Decisions (for the integrator / DECISIONS.md)
1. **One table for invoices and credit notes** (`finance_invoice.doc_type`), as operations.md §9; credit-note lines
   point at the credited invoice line, so creditable quantities are per line.
2. **A refused issue is a 200 with `issued: false`**, not a 409: the attempt is recorded (history, event, last
   blockers) and must survive the transaction; the web shows the reasons.
3. **Approval is a document action with SoD in service + CHECK**, not the proposals engine (as Slice-4 Decision 6).
4. **Tax is never invented**: without a profile no tax is calculated and the draft says so; profiles are
   business-entered with a source reference and verified by a second person. The e-invoice provider is a new
   integration `e_invoice` (Demo), so profiles that require e-invoicing stay blocked (BUILD_STATE §5 #4).
5. **Numbering**: `INV-{fy}-NNNN`, `CN-{fy}-NNNN`, `RCPT-{fy}-NNNN`, `AX-{fy}-NNNN` with the April financial year
   (`2026-27`); drafts `FD-NNNNN` never reset and never consume an invoice number. fixtures.md writes the receipt as
   `RCPT-2026-0001`; the seeded receipt is `RCPT-2026-27-0001` (FY format as the brief's `INV-FY-NNNN`).
6. **Allocations** lock source then invoice; same party and currency only; an issued credit note auto-settles its
   original invoice up to the outstanding amount.
7. **Margin** uses the latest cost version effective on the day in the quote's currency and unit; uncosted lines are
   counted, not guessed; a quote without a costed line is never flagged. Trigger: `sales.quote.issued`.
8. **Demo seed**: only the fixture's Maison receipt (EUR 2,400.0000, received D-4 so the unallocated sweep flags it at
   D0) — no tax profile, no issued invoice (honest Demo defaults). fixtures.md said "received" without a day.

## keys.py requests
- `FINANCE_REFS = SimpleNamespace(RECEIPT_MAISON="RCPT_MAISON")` (the seed currently uses a local constant
  `app/seed/world/finance.py::RECEIPT_MAISON`) and `RECEIPTS = SimpleNamespace(MAISON="RCPT-2026-27-0001")`.

## Integrator requests
1. Renumber `0080_finance_slice5.py` onto the chain after the Slice-4 integration (`down_revision` = the CP5 head).
2. `docs/architecture/events.md` is updated for §2 (`finance.margin_check`), §3.11 and §4; confirm the family list
   (`mgmt.financial_visibility` is not built).
3. e2e: the world is seeded at `--slice 2`, so `m-finance.spec.ts` turns inventory on through the Slice-4 test seam;
   when `dev.mjs` seeds `--slice 5` the hub will also show the Maison receipt.
4. PARITY_MATRIX: Slice-5 finance rows → the tests above.
5. `features/areas/area-overview.tsx` still carries the "finance planned" copy (`messages/areas.ts`) for
   `AreaOverview area="finance"` (kept because `settings.test.tsx` renders it); it is no longer routed — drop both
   when convenient.
6. Settings UI for `finance_policy` and `finance_account_mapping` uses the generic settings API (manage key
   `finance.configuration.manage`); a dedicated Settings › Finance screen is not built — the accounting-sync page links
   to it in copy only.
7. ADRs for Decisions 1–7.

## Not done (with reasons)
- Manual invoice drafts and line editing in the UI (API exists: `POST /finance/invoices` with lines, `PATCH` with
  lines); drafts in the UI come from suggestions.
- CSV reconciliation entry in the UI (API takes the accounting side's lines); the UI reconciles Demo exports.
- Agent tools `draft_invoice`, `get_receivable_ageing` (not in this brief).
- Cross-currency allocation, live accounting / e-invoice adapters, GST rules (future scope, BUILD_STATE §5).

## Gates
(filled below with the real output)
