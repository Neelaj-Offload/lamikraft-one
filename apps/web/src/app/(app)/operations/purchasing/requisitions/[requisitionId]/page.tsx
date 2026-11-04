import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { RequisitionScreen } from "@/features/procurement/requisition-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-purchasing-requisition");

export const metadata: Metadata = { title: `${route.label} · Operations` };

export default async function Page({ params }: { params: Promise<{ requisitionId: string }> }) {
  const { requisitionId } = await params;
  if (!UUID_PATTERN.test(requisitionId)) notFound();
  return <RequisitionScreen key={requisitionId} requisitionId={requisitionId} />;
}
