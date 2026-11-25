import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { WorkOrderRecord } from "~/screens/production/work-order-record";
import { workOrderViewFrom } from "~/screens/production/views";

export const metadata: Metadata = { title: "Work order · Operations" };

/** A work order: overview, materials, operations and stock postings (`?view=`). */
export default async function WorkOrderPage({
  params,
  searchParams,
}: {
  params: Promise<{ workOrderId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { workOrderId } = await params;
  if (!UUID_PATTERN.test(workOrderId)) notFound();
  const view = workOrderViewFrom((await searchParams).view);
  return <WorkOrderRecord key={workOrderId} workOrderId={workOrderId} view={view} />;
}
