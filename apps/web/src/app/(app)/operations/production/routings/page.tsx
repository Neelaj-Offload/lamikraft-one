import type { Metadata } from "next";
import { RoutingsScreen } from "@/features/production/master-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-production-routings");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Routing versions with their approval state. */
export default function Page() {
  return <RoutingsScreen />;
}
