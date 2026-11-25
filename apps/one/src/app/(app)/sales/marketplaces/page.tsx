import type { Metadata } from "next";
import { MarketplaceChannels } from "~/screens/sales/marketplaces/channels";

export const metadata: Metadata = { title: "Marketplaces" };

export default function MarketplacesPage() {
  return <MarketplaceChannels />;
}
