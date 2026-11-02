import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { priceListItemsHref, priceListItemsStateFrom } from "@/features/price-lists/list-state";
import { PriceListDetailView } from "@/features/price-lists/price-list-detail";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("products-price-list");

export const metadata: Metadata = { title: `${route.label} · Products` };

/** One price list and its items; the item search, history switch and page offset live in the URL. */
export default async function PriceListPage({
  params,
  searchParams,
}: {
  params: Promise<{ priceListId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { priceListId } = await params;
  if (!UUID_PATTERN.test(priceListId)) notFound();
  const itemsState = priceListItemsStateFrom(await searchParams);
  return <PriceListDetailView key={priceListItemsHref(priceListId, itemsState)} priceListId={priceListId} itemsState={itemsState} />;
}
