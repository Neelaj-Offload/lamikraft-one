/** URL state of the dispatch lists (a plain module: server pages read it, client screens build links). */

type Params = Record<string, string | string[] | undefined>;

const one = (params: Params, key: string): string | undefined => {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
};

const offsetOf = (params: Params): number => {
  const raw = one(params, "offset") ?? "";
  return /^\d{1,7}$/.test(raw) ? Number.parseInt(raw, 10) : 0;
};

export interface ShipmentListState {
  q: string;
  status: string | null;
  offset: number;
}

export function shipmentStateFrom(params: Params): ShipmentListState {
  return { q: one(params, "q") ?? "", status: one(params, "status") ?? null, offset: offsetOf(params) };
}

export function shipmentListHref(state: ShipmentListState): string {
  const search = new URLSearchParams();
  if (state.q.trim()) search.set("q", state.q.trim());
  if (state.status) search.set("status", state.status);
  if (state.offset) search.set("offset", String(state.offset));
  const text = search.toString();
  return text ? `/operations/dispatch?${text}` : "/operations/dispatch";
}

export interface PackingListState {
  status: string | null;
  offset: number;
}

export function packingStateFrom(params: Params): PackingListState {
  return { status: one(params, "status") ?? null, offset: offsetOf(params) };
}

export function packingListHref(state: PackingListState): string {
  const search = new URLSearchParams();
  if (state.status) search.set("status", state.status);
  if (state.offset) search.set("offset", String(state.offset));
  const text = search.toString();
  return text ? `/operations/dispatch/packing-lists?${text}` : "/operations/dispatch/packing-lists";
}
