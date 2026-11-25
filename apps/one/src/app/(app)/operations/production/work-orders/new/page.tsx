import type { Metadata } from "next";
import { WorkOrderNew } from "~/screens/production/work-order-new";

export const metadata: Metadata = { title: "Plan a work order · Operations" };

/** Plan a work order for a product with an approved bill of materials and routing. */
export default function NewWorkOrderPage() {
  return <WorkOrderNew />;
}
