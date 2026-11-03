import type { Metadata } from "next";
import { AllItemsView } from "@/features/briefing/all-items-view";
import { getRoute } from "@/lib/routes";

const route = getRoute("today-all");

export const metadata: Metadata = { title: `${route.label} · Today` };

export default function TodayAllPage() {
  return <AllItemsView />;
}
