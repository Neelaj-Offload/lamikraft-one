# Canonical fixture world

Status: frozen in Slice 0. Implements `docs/PLAN.md` canonical contract 11. Steward: the work (tasks/briefings) lane,
with integrator approval for every change to `backend/app/seed/world/keys.py` or the expected-results tables below.

All names, companies, contacts and figures are fictional. Nothing here is a real customer, supplier or credential.
Legacy bootstrap identities from `CURRENT_STATE_SPEC.md` are never reused.

---

## 1. Rules

1. **One world.** `backend/app/seed/world/` (`keys.py` constants plus one file per module) is used by the demo seed
   (`lk seed demo`), backend tests and e2e tests. No test builds its own competing world; test-local additions are
   listed in §11 and created on top of the world.
2. **Created only through services**, at clock offsets from the anchor, in chronological order, as the acting persona
   (or the system actor with `origin=seed`). No direct SQL inserts, no back-filled rows. Re-running the seed is
   idempotent on business keys.
3. **Slice tags.** Every entity carries the slice in which its producing feature exists. The seed creates an entity
   only when that slice's modules are installed, so expected results are stated per slice.
4. **Numbers are derived, not asserted blindly.** Document numbers come from the real allocator in creation order;
   the numbers below follow from that order. Tests read them from `keys.py`/fixture references, never literals.
5. **Clock.** Tests freeze the Clock at **D0 = Monday 2026-10-12 08:55 IST = 2026-10-12T03:25:00Z**. The demo seed
   accepts `--anchor-date` (default: today) and shifts every offset; demo seeds anchored on a non-working day show
   the weekend behaviour, which is expected.
6. **Tests reference constants** (`keys.USERS.MEERA`, `keys.QUOTES.PRIOR_WON`, ...) and fixture references from the
   test-support router (`GET /api/v1/_test/fixtures`), never literal names, ids or numbers.
7. **Binary assets** (product photographs and decor swatch textures) live in `backend/app/seed/world/assets/` as
   project-owned files, listed in the fixture sha256 manifest and marked binary in `.gitattributes`.

Times are IST (UTC+05:30) with UTC in brackets. D−1 = Sunday 2026-10-11, D−2 = Saturday 2026-10-10.

## 2. Company, branches, teams, calendar

| Item | Value | Slice |
|---|---|---|
| Company | key `crown-demo`; legal name **Crown Decor Pvt. Ltd. (Demo)**; display "Crown Decor (Demo)"; `is_demo = true`; country IN; base currency INR; zone Asia/Kolkata; locale en-IN | 1 |
| Brands | Lamikraft (token `LK`), Crown (token `CR`) | 1 |
| Company identity settings | address, GSTIN, PAN, IEC, bank details and logo **not configured** (documents show "Not configured — set in Settings › Company"); terms: neutral demo text labelled Demo | 1 |
| Branch HO | `HO`, "Head Office", head office; GSTIN not set | 1 |
| Branch FAC | `FAC`, "Factory" (exists so branch scope is testable) | 1 |
| Team EXP-SALES | "Export Sales": Meera, Neha, Arjun (members); Sahil (lead) | 1 |
| Team OPS-HO | "Operations HO": Ravi (lead), Kabir | 1 |
| Calendar HO-GEN | Asia/Kolkata; Monday–Saturday; shift GEN 09:30–18:30; rollover 04:00; precompute 30 min before shift start | 1 |
| Holiday | "Demo holiday" on D0+10 (Thursday 2026-10-22) | 1 |
| Shift NGT | 22:00–06:00, rollover 08:00 (Vikram) | 2 |
| Enabled currencies | INR, EUR, USD, GBP | 1 |

## 3. People

Demo users have no passwords; they sign in through one-time links (`lk demo sign-in-link <key>`). Tests sign in
through the test-support router. Email domain `demo.lamikraft.test`.

