/**
 * Copy for the Operations and Finance overview pages: honest "planned" states with the slice that
 * delivers each part (docs/BUILD_STATE.md §4, docs/PLAN.md Slices 2, 4 and 5). No figures.
 */

export interface PlannedPart {
  label: string;
  slice: number;
  /** Set once the part is delivered: the manifest route it opens. */
  routeId?: string;
}

export interface AreaCopy {
  title: string;
  intro: string;
  stateTitle: string;
  stateBody: string;
  partsHeading: string;
  parts: readonly PlannedPart[];
}

export const areaMessages = {
  planned: (slice: number) => `Planned · Slice ${slice}`,
  available: "Available",
  today: "Go to Today",
  inbox: "Open the Inbox",
  nothingOn: "Nothing in this area is switched on yet, so there are no figures to show.",
  operations: {
    title: "Operations",
    intro: "Cutting, challans, stock, purchasing, production, quality and dispatch.",
    stateTitle: "The cutting optimiser is here; the rest of Operations arrives in Slices 2 and 4",
    stateBody:
      "Saved cut plans with a true-scale board canvas are available now. Delivery challans as documents complete Slice 2; Slice 4 connects inventory, reservations, purchasing, production, quality, dispatch and logistics.",
    partsHeading: "What this area will hold",
    parts: [
      { label: "Cutting optimiser: saved plans with a true-scale board canvas", slice: 2, routeId: "operations-cutting" },
      { label: "Delivery challans as documents: numbering, transitions, PDF and CSV", slice: 2 },
      { label: "Inventory: warehouses, lots and a double-entry movement ledger", slice: 4 },
      { label: "Reservations and pick lists with no oversell", slice: 4 },
      { label: "Purchasing: requisition, purchase order, goods receipt", slice: 4 },
      { label: "Production: BOMs, routings, work orders and offcut lots", slice: 4 },
      { label: "Quality checks on receipts", slice: 4 },
      { label: "Dispatch and logistics: packing lists, shipments and cutoffs", slice: 4 },
    ],
  },
  finance: {
    title: "Finance",
    intro: "Invoices, credit notes, receipts and the handoff to accounting.",
    stateTitle: "Finance is planned for Slice 5",
    stateBody:
      "Slice 5 brings invoice and credit-note drafts with an issue gate, receipts, allocations, ageing, the accounting handoff and margin exceptions. Nothing here is switched on yet.",
    partsHeading: "What this area will hold",
    parts: [
      { label: "Invoice drafts with an issue gate on tax and provider configuration", slice: 5 },
      { label: "Credit notes", slice: 5 },
      { label: "Receipts and allocations", slice: 5 },
      { label: "Ageing", slice: 5 },
      { label: "Accounting handoff: CSV adapter and a Demo adapter, with reconciliation", slice: 5 },
      { label: "Margin policy and exceptions", slice: 5 },
    ],
  },
} as const satisfies { planned: (slice: number) => string; available: string; today: string; inbox: string; nothingOn: string; operations: AreaCopy; finance: AreaCopy };
