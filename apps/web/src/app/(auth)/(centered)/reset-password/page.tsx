import type { Metadata } from "next";
import { ResetPasswordForm } from "./reset-form";

export const metadata: Metadata = { title: "Choose a new password", referrer: "no-referrer" };

/** The token arrives in the URL fragment (`/reset-password#t=…`), never in the query string. */
export default function ResetPasswordPage() {
  return <ResetPasswordForm />;
}
