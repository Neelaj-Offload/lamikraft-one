import type { Metadata } from "next";
import { StockTakesScreen } from "@/features/inventory/document-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-inventory-stock-takes");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Stock takes: freeze, count, submit, approve. */
export default function InventoryStockTakesPage() {
  return <StockTakesScreen />;
}
