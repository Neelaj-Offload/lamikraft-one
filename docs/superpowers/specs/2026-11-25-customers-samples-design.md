# Customers and samples (module 2) — design

Date: 2026-11-25 · Status: owner asked to "complete everything" on 2026-11-25; built on `lane/crm-leads` after module 1 ·
Programme: `docs/superpowers/specs/2026-11-25-leads-module-design.md` (Programme context)

## Why

The meeting rule (`docs/meetings/2026-11-12-sales-crm-scope-and-phases.md`): a **customer** is anyone who bought or was
sent a sample; everyone else is a **lead**. Today that is a manual status edit, so the two lists drift. The team also
has to enter the old data one by one, including every sample Lamikraft has already sent (Priya's samples Excel), with
the real dates, not "today". The Infinique reference (`D:\Infinique_ERP\infinique-ops\backend\routes\customers.py`)
shows each customer with their totals and last-contact dates.

## Scope

In:
1. **Automatic promotion.** A lead becomes a customer (status `active`, stage `won`) the moment a sample to them is
   dispatched, a quotation to them is won, or a sales order for them is confirmed. Idempotent; never demotes.
2. **Past samples.** A sample can be recorded as already sent: `SampleCreate.sent_on` (a date, today or earlier) and an
   optional reference create it directly in `dispatched` with that date. Later steps (delivered, feedback) can carry
   their own past date (`SampleTransition.occurred_on`), never before the previous step and never in the future.
3. **Customer facts.** The customer record shows customer since, last contact (latest activity), quotations, samples
   and orders counts, and won business value per currency.

Out: payment terms and preferred incoterms on the customer (quotation settings already carry defaults); a sample
spreadsheet import (the meeting chose one-by-one entry); sample stock (module 4 adds sample / inventory / exhibition
stock and will post a movement when a sample leaves stock).

## Design

### Promotion (`parties.leads.promote_to_customer`)

`promote_to_customer(uow, party_id, *, reason)`; reason is `sample_sent`, `quote_won` or `order_confirmed`. It locks the
party; if it has the customer role and is a prospect or an open/lost lead, it sets `status = active`,
`lead_stage = won`, `stage_changed_at = now`, clears `lost_reason` and `next_follow_up_on`, emits
`parties.lead.stage_changed` (with `reason`) and `parties.party.updated` (`status`), and audits
`parties.lead.promoted`. Otherwise it does nothing. The follow-up rule closes the open follow-up task.

Callers are outbox subscriptions owned by the modules that know the business event (parties never imports sales or
orders): `sales` subscribes `sales.sample.dispatched` and `sales.quote.won`; `orders` subscribes
`orders.sales_order.confirmed`. Each reads its own record's party and calls the parties service. Inactive or blocked
parties are left alone.

### Past samples

- `SampleCreate.sent_on: date | None`, `dispatch_reference` reused. With `sent_on`, the sample is created `dispatched`,
  `dispatched_at` = noon of that date in the company zone, `dispatch_reference` defaults to "Sent before Lamikraft One";
  `sales.sample.created` then `sales.sample.dispatched` (origin `backfill`) are emitted, so promotion happens.
- `SampleTransition.occurred_on: date | None` for `dispatch`, `deliver` and `record_feedback`: the step's timestamp is
  noon of that date. 422 when in the future or before the previous step's date.
- The sample form gets "Already sent" with the date and reference; the deliver and feedback dialogs get "When".

### Customer facts

`GET /api/v1/sales/customers/{party_id}/facts` (sales module, `parties.party.read` + per-count permissions):
`customer_since` (stage change to won, else first contact), `last_activity_at`, counts of quotations, samples and
orders the caller may see, and won value per currency (sum of won quotations' totals as decimal strings). The customer
record's overview shows them in a facts panel.

## Testing

Integration: each of the three triggers promotes exactly once; a vendor-only party and a blocked party are untouched;
a lost lead is promoted by a sample; the follow-up task closes. Past sample: created dispatched with the date, rejects a
future date, later steps reject dates before the previous one. Facts: counts respect scope; value sums by currency.
Web: vitest for the date helpers; preview check of the "Already sent" flow.
