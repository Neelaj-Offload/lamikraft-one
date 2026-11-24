"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import type { Route } from "next";
import { useId, useMemo, type CSSProperties } from "react";
import { fetchActivity, type ActivityItem } from "@/features/collab/api";
import { isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { calendarDaysFrom, formatTime, parseInstant, zonedDateKey, type ZoneOptions } from "@/lib/format/time";
import { safeAppPath } from "@/lib/safe-path";
import { useNow, useZone } from "@/lib/session/context";
import { riseIndex } from "~/lib/motion";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, NotPermitted } from "~/shell/states";
import { Button, ButtonLink, EmptyState, GlassPanel, Skeleton, TextLink, Timeline, type IconName, type TimelineItem, type Tone } from "~/ui";

/** The team's words for the nouns the event stream uses (docs/meetings: quotation, customer, stock). */
const TEAM_WORDS: readonly [RegExp, string][] = [
  [/\bQuote\b/g, "Quotation"],
  [/\bquote\b/g, "quotation"],
  [/\bParty\b/g, "Customer"],
  [/\bparty\b/g, "customer"],
  [/\bInventory\b/g, "Stock"],
  [/\binventory\b/g, "stock"],
];

function teamWords(text: string): string {
  return TEAM_WORDS.reduce((out, [pattern, word]) => out.replace(pattern, word), text);
}

/** A marker for the kind of change. The sentence carries the meaning; the icon and tone only reinforce it. */
function markOf(item: ActivityItem): { icon: IconName; tone?: Tone } {
  const verb = item.verb.toLowerCase();
  if (item.event_type.startsWith("collab.attachment")) return { icon: "paperclip" };
  if (item.event_type.startsWith("collab.")) return { icon: "message" };
  if (/(cancel|reject|fail|void|block|decline)/.test(verb)) return { icon: "x", tone: "ember" };
  if (/(overdue|expir|late|breach)/.test(verb)) return { icon: "clock", tone: "amber" };
  if (/request/.test(verb)) return { icon: "flag" };
  if (/(approv|confirm|complet|accept|paid|receiv|deliver|passed|closed|won)/.test(verb)) return { icon: "check", tone: "leaf" };
  if (/(sent|dispatch|shipp|issued|submitted)/.test(verb)) return { icon: "send", tone: "cobalt" };
  if (/(creat|add|open)/.test(verb)) return { icon: "plus" };
  if (/(archiv|remov|delet)/.test(verb)) return { icon: "archive" };
  if (/(updat|chang|edit|revis|assign|moved)/.test(verb)) return { icon: "edit" };
  return { icon: "circleDot" };
}

/** Automatic changes are made by the product itself, which has a name. */
function actorName(item: ActivityItem): string {
  if (item.actor_type === "system") return "Lamikraft One";
  return item.actor_name ?? "Someone";
}

function recordName(item: ActivityItem): string {
  return item.resource_label ?? teamWords(item.resource_type.split(".").pop()?.replace(/_/g, " ") ?? "record");
}

interface Day {
  key: string;
  label: string;
  items: ActivityItem[];
}

function dayLabel(instant: Date, now: Date | null, zone: ZoneOptions): string {
  if (now) {
    const days = calendarDaysFrom(instant, now, zone.timeZone);
    if (days === 0) return "Today";
    if (days === -1) return "Yesterday";
  }
  const sameYear = !now || zonedDateKey(instant, zone.timeZone).slice(0, 4) === zonedDateKey(now, zone.timeZone).slice(0, 4);
  return new Intl.DateTimeFormat(zone.locale, {
    timeZone: zone.timeZone,
    weekday: "long",
    day: "numeric",
    month: "long",
    year: sameYear ? undefined : "numeric",
  }).format(instant);
}

function groupByDay(items: readonly ActivityItem[], now: Date | null, zone: ZoneOptions): Day[] {
  const days: Day[] = [];
  for (const item of items) {
    const instant = parseInstant(item.occurred_at) ?? new Date(item.occurred_at);
    const valid = !Number.isNaN(instant.getTime());
    const key = valid ? zonedDateKey(instant, zone.timeZone) : "undated";
    const last = days[days.length - 1];
    if (last && last.key === key) last.items.push(item);
    else days.push({ key, label: valid ? dayLabel(instant, now, zone) : "Earlier", items: [item] });
  }
  return days;
}

/**
 * The workspace's activity feed: every change on a record this person may open, newest first, one
 * calm line per event, grouped by day. The feed has no filters (the server offers none for it);
 * a single record's own history lives on that record.
 */
