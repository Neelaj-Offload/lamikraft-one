import type { Metadata } from "next";
import { ResetPasswordScreen } from "~/screens/auth/reset-password";

// The token lives in the URL fragment until the screen strips it; never leak the URL onwards.
export const metadata: Metadata = { title: "Choose a new password", referrer: "no-referrer" };

/** The token arrives in the URL fragment (`/reset-password#t=…`), never in the query string. */
export default function ResetPasswordPage() {
  return <ResetPasswordScreen />;
}