| Key | Name | Email | Role template | Branch / team | Manager | Notes | Slice |
|---|---|---|---|---|---|---|---|
| `SAHIL` | Sahil Mehta | sahil.mehta@demo.lamikraft.test | management (company scope) | HO / EXP-SALES lead | — | approver for quote reviews and price overrides | 1 |
| `MEERA` | Meera Iyer | meera.iyer@demo.lamikraft.test | sales (own scope) | HO / EXP-SALES | Sahil | last acknowledged briefing: Sat D−2 18:05 (12:35Z) | 1 |
| `NEHA` | Neha Joshi | neha.joshi@demo.lamikraft.test | sales (own scope) | HO / EXP-SALES | Sahil | peer persona; Monday briefing v1 generated 08:49 (03:19Z), acknowledged 08:50 (03:20Z) | 1 |
| `RAVI` | Ravi Kumar | ravi.kumar@demo.lamikraft.test | operations (branch scope HO) | HO / OPS-HO lead | — | | 1 |
| `KABIR` | Kabir Shah | kabir.shah@demo.lamikraft.test | warehouse (restricted assistant) | HO / OPS-HO | Ravi | restricted persona for isolation tests | 1 |
| `ARJUN` | Arjun Das | arjun.das@demo.lamikraft.test | sales (own scope) | HO / EXP-SALES | Sahil | new hire: membership activated D0 08:00 (02:30Z); via invitation acceptance from Slice 2 | 1 |
| `ANANYA` | Ananya Rao | ananya.rao@demo.lamikraft.test | finance | HO | — | empty briefing until Slice 5 | 1 |
| `PRIYA` | Priya Nair | priya.nair@demo.lamikraft.test | admin | HO | — | | 1 |
| `VIKRAM` | Vikram Singh | vikram.singh@demo.lamikraft.test | operations (branch scope HO) | HO / OPS-HO | Ravi | night shift NGT; delegate for Ravi's leave tests (B-11, B-13) | 2 |

## 4. Parties

Numbers `P-NNNNN` (never reset) follow creation order.

| Key | Number | Name | Country / currency | Customer type | Owner | Contact | Roles | Slice |
|---|---|---|---|---|---|---|---|---|
| `NORDHAUS` | P-00001 | **Nordhaus Interiors GmbH** | DE / EUR | standard | Meera | Lena Brandt | customer | 1 |
| `MAISON` | P-00002 | **Maison Atelier SARL** | FR / EUR | standard | Meera | Camille Laurent | customer | 1 |
| `BERG` | P-00003 | **Berg & Co AB** | SE / EUR | standard | Meera | Erik Lindqvist | customer | 1 |
| `THORNBURY` | P-00004 | **Thornbury Kitchens Ltd** | GB / GBP | dealer | Neha | Oliver Hart | customer | 1 |
| `KAVERI` | P-00005 | Kaveri Timber Supplies | IN / INR | — | Ravi | Anil Rao | vendor | 2 |
| `PRECISION_EDGE` | P-00006 | Precision Edge Fabricators | IN / INR | — | Ravi | Suresh Pillai | fabricator, job_worker | 2 |

Parties were created at D−120 to D−117 (customers) and D−100 to D−99 (vendor, fabricator) by Priya. Tax
identifiers are left empty (no fabricated GSTIN or VAT numbers). Maison's shipping address is changed by Priya at
**D−1 10:05 (04:35Z)** (`parties.party.updated`, changed field `addresses.shipping`).

## 5. Catalogue

Taxonomy (all active): **Serveware** (subcategories Trays, Trivets, Boards) and **Decorative Boards** (Veneered panels).

