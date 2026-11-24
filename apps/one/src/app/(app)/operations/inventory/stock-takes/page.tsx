import type { Metadata } from "next";
import { StockTakes } from "~/screens/stock/stock-takes";

export const metadata: Metadata = { title: "Stock takes · Operations" };

/** Stock takes: freeze, count, submit, approve. */
export default function StockTakesPage() {
  return <StockTakes />;
}
