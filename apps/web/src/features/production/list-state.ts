/** URL state of /operations/production/work-orders (a plain module: server pages read it, client screens build links). */

export interface WorkOrderListState {
  q: string;
  status: string | null;
  blocked: boolean;
  offset: number;
}

const STATUSES = ["draft", "released", "in_progress", "completed", "closed", "cancelled"] as const;

export function workOrderStateFrom(params: Record<string, string | string[] | undefined>): WorkOrderListState {
  const one = (k: string) => (Array.isArray(params[k]) ? params[k]?.[0] : params[k]) as string | undefined;
  const offset = Number.parseInt(one("offset") ?? "0", 10);
  const status = STATUSES.find((s) => s === one("status")) ?? null;
  return { q: one("q") ?? "", status, blocked: one("blocked") === "1", offset: Number.isFinite(offset) && offset > 0 ? offset : 0 };
}

export function workOrdersHref(s: WorkOrderListState): string {
  const search = new URLSearchParams();
  if (s.q.trim()) search.set("q", s.q.trim());
  if (s.status) search.set("status", s.status);
  if (s.blocked) search.set("blocked", "1");
  if (s.offset) search.set("offset", String(s.offset));
  const text = search.toString();
  return text ? `/operations/production/work-orders?${text}` : "/operations/production/work-orders";
}

/** Capacity window in the URL (`from`, `to`: business dates). */
export function capacityStateFrom(params: Record<string, string | string[] | undefined>): { from: string | null; to: string | null } {
  const one = (k: string) => (Array.isArray(params[k]) ? params[k]?.[0] : params[k]) as string | undefined;
  const iso = (v: string | undefined) => (v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null);
  return { from: iso(one("from")), to: iso(one("to")) };
}
