import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { priceListItemsStateFrom } from "@/features/price-lists/list-state";
import { UUID_PATTERN } from "@/lib/app-links";
import { PriceListRecord } from "~/screens/products/price-list-record";

export const metadata: Metadata = { title: "Price list · Catalogue" };

/** One price list: its prices, with search, history and the page offset in the URL. */
export default async function PriceListPage({
  params,
  searchParams,
}: {
  params: Promise<{ priceListId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { priceListId } = await params;
  if (!UUID_PATTERN.test(priceListId)) notFound();
  return <PriceListRecord key={priceListId} priceListId={priceListId} items={priceListItemsStateFrom(await searchParams)} />;
}
