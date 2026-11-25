import type { Metadata, Route } from "next";
import { redirect } from "next/navigation";
import { cursorFrom, inboxHref, inboxTabFrom } from "@/features/inbox/api";
import { InboxPage, type InboxSearchParams } from "~/screens/inbox/inbox-page";

export const metadata: Metadata = { title: "Inbox" };

/** Everything waiting on this person. Earlier `?tab=` links go to the view's own URL. */
export default async function Page({ searchParams }: { searchParams: InboxSearchParams }) {
  const params = await searchParams;
  if (params.tab !== undefined) redirect(inboxHref(inboxTabFrom(params.tab), cursorFrom(params.cursor)) as Route);
  return <InboxPage view="all" searchParams={searchParams} />;
}
