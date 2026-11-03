import type { Metadata } from "next";
import { AccessRequestsScreen } from "../_lib/people";

export const metadata: Metadata = { title: "Access requests · Settings" };

export default function Page() {
  return <AccessRequestsScreen />;
}
