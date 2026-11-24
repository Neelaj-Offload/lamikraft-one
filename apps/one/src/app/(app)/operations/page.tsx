import type { Metadata } from "next";
import { OperationsHub } from "~/screens/operations-hub/hub";

export const metadata: Metadata = { title: "Operations" };

/** The operations overview: the numbers that matter, what needs attention, and the way into each screen. */
export default function OperationsPage() {
  return <OperationsHub />;
}
