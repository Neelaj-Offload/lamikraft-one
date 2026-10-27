"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Link as RacLink } from "react-aria-components";
import { StatusPill } from "@/components/ui/badge";
import { DataTable, KeysetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDateTime } from "@/components/ui/format";
import { EmptyState, ErrorState, Loading, Stale } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { NavTabs } from "@/components/ui/tabs";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { queryKeys } from "@/lib/api/query-keys";
import { formatDayTime, type ZoneOptions } from "@/lib/format/time";
import { useNow, useSession } from "@/lib/session/context";
import { useUiPoll } from "@/lib/session/use-ui-poll";
import { inboxMessages as m } from "@/messages/inbox";
import { fetchInbox, fetchInboxCounts, inboxHref } from "./api";
import { assigneeLabel, inboxStatus, itemHref } from "./model";
import { TaskDrawer } from "./task-drawer";
import { INBOX_TABS, type InboxCounts, type InboxItem, type InboxPage, type InboxTab } from "./types";

export { assigneeLabel, inboxStatus, itemHref };

export function inboxColumns(now: Date | null, zone: ZoneOptions, userId: string, tab: InboxTab, cursor: string | null): DataTableColumn<InboxItem>[] {
  return [
    {
      id: "item",
      header: m.columns.item,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (item) => item.title,
      cell: (item) => (
        <RacLink href={itemHref(item, tab, cursor)} className={linkClasses}>
          {item.title}
        </RacLink>
      ),
    },
    {
      id: "status",
      header: m.columns.status,
      mobile: "status",
      cell: (item) => {
        const status = inboxStatus(item, now, zone);
        return <StatusPill tone={status.tone}>{status.label}</StatusPill>;
      },
    },
    {
      id: "due",
      header: m.columns.due,
      mobile: "meta",
      cell: (item) =>
        item.due_at && item.due_kind !== "none" ? <LocalDateTime value={item.due_at} /> : <span className="text-ink-muted">{m.noDue}</span>,
    },
    {
      id: "source",
      header: m.columns.source,
      mobile: "key",
      mobileCell: (item) => item.source?.label ?? null,
      cell: (item) =>
        item.source ? (
          item.source.href ? (
            <RacLink href={item.source.href} className={linkClasses}>
              {item.source.label}
            </RacLink>
          ) : (
            item.source.label
          )
        ) : null,
    },
    {
      id: "assignee",
      header: m.columns.assignee,
      cell: (item) => assigneeLabel(item, userId),
    },
  ];
}

/** The Inbox list for one tab: a semantic table, a linked phone list, keyset pages in the URL. */
export function InboxList({ tab, page, cursor }: { tab: InboxTab; page: InboxPage; cursor: string | null }) {
  const { zone, bootstrap } = useSession();
  const now = useNow();
  const tabLabel = m.tabs[tab];
  return (
    <DataTable
      caption={m.caption(tabLabel)}
      hideCaption
      columns={inboxColumns(now, zone, bootstrap.user.id, tab, cursor)}
      rows={page.items}
      rowId={(item) => item.id}
      rowHref={(item) => itemHref(item, tab, cursor)}
      empty={<EmptyState title={m.emptyTitle(tabLabel)}>{m.empty[tab]}</EmptyState>}
      footer={
        <KeysetPagination
          label={`${tabLabel} pages`}
          next={page.next_cursor ? { href: inboxHref(tab, page.next_cursor) } : null}
          first={cursor ? { href: inboxHref(tab) } : null}
        />
      }
    />
  );
}

/** Tab counts: the counts endpoint, else the UI poll, else the bootstrap (never invented). */
export function tabCounts(fetched: InboxCounts | undefined, polled: Partial<Record<string, number>> | null, booted: Partial<Record<string, number>> | null): InboxCounts {
  return fetched ?? (polled as InboxCounts | null) ?? (booted as InboxCounts | null) ?? {};
}

export function InboxView({ tab, cursor, taskId = null }: { tab: InboxTab; cursor: string | null; taskId?: string | null }) {
  const { bootstrap, zone } = useSession();
  const now = useNow();
  const router = useRouter();
  const query = useQuery({
    queryKey: queryKeys.tasks.inbox({ tab, cursor }),
    queryFn: ({ signal }) => fetchInbox(tab, cursor, signal),
  });
  const countsQuery = useQuery({ queryKey: queryKeys.tasks.counts(), queryFn: ({ signal }) => fetchInboxCounts(signal) });
  const poll = useUiPoll();

  const pollTabs = poll.data?.inbox_counts.status === "ok" ? poll.data.inbox_counts.value.tabs : null;
  const bootTabs = bootstrap.inbox_counts.status === "ok" ? bootstrap.inbox_counts.value.tabs : null;
  const counts = tabCounts(countsQuery.data, pollTabs, bootTabs);

  useScreenContribution(
    query.data
      ? {
          lists: [
            {
              key: `inbox_${tab}`,
              rows: query.data.items.map((item, index) => ({ type: "tasks.task", id: item.id, version: item.version, ordinal: index + 1 })),
            },
          ],
          selectedIds: taskId ? [taskId] : [],
          filters: { tab },
        }
      : null,
  );

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.title}</h1>
        <p className="text-ink-muted">{m.intro}</p>
      </header>
      <NavTabs
        label={m.tabsLabel}
        currentId={tab}
        locale={zone.locale}
        tabs={INBOX_TABS.map((id) => ({ id, label: m.tabs[id], href: inboxHref(id), count: counts[id] ?? null }))}
      />
      {query.isPending ? (
        <Loading label={`${m.tabs[tab].toLowerCase()} in your Inbox`} />
      ) : query.data ? (
        <>
          {query.isError ? (
            // A background refresh failed; the rows shown are from the last successful load.
            <Stale
              asOf={formatDayTime(new Date(query.dataUpdatedAt).toISOString().replace(/\.\d{3}Z$/, "Z"), now ?? new Date(), zone) ?? ""}
              onRefresh={() => void query.refetch()}
            />
          ) : null}
          <InboxList tab={tab} page={query.data} cursor={cursor} />
        </>
      ) : (
        <ErrorState error={query.error} what="the Inbox" onRetry={() => void query.refetch()} />
      )}
      <TaskDrawer taskId={taskId} onClose={() => router.push(inboxHref(tab, cursor) as Parameters<typeof router.push>[0])} />
    </div>
  );
}
