import type { Metadata } from "next";
import { AreaOverview } from "@/features/areas/area-overview";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations");

export const metadata: Metadata = { title: route.label };

export default function OperationsPage() {
  return <AreaOverview area="operations" />;
}
