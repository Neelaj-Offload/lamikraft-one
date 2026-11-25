import type { Metadata } from "next";
import { Delegation } from "~/screens/settings-access/delegation";

export const metadata: Metadata = { title: "Delegation · Settings" };

/** Let a colleague reach your records while you are away. */
export default function DelegationPage() {
  return <Delegation />;
}
