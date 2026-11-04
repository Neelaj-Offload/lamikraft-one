/** URL state of /operations/inventory (a plain module: server pages read it, client screens build links). */

export interface StockState {
  q: string;
  warehouse: string | null;
  short: boolean;
  offset: number;
}

export function stockStateFrom(params: Record<string, string | string[] | undefined>): StockState {
  const one = (k: string) => (Array.isArray(params[k]) ? params[k]?.[0] : params[k]) as string | undefined;
  const offset = Number.parseInt(one("offset") ?? "0", 10);
  return { q: one("q") ?? "", warehouse: one("warehouse") ?? null, short: one("short") === "1", offset: Number.isFinite(offset) && offset > 0 ? offset : 0 };
}

export function stockHref(s: StockState): string {
  const search = new URLSearchParams();
  if (s.q.trim()) search.set("q", s.q.trim());
  if (s.warehouse) search.set("warehouse", s.warehouse);
  if (s.short) search.set("short", "1");
  if (s.offset) search.set("offset", String(s.offset));
  const text = search.toString();
  return text ? `/operations/inventory?${text}` : "/operations/inventory";
}
