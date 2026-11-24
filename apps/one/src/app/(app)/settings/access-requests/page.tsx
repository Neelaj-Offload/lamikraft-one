import type { Metadata } from "next";
import { AccessRequests } from "~/screens/settings-access/access-requests";

export const metadata: Metadata = { title: "Access requests · Settings" };

/** Ask for a permission for a while; approvers decide here too. */
export default function AccessRequestsPage() {
  return <AccessRequests />;
}
