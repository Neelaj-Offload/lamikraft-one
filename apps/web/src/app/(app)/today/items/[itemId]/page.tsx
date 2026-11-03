import type { Metadata } from "next";
import { ItemPageView } from "@/features/briefing/item-page-view";
import { getRoute } from "@/lib/routes";

const route = getRoute("today-item");

export const metadata: Metadata = { title: `${route.label} · Today` };

export default async function TodayItemPage({ params }: { params: Promise<{ itemId: string }> }) {
  const { itemId } = await params;
  return <ItemPageView key={itemId} issueId={itemId} />;
}
