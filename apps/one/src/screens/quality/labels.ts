/** The quality vocabulary: inspection states, checklist results, where the goods came from, why they were rejected. */

import type { Tone } from "~/ui/badge";

export interface StatusLook {
  label: string;
  tone: Tone;
}

const INSPECTION: Record<string, StatusLook> = {
  pending: { label: "Waiting", tone: "amber" },
  passed: { label: "Passed", tone: "leaf" },
  failed: { label: "Rejected in part", tone: "ember" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export const inspectionStatus = (status: string): StatusLook => INSPECTION[status] ?? { label: status.replace(/_/g, " "), tone: "neutral" };

export const CHECK_RESULT: Record<string, StatusLook> = {
  pass: { label: "Pass", tone: "leaf" },
  fail: { label: "Fail", tone: "ember" },
  na: { label: "Not applicable", tone: "neutral" },
};

const SUBJECT: Record<string, string> = {
  "procurement.goods_receipt_line": "Goods receipt",
  "production.work_order": "Production output",
  "challans.challan_line": "Customer return",
  "inventory.stock": "Stock on hold",
};

export const subjectLabel = (type: string) => SUBJECT[type] ?? "Stock";

/** The reject reason codes the API accepts, in the words of the shop floor. */
export const REJECT_REASONS = [
  { value: "surface_damage", label: "Surface damage" },
  { value: "dimension_out_of_tolerance", label: "Dimensions out of tolerance" },
  { value: "wrong_item", label: "Wrong item" },
  { value: "moisture", label: "Moisture or warping" },
  { value: "other", label: "Something else" },
] as const;

export const rejectReasonLabel = (code: string | null) => (code ? (REJECT_REASONS.find((reason) => reason.value === code)?.label ?? code.replace(/_/g, " ")) : null);
