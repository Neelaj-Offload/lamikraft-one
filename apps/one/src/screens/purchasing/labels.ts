/**
 * The purchasing vocabulary: one word and one tone per status, shared by lists and records.
 * A plain module, so anything may import it.
 */

import type { Tone } from "~/ui/badge";

export interface StatusLook {
  label: string;
  tone: Tone;
}

function humanise(code: string): string {
  const text = code.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const look = (table: Record<string, StatusLook>, status: string): StatusLook => table[status] ?? { label: humanise(status), tone: "neutral" };

const REQUISITION: Record<string, StatusLook> = {
  draft: { label: "Draft", tone: "neutral" },
  submitted: { label: "Waiting for approval", tone: "amber" },
  approved: { label: "Approved", tone: "cobalt" },
  rejected: { label: "Rejected", tone: "ember" },
  closed: { label: "Ordered", tone: "leaf" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const PURCHASE_ORDER: Record<string, StatusLook> = {
  draft: { label: "Draft", tone: "neutral" },
  pending_approval: { label: "Waiting for approval", tone: "amber" },
  approved: { label: "Approved", tone: "cobalt" },
  issued: { label: "Sent to vendor", tone: "cobalt" },
  partially_received: { label: "Partly received", tone: "cobalt" },
  received: { label: "Received", tone: "leaf" },
  closed: { label: "Closed", tone: "neutral" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const RECEIPT: Record<string, StatusLook> = {
  draft: { label: "Not posted", tone: "amber" },
  posted: { label: "Posted", tone: "leaf" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const MATCH: Record<string, StatusLook> = {
  pending: { label: "Waiting for QC", tone: "amber" },
  matched: { label: "Matched", tone: "leaf" },
  qty_mismatch: { label: "Quantity mismatch", tone: "ember" },
  price_variance: { label: "Price variance", tone: "ember" },
  amount_mismatch: { label: "Amount mismatch", tone: "ember" },
};

export const requisitionStatus = (status: string) => look(REQUISITION, status);
export const poStatus = (status: string) => look(PURCHASE_ORDER, status);
export const receiptStatus = (status: string) => look(RECEIPT, status);
export const matchStatus = (status: string) => look(MATCH, status);

export const BILL_STATUS: Record<string, string> = {
  draft: "Draft",
  matched: "Matched",
  mismatch: "Does not match",
  handed_off: "Handed to finance",
  cancelled: "Cancelled",
};

/** Why a vendor bill did not match the order and what was received. */
export const MATCH_EXCEPTION: Record<string, string> = {
  qty_mismatch: "More is billed than was accepted",
  price_variance: "The price differs from the order",
  amount_mismatch: "The subtotal differs from the lines",
  pending_qc: "Goods are still waiting for QC",
  currency_mismatch: "The currency differs from the order",
};

export const FAILED = "That did not go through";

export const count = (n: number, one: string, many: string) => (n === 1 ? `1 ${one}` : `${n} ${many}`);
