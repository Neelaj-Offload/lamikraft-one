import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PlanWorkspace } from "@/features/cutting/plan-editor";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-cutting-plan");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** A saved cut plan: inputs, the stored latest layout with the board canvas, exports and commands. */
export default async function CutPlanPage({ params }: { params: Promise<{ planId: string }> }) {
  const { planId } = await params;
  if (!UUID_PATTERN.test(planId)) notFound();
  return <PlanWorkspace key={planId} planId={planId} />;
}
