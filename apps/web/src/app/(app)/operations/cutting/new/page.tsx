import type { Metadata } from "next";
import { NewPlan } from "@/features/cutting/plan-editor";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-cutting-new");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** A new cut plan: three blank rows and the company's board defaults until the first save. */
export default function NewCutPlanPage() {
  return <NewPlan />;
}
