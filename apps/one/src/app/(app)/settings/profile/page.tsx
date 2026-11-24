import type { Metadata } from "next";
import { Profile } from "~/screens/settings-access/profile";

export const metadata: Metadata = { title: "Profile · Settings" };

/** Your account, how Lamikraft One behaves for you, and this sign-in. */
export default function ProfilePage() {
  return <Profile />;
}
