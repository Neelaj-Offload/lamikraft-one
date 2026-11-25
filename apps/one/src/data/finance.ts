"use client";

/**
 * Data helpers for the Finance screens.
 *
 * The API calls, list state and the command hook come from the old app's non-visual modules
 * (`@/features/finance/api`, `list-state`, `use-finance-command`). This file holds only what lived
 * inside old *view* files and so could not be imported: the queries (same query keys, same
 * fetchers), the reason codes each command sends, and the words for every status and server code.
 */

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import {
  fetchAccountingStatus,
  fetchAgeing,
  fetchDocument,
  fetchDocuments,
  fetchExceptions,
  fetchExports,
  fetchReceipt,
  fetchReceipts,
  fetchSuggestions,
  fetchSummary,
  fetchTaxProfiles,
} from "@/features/finance/api";
import type { DocKind, DocListState, ReceiptListState } from "@/features/finance/list-state";
import { queryKeys } from "@/lib/api/query-keys";
import type { IconName, Tone } from "~/ui";

// ---------------------------------------------------------------------------------------------
// Queries (the keys and fetchers the old screens used, so caches and invalidation stay shared)

export const useFinanceSummary = () => useQuery({ queryKey: queryKeys.finance.summary(), queryFn: ({ signal }) => fetchSummary(signal) });

export const useInvoiceSuggestions = () => useQuery({ queryKey: queryKeys.finance.suggestions(), queryFn: ({ signal }) => fetchSuggestions(signal) });

export const useFinanceDocuments = (kind: DocKind, state: DocListState) =>
  useQuery({ queryKey: queryKeys.finance.documents(kind, { ...state }), queryFn: ({ signal }) => fetchDocuments(kind, state, signal) });

export const useFinanceDocument = (kind: DocKind, id: string) =>
  useQuery({ queryKey: queryKeys.finance.document(kind, id), queryFn: ({ signal }) => fetchDocument(kind, id, signal) });

export const useReceipts = (state: ReceiptListState) =>
  useQuery({ queryKey: queryKeys.finance.receipts({ ...state }), queryFn: ({ signal }) => fetchReceipts(state, signal) });

export const useReceipt = (receiptId: string) => useQuery({ queryKey: queryKeys.finance.receipt(receiptId), queryFn: ({ signal }) => fetchReceipt(receiptId, signal) });

export const useAgeing = (asOf: string | null) => useQuery({ queryKey: queryKeys.finance.ageing(asOf), queryFn: ({ signal }) => fetchAgeing(asOf, signal) });

export const useFinanceExceptions = () => useQuery({ queryKey: queryKeys.finance.exceptions(), queryFn: ({ signal }) => fetchExceptions(signal) });

export const useAccountingStatus = () => useQuery({ queryKey: queryKeys.finance.accounting(), queryFn: ({ signal }) => fetchAccountingStatus(signal) });

export const useAccountingExports = () => useQuery({ queryKey: queryKeys.finance.exports(), queryFn: ({ signal }) => fetchExports(signal) });

export const useTaxProfiles = () => useQuery({ queryKey: queryKeys.finance.taxProfiles(), queryFn: ({ signal }) => fetchTaxProfiles(signal) });

// ---------------------------------------------------------------------------------------------
// Paths

/** `router.push` and `Link` want typed routes; API paths and built URLs are plain strings. */
export const asRoute = (path: string) => path as Route;

/**
 * A path the server sent (a blocker's fix, an exception's record). The customer profile lives at
 * `/sales/parties/…` in this app; the finance module still names it `/sales/customers/…`.
 */
