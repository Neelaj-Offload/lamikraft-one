import type { Metadata } from "next";
import { InviteScreen } from "../../_lib/users";

export const metadata: Metadata = { title: "Invite someone · Settings" };

export default function InvitePage() {
  return <InviteScreen />;
}
