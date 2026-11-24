import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { PlanRecord } from "~/screens/cutting/plan-record";
import { planViewFrom } from "~/screens/cutting/views";

export const metadata: Metadata = { title: "Cut plan · Operations" };

/** A cut plan: overview, pieces and board, offcuts, layout (`?view=`). */
export default async function CutPlanPage({
  params,
  searchParams,
}: {
  params: Promise<{ planId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { planId } = await params;
  if (!UUID_PATTERN.test(planId)) notFound();
  const view = planViewFrom((await searchParams).view);
  return <PlanRecord key={planId} planId={planId} view={view} />;
}
