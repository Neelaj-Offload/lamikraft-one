import type { Metadata } from "next";
import { DelegationScreen } from "../_lib/people";

export const metadata: Metadata = { title: "Delegation · Settings" };

export default function Page() {
  return <DelegationScreen />;
}
