import type { Metadata } from "next";
import { ExceptionsScreen } from "@/features/finance/finance-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("finance-exceptions");

export const metadata: Metadata = { title: `${route.label} · Finance` };

export default function ExceptionsPage() {
  return <ExceptionsScreen />;
}
