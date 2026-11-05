/**
 * Copy for the Operations overview page: honest "planned" states with the slice that delivers each
 * part (docs/BUILD_STATE.md §4, docs/PLAN.md Slices 2 and 4). No figures. Finance has its own hub
 * since Slice 5 (`features/finance`).
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
  /** Replaces the shared "nothing is switched on" line once a part of the area is live. */
  liveNote?: string;
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
    stateTitle: "Cutting, challans, inventory, reservations, purchasing, quality, dispatch and production are here",
    stateBody:
      "Saved cut plans, delivery challans, the stock ledger with warehouses and stock takes, reservations with pick lists, purchasing from requisition to vendor bill, QC inspections, dispatch with packing lists and cutoffs, and production (work orders, BOMs, routings, work centres and capacity) are available now; once inventory is live an issued challan moves stock exactly once.",
    liveNote: "Every part below is available now; each opens for people whose role includes it.",
    partsHeading: "What this area will hold",
    parts: [
      { label: "Cutting optimiser: saved plans with a true-scale board canvas", slice: 2, routeId: "operations-cutting" },
      { label: "Delivery challans: numbering, transitions, PDF and CSV; one stock posting per issue", slice: 2, routeId: "operations-challans" },
      { label: "Inventory: warehouses, lots and a double-entry movement ledger", slice: 4, routeId: "operations-inventory" },
      { label: "Reservations and pick lists with no oversell", slice: 4, routeId: "operations-reservations" },
      { label: "Purchasing: requisition, purchase order, goods receipt, vendor bill match", slice: 4, routeId: "operations-purchasing-orders" },
      { label: "Production: BOMs, routings, work orders and offcut lots", slice: 4, routeId: "operations-production-work-orders" },
      { label: "Capacity: load per work centre per day against the work calendar", slice: 4, routeId: "operations-production-capacity" },
      { label: "Quality checks on receipts", slice: 4, routeId: "operations-quality" },
      { label: "Dispatch and logistics: packing lists, shipments and cutoffs", slice: 4, routeId: "operations-dispatch" },
    ],
  },
} as const satisfies { planned: (slice: number) => string; available: string; today: string; inbox: string; nothingOn: string; operations: AreaCopy };
