import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { MarketplaceChannel } from "~/screens/sales/marketplaces/channel";

export const metadata: Metadata = { title: "Marketplace" };

export default async function MarketplacePage({ params }: { params: Promise<{ channelId: string }> }) {
  const { channelId } = await params;
  if (!UUID_PATTERN.test(channelId)) notFound();
  return <MarketplaceChannel key={channelId} channelId={channelId} />;
}
