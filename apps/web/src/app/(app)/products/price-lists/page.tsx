import type { Metadata } from "next";
import { PriceLists } from "@/features/pricing/price-lists";
import { priceListStateFrom } from "@/features/pricing/list-state";
import { getRoute } from "@/lib/routes";

const route = getRoute("products-price-lists");

export const metadata: Metadata = { title: `${route.label} · Products` };

export default async function PriceListsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = priceListStateFrom(await searchParams);
  return <PriceLists key={`${state.q}|${state.status}|${state.offset}`} state={state} />;
}