| Key | product_key / SKU | Name | Category / sub | Unit | Decor | Specification | Packaging | Media | Slice |
|---|---|---|---|---|---|---|---|---|---|
| `OAK_TRAY` | **LK-OT-0450** | Oak serving tray 450 | Serveware / Trays | pcs | `0120` Natural Oak | 450 × 300 mm, thickness 12 mm, finish matte lacquer, shape rectangular, material oak veneer | carton_qty **24**, inner_qty 6, unit_weight_g 450, packing_type Poly bag, carton 48 × 33 × 30 cm, cbm 0.047520, net 10.8 kg, gross 11.6 kg | primary photo `lk-ot-0450.webp`, swatch `decor-0120-natural-oak.webp` | 1 |
| `MAPLE_TRIVET` | LK-MT-0300 | Maple trivet 300 | Serveware / Trivets | pcs | `0310` Hard Maple | 300 × 300 mm, thickness 10 mm | carton_qty 48, unit_weight_g 280, Shrink wrap, carton 62 × 32 × 34 cm, cbm 0.067456, net 13.44 kg, gross 14.4 kg | primary photo, swatch | 1 |
| `ASH_BOARD` | LK-AB-0400 | Ash chopping board 400 | Serveware / Boards | pcs | `0415` White Ash | 400 × 250 mm, thickness 18 mm | carton_qty 20, unit_weight_g 900, Carton sleeve, carton 42 × 27 × 40 cm, cbm 0.045360, net 18.0 kg, gross 19.2 kg | primary photo, swatch | 1 |
| `WALNUT_BOARD` | LK-WB-1800 | Walnut veneered board 18 mm | Decorative Boards / Veneered panels | sheets | `0457` American Walnut | board 2440 × 1220 mm, thickness 18 mm | packing_type Pallet (no carton) | swatch | 1 |
| `OAK_TRAY_VARIANTS` | LK-OT-0300, LK-OT-0600, LK-OT-0750, LK-OT-0900 | Oak serving tray 300/600/750/900 | Serveware / Trays | pcs | `0120` | sizes per name, thickness 12 mm | complete | **no primary image** (completeness case) | 2 |

Stock attributes: `hsn_sac` empty (owner to supply), `stock_uom_code` = unit of sale, `is_stock_tracked` true from
Slice 4, `track_lots` and `qc_required` true only for LK-WB-1800. The decor `0120` is text; `120` and `120.0`
normalisation cases live in test-local fixtures.

## 6. Pricing and commercial configuration

| Key | Code | Scope / type / currency | Items | Slice |
|---|---|---|---|---|
| `PL_EXP_EUR` | **EXP-EUR-2026** | standard, export, EUR, valid 2026-01-01 → 2026-12-31, active | LK-OT-0450 **24.0000**/pcs; LK-MT-0300 9.5000/pcs; LK-AB-0400 18.0000/pcs; (S2) LK-OT-0300 18.0000, LK-OT-0600 30.0000, LK-OT-0750 36.0000, LK-OT-0900 42.0000 | 1 |
| `PL_EXP_GBP` | EXP-GBP-2026 | standard, export, GBP, same validity, active | LK-OT-0450 21.0000/pcs | 1 |
| `PL_DOM_INR` | DOM-INR-2026 | standard, domestic, INR, same validity, active | LK-WB-1800 3450.0000/sheet | 1 |
| Supersede | — | — | LK-MT-0300 on EXP-EUR-2026 superseded at **D−1 15:30 (10:00Z)** by **9.9000** valid from 2026-10-12 | 2 |
| `FX_DEMO_EUR_USD` | — | EUR → USD **1.0850** dated 2026-10-09, source "Demo rate", proposed by Ananya D−3, approved by Sahil D−3 | — | 2 |

No customer-type or customer-agreement lists exist in the world (tier tests add them locally). The pricing-import
mapping for (export, EUR) targets EXP-EUR-2026. Commercial rule set `quote_commercial` v1 active: EUR minimum order
value 5,000.00, surcharge 400.00, applicable line types catalog/custom/manual. Quote defaults: EUR, FOB, 30 days,
brand LK, price type export, duplicate copies assignee.

