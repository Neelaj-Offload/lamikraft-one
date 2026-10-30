import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/api/query-keys";
import { serverGetJson } from "@/lib/session/server";
import { cursorFrom, INBOX_PAGE_SIZE, INBOX_PATH, parseInboxPage, taskIdFrom } from "./api";
import { InboxView } from "./inbox-view";
import type { InboxTab } from "./types";

export type InboxSearchParams = Promise<Record<string, string | string[] | undefined>>;

/**
 * Server part of every Inbox tab route: prefetches the tab's first page with the browser's
 * cookies so rows are in the HTML; the same query key hydrates the client. A failed or
 * unreadable response prefetches nothing, and the client fetches again and reports it.
 */
export async function InboxPage({ tab, searchParams }: { tab: InboxTab; searchParams: InboxSearchParams }) {
  const params = await searchParams;
  const cursor = cursorFrom(params.cursor);
  const taskId = taskIdFrom(params.task);

  const queryClient = new QueryClient();
  const query = new URLSearchParams({ tab, limit: String(INBOX_PAGE_SIZE) });
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
      <InboxView tab={tab} cursor={cursor} taskId={taskId} />
    </HydrationBoundary>
  );
}
