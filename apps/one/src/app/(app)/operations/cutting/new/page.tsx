import type { Metadata } from "next";
import { PlanNew } from "~/screens/cutting/plan-new";

export const metadata: Metadata = { title: "New cut plan · Operations" };

/** Start a cut plan: the pieces, then the board. It opens as a draft, where the layout is calculated. */
export default function NewCutPlanPage() {
  return <PlanNew />;
}
