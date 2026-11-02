import type { Metadata } from "next";
import { priceListListHref, priceListListStateFrom } from "@/features/price-lists/list-state";
import { PriceListList } from "@/features/price-lists/price-list-list";
import { getRoute } from "@/lib/routes";

const route = getRoute("products-price-lists");

export const metadata: Metadata = { title: `${route.label} · Products` };

/** Price lists: status, type, currency, scope, search and the page offset all live in the URL. */
export default async function PriceListsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = priceListListStateFrom(await searchParams);
  return <PriceListList key={priceListListHref(state)} state={state} />;
}