export const serverPath = (path: string) => asRoute(path.replace(/^\/sales\/customers\//, "/sales/parties/"));

// ---------------------------------------------------------------------------------------------
// Vocabulary: one word and one tone per status

export interface StatusLook {
  label: string;
  tone: Tone;
}

export function humanise(code: string): string {
  const text = code.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const DOCUMENT_STATUS: Record<string, StatusLook> = {
  draft: { label: "Draft", tone: "neutral" },
  pending_approval: { label: "Awaiting approval", tone: "amber" },
  approved: { label: "Approved", tone: "cobalt" },
  issued: { label: "Issued", tone: "leaf" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const RECEIPT_STATUS: Record<string, StatusLook> = {
  recorded: { label: "Recorded", tone: "leaf" },
  reversed: { label: "Voided", tone: "neutral" },
};

const look = (table: Record<string, StatusLook>, status: string): StatusLook => table[status] ?? { label: humanise(status), tone: "neutral" };

export const documentStatus = (status: string) => look(DOCUMENT_STATUS, status);
export const receiptStatus = (status: string) => look(RECEIPT_STATUS, status);

export const TAX_STATUS_LABEL: Record<string, string> = {
  not_configured: "Tax not calculated",
  unverified: "Not yet verified",
  verified: "Verified",
};

export const METHOD_LABEL: Record<string, string> = { bank_transfer: "Bank transfer", cheque: "Cheque", cash: "Cash", card: "Card", other: "Other" };

// ---------------------------------------------------------------------------------------------
// The issue check: every blocker code the server sends, in plain words

export const BLOCKER_TEXT: Record<string, string> = {
  not_approved: "Someone other than the person who drafted it has to approve this version.",
  approval_stale: "It changed after it was approved, so it needs a fresh approval.",
  company_identity_incomplete: "Your company's legal name, address or GSTIN is not set.",
  party_billing_incomplete: "The customer's legal name or billing address is missing.",
  tax_profile_missing: "No tax profile is chosen, so no tax has been calculated.",
  tax_profile_unverified: "The chosen tax profile has not been verified by a second person.",
  e_invoice_provider_not_verified: "This tax profile needs e-invoicing, and no e-invoice provider is connected (Demo).",
  totals_changed: "The totals no longer match the lines. Reopen the draft and save it again.",
  quantity_exceeds_delivered: "It bills more than was delivered and not yet invoiced.",
  quantity_exceeds_creditable: "It credits more than can still be credited on the invoice.",
  no_lines: "It has no lines.",
  zero_total: "The total is zero.",
};

/** What the link beside a blocker says; anything else reads "Fix this". */
export const BLOCKER_FIX_LABEL: Record<string, string> = {
  tax_profile_missing: "See tax profiles",
  tax_profile_unverified: "Verify the tax profile",
  party_billing_incomplete: "Open the customer",
};

export const blockerText = (code: string) => BLOCKER_TEXT[code] ?? humanise(code);

// ---------------------------------------------------------------------------------------------
// Reason codes each command sends (the same ids the old dialogs offered)

export interface ReasonOption {
  id: string;
  label: string;
}

export const DISMISS_REASONS: readonly ReasonOption[] = [
  { id: "invoiced_elsewhere", label: "Invoiced outside Lamikraft One" },
  { id: "no_charge", label: "No charge for this delivery" },
  { id: "duplicate", label: "Duplicate" },
];
export const REJECT_REASONS: readonly ReasonOption[] = [
  { id: "needs_changes", label: "Needs changes" },
  { id: "change_tax", label: "The tax profile has to change" },
  { id: "wrong_quantities", label: "Wrong quantities" },
];
export const CANCEL_REASONS: readonly ReasonOption[] = [
  { id: "duplicate", label: "Duplicate draft" },
  { id: "not_billable", label: "Not billable" },
  { id: "entered_in_error", label: "Entered in error" },
];
export const CREDIT_REASONS: readonly ReasonOption[] = [
  { id: "returned_goods", label: "Goods returned" },
  { id: "damaged", label: "Damaged in transit" },
  { id: "price_correction", label: "Price correction" },
];
export const VOID_REASONS: readonly ReasonOption[] = [
  { id: "bounced", label: "The payment bounced" },
  { id: "entered_in_error", label: "Entered in error" },
  { id: "duplicate", label: "Duplicate receipt" },
];
/** The one reason the old screen sent when an allocation was reversed. */
export const ALLOCATION_REVERSE_REASON = "wrong_invoice";

const ALL_REASONS = [...DISMISS_REASONS, ...REJECT_REASONS, ...CANCEL_REASONS, ...CREDIT_REASONS, ...VOID_REASONS];
export const reasonLabel = (code: string | null | undefined) => (code ? (ALL_REASONS.find((reason) => reason.id === code)?.label ?? humanise(code)) : null);

export const RECEIPT_CURRENCIES = ["EUR", "INR", "USD", "GBP"] as const;
export const RECEIPT_METHODS = ["bank_transfer", "cheque", "cash", "card", "other"] as const;

// ---------------------------------------------------------------------------------------------
// History, exceptions and exports

export const HISTORY_DID: Record<string, string> = {
  create: "drafted it",
  edit: "edited it",
  submit: "submitted it for approval",
  approve: "approved it",
  reject: "sent it back to draft",
  issue: "issued it",
  issue_blocked: "tried to issue it, and the issue check refused",
  cancel: "cancelled it",
};
export const HISTORY_ICON: Record<string, IconName> = {
  create: "filePlus",
  edit: "edit",
  submit: "send",
  approve: "check",
  reject: "undo",
  issue: "badgeCheck",
  issue_blocked: "alert",
  cancel: "xCircle",
};

export interface ExceptionLook extends StatusLook {
  icon: IconName;
  /** The plural, for the filter chip. */
  plural: string;
}

export const EXCEPTION_KINDS = ["issue_blocked", "overdue", "unallocated_receipt", "sync_failed", "sync_mismatch"] as const;

const EXCEPTION_KIND: Record<string, ExceptionLook> = {
  issue_blocked: { label: "Issue blocked", plural: "Issue blocked", tone: "amber", icon: "lock" },
  overdue: { label: "Overdue", plural: "Overdue", tone: "ember", icon: "clock" },
  unallocated_receipt: { label: "Unallocated receipt", plural: "Unallocated receipts", tone: "amber", icon: "banknote" },
  sync_failed: { label: "Export failed", plural: "Failed exports", tone: "ember", icon: "xCircle" },
  sync_mismatch: { label: "Reconciliation mismatch", plural: "Reconciliation mismatches", tone: "ember", icon: "split" },
  margin: { label: "Margin below policy", plural: "Margin below policy", tone: "amber", icon: "percent" },
};

export const exceptionKind = (kind: string): ExceptionLook => EXCEPTION_KIND[kind] ?? { label: humanise(kind), plural: humanise(kind), tone: "neutral", icon: "alert" };

const EXCEPTION_CODE: Record<string, string> = {
  days_1_30: "1 to 30 days past due",
  days_31_60: "31 to 60 days past due",
  days_61_90: "61 to 90 days past due",
  days_over_90: "Over 90 days past due",
  unallocated: "Not fully allocated",
  account_mapping_missing: "Account codes are not set",
  documents_blocked: "Every document was blocked",
  nothing_to_export: "There was nothing to export",
  missing_in_accounting: "Not found in the accounting system",
  total_differs: "The total differs in the accounting system",
};

/** A blocker, ageing or sync code in words; unknown codes are shown as written by the server. */
export const exceptionCodeText = (code: string) => BLOCKER_TEXT[code] ?? EXCEPTION_CODE[code] ?? humanise(code);

export const ADAPTER_LABEL: Record<string, string> = { csv: "CSV journal", demo: "Demo (simulated)" };

export const RECONCILIATION: Record<string, StatusLook> = {
  not_reconciled: { label: "Not reconciled", tone: "neutral" },
  matched: { label: "Matched", tone: "leaf" },
  mismatch: { label: "Mismatch", tone: "ember" },
};
