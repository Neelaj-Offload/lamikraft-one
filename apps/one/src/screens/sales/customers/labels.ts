/**
 * Words and tones for the people the team sells to. A plain module: server pages and client
 * screens both read it. "Party" is the API's word; the team says lead and customer.
 */

import type { PartyRole, PartyStatus } from "@/features/parties/types";
import type { CSSProperties } from "react";
import { riseIndex } from "~/lib/motion";
import type { Tone } from "~/ui/badge";

/** `riseIndex` typed for a `style` prop: staggers a `rise` or `rise-plain` sibling by its position. */
export function stagger(index: number): CSSProperties {
  return riseIndex(index) as CSSProperties;
}

export const STAGE_LABEL: Record<PartyStatus, string> = {
  prospect: "Lead",
  active: "Customer",
  inactive: "Inactive",
  blocked: "Blocked",
};

export const STAGE_TONE: Record<PartyStatus, Tone> = {
  prospect: "cobalt",
  active: "leaf",
  inactive: "neutral",
  blocked: "ember",
};

/** What each stage means, for the form and the record. */
export const STAGE_HINT: Record<PartyStatus, string> = {
  prospect: "Has asked, but has not bought or received a sample yet.",
  active: "Has bought from you, or has been sent a sample.",
  inactive: "No longer trading with you. Kept for the history.",
  blocked: "Do not quote or ship until this is cleared.",
};

export const ROLE_LABEL: Record<PartyRole, string> = {
  customer: "Customer",
  vendor: "Vendor",
  fabricator: "Fabricator",
  job_worker: "Job worker",
};

export const TYPE_LABEL: Record<string, string> = {
  standard: "Standard",
  dealer: "Dealer",
  distributor: "Distributor",
};

export const TAX_SCHEME_LABEL: Record<string, string> = {
  gstin: "GSTIN",
  vat: "VAT",
  eori: "EORI",
  pan: "PAN",
  iec: "IEC",
  other: "Other",
};

export const QUOTE_STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  internal_review: "In review",
  sent: "Sent",
  revised: "Revised",
  won: "Won",
  lost: "Lost",
  cancelled: "Cancelled",
  archived: "Archived",
};

export const QUOTE_STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  internal_review: "amber",
  sent: "cobalt",
  revised: "cobalt",
  won: "leaf",
  lost: "ember",
  cancelled: "neutral",
  archived: "neutral",
};

export const ORDER_STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  confirmed: "Confirmed",
  on_hold: "On hold",
  completed: "Completed",
  cancelled: "Cancelled",
};

export const ORDER_STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  confirmed: "cobalt",
  on_hold: "amber",
  completed: "leaf",
  cancelled: "neutral",
};

/** "Germany" for "DE"; the code itself when the browser does not know it. */
export function countryName(code: string | null | undefined, locale = "en"): string | null {
  if (!code) return null;
  try {
    return new Intl.DisplayNames([locale], { type: "region" }).of(code.toUpperCase()) ?? code;
  } catch {
    return code;
  }
}

/** snake_case from the API as a readable phrase, for values this screen has no word for. */
export function humanise(value: string): string {
  const text = value.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The views of a customer's record, chosen by `?view=`. */
export const CUSTOMER_VIEWS = ["overview", "log", "contacts", "quotations", "samples", "orders", "supplies", "notes", "activity"] as const;
export type CustomerView = (typeof CUSTOMER_VIEWS)[number];

export function customerViewFrom(raw: string | string[] | undefined): CustomerView {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return CUSTOMER_VIEWS.find((view) => view === value) ?? "overview";
}

export function customerHref(partyId: string, view: CustomerView = "overview"): string {
  const base = `/sales/parties/${encodeURIComponent(partyId)}`;
  return view === "overview" ? base : `${base}?view=${view}`;
}

export type CustomerListView = "leads" | "customers" | "all";

/** Which of the three list views a status filter belongs to. */
export function listViewOf(status: PartyStatus | null): CustomerListView {
  return status === "prospect" ? "leads" : status === "active" ? "customers" : "all";
}
