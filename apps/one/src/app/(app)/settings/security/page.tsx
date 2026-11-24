import type { Metadata } from "next";
import { Security } from "~/screens/settings-access/security";

export const metadata: Metadata = { title: "Security · Settings" };

/** Your password, two-step sign-in (authenticator app, recovery codes) and sessions. */
export default function SecurityPage() {
  return <Security />;
}
