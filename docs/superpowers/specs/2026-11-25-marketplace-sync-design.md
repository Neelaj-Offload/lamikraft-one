# E-commerce stock sync (module 5) — design

Date: 2026-11-25 · Status: owner asked to "complete everything" (2026-11-25) · Programme order: module 5 of 6

## Why (from `docs/meetings/`)

Sales on Amazon, Flipkart, Pepperfry and the website must come off stock automatically, and stock must stay in step
on those platforms; Unicommerce is not needed (the APIs connect straight to the ERP). Integration starts with Amazon
Seller Central (a "LamiKraft ERP" developer app exists; production access needs the developer profile approved),
then Flipkart and the website. No live credentials exist yet, and AGENTS.md rule 6 keeps every integration in a
labelled **Demo** mode until the owner places credentials.

## Design (module `marketplaces`)

- **Channels** (`marketplaces_channel`): Amazon India, Flipkart, Pepperfry, Website, each with a mode (`demo` or
  `live`), the warehouse it ships from, active flag and last sync. Live mode is allowed only when the adapter's
  credentials are configured in the environment (Amazon: `LK_AMAZON_LWA_CLIENT_ID`, `LK_AMAZON_LWA_CLIENT_SECRET`,
  `LK_AMAZON_REFRESH_TOKEN`, `LK_AMAZON_SELLER_ID`, optional `LK_AMAZON_ENDPOINT`, `LK_AMAZON_MARKETPLACE_ID`);
  credentials are never stored in the database or shown.
- **Listings** (`marketplaces_listing`): the channel's SKU (and ASIN or listing id) mapped to a catalogue product,
  with "push stock" on or off and the last quantity pushed.
- **Orders** (`marketplaces_order`): each external order once (unique per channel), its lines, status
  (`posted`, `needs_attention`, `cancelled`) and the stock posting it made. A posted order moves stock from the
  channel warehouse's inventory to the company customer location (new posting source `marketplace_order`); an order
  with an unmapped SKU or not enough free stock is held as `needs_attention` with the reason, never silently skipped.
- **Sync** (`POST /marketplaces/channels/{id}/sync` and a 15-minute schedule in production): fetch orders since the
  last sync, post them, then push the free quantity of every push-enabled listing (free = inventory available to
  sell in the channel warehouse; sample and exhibition stock never counts).
- **Adapters**: `demo` (orders come from "Simulate an order", clearly labelled Demo; pushes are recorded, nothing
  leaves the system) and `amazon` (Selling Partner API: LWA token, Orders v0 `getOrders` + `getOrderItems`, Listings
  Items 2021-08-01 `patchListingsItem` for `fulfillment_availability`), tested against a mocked HTTP transport.
  Flipkart, Pepperfry and the website run in Demo until their APIs are wired (module scope after approval).
- Permissions: `marketplaces.channel.read` (mgt, sal, ops), `.channel.manage` (mgt), `.channel.run` (mgt, ops; sync
  and simulate). Events: `marketplaces.order.imported` (channel_id, order_id, status), `marketplaces.sync.completed`.

## Screens (`apps/one`, Sales › Marketplaces)

Channels as tiles (mode badge Demo/Live, warehouse, last sync, Sync now); a channel page with listings (map a
product to a SKU, push on/off, last pushed), recent orders (status, stock posted or the reason it needs attention),
and in Demo "Simulate an order".

## Testing

Integration: an imported order posts stock out once (re-sync does not post twice); unmapped SKU and short stock hold
the order with a reason; push computes free stock excluding sample/exhibition; live mode refused without credentials;
Amazon adapter parses orders and sends the listings patch (mocked transport). Web: list state; preview of simulate →
sync → stock down.
