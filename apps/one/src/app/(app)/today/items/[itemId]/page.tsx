import type { Metadata } from "next";
import { ItemScreen } from "~/screens/today/item-screen";

export const metadata: Metadata = { title: "Briefing item · Today" };

export default async function TodayItemPage({ params }: { params: Promise<{ itemId: string }> }) {
  const { itemId } = await params;
  return <ItemScreen key={itemId} issueId={itemId} />;
}
