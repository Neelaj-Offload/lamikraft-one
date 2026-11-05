import type { Metadata } from "next";
import { FinanceHub } from "@/features/finance/finance-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("finance");

export const metadata: Metadata = { title: route.label };

/** The finance hub: server-computed figures per currency, the issue gate explained, invoice suggestions. */
export default function FinancePage() {
  return <FinanceHub />;
}
