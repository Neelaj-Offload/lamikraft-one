import type { Metadata } from "next";
import { SignOutScreen } from "~/screens/auth/sign-out";

export const metadata: Metadata = { title: "Sign out" };

export default function SignOutPage() {
  return <SignOutScreen />;
}
