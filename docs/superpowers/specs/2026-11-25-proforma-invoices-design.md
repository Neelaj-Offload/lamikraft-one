# Proforma invoices (module 3) — design

Date: 2026-11-25 · Status: owner asked to "complete everything" (2026-11-25) · Programme order: module 3 of 6

## Why

Meeting `docs/meetings/2026-11-12-stock-categories-crm-vs-erp-po-pi.md`: a **PI** (proforma invoice) is what Lamikraft
sends the client, priced at the selling price; it has nothing to do with the client's PO. **PO** is only in-house
(Crown for sheets, Stonecraft for CNC) and already exists in purchasing. Quotations already exist and attach to a
customer. Priya will send every PI issued so far; they must be entered with their original number and date. The
reference is Infinique (`routes/quotations.py`, `proforma-invoices*`): one or more PIs from a sent or approved
quotation, lines copied, ports and payment terms, bank details, declaration, status, PDF.

## Scope

In: create a PI from a quotation's latest issued revision; edit its header while draft; issue (numbered, frozen,
PDF); cancel with a reason; list and record screens; link to the customer, the quotation and (read-only) the order
made from that quotation; enter a historical PI with its original number and date.

Out: converting a PI into an order (orders already come from won quotations); payments against a PI (finance);
e-mailing the PDF (Demo channels, later); editing lines on a PI (change the quotation and make a new PI).

## Model (`sales_proforma_invoice`, tenant table, RLS)

| Column | Notes |
|---|---|
| `pi_number` | `PI-YYYY-NNNN` from a new sequence `sales.proforma_invoice` at issue; drafts show `draft_ref` (`PI-DRAFT-<short id>`). A historical PI keeps the number it was issued with (unique per company, `^[A-Za-z0-9/_.-]{3,40}$`). |
| `quote_id`, `revision_no` | the quotation and the issued revision the lines come from |
| `party_id`, `owner_user_id`, `branch_id` | from the quotation; scope like quotations (own < team < branch < company) |
| `status` | `draft`, `issued`, `cancelled` |
| `pi_date` | the document date; today at issue unless entered from history (today or earlier) |
| `currency`, `snapshot` (JSONB) | lines, party block and totals copied from the revision snapshot at creation |
| `port_of_loading`, `port_of_discharge`, `payment_terms`, `delivery_terms`, `bank_account_label`, `declaration`, `notes` | editable while draft; payment and delivery terms default from the quotation; the bank account is chosen from Settings › Company › Bank details by label (default: the one in the PI currency, else the default) |
| `issued_at`, `issued_by`, `document_sha256`, `document_file_id` | set at issue; the PDF is stored |
| `cancelled_at`, `cancel_reason` | |

Several PIs per quotation are allowed (partial shipments), as in Infinique.

## Behaviour

- `POST /sales/quotes/{id}/proforma-invoices` (`sales.proforma.create`): the quotation must be `sent`, `revised` or
  `won` and have an issued revision; 409 otherwise. Body: optional header fields and, for history, `pi_number` +
  `pi_date` (needs `sales.proforma.backfill`; the PI is created already issued with that number and date, PDF rendered).
- `PATCH /sales/proforma-invoices/{id}` (draft only, `expected_version`).
- `POST .../issue` allocates the number, sets `pi_date` (today unless given, never in the future), renders and stores
  the PDF, freezes the header. `POST .../cancel` needs a reason; an issued PI stays readable and printable with a
  "Cancelled" mark.
- `GET /sales/proforma-invoices` (filters: q, status, party_id, quote_id), `GET .../{id}`, `GET .../{id}/document` (PDF;
  a draft prints with the "DRAFT - NOT VALID FOR TRADE" watermark).
- PDF: company identity, "Proforma invoice", number/date/currency/quotation reference/customer reference, bill-to
  from the snapshot, items (#, item, decor/size, quantity, unit price, amount), totals and amount in words, delivery
  terms, ports, payment terms, bank block (restricted-number rule), declaration, signature box. Unconfigured identity
  prints labelled placeholders, never invented values.
- Permissions (`permissions.md`, slice 7): `sales.proforma.read` (R, D; sal O, mgt C, fin C), `.create` (sal, mgt),
  `.issue` (sal, mgt), `.reverse` (cancel; mgt), `.import` (enter from history; mgt). Events (`events.md`): `sales.proforma.created`, `.issued`,
  `.cancelled` (proforma_id, pi_number, quote_id, party_id).
- Every read carries `capabilities` (`update`, `issue`, `cancel`, `download`).

## Screens (`apps/one`)

- **Proforma invoices** list (`/sales/proforma-invoices`, in the Sales menu): number, customer, quotation, date, total,
  status; filters by status and search. Route lives in `apps/one/src/lib/routes.ts` (this app's own routes).
- **PI record**: header (number or draft reference, status, customer, quotation, total), primary action Issue (draft)
  or Download PDF (issued), menu Cancel; views Overview (lines and totals), Details (ports, terms, bank, declaration,
  editable while draft).
- **Quotation record**: "Create proforma invoice" when allowed, and a list of its PIs.
- **Customer record**: a "Proforma invoices" tab.
- **Enter a past PI**: on the quotation, "Enter an issued PI" (backfill permission) asks for the original number and
  date.

## Testing

Integration: create from a sent quotation (lines equal the revision snapshot), refused from a draft quotation; edit
draft and 409 on stale version; issue allocates `PI-YYYY-NNNN`, renders a PDF, freezes edits; cancel needs a reason;
backfill keeps the given number, rejects duplicates and future dates, needs the backfill permission; scope (a sales
user sees only own PIs); RLS isolation. Unit: amount in words for INR/EUR/USD/GBP; PDF renders with and without
company identity. Web: vitest for list state; preview of create → issue → download.
