import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import { cursorFrom, INBOX_PAGE_SIZE, INBOX_PATH, parseInboxPage, taskIdFrom } from "@/features/inbox/api";
import type { InboxTab } from "@/features/inbox/types";
import { queryKeys } from "@/lib/api/query-keys";
import { serverGetJson } from "@/lib/session/server";
import { InboxScreen } from "./inbox-screen";
import { VIEW_TAB, type InboxView } from "./model";

export type InboxSearchParams = Promise<Record<string, string | string[] | undefined>>;

/**
 * The server half of every Inbox view. It reads the first page with the browser's cookies so the
 * rows are in the HTML, under the same query keys the screen uses. A failed or unreadable answer
 * prefetches nothing; the screen then fetches again and reports what went wrong.
 */
export async function InboxPage({ view, searchParams }: { view: InboxView; searchParams: InboxSearchParams }) {
  const params = await searchParams;
  const cursor = cursorFrom(params.cursor);
  const taskId = taskIdFrom(params.task);

  const queryClient = new QueryClient();
  const prefetch = async (tab: InboxTab, at: string | null) => {
    const query = new URLSearchParams({ tab, limit: String(INBOX_PAGE_SIZE) });
    if (at) query.set("cursor", at);
    const raw = await serverGetJson(`${INBOX_PATH}?${query.toString()}` as `/api/v1/${string}`);
    if (raw === null) return;
    try {
      queryClient.setQueryData(queryKeys.tasks.inbox({ tab, cursor: at }), parseInboxPage(raw));
    } catch {
      // Unreadable: the screen fetches again and reports it.
    }
  };

  // All shows three kinds on its first page; further pages continue the tasks only.
  const wanted: [InboxTab, string | null][] =
    view === "all" && cursor === null ? [["approvals", null], ["conversations", null], ["tasks", null]] : [[VIEW_TAB[view], cursor]];
  await Promise.all(wanted.map(([tab, at]) => prefetch(tab, at)));

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <InboxScreen view={view} cursor={cursor} taskId={taskId} />
    </HydrationBoundary>
  );
}
