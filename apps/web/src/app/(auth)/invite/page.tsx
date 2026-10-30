import type { Metadata } from "next";
import { InviteAcceptForm } from "./invite-form";

export const metadata: Metadata = { title: "Accept your invitation", referrer: "no-referrer" };

/** The token arrives in the URL fragment (`/invite#t=…`): the page reads it, removes it and posts it. */
export default function InvitePage() {
  return <InviteAcceptForm />;
}
