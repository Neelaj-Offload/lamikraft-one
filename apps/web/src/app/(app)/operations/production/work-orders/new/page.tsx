import type { Metadata } from "next";
import { NewWorkOrderScreen } from "@/features/production/work-order-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-production-work-order-new");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Plan a work order for a product with an approved BOM and routing. */
export default function Page() {
  return <NewWorkOrderScreen />;
}
