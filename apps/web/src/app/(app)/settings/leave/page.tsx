import type { Metadata } from "next";
import { LeaveScreen } from "../_lib/people";

export const metadata: Metadata = { title: "Leave · Settings" };

export default function Page() {
  return <LeaveScreen />;
}
