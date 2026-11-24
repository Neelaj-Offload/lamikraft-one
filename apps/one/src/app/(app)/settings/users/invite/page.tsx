import type { Metadata } from "next";
import { UserInvite } from "~/screens/settings-access/user-invite";

export const metadata: Metadata = { title: "Invite someone · Settings" };

/** Invite one person: who they are, then the roles they start with. */
export default function InvitePage() {
  return <UserInvite />;
}
