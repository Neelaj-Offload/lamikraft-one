import type { Metadata } from "next";
import { StockScreen, stockStateFrom } from "@/features/inventory/stock-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-inventory");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Stock by product and warehouse from the ledger projections; search, warehouse and "short only" live in the URL. */
export default async function InventoryPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <StockScreen state={stockStateFrom(await searchParams)} />;
}
