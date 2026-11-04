/** URL state of the purchasing lists (a plain module: server pages read it, client screens build links). */

type Params = Record<string, string | string[] | undefined>;

const one = (params: Params, key: string): string | undefined => {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
};

const offsetOf = (params: Params): number => {
  const raw = one(params, "offset") ?? "";
  return /^\d{1,7}$/.test(raw) ? Number.parseInt(raw, 10) : 0;
};

export interface PoListState {
  q: string;
  status: string | null;
  overdue: boolean;
  offset: number;
}

export function poStateFrom(params: Params): PoListState {
  return { q: one(params, "q") ?? "", status: one(params, "status") ?? null, overdue: one(params, "overdue") === "1", offset: offsetOf(params) };
}

export function poListHref(state: PoListState): string {
  const search = new URLSearchParams();
  if (state.q.trim()) search.set("q", state.q.trim());
  if (state.status) search.set("status", state.status);
  if (state.overdue) search.set("overdue", "1");
  if (state.offset) search.set("offset", String(state.offset));
  const text = search.toString();
  return text ? `/operations/purchasing/orders?${text}` : "/operations/purchasing/orders";
}

export interface RequisitionListState {
  status: string | null;
  offset: number;
}

export function requisitionStateFrom(params: Params): RequisitionListState {
  return { status: one(params, "status") ?? null, offset: offsetOf(params) };
}

export function requisitionListHref(state: RequisitionListState): string {
  const search = new URLSearchParams();
  if (state.status) search.set("status", state.status);
  if (state.offset) search.set("offset", String(state.offset));
  const text = search.toString();
  return text ? `/operations/purchasing/requisitions?${text}` : "/operations/purchasing/requisitions";
}

export interface ReceiptListState {
  awaitingQc: boolean;
  offset: number;
}

export function receiptStateFrom(params: Params): ReceiptListState {
  return { awaitingQc: one(params, "awaiting_qc") === "1", offset: offsetOf(params) };
}

export function receiptListHref(state: ReceiptListState): string {
  const search = new URLSearchParams();
  if (state.awaitingQc) search.set("awaiting_qc", "1");
  if (state.offset) search.set("offset", String(state.offset));
  const text = search.toString();
  return text ? `/operations/purchasing/receipts?${text}` : "/operations/purchasing/receipts";
}
