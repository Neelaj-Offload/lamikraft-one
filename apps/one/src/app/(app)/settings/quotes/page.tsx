import type { Metadata } from "next";
import { QuotationSettings } from "~/screens/settings-data/quotes";

export const metadata: Metadata = { title: "Quotations · Settings" };

export default function QuotationSettingsPage() {
  return <QuotationSettings />;
}
