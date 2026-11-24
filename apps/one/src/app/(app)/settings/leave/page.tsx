import type { Metadata } from "next";
import { Leave } from "~/screens/settings-access/leave";

export const metadata: Metadata = { title: "Leave · Settings" };

/** Your time away, and the leave you approve for others. */
export default function LeavePage() {
  return <Leave />;
}
