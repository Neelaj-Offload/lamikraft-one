import type { Metadata } from "next";
import { InboxPage, type InboxSearchParams } from "~/screens/inbox/inbox-page";

export const metadata: Metadata = { title: "Approvals · Inbox" };

export default function Page({ searchParams }: { searchParams: InboxSearchParams }) {
  return <InboxPage view="approvals" searchParams={searchParams} />;
}
