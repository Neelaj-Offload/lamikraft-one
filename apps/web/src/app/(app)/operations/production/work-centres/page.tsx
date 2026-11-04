import type { Metadata } from "next";
import { WorkCentresScreen } from "@/features/production/master-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-production-work-centres");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Work centres and their standard daily capacity. */
export default function Page() {
  return <WorkCentresScreen />;
}
