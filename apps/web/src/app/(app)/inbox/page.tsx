import type { Metadata, Route } from "next";
import { redirect } from "next/navigation";
import { cursorFrom, inboxHref, inboxTabFrom } from "@/features/inbox/api";
import { InboxPage, type InboxSearchParams } from "@/features/inbox/inbox-page";
import { getRoute } from "@/lib/routes";

const route = getRoute("inbox");

export const metadata: Metadata = { title: route.label };

/** Tasks, the default Inbox tab. Earlier `?tab=` links are sent to the tab's own route. */
export default async function InboxTasksPage({ searchParams }: { searchParams: InboxSearchParams }) {
  const params = await searchParams;
  if (params.tab !== undefined) redirect(inboxHref(inboxTabFrom(params.tab), cursorFrom(params.cursor)) as Route);
  return <InboxPage tab="tasks" searchParams={searchParams} />;
}
