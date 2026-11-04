import type { Metadata } from "next";
import { BomsScreen } from "@/features/production/master-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-production-boms");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** BOM versions with their approval state. */
export default function Page() {
  return <BomsScreen />;
}