export function ActivityScreen() {
  const zone = useZone();
  const now = useNow();
  const query = useInfiniteQuery({
    queryKey: queryKeys.collab.activity({ resourceType: null, resourceId: null }),
    queryFn: ({ pageParam, signal }) => fetchActivity({ resourceType: null, resourceId: null, before: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });

  const items = useMemo(() => query.data?.pages.flatMap((page) => page.items) ?? [], [query.data]);
  const days = useMemo(() => groupByDay(items, now, zone), [items, now, zone]);

  return (
    <Page width="reading">
      <PageHeader title="Activity" lead="What changed on the records you can open, newest first." />

      {query.isPending ? (
        <ActivityLoading />
      ) : query.isError ? (
        isProblemError(query.error) && query.error.status === 403 ? (
          <GlassPanel padding="lg">
            <NotPermitted what="Activity" icon="activity" />
          </GlassPanel>
        ) : (
          <ErrorBlock error={query.error} what="Activity" onRetry={() => void query.refetch()} />
        )
      ) : items.length === 0 ? (
        <GlassPanel padding="lg" className="rise" style={riseIndex(1) as CSSProperties}>
          <EmptyState
            icon="activity"
            title="Nothing has happened yet"
            text="When someone creates, sends or changes a record you can open, it appears here."
            actions={
              <ButtonLink href="/today" variant="inverse">
                Go to Today
              </ButtonLink>
            }
          />
        </GlassPanel>
      ) : (
        <>
          {days.map((day, index) => (
            <DaySection key={day.key} day={day} index={index} zone={zone} />
          ))}
          <div className="flex flex-col items-center gap-2 pt-1">
            {query.hasNextPage ? (
              <Button variant="secondary" iconLeft="history" loading={query.isFetchingNextPage} onPress={() => void query.fetchNextPage()}>
                Show older activity
              </Button>
            ) : (
              <p className="t-body-sm text-ink-3">That is everything on the records you can open.</p>
            )}
            {query.isFetchNextPageError ? (
              <p className="t-body-sm text-ember-text" role="alert">
                Older activity could not load. Try again.
              </p>
            ) : null}
          </div>
        </>
      )}
    </Page>
  );
}

function DaySection({ day, index, zone }: { day: Day; index: number; zone: ZoneOptions }) {
  const headingId = useId();
  const entries: TimelineItem[] = day.items.map((item) => {
    const path = safeAppPath(item.path);
    const instant = parseInstant(item.occurred_at);
    const record = recordName(item);
    const mark = markOf(item);
    const changed = item.changed_fields.map((field) => teamWords(field.replace(/_/g, " ")));
    return {
      id: item.id,
      icon: mark.icon,
      tone: mark.tone,
      title: (
        <>
          <span className="font-medium">{teamWords(item.summary)}</span>
          <span className="text-ink-3" aria-hidden>
            {" · "}
          </span>
          {path ? (
            <TextLink href={path as Route} className="break-words">
              {record}
            </TextLink>
          ) : (
            <span className="break-words text-ink-2">{record}</span>
          )}
        </>
      ),
      meta: instant ? <time dateTime={item.occurred_at}>{formatTime(instant, zone)}</time> : undefined,
      body: (
        <>
          {actorName(item)}
          {changed.length > 0 ? <span className="text-ink-3"> changed {changed.join(", ")}</span> : null}
        </>
      ),
    };
  });

  return (
    <section className="rise flex flex-col gap-3" style={riseIndex(index + 1) as CSSProperties} aria-labelledby={headingId}>
      <div className="flex items-baseline justify-between gap-3 px-1">
        <h2 id={headingId} className="t-h4">
          {day.label}
        </h2>
        <p className="t-body-sm lk-tnum text-ink-3">
          {day.items.length} {day.items.length === 1 ? "change" : "changes"}
        </p>
      </div>
      <GlassPanel padding="md">
        <Timeline label={`Activity, ${day.label}`} items={entries} />
      </GlassPanel>
    </section>
  );
}

function ActivityLoading() {
  return (
    <div className="flex flex-col gap-3" role="status" aria-label="Loading activity">
      <Skeleton width={88} height={14} className="mx-1" />
      <GlassPanel padding="md" className="flex flex-col gap-5">
        {[62, 48, 70, 54, 40, 58].map((width, row) => (
          <div key={row} className="flex items-start gap-3">
            <Skeleton circle width={28} height={28} className="flex-none" />
            <div className="flex min-w-0 flex-1 flex-col gap-2 pt-1">
              <Skeleton width={`${width}%`} height={14} />
              <Skeleton width={`${Math.round(width / 2)}%`} height={10} />
            </div>
          </div>
        ))}
      </GlassPanel>
    </div>
  );
}
