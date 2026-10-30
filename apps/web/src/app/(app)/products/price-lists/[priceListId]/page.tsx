import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PriceListView } from "@/features/pricing/price-lists";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("products-price-list");

export const metadata: Metadata = { title: `${route.label} · Products` };

/** A price list: its prices, draft edits, changes from a date with history, activation and retirement. */
export default async function PriceListPage({ params }: { params: Promise<{ priceListId: string }> }) {
  const { priceListId } = await params;
  if (!UUID_PATTERN.test(priceListId)) notFound();
  return <PriceListView key={priceListId} priceListId={priceListId} />;
}
