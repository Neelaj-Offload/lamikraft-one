/** URL state of the finance lists (a plain module: server pages read it, client screens build links). */

export type DocKind = "invoice" | "credit_note";

export interface DocListState {
  q: string;
  status: string | null;
  open: boolean;
  overdue: boolean;
  offset: number;
}

export interface ReceiptListState {
  q: string;
  unallocated: boolean;
  offset: number;
}

type Params = Record<string, string | string[] | undefined>;

function one(params: Params, k: string): string | undefined {
  const v = params[k];
  return Array.isArray(v) ? v[0] : v;
}

function offsetOf(params: Params): number {
  const n = Number.parseInt(one(params, "offset") ?? "0", 10);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

export const DOC_STATUSES = ["draft", "pending_approval", "approved", "issued", "cancelled"] as const;

export function docStateFrom(params: Params): DocListState {
  const status = one(params, "status") ?? null;
  return {
    q: one(params, "q") ?? "",
    status: status && (DOC_STATUSES as readonly string[]).includes(status) ? status : null,
    open: one(params, "open") === "1",
    overdue: one(params, "overdue") === "1",
    offset: offsetOf(params),
  };
}

export function docBase(kind: DocKind): "/finance/invoices" | "/finance/credit-notes" {
  return kind === "credit_note" ? "/finance/credit-notes" : "/finance/invoices";
}

export function docHref(kind: DocKind, s: DocListState): string {
  const search = new URLSearchParams();
  if (s.q.trim()) search.set("q", s.q.trim());
  if (s.status) search.set("status", s.status);
  if (s.open) search.set("open", "1");
  if (s.overdue) search.set("overdue", "1");
  if (s.offset) search.set("offset", String(s.offset));
  const text = search.toString();
  return text ? `${docBase(kind)}?${text}` : docBase(kind);
}

export function receiptStateFrom(params: Params): ReceiptListState {
  return { q: one(params, "q") ?? "", unallocated: one(params, "unallocated") === "1", offset: offsetOf(params) };
}

export function receiptHref(s: ReceiptListState): string {
  const search = new URLSearchParams();
  if (s.q.trim()) search.set("q", s.q.trim());
  if (s.unallocated) search.set("unallocated", "1");
  if (s.offset) search.set("offset", String(s.offset));
  const text = search.toString();
  return text ? `/finance/receipts?${text}` : "/finance/receipts";
}

/** The ageing date in the URL (``YYYY-MM-DD``), or null for "today in company time". */
export function ageingDateFrom(params: Params): string | null {
  const v = one(params, "as_of");
  return v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null;
}
