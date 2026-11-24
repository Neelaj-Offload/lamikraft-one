import type { Metadata } from "next";
import { SalesHub } from "~/screens/sales/hub/hub";

export const metadata: Metadata = { title: "Sales" };

/** The sales overview: live numbers, what needs attention, and the way into each sales screen. */
export default function SalesPage() {
  return <SalesHub />;
}
