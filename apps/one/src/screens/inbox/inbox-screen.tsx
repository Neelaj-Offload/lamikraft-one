"use client";

import type { Route } from "next";
import type { ReactNode } from "react";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import type { InboxItem, InboxPage } from "@/features/inbox/types";
import { formatDayTime } from "@/lib/format/time";
import { canAccessRoute, matchRoute } from "@/lib/routes";
import { useNow, useSession } from "@/lib/session/context";
import { useInboxCounts, useInboxList } from "~/data/inbox";
import { Page, PageHeader, PageSection } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, Banner, Button, ButtonLink, EmptyState, GlassPanel, Icon, Tabs, TextLink } from "~/ui";
import { InboxRows, InboxRowsSkeleton } from "./inbox-rows";
import { EMPTY, INBOX_VIEWS, VIEW_LABEL, VIEW_LEAD, VIEW_TAB, viewCount, viewHref, type InboxView } from "./model";
import { TaskDrawer } from "./task-drawer";

interface ListQuery {
  data: InboxPage | undefined;
  error: unknown;
  isPending: boolean;
  isError: boolean;
  dataUpdatedAt: number;
  refetch: () => unknown;
}

/**
 * The Inbox: triage. One header, the four views as tabs with live counts, then the list for the
 * view in the URL. `?cursor=` pages a list; `?task=` opens one item in place.
 */
export function InboxScreen({ view, cursor, taskId }: { view: InboxView; cursor: string | null; taskId: string | null }) {
  const counts = useInboxCounts();

  return (
    <Page>
      <PageHeader display title="Inbox" lead={VIEW_LEAD[view]} />
      <Tabs
        label="Inbox views"
        selectedKey={view}
        tabs={INBOX_VIEWS.map((id) => ({ id, label: VIEW_LABEL[id], href: viewHref(id), count: viewCount(id, counts) }))}
      />
      {view === "all" ? <AllView cursor={cursor} taskId={taskId} /> : <KindView view={view} cursor={cursor} taskId={taskId} />}
      <TaskDrawer taskId={taskId} closeHref={viewHref(view, cursor)} />
    </Page>
  );
}

/** Tells the assistant which rows are on screen, as the old Inbox did. */
function useInboxContribution(key: string, items: readonly InboxItem[] | undefined, taskId: string | null, filter: string) {
  useScreenContribution(
    items
      ? {
          lists: [{ key, rows: items.map((item, index) => ({ type: "tasks.task", id: item.id, version: item.version, ordinal: index + 1 })) }],
          selectedIds: taskId ? [taskId] : [],
          filters: { tab: filter },
        }
      : null,
  );
}

/** A background refresh failed: the rows are real, but from the last load that worked. */
function StaleNote({ query }: { query: ListQuery }) {
  const { zone } = useSession();
  const now = useNow();
  if (!query.isError || !query.data) return null;
  const at = formatDayTime(new Date(query.dataUpdatedAt).toISOString().replace(/\.\d{3}Z$/, "Z"), now ?? new Date(), zone);
  return (
    <Banner
      tone="amber"
      title="This list may be out of date."
      action={
        <Button variant="secondary" size="sm" iconLeft="refresh" onPress={() => void query.refetch()}>
          Refresh
        </Button>
      }
    >
      {at ? `It last loaded ${at}; the newest version could not be fetched.` : "The newest version could not be fetched."}
    </Banner>
  );
}

function EmptyPanel({ view, action }: { view: InboxView; action?: ReactNode }) {
  const empty = EMPTY[view];
  return (
    <GlassPanel padding="lg" className="rise">
      <EmptyState icon={empty.icon} title={empty.title} text={empty.text} actions={action} />
    </GlassPanel>
  );
}

/** One kind of work: approvals, exceptions or conversations. */
function KindView({ view, cursor, taskId }: { view: Exclude<InboxView, "all">; cursor: string | null; taskId: string | null }) {
  const { permissionKeys } = useSession();
  const query = useInboxList(VIEW_TAB[view], cursor);
  useInboxContribution(`inbox_${VIEW_TAB[view]}`, query.data?.items, taskId, VIEW_TAB[view]);

  if (query.isPending) return <InboxRowsSkeleton label={`Loading ${VIEW_LABEL[view].toLowerCase()}`} />;
  if (!query.data) return <ErrorBlock error={query.error} what={VIEW_LABEL[view]} onRetry={() => void query.refetch()} />;

  if (query.data.items.length === 0) {
    const messagesRoute = matchRoute("/sales/customer-messages");
    const action = cursor ? (
      <ButtonLink href={viewHref(view)} variant="secondary" iconLeft="arrowLeft">
        Back to the start
      </ButtonLink>
    ) : view === "conversations" && messagesRoute && canAccessRoute(messagesRoute, permissionKeys) ? (
      <ButtonLink href={"/sales/customer-messages" as Route} variant="secondary" iconRight="arrowRight">
        See every customer message
      </ButtonLink>
    ) : (
      <ButtonLink href="/today" variant="secondary" iconRight="arrowRight">
        Go to Today
      </ButtonLink>
    );
    return (
      <>
        <StaleNote query={query} />
        <EmptyPanel view={view} action={action} />
      </>
    );
  }

  return (
    <>
      <StaleNote query={query} />
      <InboxRows
        label={`${VIEW_LABEL[view]} waiting on you`}
        items={query.data.items}
        view={view}
        cursor={cursor}
        nextCursor={query.data.next_cursor}
        showKind={view === "exceptions"}
        selectedId={taskId}
      />
    </>
  );
}

