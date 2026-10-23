import type { Metadata } from "next";
import { getRoute } from "@/lib/routes";

const route = getRoute("inbox");

export const metadata: Metadata = { title: route.label };

export default function InboxPage() {
  return <h1 className="text-3xl font-bold tracking-tight">{route.label}</h1>;
}