Approval policy `sales.quote.review` (demo seed; thresholds are an owner decision): review only when requested,
**plus** a demo rule that a quote containing a price override, a discount or a below-minimum applicable subtotal
must have an approved review before it can be issued. Eligibility per [permissions.md](permissions.md) §10.
Sequences: `sales.quote` `{brand}-QT-{yyyy}-{seq:04}` never; `sales.enquiry` `ENQ-{yyyy}-{seq:04}` yearly;
`parties.party` `P-{seq:05}` never; from Slice 2 `sales.custom_product` `CP-{seq:04}` never, `sales.sample`
`SMP-{yyyy}-{seq:04}` yearly, `challans.challan` `DC-{yyyy}-{seq:04}` yearly, `cutting.plan` `CUT-{yyyy}-{seq:04}`
yearly, `imports.job` `IMP-{yyyy}-{seq:04}` yearly.

## 7. Enquiries, customer messages, quotes, reminders and tasks

### 7.1 Enquiries (Slice 1)

| Key | Number | Party | Owner | Received | Status |
|---|---|---|---|---|---|
| `ENQ_MAISON` | ENQ-2026-0001 | Maison | Meera | D−34 (2026-09-08), email | quoted (linked to LK-QT-2026-0005) |
| `ENQ_THORNBURY` | ENQ-2026-0002 | Thornbury | Neha | D−5 (2026-10-07), phone | quoted (linked to LK-QT-2026-0007) |

### 7.2 Customer messages (Slice 1; bodies carry external provenance)

| Key | Party / contact | Channel | Received | Assignee | Linked quote | State at D0 |
|---|---|---|---|---|---|---|
| `MSG_NORDHAUS` (M1) | Nordhaus / Lena Brandt | email | **D−1 19:20 (13:50Z)** | Meera | LK-QT-2026-0008 (origin) | not replied |
| `MSG_BERG` (M2) | Berg / Erik Lindqvist | email | **D−1 17:40 (12:10Z)** | Meera | LK-QT-2026-0006 | not replied |

Reply SLA (demo policy): due at the shift end of the next working day after receipt; both are due **D0 18:30 (13:00Z)**.
A reply task closes when the message is marked replied or when a linked quote is marked sent after the message
arrived.

### 7.3 Quotes (Slice 1; created in this order, so the allocator yields these numbers)

| Key | Number | Party | Owner | Lines | Total | History | Status at D0 |
|---|---|---|---|---|---|---|---|
| `Q_BERG_WON` | LK-QT-2026-0001 | Berg | Meera | 600 × LK-MT-0300 @ EUR 9.5000 | EUR 5,700.00 | created 2026-07-24, sent 07-25, won 08-03 | won |
| `Q_THORNBURY_LOST` | LK-QT-2026-0002 | Thornbury | Neha | 250 × LK-OT-0450 @ GBP 21.0000 | GBP 5,250.00 | created 2026-08-03, sent 08-04, lost 08-20 (reason price) | lost |
| `PRIOR_WON` | **LK-QT-2026-0003** | Nordhaus | Meera | **240** × LK-OT-0450 @ EUR 24.0000 | EUR 5,760.00 | created 2026-08-13, sent 08-14, won 08-21 (accepted revision 1) | won |
| `Q_THORNBURY_EXPIRING` | LK-QT-2026-0004 | Thornbury | Neha | 280 × LK-OT-0450 @ GBP 21.0000 | GBP 5,880.00 | created 2026-09-09, sent Sat 2026-09-12, validity 30 → valid until **2026-10-12** | sent, expires today |
| `Q_MAISON_OVERRIDE` | LK-QT-2026-0005 | Maison | Meera | 320 × LK-AB-0400, default EUR 18.0000, override **16.5000** ("Volume price agreed for launch order") | EUR 5,280.00 | created 2026-09-10 (from ENQ-2026-0001), override set D0 08:15, review requested **D0 08:20 (02:50Z)** | internal_review, awaiting approval |
| `Q_BERG_EXPIRING` | LK-QT-2026-0006 | Berg | Meera | 600 × LK-MT-0300 @ EUR 9.5000 | EUR 5,700.00 | created 2026-09-11, sent Sat 2026-09-12 10:00, validity 30 → valid until **2026-10-12** | sent, expires today |
| `Q_THORNBURY_OVERRIDE` | LK-QT-2026-0007 | Thornbury | Neha | 300 × LK-OT-0450, default GBP 21.0000, override **19.5000** ("Dealer volume discount requested") | GBP 5,850.00 | created D−3 (2026-10-09) from ENQ-2026-0002, review requested **D0 08:30 (03:00Z)** | internal_review, awaiting approval |
| `Q_NORDHAUS_DRAFT` | LK-QT-2026-0008 | Nordhaus | Meera | 240 × LK-OT-0450 @ EUR 24.0000 | EUR 5,760.00 | drafted by Meera's assistant (origin agent, from M1) at **D0 08:40 (03:10Z)**; review requested by Meera **D0 08:45 (03:15Z)** | internal_review, awaiting approval |

