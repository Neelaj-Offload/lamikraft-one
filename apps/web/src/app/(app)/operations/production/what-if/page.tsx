import type { Metadata } from "next";
import { WhatIfScreen } from "@/features/production/what-if";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-production-what-if");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Read-only production simulation: baseline vs a stock or capacity change (nothing is reserved, posted or saved). */
export default function Page() {
  return <WhatIfScreen />;
}
