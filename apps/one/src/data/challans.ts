/**
 * Data helpers for the challan screens.
 *
 * The API calls, parsers, list state, form model, pickers and command hooks come from the old
 * app's non-visual modules (`@/features/challans/*`). This file holds only what lived inside old
 * *view* files and so could not be imported: which actions the server offers, why a draft cannot
 * be issued yet, the body of a new line, and the words for each status, type and destination.
 * A plain module (no hooks), so server route files may read it too.
 */

import type { Route } from "next";
import type { ProductOption } from "@/features/sales/pickers";
import type { ChallanDetail, ChallanType, DestinationType, LineCreateRequest, TransitionOption } from "@/features/challans/types";
import type { Tone } from "~/ui/badge";
import type { IconName } from "~/ui/icon";

/** `router.push` and `Link` want typed routes; API paths and built URLs are plain strings. */
export const asRoute = (path: string) => path as Route;

export const CHALLANS_HOME = "/operations/challans";

// ---------------------------------------------------------------------------------------------
// Vocabulary: one word and one tone per status, shared by the list, the record and the hub

export interface StatusLook {
  label: string;
  tone: Tone;
}

const STATUS: Record<string, StatusLook> = {
  draft: { label: "Draft", tone: "neutral" },
  issued: { label: "Issued", tone: "cobalt" },
  closed: { label: "Closed", tone: "leaf" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export function humanise(code: string): string {
  const text = code.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const challanStatus = (status: string): StatusLook => STATUS[status] ?? { label: humanise(status), tone: "neutral" };

export const TYPE_LABEL: Record<string, string> = {
  outward: "Outward",
  inward: "Inward",
  return: "Return",
  job_work: "Job work",
  transfer: "Transfer",
  sample: "Sample",
};

/** What each kind of movement is for, in a line; shown when choosing one. */
export const TYPE_HINT: Record<ChallanType, string> = {
  outward: "Goods leaving for a customer, fabricator, vendor or transporter.",
  inward: "Goods coming in to you.",
  return: "Goods coming back from where they were sent.",
  job_work: "Material sent out to be worked on. It always comes back.",
  transfer: "Between your own warehouses and offices.",
  sample: "Samples sent out, usually expected back.",
};

export const TYPE_ICON: Record<ChallanType, IconName> = {
  outward: "arrowUpRight",
  inward: "arrowDownRight",
  return: "undo",
  job_work: "hammer",
  transfer: "warehouse",
  sample: "packageOpen",
};

export const RETURN_LABEL: Record<string, string> = { returnable: "Returnable", non_returnable: "Non-returnable" };

export const DESTINATION_LABEL: Record<string, string> = {
  fabricator: "Fabricator",
  customer: "Customer",
  warehouse: "Warehouse",
  vendor: "Vendor",
  office: "Office",
  transporter: "Transporter",
};

/** "to a customer", "to a warehouse": the destination in running text. */
export const DESTINATION_PHRASE: Record<DestinationType, string> = {
  fabricator: "to a fabricator",
  customer: "to a customer",
  warehouse: "to a warehouse",
  vendor: "to a vendor",
  office: "to an office",
  transporter: "with a transporter",
};

export const LINE_KIND_LABEL: Record<string, string> = { catalog: "Catalogue product", custom: "Custom product", manual: "Typed in by hand" };

/** The reasons the server accepts for a cancellation (the old screen's list, in new words). */
export const CANCEL_REASONS: readonly { value: string; label: string }[] = [
  { value: "entered_in_error", label: "Entered by mistake" },
  { value: "not_dispatched", label: "The goods never left" },
  { value: "replaced", label: "Replaced by another challan" },
  { value: "other", label: "Another reason" },
];

export const cancelReasonLabel = (code: string | null): string | null =>
  code ? (CANCEL_REASONS.find((reason) => reason.value === code)?.label ?? humanise(code)) : null;

// ---------------------------------------------------------------------------------------------
// What can be done with a challan now: only what the server offers

export interface ChallanActionModel {
  /** Issue (a draft) or close (an issued challan): the step that moves it forward. */
  forward: (TransitionOption & { action: "issue" | "close" }) | null;
  cancel: TransitionOption | null;
  canDuplicate: boolean;
  canDelete: boolean;
  /** The PDF and the print view. */
  canExport: boolean;
}

export function challanActions(challan: ChallanDetail): ChallanActionModel {
  const find = (action: string) => challan.allowed_transitions.find((option) => option.action === action) ?? null;
  const issue = find("issue");
  const close = find("close");
  const forward = issue ? { ...issue, action: "issue" as const } : close ? { ...close, action: "close" as const } : null;
  return {
    forward,
    cancel: find("cancel"),
    canDuplicate: challan.capabilities.duplicate?.allowed === true && !challan.deleted_at,
    canDelete: challan.capabilities.delete?.allowed === true,
    canExport: challan.capabilities.export?.allowed === true,
  };
}

const ISSUE_BLOCKED: Record<string, string> = {
  no_lines: "Add at least one line before you issue it.",
  original_required: "A return needs the original challan it comes back against.",
  lines_need_original_lines: "Link every line to a line of the original challan.",
};

/** Why Issue is not offered yet (the server's guard code), so the person knows what to do next. */
export function issueBlockedText(challan: ChallanDetail): string | null {
  const capability = challan.capabilities.issue;
  if (challan.status !== "draft" || !capability || capability.allowed || !capability.reason_code) return null;
  return ISSUE_BLOCKED[capability.reason_code] ?? null;
}

/** A draft the person may still change. */
export function isEditable(challan: ChallanDetail): boolean {
  return challan.status === "draft" && !challan.deleted_at && challan.capabilities.update?.allowed === true;
}

/** Returns are tracked for a challan that is returnable, is itself a return, or already has links. */
export function tracksReturns(challan: ChallanDetail): boolean {
  return challan.return_links.length > 0 || challan.return_type === "returnable" || challan.challan_type === "return";
}

// ---------------------------------------------------------------------------------------------
// A new line (the body the old add-line form sent)

export interface LineForm {
  kind: "catalog" | "manual";
  product: ProductOption | null;
  item_code: string;
  item_name: string;
  hsn_sac: string;
  /** A decimal string; empty until typed. */
  quantity: string;
  unit: string;
  remarks: string;
  original_line_id: string | null;
}

export const EMPTY_LINE: LineForm = {
  kind: "catalog",
  product: null,
  item_code: "",
  item_name: "",
  hsn_sac: "",
  quantity: "",
  unit: "pcs",
  remarks: "",
  original_line_id: null,
};

/** The request for the form, or null while a required value is missing (product, name or quantity). */
export function lineRequest(form: LineForm): LineCreateRequest | null {
  if (!form.quantity) return null;
  const optional = (value: string) => value.trim() || null;
  const common = {
    quantity: form.quantity,
    remarks: optional(form.remarks),
    ...(form.original_line_id ? { original_line_id: form.original_line_id } : {}),
  };
  if (form.kind === "catalog") {
    if (!form.product) return null;
    return { line_type: "catalog", product_id: form.product.id, ...common };
  }
  if (!form.item_name.trim()) return null;
  return {
    line_type: "manual",
    item_name: form.item_name.trim(),
    item_code: optional(form.item_code),
    hsn_sac: optional(form.hsn_sac),
    unit: form.unit,
    ...common,
  };
}