Quote totals exclude taxes (tax not calculated). EUR quotes at or above 5,000.00 carry no surcharge; GBP quotes are not
evaluated against the EUR rule.

### 7.4 Proposals (Slice 1)

| Key | Proposal | Target | Initiator | Submitted | Exceptions | Eligible approvers |
|---|---|---|---|---|---|---|
| `PROP_MAISON` | `sales.quote.review` v1 | LK-QT-2026-0005 v(n) | Meera | D0 08:20 | price override | Sahil, Priya |
| `PROP_THORNBURY` | `sales.quote.review` v1 | LK-QT-2026-0007 | Neha | D0 08:30 | price override | Sahil, Priya |
| `PROP_NORDHAUS` | `sales.quote.review` v1 | LK-QT-2026-0008 | Meera | D0 08:45 | none (explicit review request) | Sahil, Priya |

Approval tasks are due at the shift end of the submission work date, **D0 18:30 (13:00Z)**, soft; proposals expire
after 24 hours.

### 7.5 Reminders and manual tasks

| Key | What | Owner / assignee | Created | Due | Slice |
|---|---|---|---|---|---|
| `REMINDER_MEERA` | personal reminder "Call Maison about finish preferences" | Meera (private) | D−2 17:30 | **D0+1 10:00 (2026-10-13T04:30Z)** | 1 |
| `TASK_KABIR_COUNT` | manual task "Count walnut boards in bin A-12" (linked to location A-12 and LK-WB-1800 from Slice 4) | owner Ravi, assignee Kabir | D0 08:10 by Ravi | **D0 14:00 (08:30Z)** | 1 |
| `TASK_ARJUN_WALKTHROUGH` | manual task "Complete product catalogue walkthrough" | owner and assignee Arjun, assigned by Sahil | D0 08:05 by Sahil | D0+2 18:30 (2026-10-14T13:00Z) | 1 |
| `ONBOARDING_ARJUN` | 3 onboarding steps from the sales template: choose language and briefing detail (completion: briefing preference saved); open a product record (completion: recent-record entry); use global search (completion: recent search exists) | Arjun | on activation D0 08:00 | D0 18:30, soft | 1 |
| `CHECKIN_SAHIL` | manager check-in for Arjun | Sahil | on activation | D0+2 18:30, soft | 1 |

## 8. Slice 2–5 additions

