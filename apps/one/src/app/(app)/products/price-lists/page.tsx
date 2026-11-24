import type { Metadata } from "next";
import { priceListListStateFrom } from "@/features/price-lists/list-state";
import { PriceLists } from "~/screens/products/price-lists";

export const metadata: Metadata = { title: "Price lists · Catalogue" };

/** Price lists: status, kind, currency, scope, search and the page offset all live in the URL. */
export default async function PriceListsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <PriceLists state={priceListListStateFrom(await searchParams)} />;
}
