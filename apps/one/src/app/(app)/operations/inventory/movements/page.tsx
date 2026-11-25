import type { Metadata } from "next";
import { offsetFrom } from "~/screens/stock/labels";
import { Movements } from "~/screens/stock/movements";

export const metadata: Metadata = { title: "Stock movements · Operations" };

/** The stock ledger, newest first; the page offset lives in the URL. */
export default async function StockMovementsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <Movements offset={offsetFrom((await searchParams).offset)} />;
}
