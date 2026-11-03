import type { Metadata } from "next";
import { QuoteSettingsPage } from "@/features/sales/quote-settings";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-quotes");

export const metadata: Metadata = { title: `${route.label} · Settings` };

export default function QuoteSettingsRoute() {
  return <QuoteSettingsPage />;
}