| Slice | Entity | Facts |
|---|---|---|
| 2 | Job-work challan **DC-2026-0001** | Job Work, returnable, to Precision Edge Fabricators, issued D−7 by Ravi, expected return D0+1 |
| 2 | Sample **SMP-2026-0001** + sample challan **DC-2026-0002** | Maison, 2 × LK-AB-0400 sample, owner Meera; challan issued D−3 by Ravi; delivered **D−1 16:12 (10:42Z)**, evidence: courier confirmation recorded by Ravi |
| 2 | Cut plan **CUT-2026-0001** | LK-WB-1800 panels, owner Ravi, saved and calculated D0 08:15 |
| 2 | Import **IMP-2026-0001** | pricing_master by Priya at D−1 18:40, failed with 3 row-numbered errors |
| 2 | Completeness | 4 Serveware products (LK-OT-0300/0600/0750/0900, created D−6 by Priya) missing a primary image |
| 2 | Access request | Kabir requests `challans.challan.read` at branch scope, D0 08:20, decided by an admin |
| 2 | Invitation | Arjun invited by Priya D−3; accepted D0 08:00 (this is how his membership activates from Slice 2) |
| 2 | FX demo rate | §6 |
| 2 | Vikram, shift NGT | §2, §3 |
| 4 | Warehouses | Main Warehouse `WH-MAIN` (HO) with bin A-12; opening batch approved by Sahil (created by Ravi) |
| 4 | Purchase order **PO-2026-0001** | Kaveri, line 1 LK-WB-1800; expected date moved from D0 to D0+3 at D−1 11:03 |
| 4 | Shortage | LK-WB-1800 at WH-MAIN, caused by the late PO line |
| 4 | Work order **WO-2026-0001** | afternoon shift, blocked by the shortage |
| 4 | Reservation conflict | two demands on LK-WB-1800 → a decision for Sahil |
| 5 | Receipt **RCPT-2026-0001** | Maison, EUR 2,400.0000, unallocated |
| 5 | Accounting adapter | "Not connected (demo)" |

## 9. Expected Slice-1 briefings at D0 08:55

Default priority weights (briefing design §5; the single highest responsibility component applies):
DUE_TODAY 35, CUSTOMER_COMMITMENT_AT_RISK 25 (reply and quote-expiry tasks), YOUR_DECISION 20, ASSIGNED_TO_YOU 15,
YOU_OWN 5, BLOCKED_BY −10. Bands: P1 ≥ 70, P2 40–69, P3 15–39, P4 < 15. Order: section, band, score desc, due asc,
fact_at asc, issue id. Initial view: first 5 by global rank; empty sections are omitted.

### 9.1 Meera (sales, own scope) — `test_sales_overview_computed`, `test_sections_top5_no_empty`

| # | Section | Issue key | Item | Derivation | Due |
|---|---|---|---|---|---|
| 1 | Needs you now | `msg:{MSG_BERG}` | Reply to Berg & Co AB | 35 + 25 + 15 = 75 (P1) | Today 18:30 (13:00Z) |
| 2 | Needs you now | `quote:{Q_BERG_EXPIRING}:expiry` | LK-QT-2026-0006 expires today | 35 + 25 + 15 = 75 (P1); later due than #1 | Expires today (end of 2026-10-12 = 18:30Z) |
| 3 | Plan for today | `msg:{MSG_NORDHAUS}` | Reply to Nordhaus Interiors GmbH — waiting for review of LK-QT-2026-0008 (draft as evidence) | 35 + 25 + 15 − 10 = 65 (P2); blocked by the open approval, expected to unblock today | Today 18:30 |
| 4 | Changes since your last visit | `info:party:{MAISON}` | Maison Atelier SARL shipping address updated by Priya | FYI; change at D−1 10:05 after the D−2 18:05 acknowledgement | — |
| 5 | Coming next | reminder | Call Maison about finish preferences | personal reminder | Tomorrow 10:00 |

- Recommendations and Handled for you: absent. Initial view 5 items; full list 5.
- Overview facts: customer_replies = 2, quotes_expiring_today = 1.
- Greeting: **"Good morning, Meera."** Overview sentence: **"Two customer replies need attention and one quote expires today."**
- Not visible to Meera: anything about Thornbury, GBP amounts, Neha's quotes or proposals.

### 9.2 Sahil (management) — `test_management_three_decisions`

