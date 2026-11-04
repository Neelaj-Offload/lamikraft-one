import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { WorkOrderScreen } from "@/features/production/work-order-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-production-work-order");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** A work order: materials, operations, postings and its actions. */
export default async function Page({ params }: { params: Promise<{ workOrderId: string }> }) {
  const { workOrderId } = await params;
  if (!UUID_PATTERN.test(workOrderId)) notFound();
  return <WorkOrderScreen key={workOrderId} workOrderId={workOrderId} />;
}
