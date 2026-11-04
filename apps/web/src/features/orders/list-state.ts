/** URL state of /sales/orders (a plain module: server pages read it, client screens build links). */

export const ORDER_STATUSES = ["draft", "confirmed", "on_hold", "completed", "cancelled"] as const;

export interface OrderListState {
  q: string;
  status: string | null;
  offset: number;
}

export function orderListStateFrom(params: Record<string, string | string[] | undefined>): OrderListState {
  const one = (k: string) => (Array.isArray(params[k]) ? params[k]?.[0] : params[k]) as string | undefined;
  const offset = Number.parseInt(one("offset") ?? "0", 10);
  return { q: one("q") ?? "", status: ORDER_STATUSES.find((s) => s === one("status")) ?? null, offset: Number.isFinite(offset) && offset > 0 ? offset : 0 };
}

export function orderListHref(state: OrderListState): string {
  const search = new URLSearchParams();
  if (state.q.trim()) search.set("q", state.q.trim());
  if (state.status) search.set("status", state.status);
  if (state.offset) search.set("offset", String(state.offset));
  const text = search.toString();
  return text ? `/sales/orders?${text}` : "/sales/orders";
}
