# Meeting notes and owner instructions

Summaries of Lamikraft team meetings, filed as the owner sends them. Read this folder before designing or building any new feature: it holds the agreed business flow, vocabulary and priorities. Each file keeps the original text; this page is the English digest.

| File | Topic |
|---|---|
| [2026-11-12-sales-crm-scope-and-phases.md](2026-11-12-sales-crm-scope-and-phases.md) | Sales CRM scope, customer page, phases |
| [2026-11-12-stock-categories-crm-vs-erp-po-pi.md](2026-11-12-stock-categories-crm-vs-erp-po-pi.md) | Three stock categories, CRM versus ERP, PO and PI |
| [2026-11-12-amazon-integration-and-catalogue.md](2026-11-12-amazon-integration-and-catalogue.md) | Amazon integration, product variations |

Dates in file names are the day the summary was received; the meeting dates were not stated.

## Phases and priority

1. **Phase one, sales modules** (target: "next Friday" as of the meeting): leads, customers, quotations, proforma invoices (PI), samples, products (catalogue and custom), stock inventory of finished products, e-commerce stock sync. All with the old data, entered record by record (no Excel or batch import).
2. **Phase two**: production and operations (orders to Crown, Kronecraft, the Moradabad metal vendor, the glass and porcelain vendor), finance (all cost heads in one place, including Google Ads, Meta Ads and website costs), website integration.
3. The system must be hosted and handed to the team so they can start entering data. Hosting target: Railway and/or Supabase (owner's message, 2026-11-12).

## Vocabulary the team uses

| Team says | Meaning |
|---|---|
| Lead | Anyone who has not bought and has not received a sample |
| Customer | Anyone who has bought, or has been sent a sample. Every customer has a profile page; every quotation attaches to a customer |
| Quotation | The price offer to a customer |
| PI (proforma invoice) | Sent to the client, based on selling price. It has no link to the client's own PO |
| PO (purchase order) | In-house only: to Crown (Ahmedabad) for sheets, to Stonecraft for CNC cutting. Sheet size HBI 1220 x 244; use stock if available, otherwise order |
| Sample | Always taken from stock. One of two kinds (see below) |
| Custom product | A separate item from catalogue products, for example a riser in a changed colour |

## Flow rules

- **Navigation**: custom products and the other sales items sit directly in the left-side menu (owner action item).
- **Customers and orders** are linked, but the CRM is its own section and orders are fully separate. Leads live in both CRM and ERP; the ERP records everything from conception to sale and processes orders. The existing Lamikraft CRM stays unchanged.
- **Quotations, customers, leads and PI** follow the Infiniq process the team already knows.
- **Stock is one pool with a category filter**: sample stock, stock inventory, exhibition stock. Taking units out of any category is a plus or minus movement.
  - Exhibition stock exists in both domestic and international warehouses.
  - Netherlands and US warehouse stock must be visible, so orders can be drop-shipped from there.
  - Domestic and export catalogues differ, so domestic and export stock are kept apart.
  - Consignment shipments are not outright purchases: they stay as stock in the warehouse.
  - Work in progress ordered from the factory (for example 50 or 200 pieces) shows with a status.
  - Only complete, finished products are stocked first (not PRM, BRW or IP).
- **Samples** (owner instruction, 2026-11-12): a sample is taken from stock and must be clearly categorised as one of
  - **Exhibition sample**: goes to an exhibition. Must be A+ quality.
  - **Customer sample**: goes to a customer. Any party that received a sample has a record under samples and counts as a customer.
- **Products**: one unit is design number + decor number + size. Example: chopping boards CB01 to CB26, each in 4 or 5 sizes (small, medium, large, XL). A different decor (for example 892 and 959) is a different SKU. Sizes stay as variations but count as one unit for stock; the final structure is not decided.
- **E-commerce**: sales on Amazon, Flipkart, Pepperfry and the website must reduce stock automatically. Marketplace APIs connect directly (Unicommerce is not needed). Order of work: Amazon first, then Flipkart and the website. Amazon production API access needs developer profile approval, still to be researched.

## People named

Sahil (hosting, sales modules), Neelaj Debnath (left menu, build), Priya (leads, customers, samples data, PO and PI), Priyanka (samples), Francis (stock and consignment updates), Anirudh (stock inventory including risers), Raj Ji / Rajji (operations, PO and PI), Sharman (new clients). Customers mentioned: Luka / Lukka, Nayla (SRL), Ida.

## Gap against the backend today

Checked by searching `backend/app` on 2026-11-12. The frontend rebuild is frontend-only, so anything in the right-hand column needs backend work before a screen can exist for it (house rule: no control that does not work).

| Requirement | Backend today |
|---|---|
| Leads | Enquiries exist (`sales` module: received, assigned, quoted, closed). Closest match; no separate lead record |
| Customers | Parties exist (`parties` module) |
| Quotations | Quotes exist (`sales` module), each attached to a party |
| Proforma invoice (PI) | Not found. Finance has invoices, receipts and credit notes |
| Samples | Exist (`sales` module). No exhibition or customer category and no quality grade field found |
| Catalogue and custom products | Exist (`catalogue`, custom products) |
| Stock in three categories, consignment | Inventory exists. No sample, inventory or exhibition category and no consignment concept found |
| Domestic, export, Netherlands and US warehouses | Not verified |
| Marketplace stock sync (Amazon, Flipkart, Pepperfry, website) | Not found |
| In-house PO to Crown and Stonecraft | Procurement module exists; fit not verified |

## Not about the ERP

The Amazon meeting also covered side-business ideas (digital products, a companionship report, a one-product store, faceless YouTube). They are kept in the original file and do not affect this product.
