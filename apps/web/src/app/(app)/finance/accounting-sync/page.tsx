import type { Metadata } from "next";
import { AccountingSyncScreen } from "@/features/finance/finance-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("finance-accounting-sync");

export const metadata: Metadata = { title: `${route.label} · Finance` };

export default function AccountingSyncPage() {
  return <AccountingSyncScreen />;
}