| # | Section | Issue key | Item | Derivation | Due |
|---|---|---|---|---|---|
| 1 | Needs you now | `approval:{PROP_MAISON}` | Approve price override on LK-QT-2026-0005 (Maison Atelier SARL) | YOUR_DECISION 20 + DUE_TODAY 35 = 55 (P2); decision due in the current work window | Today 18:30 |
| 2 | Needs you now | `approval:{PROP_THORNBURY}` | Approve price override on LK-QT-2026-0007 (Thornbury Kitchens Ltd) | 55; submitted after #1 | Today 18:30 |
| 3 | Needs you now | `approval:{PROP_NORDHAUS}` | Review LK-QT-2026-0008 (Nordhaus Interiors GmbH) | 55; submitted after #2 | Today 18:30 |
| 4 | Coming next | `onboarding:{ARJUN}:checkin` | Check in with Arjun | YOU_OWN | Wed 18:30 |

- Overview facts: decisions_pending = 3, rest_moving = true (no visible non-decision item is overdue or a cross-team blocker).
- Greeting: **"Good morning, Sahil."** Overview sentence: **"Three decisions need you. The rest is moving."**
- Each decision item carries `proposal_ref{id, version: 1, content_hash, expires_at}`; Review opens proposal v1.
- A-08 variant: adding an overdue task for Sahil changes the second clause to "One item is overdue."
- A-09 variant: revoking Sahil's `sales.quote_price.approve` removes #1 and #2 → **"One decision needs you. The rest is moving."**

### 9.3 Other personas (Slice 1)

| Persona | Expected | Sentence |
|---|---|---|
| Neha | Needs you now: LK-QT-2026-0004 expires today (75, P1). Briefing v1 acknowledged at 08:50, so no "Changes since your last visit" section. | "One quote expires today." |
| Arjun | Plan for today: 3 onboarding steps; Coming next: catalogue walkthrough. No changes or handled sections (cutoff = activation time). | "Welcome, Arjun. You have three onboarding steps and one assigned task." |
| Kabir | Plan for today: count task only (ASSIGNED 15 + DUE_TODAY 35 = 50). No customer names, amounts or other counts anywhere in the payload. | "One task is due today." |
| Ravi | Plan for today: Kabir's count task (owner; YOU_OWN 5 + DUE_TODAY 35 = 40). | "One task is due today." |
| Priya | Needs you now: the same three decisions (admin is an eligible approver). | "Three decisions need you. The rest is moving." |
| Ananya | Empty state. | "Nothing needs you right now." |

## 10. Expected results in later slices

