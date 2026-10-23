import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import type { Metadata } from "next";
import { cursorFrom, inboxTabFrom, INBOX_PATH, parseInboxPage } from "@/features/inbox/api";
import { InboxView } from "@/features/inbox/inbox-view";
import { queryKeys } from "@/lib/api/query-keys";
import { getRoute } from "@/lib/routes";
import { serverGetJson } from "@/lib/session/server";

const route = getRoute("inbox");

export const metadata: Metadata = { title: route.label };

export default async function InboxPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const tab = inboxTabFrom(params.tab);
  const cursor = cursorFrom(params.cursor);

  const queryClient = new QueryClient();
  const query = new URLSearchParams({ tab });
  if (cursor) query.set("cursor", cursor);
  const raw = await serverGetJson(`${INBOX_PATH}?${query.toString()}` as `/api/v1/${string}`);
  if (raw !== null) {
    try {
      queryClient.setQueryData(queryKeys.tasks.inbox({ tab, cursor }), parseInboxPage(raw));
    } catch {
      // Unreadable: the client fetches again and reports it.
    }
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <InboxView tab={tab} cursor={cursor} />
    </HydrationBoundary>
  );
}