const GROUPS = [
  { view: "approvals", title: "To decide", more: "All approvals" },
  { view: "conversations", title: "To answer", more: "All conversations" },
] as const;

/**
 * Everything waiting on this person, the most blocking kind first: decisions other people are
 * waiting for, then customers, then the person's own tasks. Approvals and conversations show
 * their first page here and link to their own view for the rest; tasks page in place. Past the
 * first page (`?cursor=`) only the tasks continue.
 */
function AllView({ cursor, taskId }: { cursor: string | null; taskId: string | null }) {
  const firstPage = cursor === null;
  const approvals = useInboxList("approvals", null, firstPage);
  const conversations = useInboxList("conversations", null, firstPage);
  const tasks = useInboxList("tasks", cursor);
  const groups = { approvals, conversations } as const;

  const shown = [...(firstPage ? [...(approvals.data?.items ?? []), ...(conversations.data?.items ?? [])] : []), ...(tasks.data?.items ?? [])];
  useInboxContribution("inbox_tasks", tasks.data ? shown : undefined, taskId, "tasks");

  const loading = tasks.isPending || (firstPage && (approvals.isPending || conversations.isPending));
  if (loading) return <InboxRowsSkeleton label="Loading your inbox" />;

  const failed = firstPage ? [approvals, conversations, tasks].filter((query) => !query.data) : [tasks].filter((query) => !query.data);
  const nothing = failed.length === 0 && shown.length === 0;

  if (nothing) {
    return (
      <EmptyPanel
        view="all"
        action={
          cursor ? (
            <ButtonLink href={viewHref("all")} variant="secondary" iconLeft="arrowLeft">
              Back to the start
            </ButtonLink>
          ) : (
            <ButtonLink href="/today" variant="secondary" iconRight="arrowRight">
              Go to Today
            </ButtonLink>
          )
        }
      />
    );
  }

  // Say what is clear too: an empty kind is information when triaging.
  const clear = firstPage
    ? [
        approvals.data?.items.length === 0 ? "decisions" : null,
        conversations.data?.items.length === 0 ? "customer replies" : null,
        tasks.data?.items.length === 0 ? "tasks" : null,
      ].filter((kind): kind is string => kind !== null)
    : [];

  return (
    <>
      {firstPage
        ? GROUPS.map((group, index) => {
            const query = groups[group.view];
            if (!query.data) {
              return (
                <PageSection key={group.view} title={group.title} index={index}>
                  <ErrorBlock error={query.error} what={VIEW_LABEL[group.view]} onRetry={() => void query.refetch()} />
                </PageSection>
              );
            }
            if (query.data.items.length === 0) return null;
            return (
              <PageSection
                key={group.view}
                index={index}
                title={<GroupTitle title={group.title} count={query.data.next_cursor ? null : query.data.items.length} />}
                action={query.data.next_cursor ? <TextLink href={viewHref(group.view)}>{group.more}</TextLink> : undefined}
              >
                <StaleNote query={query} />
                <InboxRows label={`${VIEW_LABEL[group.view]} waiting on you`} items={query.data.items} view="all" cursor={null} selectedId={taskId} />
              </PageSection>
            );
          })
        : null}

      {!tasks.data ? (
        <PageSection title="To do" index={2}>
          <ErrorBlock error={tasks.error} what="Your tasks" onRetry={() => void tasks.refetch()} />
        </PageSection>
      ) : tasks.data.items.length > 0 ? (
        <PageSection index={2} title={<GroupTitle title="To do" count={cursor || tasks.data.next_cursor ? null : tasks.data.items.length} />}>
          <StaleNote query={tasks} />
          <InboxRows label="Tasks waiting on you" items={tasks.data.items} view="all" cursor={cursor} nextCursor={tasks.data.next_cursor} selectedId={taskId} />
        </PageSection>
      ) : null}

      {clear.length > 0 ? (
        <p className="t-body-sm text-ink-3 rise-plain flex items-center gap-2 px-1">
          <Icon name="checkCircle" size={16} aria-hidden="true" />
          No {clear.join(" or ")} are waiting on you.
        </p>
      ) : null}
    </>
  );
}

/** A group heading with how many it holds; the count is left out when the list runs past one page. */
function GroupTitle({ title, count }: { title: string; count: number | null }) {
  return (
    <span className="flex items-center gap-2">
      {title}
      {count === null ? null : (
        <Badge size="sm" className="lk-tnum">
          {count}
        </Badge>
      )}
    </span>
  );
}
