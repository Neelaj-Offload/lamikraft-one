import type { Metadata } from "next";
import { DemoSignInScreen } from "~/screens/auth/demo-sign-in";

// The token lives in the URL fragment until the screen strips it; never leak the URL onwards.
export const metadata: Metadata = { title: "Demo sign-in", referrer: "no-referrer" };

export default function DemoSignInPage() {
  return <DemoSignInScreen />;
}
