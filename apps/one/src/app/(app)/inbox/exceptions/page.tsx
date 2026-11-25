import type { Metadata } from "next";
import { InboxPage, type InboxSearchParams } from "~/screens/inbox/inbox-page";

export const metadata: Metadata = { title: "Exceptions · Inbox" };

export default function Page({ searchParams }: { searchParams: InboxSearchParams }) {
  return <InboxPage view="exceptions" searchParams={searchParams} />;
}
