import type { Metadata } from "next";
import { InviteScreen } from "~/screens/auth/invite";

// The token lives in the URL fragment until the screen strips it; never leak the URL onwards.
export const metadata: Metadata = { title: "Accept your invitation", referrer: "no-referrer" };

/** The token arrives in the URL fragment (`/invite#t=…`): the screen reads it, removes it and posts it. */
export default function InvitePage() {
  return <InviteScreen />;
}
