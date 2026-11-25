import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { InspectionRecord } from "~/screens/quality/inspection-record";

export const metadata: Metadata = { title: "Inspection · Operations" };

/** One quality inspection: what is held and its result. */
export default async function InspectionPage({ params }: { params: Promise<{ inspectionId: string }> }) {
  const { inspectionId } = await params;
  if (!UUID_PATTERN.test(inspectionId)) notFound();
  return <InspectionRecord key={inspectionId} inspectionId={inspectionId} />;
}
