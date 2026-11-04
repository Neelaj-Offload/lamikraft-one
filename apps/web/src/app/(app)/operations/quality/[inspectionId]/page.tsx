import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { InspectionScreen } from "@/features/quality/inspection-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-quality-inspection");

export const metadata: Metadata = { title: `${route.label} · Operations` };

export default async function Page({ params }: { params: Promise<{ inspectionId: string }> }) {
  const { inspectionId } = await params;
  if (!UUID_PATTERN.test(inspectionId)) notFound();
  return <InspectionScreen key={inspectionId} inspectionId={inspectionId} />;
}
