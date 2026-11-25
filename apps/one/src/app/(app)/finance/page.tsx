import type { Metadata } from "next";
import { FinanceHub } from "~/screens/finance/hub";

export const metadata: Metadata = { title: "Finance" };

/** The finance overview: the counts that matter, what needs attention, deliveries to invoice, what is owed. */
export default function FinancePage() {
  return <FinanceHub />;
}
