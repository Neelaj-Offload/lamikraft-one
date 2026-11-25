# Products and stock (module 4) — design

Date: 2026-11-25 · Status: owner asked to "complete everything" (2026-11-25) · Programme order: module 4 of 6

## Why (from `docs/meetings/`)

- A sellable unit is **design × decor × size** (CB01–CB26 in 4–5 sizes; decors such as 892 and 959 give different
  SKUs). There is no products spreadsheet, only the catalogue: products are entered one design at a time, variation
  by variation. Custom products (a riser in a changed colour) stay separate items (already in Sales › Custom products).
- Only **finished products** go into this stock (not PRM, BRW, IP raw materials).
- **One stock pool, three categories**: sample stock, stock inventory, exhibition stock; taking stock out of each is a
  plus/minus. Exhibition stock exists in domestic and international warehouses. Netherlands and US warehouses must be
  known for drop shipping. Domestic and export stock are kept apart.
- Factory orders (e.g. 50 or 200 pieces) must show as **work in progress** with status.
- Anirudh will send the full stock list; the team enters it one item at a time.

## Survey (2026-11-25)

Catalogue `Product` has decor, finish, size fields and a free-text `variant_group` (shown as "family"); no design
column and no finished/raw distinction. Inventory has warehouses (no country or market), locations with a type and a
`counts_available` flag, opening batches, adjustments, transfers and relocations (services and routes exist; the web
has no create forms). Factory orders are purchase orders to a vendor (Crown, Stonecraft) with lines, expected dates and
outstanding quantities.

## Design

### Catalogue

- New product columns: `design_no` (e.g. `CB07`, uppercase, ≤ 20) and `item_class` (`finished`, `raw_material`,
  `packaging`; existing rows backfill to `finished`, the demo walnut board `LK-WB-1800` to `raw_material`).
- **Variant builder** `POST /catalogue/products/variants` (`catalogue.product.create`): design no, name, category
  (and subcategory), product type, decors (`[{decor_no, decor_name}]`), sizes (`[{code, label, length_mm, width_mm}]`)
  → one product per decor × size, key `{design}-{decor}-{size}` (`CB07-892-M`), `variant_group` = the design name.
  Existing keys are reported and skipped (re-runnable); everything else is created in one transaction.
- Catalogue list filter by design no and item class.

### Stock categories, markets and countries

- `inventory_location.stock_category`: `inventory`, `sample` or `exhibition` (NULL for non-stock locations).
  Every warehouse has a `SAMPLE` and an `EXHIB` location (internal, stock-bearing, **not** counted as available to
  sell, so reservations never take sample or exhibition stock); the existing `STOCK` location and bins are
  `inventory`. Backfill for existing warehouses; `create_warehouse` provisions them.
- `inventory_warehouse.market` (`domestic`, `export`) and `country_code` (ISO-2). Demo `WH-MAIN` → domestic, IN.
  Warehouse create and edit take both (NL and US warehouses are entered by the team).
- **Category stock** `GET /inventory/stock-by-category` (filters: q, warehouse, market, category, design, finished
  only by default): per product and warehouse, on hand in inventory / sample / exhibition, and **on order** = the
  outstanding quantity of open purchase-order lines for that product and warehouse (factory WIP).
- **Moving stock between categories** uses the existing relocation (internal → internal) with a reason; the web gets
  a "Move stock" dialog (e.g. 5 boards from inventory to exhibition).
- **Factory work in progress** `GET /inventory/factory-orders`: open purchase-order lines for finished products with
  vendor, PO number and status, expected date, ordered and outstanding quantities.

### Screens (`apps/one`)

- Products: "Add a design" (variant builder: decors × sizes preview, then create); design and class filters.
- Stock: category tabs (All, Inventory, Sample, Exhibition) and market filter on the stock list, with an "On order"
  column; "Move stock" dialog; "Add opening stock" form (product, warehouse, category, quantity, lot) that creates and
  submits an opening batch for approval; a "Factory orders" view.
- Warehouses: market and country on create/edit.

## Testing

Integration: variant builder creates the cross product, skips existing keys, rejects an empty list; backfill and
provisioning of category locations; sample/exhibition stock is not available to reserve; relocation between categories
moves stock; stock-by-category sums per category and on-order from an open PO; factory orders list. Web: vitest for the
variant key builder and list state; preview of opening stock → approve → stock shows in the category.
