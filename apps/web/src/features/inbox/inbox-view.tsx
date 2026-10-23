"use client";

import { useQuery } from "@tanstack/react-query";
import { Link as RacLink } from "react-aria-components";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { DataTable, KeysetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDateTime, RelativeTime } from "@/components/ui/format";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { NavTabs } from "@/components/ui/tabs";
import { queryKeys } from "@/lib/api/query-keys";
import { cx } from "@/lib/cx";
import { formatDayTime, type ZoneOptions } from "@/lib/format/time";
import { useNow, useSession } from "@/lib/session/context";
import { useUiPoll } from "@/lib/session/use-ui-poll";
import { inboxMessages as m } from "@/messages/inbox";
import { fetchInbox, inboxHref } from "./api";
import { INBOX_TABS, type InboxItem, type InboxPage, type InboxTab } from "./types";

export function inboxStatus(item: InboxItem, now: Date | null, zone: ZoneOptions): { label: string; tone: Tone } {
  if (item.snoozed_until && (item.state === "open" || item.state === "in_progress")) {
    const until = now ? formatDayTime(item.snoozed_until, now, zone) : null;
    return { label: until ? `${m.state.snoozed} · ${until}` : m.state.snoozed, tone: "neutral" };
  }
  if (item.overdue && (item.state === "open" || item.state === "in_progress")) return { label: m.state.overdue, tone: "danger" };
  const tones: Record<InboxItem["state"], Tone> = {
    open: "info",
    in_progress: "forest",
    done: "success",
    dismissed: "neutral",
    cancelled: "neutral",
    expired: "warning",
  };
  return { label: m.state[item.state], tone: tones[item.state] };
}

export function inboxColumns(now: Date | null, zone: ZoneOptions): DataTableColumn<InboxItem>[] {
  return [
    {
      id: "item",
      header: m.columns.item,
      isRowHeader: true,
      mobile: "title",
      cell: (item) => (
        <span className="flex flex-col gap-0.5">
          {item.href ? (
            <RacLink href={item.href} className={cx(linkClasses, "max-md:no-underline max-md:text-ink")}>
              {item.title}
            </RacLink>
          ) : (
            <span>{item.title}</span>
          )}
          {item.summary ? <span className="font-normal text-ink-muted">{item.summary}</span> : null}
        </span>
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
      cell: (item) => (
        <span>
          {item.assignee?.display_name ?? <span className="text-ink-muted">{m.unassigned}</span>}
          {item.on_behalf_of ? <span className="text-ink-muted"> {m.forPerson(item.on_behalf_of.display_name)}</span> : null}
        </span>
      ),
    },
    {
      id: "updated",
      header: m.columns.updated,
      cell: (item) => (item.updated_at ? <RelativeTime value={item.updated_at} className="text-ink-muted" /> : null),
    },
  ];
}

/** The Inbox list for one tab: a semantic table, a linked phone list, keyset pages in the URL. */
export function InboxList({ tab, page, cursor }: { tab: InboxTab; page: InboxPage; cursor: string | null }) {
  const { zone } = useSession();
  const now = useNow();
  const tabLabel = m.tabs[tab];
  return (
    <DataTable
      caption={m.caption(tabLabel)}
      hideCaption
      columns={inboxColumns(now, zone)}
      rows={page.items}
      rowId={(item) => item.id}
      rowHref={(item) => item.href ?? item.source?.href ?? null}
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

export function InboxView({ tab, cursor }: { tab: InboxTab; cursor: string | null }) {
  const { bootstrap, zone } = useSession();
  const query = useQuery({
    queryKey: queryKeys.tasks.inbox({ tab, cursor }),
    queryFn: ({ signal }) => fetchInbox(tab, cursor, signal),
  });
  const poll = useUiPoll();

  const pollTabs = poll.data?.inbox_counts.status === "ok" ? poll.data.inbox_counts.value.tabs : null;
  const bootTabs = bootstrap.inbox_counts.status === "ok" ? bootstrap.inbox_counts.value.tabs : null;
  const counts = query.data?.counts ?? pollTabs ?? bootTabs ?? {};

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
        tabs={INBOX_TABS.map((id) => ({
          id,
          label: m.tabs[id],
          href: inboxHref(id),
          // Done has no meaningful open count; other tabs show the server's number when known.
          count: id === "done" ? null : (counts[id] ?? null),
        }))}
      />
      {query.isPending ? (
        <Loading label={`${m.tabs[tab].toLowerCase()} in your Inbox`} />
      ) : query.isError ? (
        <ErrorState error={query.error} what="the Inbox" onRetry={() => void query.refetch()} />
      ) : (
        <InboxList tab={tab} page={query.data} cursor={cursor} />
      )}
    </div>
  );
}
