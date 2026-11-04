import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { WorkCentreScreen } from "@/features/production/master-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-production-work-centre");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** A work centre: calendar, shifts and capacity exceptions. */
export default async function Page({ params }: { params: Promise<{ workCenterId: string }> }) {
  const { workCenterId } = await params;
  if (!UUID_PATTERN.test(workCenterId)) notFound();
  return <WorkCentreScreen key={workCenterId} workCenterId={workCenterId} />;
}