| Slice | Persona | Change |
|---|---|---|
| 2 | Meera | Adds Recommendations: follow up on the Maison sample (`sample:{SMP-2026-0001}:followup`, PREPARE_FOLLOWUP). Berg expiry (#2) gains a "Changed" marker: the LK-MT-0300 price on EXP-EUR-2026 was superseded at D−1 15:30 (reprice preview from the sales service: EUR 5,940.00). Order: Berg reply, Berg expiry, Nordhaus reply, Maison follow-up, Maison address, reminder; initial 5, full 6. Overview facts add samples_delivered = 1 with fact date D−1. Sentence: **"Two customer replies need attention, one quote expires today, and yesterday's sample has been delivered."** |
| 2 | Ravi | Adds DC-2026-0001 returnable due back tomorrow (Coming next) and CUT-2026-0001 review (Plan for today). |
| 2 | Priya | Adds IMP-2026-0001 failed with 3 errors, completeness (4 Serveware products without a primary image), Kabir's access request; Arjun's accepted invitation appears under Handled for you. |
| 1–3 | Sahil | Unchanged three decisions and sentence. |
| 4 | Sahil, Ravi | Shortage → blocked WO-2026-0001 → at-risk dispatch grouped under the root cause `po_line:{PO-2026-0001 line 1}:late`; the reservation conflict becomes a fourth decision for Sahil. Exact sentences are fixed when the Slice-4 families merge. |
| 5 | Ananya | Unallocated Maison receipt EUR 2,400.0000; accounting adapter Not connected (demo). |

## 11. Scenario constants and test-local additions

| Scenario | Fixture facts | Expected |
|---|---|---|
| C | Meera asks "Prepare Nordhaus's usual oak tray quote" at D0 | resolve_party → Nordhaus Interiors GmbH (unique); find_usual_order → LK-QT-2026-0003 line 1 (LK-OT-0450 × 240); resolve_price → EXP-EUR-2026 item EUR 24.0000/pcs (tier standard); calculate → gross/net/applicable EUR 5,760.00, minimum MEETS, surcharge AT_OR_ABOVE_MINIMUM, recommended quantity 216, grand total EUR 5,760.00 excluding taxes; draft **LK-QT-2026-0009** owned by Meera, status draft, not sent; a `review_draft` task for Meera only, due Today 18:30 |
| C (snapshot) | test-local: supersede LK-OT-0450 on EXP-EUR-2026 to 26.0000 and rename the product | the draft still shows 24.0000, 5,760.00 and the old name with PRICE_CHANGED_SINCE_SNAPSHOT; only an explicit refresh gives 26.0000 and 6,240.00 |
| C (ambiguity) | test-local party "Nordhaus Logistik AG" (CH, EUR, owner Meera) | a ClarificationCard with exactly two options; no draft until one is chosen |
| C (follow-up) | "change it to 300" on the focused line | 300 × 24.0000 = EUR 7,200.00 from the calculation service |
| D | engine inputs | EUR 24 with carton 24 → recommended 216 (ceil(5000/24) = 209, rounded up to a carton multiple); 200 × 24 = 4,800.00: toggle off 4,800.00, toggle on 5,200.00; 200 × 25 = 5,000.00 → no surcharge; 4,999.99 with toggle on → 5,399.99; 250 × 24 less 20 % = 4,800.00 → surcharge applies; price 0 or missing → recommendation unavailable, grand total null; USD quote → minimum NOT_EVALUATED, no surcharge |
| E | FX_DEMO_EUR_USD | switching a 240 × LK-OT-0450 EUR quote to USD with conversion enabled: 24.0000 × 1.0850 = 26.04 USD/unit, total USD 6,249.60; with no USD list and no approved rate the change returns 409 and the quote is unchanged |
| A / B | world as above | §9 and briefing tests A-01 … B-18 |
| F | world | sales personas Meera and Neha against each other's quotes; 40-way concurrent numbering on a test-local tenant |
| G, H, L | test-local import files, cut lists and long documents under `backend/tests/fixtures/` | see PARITY_MATRIX |

Berlin-zone variant (A-05): a test-local user with zone Europe/Berlin sees the Berg reply due "Today 15:00".

## 12. `keys.py` outline

```python
CLOCK_D0 = datetime(2026, 10, 12, 3, 25, tzinfo=UTC)          # Mon 08:55 IST
COMPANY_KEY = "crown-demo"
USERS = SimpleNamespace(SAHIL=..., MEERA=..., NEHA=..., RAVI=..., KABIR=..., ARJUN=..., ANANYA=..., PRIYA=..., VIKRAM=...)
PARTIES = SimpleNamespace(NORDHAUS="P-00001", MAISON="P-00002", BERG="P-00003", THORNBURY="P-00004", ...)
PRODUCTS = SimpleNamespace(OAK_TRAY="LK-OT-0450", MAPLE_TRIVET="LK-MT-0300", ASH_BOARD="LK-AB-0400", WALNUT_BOARD="LK-WB-1800")
PRICE_LISTS = SimpleNamespace(EXP_EUR="EXP-EUR-2026", EXP_GBP="EXP-GBP-2026", DOM_INR="DOM-INR-2026")
QUOTES = SimpleNamespace(PRIOR_WON="LK-QT-2026-0003", NORDHAUS_DRAFT="LK-QT-2026-0008", BERG_EXPIRING="LK-QT-2026-0006", ...)
EXPECTED = SimpleNamespace(MEERA_S1_SENTENCE=..., SAHIL_S1_SENTENCE=..., ...)  # §9 tables
```
