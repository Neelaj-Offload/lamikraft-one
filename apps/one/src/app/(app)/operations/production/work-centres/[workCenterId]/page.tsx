import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { WorkCentreRecord } from "~/screens/production/work-centre-record";

export const metadata: Metadata = { title: "Work centre · Operations" };

/** A work centre: its calendar, shifts and the days with their own capacity. */
export default async function WorkCentrePage({ params }: { params: Promise<{ workCenterId: string }> }) {
  const { workCenterId } = await params;
  if (!UUID_PATTERN.test(workCenterId)) notFound();
  return <WorkCentreRecord key={workCenterId} workCenterId={workCenterId} />;
}
