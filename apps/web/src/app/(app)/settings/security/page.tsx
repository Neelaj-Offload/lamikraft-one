import type { Metadata } from "next";
import { SecurityScreen } from "../_lib/security";

export const metadata: Metadata = { title: "Security · Settings" };

/** Your password, two-step sign-in (authenticator app, recovery codes) and sessions. */
export default function SecurityPage() {
  return <SecurityScreen />;
}
