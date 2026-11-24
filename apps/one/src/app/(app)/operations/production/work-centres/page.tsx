import type { Metadata } from "next";
import { WorkCentreList } from "~/screens/production/work-centre-list";

export const metadata: Metadata = { title: "Work centres · Operations" };

/** Work centres: machines, efficiency, the standard day and the rate. */
export default function WorkCentresPage() {
  return <WorkCentreList />;
}
