"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Link as RacLink } from "react-aria-components";
import { Button } from "@/components/ui/button";
import { LocalDateTime, RelativeTime } from "@/components/ui/format";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { safeAppPath } from "@/lib/safe-path";
import { fetchActivity, type ActivityItem } from "./api";

/** One line of activity: who, what, on which record (a link only to an in-app path). */
export function ActivityLine({ item, showRecord }: { item: ActivityItem; showRecord: boolean }) {
  const path = safeAppPath(item.path);
  const record = item.resource_label ?? item.resource_type.split(".").pop()?.replace(/_/g, " ") ?? "record";
  return (
    <li className="flex flex-col gap-0.5 px-4 py-2">
      <span>
        <span className="font-medium">{item.actor_name ?? "Someone"}</span> · {item.summary}
        {showRecord ? (
          <>
            {" · "}
            {path ? (
              <RacLink href={path} className={linkClasses}>
                {record}
              </RacLink>
            ) : (
              record
            )}
          </>
        ) : null}
      </span>
      <span className="text-sm text-ink-muted">
        <RelativeTime value={item.occurred_at} /> (<LocalDateTime value={item.occurred_at} />)
        {item.changed_fields.length ? ` · changed ${item.changed_fields.join(", ")}` : ""}
      </span>
    </li>
  );
}

function useActivity(resourceType: string | null, resourceId: string | null) {
  return useInfiniteQuery({
    queryKey: queryKeys.collab.activity({ resourceType, resourceId }),
    queryFn: ({ pageParam, signal }) => fetchActivity({ resourceType, resourceId, before: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}

function ActivityList({ resourceType, resourceId }: { resourceType: string | null; resourceId: string | null }) {
  const query = useActivity(resourceType, resourceId);
  if (query.isPending) return <Loading label="activity" />;
  if (query.isError) {
    if (isProblemError(query.error) && query.error.status === 403) return <PermissionDenied area="activity" headingLevel={2} />;
    return <ErrorState error={query.error} what="the activity" onRetry={() => void query.refetch()} />;
  }
  const items = query.data.pages.flatMap((p) => p.items);
  if (items.length === 0) return <EmptyState title="No activity yet">Changes to records you can open show up here.</EmptyState>;
  return (
    <div className="flex flex-col gap-3">
      <ul className="divide-y rounded-xl border bg-surface">
        {items.map((item) => (
          <ActivityLine key={item.id} item={item} showRecord={resourceId === null} />
        ))}
      </ul>
      {query.hasNextPage ? (
        <div>
          <Button isPending={query.isFetchingNextPage} pendingLabel="Loading…" onPress={() => void query.fetchNextPage()}>
            Show older activity
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/** The company feed (PARITY LM-98 / UI-29): only records the person may open contribute. */
export function ActivityFeed() {
  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">Activity</h1>
      <ActivityList resourceType={null} resourceId={null} />
    </div>
  );
}

/** A record's timeline, for record pages (quote, challan, product ...). */
export function RecordActivity({ resourceType, resourceId }: { resourceType: string; resourceId: string }) {
  return <ActivityList resourceType={resourceType} resourceId={resourceId} />;
}
