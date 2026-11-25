/** URL <-> the stock-by-category view. Plain module: the server page parses with it, the client screen builds links. */

import { CATEGORY_PAGE_SIZE, type Market, type StockCategory } from "~/data/stock-categories";

const CATEGORIES: readonly StockCategory[] = ["inventory", "sample", "exhibition"];

export interface CategoryState {
  q: string;
  warehouse: string | null;
  market: Market | null;
  category: StockCategory | null;
  offset: number;
}

type Search = Record<string, string | string[] | undefined>;
const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

export function categoryStateFrom(search: Search): CategoryState {
  const rawOffset = Number.parseInt(first(search.offset) ?? "0", 10);
  const warehouse = first(search.warehouse) ?? "";
  return {
    q: (first(search.q) ?? "").slice(0, 200),
    warehouse: /^[0-9a-f-]{36}$/i.test(warehouse) ? warehouse : null,
    market: (["domestic", "export"] as const).find((m) => m === first(search.market)) ?? null,
    category: CATEGORIES.find((c) => c === first(search.category)) ?? null,
    offset: Number.isFinite(rawOffset) && rawOffset > 0 ? rawOffset - (rawOffset % CATEGORY_PAGE_SIZE) : 0,
  };
}

export function categoryHref(state: Partial<CategoryState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.warehouse) query.set("warehouse", state.warehouse);
  if (state.market) query.set("market", state.market);
  if (state.category) query.set("category", state.category);
  if (state.offset) query.set("offset", String(state.offset));
  const s = query.toString();
  return s ? `/operations/inventory/categories?${s}` : "/operations/inventory/categories";
}

