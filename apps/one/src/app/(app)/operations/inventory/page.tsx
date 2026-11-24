import type { Metadata } from "next";
import { stockStateFrom } from "@/features/inventory/list-state";
import { StockList } from "~/screens/stock/stock-list";

export const metadata: Metadata = { title: "Stock · Operations" };

/** Stock on hand by product and warehouse: search, warehouse, "short only" and the page offset live in the URL. */
export default async function StockPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = stockStateFrom(await searchParams);
  return <StockList key={`${state.q}|${state.warehouse}|${state.short}|${state.offset}`} state={state} />;
}
