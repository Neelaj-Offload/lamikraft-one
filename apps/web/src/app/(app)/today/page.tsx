import type { Metadata } from "next";
import { getRoute } from "@/lib/routes";

const route = getRoute("today");

export const metadata: Metadata = { title: route.label };

export default function TodayPage() {
  return <h1 className="text-3xl font-bold tracking-tight">{route.label}</h1>;
}
